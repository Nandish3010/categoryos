"""Loaders for the Run (existing vendors) data under data/synthetic/ops. Pure data, no business rules."""

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cache
from pathlib import Path
from typing import Any

from app.config import settings
from app.errors import OpsDataMissing

OPS_DIR = "ops"
OPS_FILES = (
    "meta.json",
    "vendors.json",
    "skus.csv",
    "sales_daily.csv",
    "inventory_batches.csv",
    "purchase_orders.csv",
    "returns.csv",
    "ratings.csv",
    "vendor_replies.json",
)


@dataclass(frozen=True)
class Vendor:
    id: str
    company_name: str
    brand: str
    contact_name: str
    contact_email: str
    category: str
    lead_time_days: int


@dataclass(frozen=True)
class Sku:
    code: str
    vendor_id: str
    name: str
    mrp: float
    cost: float
    selling_price: float


@dataclass(frozen=True)
class PoLine:
    po_id: str
    vendor_id: str
    sku_code: str
    ordered: int
    received: int
    po_date: date
    promised: date
    actual: date | None
    status: str  # open | closed


@dataclass(frozen=True)
class Batch:
    sku_code: str
    received: date
    units: int


@dataclass(frozen=True)
class Return:
    day: date
    sku_code: str
    units: int
    reason: str


@dataclass(frozen=True)
class Reply:
    id: str
    po_id: str
    vendor_id: str
    received_at: datetime
    sender: str
    subject: str
    body: str


@dataclass
class OpsData:
    as_of: date
    data_end: date
    vendors: dict[str, Vendor]
    skus: dict[str, Sku]
    sales: dict[str, dict[date, tuple[int, float]]]  # sku -> day -> (units, gmv)
    batches: list[Batch]
    po_lines: list[PoLine]
    returns: list[Return]
    ratings: dict[str, list[tuple[date, float]]]  # sku -> weekly snapshots, oldest first
    replies: list[Reply]
    weeks: int = 13
    skus_by_vendor: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.skus_by_vendor:
            for s in self.skus.values():
                self.skus_by_vendor.setdefault(s.vendor_id, []).append(s.code)


def ops_dir() -> Path:
    return Path(settings.data_dir) / OPS_DIR


def allowed_files() -> frozenset[str]:
    return frozenset(f"{OPS_DIR}/{f}" for f in OPS_FILES)


def file_sha256(rel: str) -> str:
    """sha256 of an ops data file given as ``ops/<name>``."""
    if rel not in allowed_files():
        raise ValueError(f"not an ops data file: {rel}")
    return hashlib.sha256((Path(settings.data_dir) / rel).read_bytes()).hexdigest()


def _csv(name: str) -> list[dict[str, str]]:
    path = ops_dir() / name
    if not path.exists():
        raise OpsDataMissing(cause=f"{path} does not exist")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _json(name: str) -> Any:
    path = ops_dir() / name
    if not path.exists():
        raise OpsDataMissing(cause=f"{path} does not exist")
    return json.loads(path.read_text(encoding="utf-8"))


def _d(value: str) -> date:
    return date.fromisoformat(value)


@cache
def _load(data_dir: str) -> OpsData:  # data_dir is only the cache key
    meta = _json("meta.json")
    vendors = {v["id"]: Vendor(**v) for v in _json("vendors.json")}
    skus = {
        r["sku_code"]: Sku(r["sku_code"], r["vendor_id"], r["name"], float(r["mrp"]), float(r["cost"]), float(r["selling_price"]))
        for r in _csv("skus.csv")
    }
    sales: dict[str, dict[date, tuple[int, float]]] = {}
    for r in _csv("sales_daily.csv"):
        sales.setdefault(r["sku_code"], {})[_d(r["date"])] = (int(r["units"]), float(r["gmv"]))
    ratings: dict[str, list[tuple[date, float]]] = {}
    for r in _csv("ratings.csv"):
        ratings.setdefault(r["sku_code"], []).append((_d(r["date"]), float(r["rating"])))
    for series in ratings.values():
        series.sort()
    return OpsData(
        as_of=_d(meta["as_of"]),
        data_end=_d(meta["data_end"]),
        weeks=int(meta.get("weeks", 13)),
        vendors=vendors,
        skus=skus,
        sales=sales,
        batches=[Batch(r["sku_code"], _d(r["received_date"]), int(r["units"])) for r in _csv("inventory_batches.csv")],
        po_lines=[
            PoLine(
                r["po_id"], r["vendor_id"], r["sku_code"], int(r["ordered_qty"]), int(r["received_qty"]),
                _d(r["po_date"]), _d(r["promised_date"]), _d(r["actual_date"]) if r["actual_date"] else None, r["status"],
            )
            for r in _csv("purchase_orders.csv")
        ],
        returns=[Return(_d(r["date"]), r["sku_code"], int(r["units"]), r["reason"]) for r in _csv("returns.csv")],
        ratings=ratings,
        replies=[
            Reply(r["id"], r["po_id"], r["vendor_id"], datetime.fromisoformat(r["received_at"]), r["from"], r["subject"], r["body"])
            for r in _json("vendor_replies.json")
        ],
    )


def load() -> OpsData:
    return _load(str(settings.data_dir))
