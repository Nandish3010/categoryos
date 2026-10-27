import csv
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from app import registry, scope
from app.config import settings
from app.constants import ALLOWED_VENDORS
from app.errors import UnknownVendor


@dataclass(frozen=True)
class SheetRow:
    """row is 1-based as in a spreadsheet: the header is row 1, the first SKU row is 2."""

    row: int
    cells: dict[str, str]


@dataclass(frozen=True)
class Listing:
    vendor_sku_ref: str
    marketplace: str
    title: str
    price: float
    rating: float | None
    review_count: int | None
    est_monthly_sales: int | None


@dataclass(frozen=True)
class CatalogSku:
    sku_id: str
    brand: str
    name: str
    category: str
    subcategory: str
    pack_size: str
    mrp: float
    selling_price: float
    rating: float | None
    monthly_units: float


@dataclass(frozen=True)
class Keyword:
    keyword: str
    monthly_searches: int
    trend_3m_pct: float
    competition: str


def check_vendor(vendor_id: str) -> str:
    """The built-in vendors, or a live (not expired) sandbox vendor created at /try."""
    if vendor_id not in ALLOWED_VENDORS and not registry.exists(vendor_id):
        raise UnknownVendor(vendor_id)
    return vendor_id


def _root() -> str:
    """Where market data (benchmarks, catalog, listings, keywords, reviews) is read from: the active sandbox vendor's own
    stubs when it has them, else the shared synthetic data."""
    sc = scope.current()
    if sc is not None and sc.market_dir:
        return str(Path(sc.market_dir))
    return str(Path(settings.data_dir))


def _vendor_root() -> str:
    return str(Path(settings.data_dir) / "vendors")


def _vendor_dir(vendor_id: str) -> Path:
    """The folder of a vendor's own files: data/synthetic/vendors/<id> or the sandbox folder."""
    return registry.vendor_dir(vendor_id) if vendor_id not in ALLOWED_VENDORS else Path(_vendor_root()) / vendor_id  # type: ignore[return-value]


