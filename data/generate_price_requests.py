#!/usr/bin/env python3
"""Synthetic price-increase requests from EXISTING vendors E001-E006 (all fictional). Deterministic (seed 42).

Reads each vendor's costs, prices and contact from the Run area's data (data/synthetic/ops/skus.csv, vendors.json), so the
requests agree with the platform's own numbers, and writes
  data/synthetic/price_requests/<id>/{email.txt, price_list.csv|price_list.txt, meta.json}
  data/synthetic/price_requests/index.json
  data/synthetic/price_requests/competitors.csv   (three competitor prices per SKU; the median is our selling price today)
plus the mock model fixtures that mirror what the model returns for each request (backend/fixtures/mock/negotiate/price_request_*).
Does not touch generate.py, generate_docs.py or generate_ops.py.

Planted requests (Python decides these; the numbers are what the engine produces under the default playbook):
  PR-001  E006 Groomwell       4% on five SKUs, justified by the raw-material index, 38 days notice, plus "an extra 2%
                               marketing support if you take the full revision"                 -> accept
  PR-002  E004 Tailwind Play   8-12% on thin-margin SKUs, plus "we will absorb half if you commit 1,500 units/month"
                               (we sell about 600 a month: the chance is under 1%)             -> counter, sweetener counted at 0
  PR-003  E003 NutriPaws       15% on four SKUs with 15 days notice; passing it on would put us 15% above competitors
                                                                                               -> delay (later date) then counter
"""

import csv
import io
import json
import random
import re
from pathlib import Path

SEED = 42
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "synthetic" / "price_requests"
OPS = ROOT / "synthetic" / "ops"
FIXTURES = ROOT.parent / "backend" / "fixtures" / "mock" / "negotiate"


def ops_skus() -> dict[str, dict]:
    with open(OPS / "skus.csv", newline="", encoding="utf-8") as fh:
        return {r["sku_code"]: r for r in csv.DictReader(fh)}


def ops_vendors() -> dict[str, dict]:
    return {v["id"]: v for v in json.loads((OPS / "vendors.json").read_text(encoding="utf-8"))}


def bump(old: float, pct: float) -> float:
    return round(old * (1 + pct / 100) + 1e-9, 2)


def fmt(x: float) -> str:
    return f"{x:,.2f}"


