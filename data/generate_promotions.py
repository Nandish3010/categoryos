#!/usr/bin/env python3
"""Synthetic vendor funding replies for the CategoryOS promotions planner (Run). All data FICTIONAL, INR.

Usage: python3 data/generate_promotions.py   (stdlib only, deterministic: seed 42, byte-identical on re-run)
Writes data/synthetic/ops/promo_vendor_replies.json. Separate from generate_ops.py on purpose (that file is not touched).

The sale calendar itself lives in the playbook (config/policy.yaml, ``promotions.events``). This script writes what the
vendors answered when asked to fund an event: six messy emails, read by the model into structured offers and checked
against the text by the verifier. It reads the ops sales file so that sales targets in the offers are sized against
real run rates.

PLANTED
  F001 E001 Barkley   conditional funding that cannot be met: 50% of the markdown "if the range sells N units", N about
                      4.5x what the range sells in the event even without a discount -> the deal evaluator gives it a
                      near-zero chance, the offer counts as 0 and the planner counters
  F002 E002 Purrline  flat 30% of the markdown, no conditions
  F003 E003 NutriPaws 35% of the markdown if the range sells a realistic target (about 0.9x the 7-day baseline, which the promo uplift beats)
  F004 E005 Litterly  declines to fund anything
  F005 E006 Groomwell 25% on two hero SKUs if we give them a top-3 banner (no sales target)
  F006 E004 Tailwind  40% on two SKUs, and says its lead time is 14 days (no restock before the event)
  F007 E002 Purrline  a separate, smaller offer for the Payday Sale
"""

import csv
import json
import os
import random
from datetime import timedelta, date

SEED = 42
HERE = os.path.dirname(os.path.abspath(__file__))
OPS = os.path.join(HERE, "synthetic", "ops")

EVENT_DAYS = 7  # the festive sale in config/policy.yaml runs 6 to 12 Nov


def vendor_daily_units() -> dict[str, float]:
    """Average units per day over the last 28 days of the ops sales file, per vendor."""
    sku_vendor = {}
    with open(os.path.join(OPS, "skus.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sku_vendor[r["sku_code"]] = r["vendor_id"]
    rows = list(csv.DictReader(open(os.path.join(OPS, "sales_daily.csv"), newline="", encoding="utf-8")))
    last = max(date.fromisoformat(r["date"]) for r in rows)
    start = last - timedelta(days=27)
    out: dict[str, float] = {}
    for r in rows:
        if date.fromisoformat(r["date"]) >= start:
            out[sku_vendor[r["sku_code"]]] = out.get(sku_vendor[r["sku_code"]], 0.0) + int(r["units"]) / 28
    return out


def target(daily: float, factor: float, step: int = 50) -> int:
    return int(round(daily * EVENT_DAYS * factor / step) * step)


def build() -> list[dict]:
    random.seed(SEED)
    d = vendor_daily_units()
    t1, t3 = target(d["E001"], 4.5, 100), target(d["E003"], 0.9)
    return [
        {
            "id": "F001", "event_id": "festive", "vendor_id": "E001", "received_at": "2026-10-23T11:02:00",
            "from": "Anil Rao <orders@barkley.example>", "subject": "RE: Festive Sale - funding",
            "body": (
                "Hi team,\n\nThanks for the Festive Sale slot. We can fund 50% of the markdown on the Barkley range, provided you guarantee "
                f"a top-3 banner and the range sells {t1:,} units between 6th and 12th Nov. If the target is missed the funding lapses.\n\n"
                "Regards\nAnil Rao\nBarkley Foods"
            ),
        },
        {
            "id": "F002", "event_id": "festive", "vendor_id": "E002", "received_at": "2026-10-23T16:40:00",
            "from": "Rakesh Shah <dispatch@purrline.example>", "subject": "Festive sale - Purrline support",
            "body": (
                "Dear Sir/Madam,\n\nFor the Festive Sale Purrline will fund 30% of the markdown on every Purrline SKU you put on promo. No other "
                "conditions. We will send the credit note after the event.\n\nThanks & regards\nRakesh Shah\nPurrline Nutrition LLP"
            ),
        },
        {
            "id": "F003", "event_id": "festive", "vendor_id": "E003", "received_at": "2026-10-24T09:15:00",
            "from": "Meera Iyer <supply@nutripaws.example>", "subject": "RE: Festive Sale funding ask",
            "body": (
                f"Hello,\n\nNutriPaws can support 35% of the discount cost across our range if the range sells {t3:,} units during 6-12 Nov. "
                "Happy to review after the event.\n\nBest\nMeera Iyer"
            ),
        },
        {
            "id": "F004", "event_id": "festive", "vendor_id": "E005", "received_at": "2026-10-24T13:30:00",
            "from": "Sanjay Kulkarni <ops@litterly.example>", "subject": "RE: Festive Sale - funding",
            "body": (
                "Hi,\n\nSorry, margins are very thin this quarter and we are not able to fund any discount for the Festive Sale. "
                "We will keep stock ready as usual.\n\nSanjay\nLitterly Products"
            ),
        },
        {
            "id": "F005", "event_id": "festive", "vendor_id": "E006", "received_at": "2026-10-24T15:05:00",
            "from": "Neha Bhatt <care@groomwell.example>", "subject": "Groomwell festive support",
            "body": (
                "Hi team,\n\nGroomwell will fund 25% of the markdown on GW-01 and GW-03 for the Festive Sale if you give us a top-3 banner "
                "placement. No sales target from our side.\n\nRegards\nNeha Bhatt\nGroomwell Care"
            ),
        },
        {
            "id": "F006", "event_id": "festive", "vendor_id": "E004", "received_at": "2026-10-25T10:20:00",
            "from": "Vikram Sethi <sales@tailwindplay.example>", "subject": "RE: Festive sale, TW-01 and TW-02",
            "body": (
                "Dear team,\n\nWe can fund 40% of the markdown on TW-01 and TW-02. Please note our lead time is 14 days, so we cannot ship "
                "fresh stock before the sale starts.\n\nVikram Sethi\nTailwind Play Co"
            ),
        },
        {
            "id": "F007", "event_id": "payday", "vendor_id": "E002", "received_at": "2026-10-25T17:45:00",
            "from": "Rakesh Shah <dispatch@purrline.example>", "subject": "Payday sale",
            "body": "Dear team,\n\nFor the Payday Sale we can fund 20% of the markdown, nothing more this month.\n\nRakesh Shah\nPurrline Nutrition LLP",
        },
    ]


def main() -> None:
    path = os.path.join(OPS, "promo_vendor_replies.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(build(), fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
