#!/usr/bin/env python3
"""Synthetic daily price snapshots for the CategoryOS competitor price monitor (Run). All data FICTIONAL, INR.

Usage: python3 data/generate_price_watch.py   (stdlib only, deterministic: seed 42, byte-identical on re-run)
Writes data/synthetic/ops/price_snapshots.csv and price_watch_map.csv. Separate from generate_ops.py on purpose.

30 days (the last is the ops as-of date) of prices for the 36 SKUs of E001 to E006 on three marketplaces:
  * seller_type competitor: the lowest competitor price on that marketplace. Each SKU and marketplace sits at a steady level
    between 1.8% under and 4% over our selling price and wanders within +-0.4% a day. (Independent of the single snapshot in
    price_requests/competitors.csv, whose MarketA level sits 3 to 7% under ours for most SKUs and would make everything an undercut.)
  * seller_type vendor: the vendor's own storefront on ONE marketplace, normally priced at our selling price.
price_watch_map.csv holds the minimum advertised price (MAP) agreed with the two vendors that have one.

PLANTED
  BK-01  MarketA  competitor 7% under us for the last 9 days            sustained undercut; matching breaks the margin floor -> ask the vendor
  GW-01  MarketB  competitor 9% under us for the last 6 days            sustained undercut; margin is healthy -> match
  TW-02  MarketC  competitor slides 0.75% a day, from 2% over us to 2.5% under  trend, not yet beyond the threshold -> watch
  NP-04  MarketC  competitor 14% under us for the LAST DAY ONLY         one-day blip -> must NOT trigger a match
  PL-03  MarketA  a 20% dip on day 12 that recovered next day            old blip, informational
  LT-01  MarketB  the vendor (Litterly) itself sells 12% under us for the last 9 days  parity breach, also under MAP
"""

import csv
import json
import os
import random
from datetime import date, timedelta

SEED = 42
HERE = os.path.dirname(os.path.abspath(__file__))
OPS = os.path.join(HERE, "synthetic", "ops")

AS_OF = date(2026, 10, 26)
DAYS = 30
MARKETS = ["MarketA", "MarketB", "MarketC"]
VENDOR_STORE = {"E001": "MarketA", "E002": "MarketC", "E003": "MarketA", "E004": "MarketB", "E005": "MarketB", "E006": "MarketC"}
MAP_RATIO = {"E001": 0.95, "E005": 0.97}  # vendors with a minimum advertised price, as a share of our selling price


def read_skus() -> list[dict]:
    with open(os.path.join(OPS, "skus.csv"), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def competitor_series(rng: random.Random, sku: str, mp: str, ours: float) -> list[int]:
    """Prices for days 0..DAYS-1 (the last is today), plus the planted behaviour."""
    level = ours * (1 + rng.uniform(-0.018, 0.04))
    wander = [level * (1 + rng.uniform(-0.004, 0.004)) for _ in range(DAYS)]
    if (sku, mp) == ("BK-01", "MarketA"):
        for i in range(DAYS - 9, DAYS):
            wander[i] = ours * 0.93 * (1 + rng.uniform(-0.002, 0.002))
    elif (sku, mp) == ("GW-01", "MarketB"):
        for i in range(DAYS - 6, DAYS):
            wander[i] = ours * 0.91 * (1 + rng.uniform(-0.002, 0.002))
    elif (sku, mp) == ("TW-02", "MarketC"):
        for k, i in enumerate(range(DAYS - 7, DAYS)):
            wander[i] = ours * (1.02 - 0.0075 * k)
    elif (sku, mp) == ("NP-04", "MarketC"):
        wander[-1] = ours * 0.86
    elif (sku, mp) == ("PL-03", "MarketA"):
        wander[DAYS - 19] = ours * 0.80
    return [round(x) for x in wander]


def vendor_series(rng: random.Random, vendor: str, sku: str, ours: float) -> list[int]:
    out = [round(ours * (1 + rng.uniform(0.0, 0.01))) for _ in range(DAYS)]
    if sku == "LT-01":  # PLANTED: Litterly undercuts us on its own storefront for the last 9 days
        for i in range(DAYS - 9, DAYS):
            out[i] = round(ours * 0.88)
    return out


def main() -> None:
    rng = random.Random(SEED)
    skus = read_skus()
    start = AS_OF - timedelta(days=DAYS - 1)
    rows = []
    for s in skus:
        ours = float(s["selling_price"])
        for mp in MARKETS:
            series = competitor_series(rng, s["sku_code"], mp, ours)
            for i, price in enumerate(series):
                rows.append([(start + timedelta(days=i)).isoformat(), s["sku_code"], mp, "competitor", price])
        series = vendor_series(rng, s["vendor_id"], s["sku_code"], ours)
        for i, price in enumerate(series):
            rows.append([(start + timedelta(days=i)).isoformat(), s["sku_code"], VENDOR_STORE[s["vendor_id"]], "vendor", price])
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    with open(os.path.join(OPS, "price_snapshots.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["date", "sku_code", "marketplace", "seller_type", "price"])
        w.writerows(rows)
    with open(os.path.join(OPS, "price_watch_map.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["sku_code", "vendor_id", "map_price"])
        for s in skus:
            if s["vendor_id"] in MAP_RATIO:
                w.writerow([s["sku_code"], s["vendor_id"], round(float(s["selling_price"]) * MAP_RATIO[s["vendor_id"]])])
    with open(os.path.join(OPS, "price_watch_meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"as_of": AS_OF.isoformat(), "start": start.isoformat(), "days": DAYS, "marketplaces": MARKETS, "vendor_storefront": VENDOR_STORE,
                   "note": "Synthetic. Generated by data/generate_price_watch.py (seed 42)."}, fh, indent=2)
        fh.write("\n")
    print(f"wrote {len(rows)} snapshot rows to {OPS}")


if __name__ == "__main__":
    main()