def _num(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


@cache
def _csv_rows(path: str) -> tuple[list[str], tuple[SheetRow, ...]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        headers = next(reader)
        rows: list[SheetRow] = []
        for idx, record in enumerate(reader, start=2):
            if not any(cell.strip() for cell in record):
                continue
            padded = record + [""] * (len(headers) - len(record))
            rows.append(SheetRow(idx, dict(zip(headers, padded))))
    return headers, tuple(rows)


@cache
def _json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_sheet(vendor_id: str) -> tuple[list[str], tuple[SheetRow, ...]]:
    check_vendor(vendor_id)
    return _csv_rows(str(_vendor_dir(vendor_id) / "sku_sheet.csv"))


def load_application(vendor_id: str) -> dict[str, Any]:
    check_vendor(vendor_id)
    return _json(str(_vendor_dir(vendor_id) / "application.json"))


_TRANSCRIPT_OVERRIDES: dict[str, list[dict[str, Any]]] = {}


def set_transcript_override(vendor_id: str, turns: list[dict[str, Any]]) -> None:
    """A finished live call becomes the canonical transcript for this process: Negotiate and the verifier read it."""
    check_vendor(vendor_id)
    _TRANSCRIPT_OVERRIDES[vendor_id] = [dict(t) for t in turns]


def clear_transcript_overrides() -> None:
    _TRANSCRIPT_OVERRIDES.clear()


def load_transcript(vendor_id: str) -> list[dict[str, Any]] | None:
    """Canonical call transcript (speaker turns) for vendors that have one, else None."""
    check_vendor(vendor_id)
    if vendor_id in _TRANSCRIPT_OVERRIDES:
        return _TRANSCRIPT_OVERRIDES[vendor_id]
    path = _vendor_dir(vendor_id) / "call_transcript.json"
    return _json(str(path)) if path.exists() else None


def load_benchmarks() -> dict[str, dict[str, Any]]:
    return _json(f"{_root()}/category_benchmarks.json")


@cache
def _catalog(root: str) -> tuple[CatalogSku, ...]:
    _, rows = _csv_rows(f"{root}/platform_catalog.csv")
    return tuple(
        CatalogSku(
            sku_id=r.cells["sku_id"],
            brand=r.cells["brand"],
            name=r.cells["name"],
            category=r.cells["category"],
            subcategory=r.cells["subcategory"],
            pack_size=r.cells["pack_size"],
            mrp=_num(r.cells["mrp"]) or 0.0,
            selling_price=_num(r.cells["selling_price"]) or 0.0,
            rating=_num(r.cells["rating"]),
            monthly_units=_num(r.cells["monthly_units"]) or 0.0,
        )
        for r in rows
    )


def load_catalog() -> tuple[CatalogSku, ...]:
    return _catalog(_root())


@cache
def _listings(root: str) -> dict[str, tuple[Listing, ...]]:
    _, rows = _csv_rows(f"{root}/market/competitor_listings.csv")
    grouped: dict[str, list[Listing]] = {}
    for r in rows:
        c = r.cells
        price = _num(c["price"])
        if price is None or price <= 0:
            continue
        reviews = _num(c.get("review_count"))
        sales = _num(c.get("est_monthly_sales"))
        grouped.setdefault(c["vendor_sku_ref"], []).append(
            Listing(
                vendor_sku_ref=c["vendor_sku_ref"],
                marketplace=c["marketplace"],
                title=c["title"],
                price=price,
                rating=_num(c.get("rating")),
                review_count=int(reviews) if reviews is not None else None,
                est_monthly_sales=int(sales) if sales is not None else None,
            )
        )
    return {k: tuple(v) for k, v in grouped.items()}


def load_listings() -> dict[str, tuple[Listing, ...]]:
    return _listings(_root())


def load_reviews() -> dict[str, list[dict[str, Any]]]:
    return _json(f"{_root()}/market/reviews.json")


@cache
def _keywords(root: str) -> tuple[Keyword, ...]:
    _, rows = _csv_rows(f"{root}/market/search_demand.csv")
    return tuple(
        Keyword(
            keyword=r.cells["keyword"],
            monthly_searches=int(float(r.cells["monthly_searches"])),
            trend_3m_pct=float(r.cells["trend_3m_pct"]),
            competition=r.cells["competition"],
        )
        for r in rows
    )


def load_keywords() -> tuple[Keyword, ...]:
    return _keywords(_root())


# ---------- scanned documents (vendors/<VID>/docs) ----------


def _docs_dir(vendor_id: str) -> Path:
    return _vendor_dir(vendor_id) / "docs"


def load_doc_manifest(vendor_id: str) -> list[dict[str, Any]]:
    """The vendor's uploaded documents: ``[{file, kind, title, pages, declares?, sku_code?}]``.

    ``kind`` and ``declares`` are what the vendor said the file is (vendor-supplied, untrusted). Empty when the
    vendor uploaded nothing."""
    check_vendor(vendor_id)
    path = _docs_dir(vendor_id) / "manifest.json"
    if not path.exists():
        return []
    items = _json(str(path)).get("documents", [])
    return [d for d in items if isinstance(d, dict) and d.get("file") and d.get("kind")]


def doc_files(vendor_id: str) -> set[str]:
    """Every file name the manifest vouches for: documents and their page images."""
    names: set[str] = set()
    for d in load_doc_manifest(vendor_id):
        names.add(str(d["file"]))
        names.update(str(p) for p in d.get("pages", []))
    return names


def doc_path(vendor_id: str, name: str) -> Path | None:
    """Path-safe lookup: a plain file name that the vendor's manifest lists, inside the vendor's docs folder."""
    if name != Path(name).name or not _known_vendor(vendor_id) or name not in doc_files(vendor_id):
        return None
    folder = _docs_dir(vendor_id).resolve()
    path = (folder / name).resolve()
    return path if path.parent == folder and path.is_file() else None


def _known_vendor(vendor_id: str) -> bool:
    return vendor_id in ALLOWED_VENDORS or registry.exists(vendor_id)
