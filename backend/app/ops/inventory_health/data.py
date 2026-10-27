"""Loaders for the inventory health review: purchasing terms per SKU (MOQ, sell-or-return) and the legacy lots that sit outside the
live SKU list. Pure data, no rules. Written by data/generate_inventory_health.py. Stock, sales and PO lines come from app.ops.data."""

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from app.config import settings
from app.errors import InventoryHealthDataMissing
from app.ops import data as od

TERMS = "ops/inventory_terms.csv"
LEGACY = "ops/inventory_legacy.csv"
META = "ops/inventory_health_meta.json"
FILES = (TERMS, LEGACY, META)
# the ops files the review reads through app.ops.data: a change in any of them moves the claims' data hash
OPS_INPUTS = ("ops/sales_daily.csv", "ops/inventory_batches.csv", "ops/purchase_orders.csv", "ops/skus.csv", "ops/vendors.json", "ops/meta.json")


@dataclass(frozen=True)
class Terms:
    sku_code: str
    vendor_id: str
    moq_units: int
    return_terms: str  # sell_or_return | none
    return_window_ends: date | None
    restocking_fee_pct: float


@dataclass(frozen=True)
class LegacyLot:
    sku_code: str
    vendor_id: str
    name: str
    cost: float
    selling_price: float
    units: int
    received: date
    last_sale: date


@dataclass(frozen=True)
class InventoryData:
    as_of: date
    terms: dict[str, Terms]
    legacy: dict[str, LegacyLot]


def path(rel: str) -> Path:
    return Path(settings.data_dir) / rel


def file_sha256(rel: str) -> str:
    if rel not in (*FILES, *OPS_INPUTS):
        raise ValueError(f"not an inventory health data file: {rel}")
    return hashlib.sha256(path(rel).read_bytes()).hexdigest()


def data_sha() -> str:
    h = hashlib.sha256()
    for rel in (*FILES, *OPS_INPUTS):
        h.update(file_sha256(rel).encode())
    return h.hexdigest()


@cache
def _load(data_dir: str) -> InventoryData:  # data_dir is only the cache key
    for rel in FILES:
        if not path(rel).exists():
            raise InventoryHealthDataMissing(cause=f"{path(rel)} does not exist")
    meta = json.loads(path(META).read_text(encoding="utf-8"))
    with path(TERMS).open(newline="", encoding="utf-8") as fh:
        terms = {
            r["sku_code"]: Terms(
                r["sku_code"], r["vendor_id"], int(r["moq_units"]), r["return_terms"],
                date.fromisoformat(r["return_window_ends"]) if r["return_window_ends"] else None, float(r["restocking_fee_pct"]),
            )
            for r in csv.DictReader(fh)
        }
    with path(LEGACY).open(newline="", encoding="utf-8") as fh:
        legacy = {
            r["sku_code"]: LegacyLot(
                r["sku_code"], r["vendor_id"], r["name"], float(r["cost"]), float(r["selling_price"]), int(r["units"]),
                date.fromisoformat(r["received_date"]), date.fromisoformat(r["last_sale_date"]),
            )
            for r in csv.DictReader(fh)
        }
    return InventoryData(as_of=date.fromisoformat(meta["as_of"]), terms=terms, legacy=legacy)


def load() -> InventoryData:
    return _load(str(settings.data_dir))


def ops() -> od.OpsData:
    return od.load()
