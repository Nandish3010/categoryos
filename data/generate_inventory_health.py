#!/usr/bin/env python3
"""Synthetic purchasing terms and legacy stock for the CategoryOS inventory health review (Run). All data FICTIONAL, INR.

Usage: python3 data/generate_inventory_health.py   (stdlib only, deterministic: seed 42, byte-identical on re-run)
Reads data/synthetic/ops/skus.csv and sales_daily.csv (run data/generate_ops.py first). Writes, into data/synthetic/ops/:
  inventory_terms.csv          minimum order quantity and sell-or-return terms per SKU (36 live SKUs and the 2 legacy ones)
  inventory_legacy.csv         stock of two discontinued packs still on the shelf: not in skus.csv, no sales in the 13-week window
  inventory_health_meta.json   as-of date and a note
Separate from generate_ops.py on purpose: the other Run modules' data and recorded goldens stay byte-identical.

The ops data already plants the stock-out and ageing cases (see generate_ops.py: NP-03, PL-01, LT-05 low cover with late POs; TW-03,
TW-04, TW-05 slow movers with aged batches). This file adds what the review also needs and what they lack: the vendors' MOQs, the
sell-or-return terms, and stock that has not sold at all.

PLANTED (what the module must catch)
  NP-03  E003  hero SKU, 22 units against ~57 a day, open PO balance 600 two days late    stock-out inside the day -> reorder (MOQ 600)
  LT-05  E005  5 days of cover, PO 7 days past due                                         stock-out before the PO lands -> expedite the PO
  PL-01  E002  6 days of cover, PO 2 days past due                                         stock-out before the PO lands -> expedite the PO
  TW-05  E004  260 days of cover, 150-day-old batch, sell-or-return window closes 2026-11-13 -> return to vendor (urgent)
  TW-03  E004  150 days of cover, aged batch, sell-or-return window lapsed 2026-10-10        -> liquidate via promo
  TW-04  E004  140 days of cover, aged batch, no return terms                                -> liquidate via promo
  TW-06  E004  open PO 300 (= MOQ) on top of 30 days of cover, tomorrow's delivery            -> pause the PO (MOQ-driven overbuy)
  NP-91  E003  discontinued pack, 240 units, last sale 2026-07-02, sell-or-return open       -> return to vendor (dead stock)
  GW-91  E006  discontinued label, 180 units, last sale 2026-07-18, no return terms           -> liquidate via promo (dead stock)
"""

import csv
import json
import math
import os
import random
from datetime import date, timedelta

SEED = 42
HERE = os.path.dirname(os.path.abspath(__file__))
OPS = os.path.join(HERE, "synthetic", "ops")
AS_OF = date(2026, 10, 26)

# vendors that take unsold stock back, with the window end as days after AS_OF and a restocking fee (%)
SELL_OR_RETURN_VENDORS = {"E001": (60, 5.0), "E003": (60, 5.0)}

MOQ_OVERRIDE = {  # PLANTED: vendor minimums that do not fit the demand
    "TW-03": 300, "TW-04": 300, "TW-05": 300, "TW-06": 300,  # E004 will not ship a small lot
    "NP-03": 600, "LT-05": 400, "PL-01": 300,
}
TERMS_OVERRIDE = {  # sku -> (return_terms, window end, fee %)
    "TW-05": ("sell_or_return", date(2026, 11, 13), 5.0),  # PLANTED: window closes in 18 days
    "TW-03": ("sell_or_return", date(2026, 10, 10), 5.0),  # PLANTED: window lapsed
}

LEGACY = [  # code, vendor, name, cost, selling price, units, received, last sale, terms
    ("NP-91", "E003", "Training Bites (old pack)", 66, 104, 240, date(2026, 5, 12), date(2026, 7, 2), ("sell_or_return", date(2026, 12, 31), 5.0)),
    ("GW-91", "E006", "Oatmeal Shampoo (old label)", 118, 188, 180, date(2026, 4, 20), date(2026, 7, 18), ("none", None, 0.0)),
]


def read(name: str) -> list[dict]:
    with open(os.path.join(OPS, name), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    rng = random.Random(SEED)
    skus = read("skus.csv")
    sales: dict[str, list[int]] = {}
    for r in read("sales_daily.csv"):
        sales.setdefault(r["sku_code"], []).append(int(r["units"]))
    terms = []
    for s in skus:
        code, vendor = s["sku_code"], s["vendor_id"]
        recent = sales[code][-28:]
        daily = sum(recent) / len(recent)
        moq = MOQ_OVERRIDE.get(code) or max(20, math.ceil(daily * rng.uniform(8, 12) / 10) * 10)
        kind, end, fee = "none", None, 0.0
        if vendor in SELL_OR_RETURN_VENDORS:
            days, fee = SELL_OR_RETURN_VENDORS[vendor]
            kind, end = "sell_or_return", AS_OF + timedelta(days=days)
        if code in TERMS_OVERRIDE:
            kind, end, fee = TERMS_OVERRIDE[code]
        terms.append([code, vendor, moq, kind, end.isoformat() if end else "", f"{fee:g}"])
    for code, vendor, _n, _c, _p, _u, _r, _l, (kind, end, fee) in LEGACY:
        terms.append([code, vendor, 100, kind, end.isoformat() if end else "", f"{fee:g}"])
    with open(os.path.join(OPS, "inventory_terms.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["sku_code", "vendor_id", "moq_units", "return_terms", "return_window_ends", "restocking_fee_pct"])
        w.writerows(terms)
    with open(os.path.join(OPS, "inventory_legacy.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["sku_code", "vendor_id", "name", "cost", "selling_price", "units", "received_date", "last_sale_date"])
        for code, vendor, name, cost, price, units, received, last, _t in LEGACY:
            w.writerow([code, vendor, name, cost, price, units, received.isoformat(), last.isoformat()])
    with open(os.path.join(OPS, "inventory_health_meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"as_of": AS_OF.isoformat(), "note": "Synthetic. Generated by data/generate_inventory_health.py (seed 42)."}, fh, indent=2)
        fh.write("\n")
    print(f"wrote {len(terms)} term rows and {len(LEGACY)} legacy lots to {OPS}")


if __name__ == "__main__":
    main()
