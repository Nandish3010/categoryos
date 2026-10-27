"""Loaders for the live catalog of existing vendors (data/synthetic/ops/catalog_live.csv and friends). Pure data, no rules.

Files (all written by data/generate_catalog_live.py):
  catalog_live.csv        one row per marketplace listing, as it is today
  vendor_price_list.csv   vendor price lists; the LATEST one in force on the as-of date is the truth for MRP and pack size
  catalog_licences.json   FSSAI licence records with valid_until
  catalog_labels/         pack-label photos and their manifest.json"""

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

from app.config import settings
from app.errors import CatalogDataMissing
from app.ops.data import load as load_ops

LIVE = "ops/catalog_live.csv"
PRICES = "ops/vendor_price_list.csv"
LICENCES = "ops/catalog_licences.json"
LABEL_DIR = "ops/catalog_labels"
MANIFEST = f"{LABEL_DIR}/manifest.json"
RETURNS = "ops/returns.csv"
SALES = "ops/sales_daily.csv"
FILES = (LIVE, PRICES, LICENCES, RETURNS, SALES)


@dataclass(frozen=True)
class Listing:
    listing_id: str
    vendor_id: str
    sku_code: str
    title: str
    bullets: tuple[str, ...]
    description: str
    category: str
    subcategory: str
    mrp: float
    pack_size: str
    attributes: dict[str, Any]
    image_count: int
    image_width: int
    image_height: int
    fssai_number: str
    gmv_share: float
    status: str
    listed_on: str
    row: int = 0  # line in catalog_live.csv (header is line 1)

    @property
    def text(self) -> str:
        return " | ".join([self.title, *self.bullets, self.description])

    @property
    def sku_key(self) -> str:
        return f"{self.vendor_id}:{self.sku_code}"

    def snapshot(self) -> dict[str, Any]:
        """The fields a fix may change, in the shape the API and the diff show."""
        return {
            "title": self.title,
            "bullets": list(self.bullets),
            "description": self.description,
            "category": self.category,
            "subcategory": self.subcategory,
            "mrp": self.mrp,
            "pack_size": self.pack_size,
            "attributes": dict(self.attributes),
            "fssai_number": self.fssai_number,
            "status": self.status,
            "images": f"{self.image_count} image(s), main {self.image_width}x{self.image_height} px" if self.image_count else "no image",
        }


@dataclass(frozen=True)
class PriceRow:
    vendor_id: str
    sku_code: str
    effective_date: date
    mrp: float
    pack_size: str
    row: int  # line in vendor_price_list.csv


@dataclass(frozen=True)
class Licence:
    vendor_id: str
    type: str
    number: str
    valid_from: date
    valid_until: date


@dataclass
class CatalogData:
    listings: list[Listing]
    prices: dict[str, list[PriceRow]] = field(default_factory=dict)  # sku_code -> rows, oldest first
    licences: list[Licence] = field(default_factory=list)
    labels: list[dict[str, Any]] = field(default_factory=list)  # manifest entries

    def listing(self, listing_id: str) -> Listing | None:
        return next((x for x in self.listings if x.listing_id == listing_id), None)

    def latest_price(self, sku_code: str, as_of: date) -> PriceRow | None:
        """The price-list row in force on ``as_of``: the newest effective date not after it (a future-dated list is not yet the truth)."""
        rows = [r for r in self.prices.get(sku_code, []) if r.effective_date <= as_of]
        return max(rows, key=lambda r: r.effective_date) if rows else None

    def licence(self, number: str) -> Licence | None:
        return next((x for x in self.licences if x.number == number), None)

    def valid_licence(self, vendor_id: str, kind: str, as_of: date) -> Licence | None:
        ok = [x for x in self.licences if x.vendor_id == vendor_id and x.type == kind and x.valid_from <= as_of <= x.valid_until]
        return max(ok, key=lambda x: x.valid_until) if ok else None


def data_dir() -> Path:
    return Path(settings.data_dir)


def path_of(rel: str) -> Path:
    return data_dir() / rel


def file_sha256(rel: str) -> str:
    return hashlib.sha256(path_of(rel).read_bytes()).hexdigest()


def label_path(name: str) -> Path | None:
    """A label image the manifest lists (a plain file name; nothing else is served)."""
    if name != Path(name).name or name not in {str(p) for e in load().labels for p in e.get("pages", [])}:
        return None
    path = path_of(LABEL_DIR) / name
    return path if path.is_file() else None


def _need(rel: str) -> Path:
    path = path_of(rel)
    if not path.exists():
        raise CatalogDataMissing(cause=f"{path} does not exist")
    return path


def _num(raw: str) -> float:
    return float(raw)


@cache
def _load(data_dir_key: str) -> CatalogData:  # the key only busts the cache when the data dir changes
    with _need(LIVE).open(newline="", encoding="utf-8") as f:
        listings = [
            Listing(
                listing_id=r["listing_id"], vendor_id=r["vendor_id"], sku_code=r["sku_code"], title=r["title"],
                bullets=tuple(b.strip() for b in r["bullets"].split("||") if b.strip()), description=r["description"],
                category=r["category"], subcategory=r["subcategory"], mrp=_num(r["mrp"]), pack_size=r["pack_size"],
                attributes=json.loads(r["attributes"] or "{}"), image_count=int(r["image_count"]), image_width=int(r["image_width"]),
                image_height=int(r["image_height"]), fssai_number=r["fssai_number"], gmv_share=_num(r["gmv_share"]), status=r["status"],
                listed_on=r["listed_on"], row=i,
            )
            for i, r in enumerate(csv.DictReader(f), start=2)
        ]
    prices: dict[str, list[PriceRow]] = {}
    with _need(PRICES).open(newline="", encoding="utf-8") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            prices.setdefault(r["sku_code"], []).append(
                PriceRow(r["vendor_id"], r["sku_code"], date.fromisoformat(r["effective_date"]), _num(r["mrp"]), r["pack_size"], i)
            )
    lic = json.loads(_need(LICENCES).read_text(encoding="utf-8"))["licences"]
    licences = [
        Licence(x["vendor_id"], x["type"], x["number"], date.fromisoformat(x["valid_from"]), date.fromisoformat(x["valid_until"])) for x in lic
    ]
    manifest = path_of(MANIFEST)
    labels = json.loads(manifest.read_text(encoding="utf-8")).get("documents", []) if manifest.exists() else []
    return CatalogData(listings, prices, licences, labels)


def load() -> CatalogData:
    return _load(str(settings.data_dir))


def as_of() -> date:
    return load_ops().as_of