def write(req_id: str, meta: dict, email: str, list_name: str, list_text: str) -> None:
    d = OUT / req_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "email.txt").write_text(email, encoding="utf-8")
    (d / list_name).write_text(list_text, encoding="utf-8")
    meta = {**meta, "id": req_id, "price_list": list_name}
    (d / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def competitors(rng: random.Random, skus: dict[str, dict]) -> None:
    """Three marketplace prices per SKU: one below us, one at our price (so the median IS our price), one above."""
    rows = [["sku_code", "marketplace", "price"]]
    for code, s in skus.items():
        price = float(s["selling_price"])
        low = round(price * (1 - rng.choice([0.02, 0.03, 0.04, 0.05])))
        high = round(price * (1 + rng.choice([0.02, 0.04, 0.06, 0.08])))
        for market, p in (("MarketA", low), ("MarketB", price), ("MarketC", high)):
            rows.append([code, market, f"{p:g}"])
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    (OUT / "competitors.csv").write_text(out.getvalue(), encoding="utf-8")


def main() -> None:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    skus, vendors = ops_skus(), ops_vendors()
    competitors(rng, skus)
    greetings = ["Dear Sir/Madam,", "Dear Team,", "Hello Buying Team,"]
    thanks = ["Thanks & regards", "Warm regards", "With regards"]

    def cost(code: str) -> float:
        return float(skus[code]["cost"])

    def sender(vid: str) -> str:
        v = vendors[vid]
        return f"{v['contact_name']} <{v['contact_email']}>"

    # ---- PR-001: reasonable, Groomwell (E006) ----
    codes = ["GW-01", "GW-03", "GW-04", "GW-05", "GW-06"]
    fmts = ["Rs. {}", "{}", "INR {}", "{}", "Rs.{}"]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Item Code", "Description", "Old Rate (Rs)", "New Rate (Rs)", "W.E.F"])
    for code, tpl in zip(codes, fmts):
        old = cost(code)
        w.writerow([code, skus[code]["name"], tpl.format(f"{old:,.0f}"), fmt(bump(old, 4)), "01-Dec-2026"])
    email = f"""From: {sender('E006')}
To: buying@petshop.example
Date: Fri, 23 Oct 2026 10:42:00 +0530
Subject: Price revision - Groomwell w.e.f. 1st Dec 2026

{rng.choice(greetings)}

Due to the continued rise in raw material costs (oat extract, surfactants and packaging film) we are revising our prices
by 4% from 1st Dec 2026 on the attached list. Rates are cost to you, GST extra.

We value the partnership and so we will give an extra 2% marketing support if you take the full revision.

Kindly acknowledge and update your system. Old rates stay valid till 30th Nov.

{rng.choice(thanks)},
Neha Bhatt
Groomwell Care Pvt Ltd
"""
    write("PR-001", {"vendor_id": "E006", "received_at": "2026-10-23", "sender": sender("E006"), "subject": "Price revision - Groomwell w.e.f. 1st Dec 2026",
                     "story": "reasonable: 4% on healthy-margin SKUs, justified by the index, enough notice, a harmless sweetener"}, email, "price_list.csv", out.getvalue())

    # ---- PR-002: excessive + improbable sweetener, Tailwind Play (E004) ----
    lines = [("TW-01", 12), ("TW-02", 10), ("TW-04", 12), ("TW-06", 8)]
    table = ["TAILWIND PLAY CO - REVISED COST LIST (to retailer)   w.e.f. 01.12.2026", "", "Code     Item                           Old        New      Rise"]
    for code, pct in lines:
        old = cost(code)
        table.append(f"{code:<8} {skus[code]['name']:<30} {old:>8.2f}   {bump(old, pct):>8.2f}   {pct}%")
    table += ["", "All rates ex-GST. Subject to change without notice."]
    email = f"""From: {sender('E004')}
To: buying@petshop.example
Date: Tue, 20 Oct 2026 16:05:00 +0530
Subject: URGENT - revised prices from 1 Dec (8-12%)

{rng.choice(greetings)}

due to raw material costs (resin, nylon webbing, imported packaging) we are revising prices by 8-12% depending on the SKU, effective 1st Dec 2026,
as per the attached list. The market has moved and we cannot hold the old rates any longer.

To support you we will absorb half of the revision across the range if you commit 1,500 units/month. Please confirm at the earliest.

{rng.choice(thanks)},
Vikram Sethi
Tailwind Play Co
"""
    write("PR-002", {"vendor_id": "E004", "received_at": "2026-10-20", "sender": sender("E004"), "subject": "URGENT - revised prices from 1 Dec (8-12%)",
                     "story": "excessive 8-12% on thin-margin SKUs; the 'absorb half if 1,500 units/month' sweetener is very unlikely (we sell about 600 a month)"},
          email, "price_list.txt", "\n".join(table) + "\n")

    # ---- PR-003: pass-through would put us 15% above competitors, NutriPaws (E003) ----
    lines = [("NP-01", 15), ("NP-02", 15), ("NP-04", 15), ("NP-05", 15)]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Style No", "Product", "Existing cost", "Revised cost", "Applicable from", "Remarks"])
    for code, pct in lines:
        old = cost(code)
        w.writerow([code, skus[code]["name"], f"{old:.2f}", f"{bump(old, pct):.2f}", "10 Nov 2026", f"+{pct}% chicken/tuna/packaging"])
    email = f"""From: {sender('E003')}
To: buying@petshop.example
Date: Mon, 26 Oct 2026 09:15:00 +0530
Subject: Revised price list - NutriPaws (new rates from 10th Nov)

{rng.choice(greetings)}

Because of higher meat, fish and packaging costs we are revising our prices by 15% from 10th Nov 2026 on the attached list.
Please process the new rates from the effective date.

{rng.choice(thanks)},
Meera Iyer
NutriPaws Snacks Pvt Ltd
"""
    write("PR-003", {"vendor_id": "E003", "received_at": "2026-10-26", "sender": sender("E003"), "subject": "Revised price list - NutriPaws (new rates from 10th Nov)",
                     "story": "15% on four SKUs with 15 days notice; passing it on would put us 15% above competitor prices"}, email, "price_list.csv", out.getvalue())

    index = []
    for req_id in ("PR-001", "PR-002", "PR-003"):
        meta = json.loads((OUT / req_id / "meta.json").read_text())
        index.append({k: meta[k] for k in ("id", "vendor_id", "received_at", "sender", "subject", "price_list")})
    (OUT / "index.json").write_text(json.dumps({"requests": index}, indent=2) + "\n", encoding="utf-8")
    write_mock_fixtures()
    print(f"wrote {len(index)} requests to {OUT}")


# What the model is expected to return for each request (live shape: backend/app/pricereq.py PriceRequestExtraction).
# Quotes are copied from the generated files, so they are verbatim by construction. PR-003 plants one transposed cost
# (NP-02 189.75 read as 819.75): the verifier rejects it and the scripted retry answers 189.75.
READ = {
    "PR-001": {
        "effective_date": "2026-12-01", "effective_quote": "by 4% from 1st Dec 2026 on the attached list",
        "reason": "raw material costs", "reason_quote": "Due to the continued rise in raw material costs (oat extract, surfactants and packaging film)",
        "codes": ["GW-01", "GW-03", "GW-04", "GW-05", "GW-06"],
        "sweeteners": [{"id": "s1", "kind": "support_if_full_acceptance", "support_pct": 2, "source": "email", "quote": "we will give an extra 2% marketing support if you take the full revision"}],
    },
    "PR-002": {
        "effective_date": "2026-12-01", "effective_quote": "effective 1st Dec 2026",
        "reason": "raw material costs", "reason_quote": "due to raw material costs (resin, nylon webbing, imported packaging)",
        "codes": ["TW-01", "TW-02", "TW-04", "TW-06"],
        "sweeteners": [{"id": "s1", "kind": "absorb_if_volume", "share_pct": 50, "threshold_units": 1500, "window_days": 30, "scope": [], "source": "email",
                        "quote": "we will absorb half of the revision across the range if you commit 1,500 units/month"}],
    },
    "PR-003": {
        "effective_date": "2026-11-10", "effective_quote": "from 10th Nov 2026",
        "reason": "meat, fish and packaging costs", "reason_quote": "Because of higher meat, fish and packaging costs",
        "codes": ["NP-01", "NP-02", "NP-04", "NP-05"], "sweeteners": [],
    },
}
PLANTED = {"PR-003": "NP-02"}  # the line whose new cost the mock model transposes on its first read


def read_lines(req_id: str, codes: list[str]) -> list[dict]:
    meta = json.loads((OUT / req_id / "meta.json").read_text())
    rows = (OUT / req_id / meta["price_list"]).read_text(encoding="utf-8").splitlines()
    out = []
    for code in codes:
        row = next(r for r in rows if r.startswith(code))
        if meta["price_list"].endswith(".csv"):
            cells = next(csv.reader([row]))
            old, new = (float(re.search(r"\d[\d,]*(?:\.\d+)?", c).group(0).replace(",", "")) for c in (cells[2], cells[3]))
        else:
            cols = row.split()
            old, new = float(cols[-3]), float(cols[-2])
        out.append({"sku_code": code, "old_cost": old, "new_cost": new, "source": "price_list", "quote": row})
    return out


def write_fixture(task: str, content: dict) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "parser_version": "1.0", "model": "muse-spark-1.3", "input_tokens": 0, "output_tokens": 0, "content": content}
    (FIXTURES / f"{task}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def transposed(x: float) -> float:
    s = f"{x:.2f}"
    return float(s[1] + s[0] + s[2:])


def write_mock_fixtures() -> None:
    for req_id, spec in READ.items():
        lines = read_lines(req_id, spec["codes"])
        planted = PLANTED.get(req_id)
        if planted:
            lines = [{**ln, "new_cost": transposed(ln["new_cost"])} if ln["sku_code"] == planted else ln for ln in lines]
        content = {k: spec[k] for k in ("effective_date", "effective_quote", "reason", "reason_quote")}
        content.update(lines=lines, sweeteners=spec["sweeteners"])
        write_fixture(f"price_request_{req_id}", content)
        if planted:
            right = read_lines(req_id, [planted])[0]
            write_fixture(f"price_request_{req_id}__fix1", {"fixes": [{"claim_id": f"{req_id}:line:{planted}:new_cost", "value": right["new_cost"], "transcript_quote": right["quote"]}]})


if __name__ == "__main__":
    main()
