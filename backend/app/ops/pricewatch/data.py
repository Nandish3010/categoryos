"""Loaders for the competitor price monitor: daily snapshots (data/synthetic/ops/price_snapshots.csv), the minimum advertised
prices on file and the snapshot metadata. Pure data, no rules. Written by data/generate_price_watch.py."""

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from app.config import settings
from app.errors import PriceWatchDataMissing

SNAPSHOTS = "ops/price_snapshots.csv"
MAP = "ops/price_watch_map.csv"
META = "ops/price_watch_meta.json"
FILES = (SNAPSHOTS, MAP, META)


@dataclass(frozen=True)
class Snapshots:
    as_of: date
    marketplaces: tuple[str, ...]
    comp: dict[tuple[str, str], tuple[tuple[date, int], ...]]  # (sku, marketplace) -> days, oldest first: lowest competitor price
    vendor: dict[tuple[str, str], tuple[tuple[date, int], ...]]  # (sku, marketplace) -> the vendor's own storefront
    map_price: dict[str, int]  # sku -> minimum advertised price
    rows: int


def path(rel: str) -> Path:
    return Path(settings.data_dir) / rel


def file_sha256(rel: str) -> str:
    if rel not in FILES:
        raise ValueError(f"not a price-watch data file: {rel}")
    return hashlib.sha256(path(rel).read_bytes()).hexdigest()


def data_sha() -> str:
    h = hashlib.sha256()
    for rel in FILES:
        h.update(file_sha256(rel).encode())
    return h.hexdigest()


@cache
def _load(data_dir: str) -> Snapshots:  # data_dir is only the cache key
    for rel in FILES:
        if not path(rel).exists():
            raise PriceWatchDataMissing(cause=f"{path(rel)} does not exist")
    meta = json.loads(path(META).read_text(encoding="utf-8"))
    comp: dict[tuple[str, str], list[tuple[date, int]]] = {}
    vendor: dict[tuple[str, str], list[tuple[date, int]]] = {}
    n = 0
    with path(SNAPSHOTS).open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            n += 1
            target = comp if r["seller_type"] == "competitor" else vendor
            target.setdefault((r["sku_code"], r["marketplace"]), []).append((date.fromisoformat(r["date"]), int(float(r["price"]))))
    with path(MAP).open(newline="", encoding="utf-8") as fh:
        maps = {r["sku_code"]: int(float(r["map_price"])) for r in csv.DictReader(fh)}
    return Snapshots(
        as_of=date.fromisoformat(meta["as_of"]),
        marketplaces=tuple(meta["marketplaces"]),
        comp={k: tuple(sorted(v)) for k, v in comp.items()},
        vendor={k: tuple(sorted(v)) for k, v in vendor.items()},
        map_price=maps,
        rows=n,
    )


def load() -> Snapshots:
    return _load(str(settings.data_dir))
