#!/usr/bin/env python3
"""Synthetic operations data for CategoryOS "Run" (existing vendors). All data FICTIONAL, INR.

Usage: python3 data/generate_ops.py   (stdlib only, deterministic: seed 42, byte-identical on re-run)
Writes data/synthetic/ops/. Separate from generate.py on purpose (that file is edited on other branches).

Six existing vendors, 13 weeks of daily sales per SKU, inventory batches, open and closed PO lines, returns,
weekly ratings and a few messy vendor email replies. Issues are planted on purpose (see PLANTED below)."""

import csv
import json
import os
import random
from datetime import date, timedelta

SEED = 42
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "synthetic", "ops")

AS_OF = date(2026, 10, 26)  # Monday: "today" for the Run module
DATA_END = AS_OF - timedelta(days=1)  # last day with sales (Sunday)
WEEKS = 13
DAYS = WEEKS * 7
START = DATA_END - timedelta(days=DAYS - 1)  # a Monday

WEEKDAY = [0.95, 0.95, 1.0, 1.0, 1.05, 1.12, 0.93]  # Monday..Sunday

# id, name, brand, contact, email, category, lead_time_days
VENDORS = [
    ("E001", "Barkley Foods Pvt Ltd", "Barkley & Co", "Anil Rao", "orders@barkley.example", "dog food", 7),
    ("E002", "Purrline Nutrition LLP", "Purrline Foods", "Rakesh Shah", "dispatch@purrline.example", "cat food", 10),
    ("E003", "NutriPaws Snacks Pvt Ltd", "NutriPaws", "Meera Iyer", "supply@nutripaws.example", "treats", 6),
    ("E004", "Tailwind Play Co", "Tailwind Play", "Vikram Sethi", "sales@tailwindplay.example", "toys and accessories", 14),
    ("E005", "Litterly Products", "Litterly", "Sanjay Kulkarni", "ops@litterly.example", "cat litter", 8),
    ("E006", "Groomwell Care Pvt Ltd", "Groomwell", "Neha Bhatt", "care@groomwell.example", "grooming", 9),
]

# code, vendor, name, mrp, cost, base units/day, trend per week (fraction), on hand units (None: set below)
SKUS = [
    ("BK-01", "E001", "Chicken & Rice Adult 3 kg", 1050, 760, 14, 0.00),
    ("BK-02", "E001", "Lamb & Rice Adult 3 kg", 1100, 800, 9, 0.00),
    ("BK-03", "E001", "Puppy Starter 1 kg", 420, 300, 18, 0.005),
    ("BK-04", "E001", "Senior Care 3 kg", 1150, 840, 6, 0.00),
    ("BK-05", "E001", "Chicken Gravy Pouch 100 g", 90, 62, 40, 0.00),
    ("BK-06", "E001", "Beef Pate Can 350 g", 190, 135, 16, 0.00),
    ("PL-01", "E002", "Ocean Fish Adult 1.2 kg", 640, 450, 16, 0.00),
    ("PL-02", "E002", "Chicken & Tuna Adult 1.2 kg", 660, 465, 13, 0.00),
    ("PL-03", "E002", "Kitten Starter 400 g", 290, 205, 12, 0.00),
    ("PL-04", "E002", "Indoor Hairball Care 1.2 kg", 680, 480, 10, 0.00),
    ("PL-05", "E002", "Tuna in Gravy Pouch 70 g", 55, 38, 45, 0.00),
    ("PL-06", "E002", "Mackerel Mousse Can 85 g", 75, 52, 25, 0.00),
    ("NP-01", "E003", "Chicken Strips 150 g", 229, 150, 30, 0.00),
    ("NP-02", "E003", "Dental Chew Sticks 150 g", 249, 165, 22, 0.00),
    ("NP-03", "E003", "Peanut Butter Biscuits 400 g", 499, 330, 55, 0.01),
    ("NP-04", "E003", "Training Bites 60 g", 110, 70, 38, 0.00),
    ("NP-05", "E003", "Tuna Cat Treats 60 g", 120, 78, 20, 0.00),
    ("NP-06", "E003", "Creamy Lick Treat 4 pack", 199, 130, 17, 0.00),
    ("TW-01", "E004", "Rope Tug Toy Large", 349, 210, 6, 0.00),
    ("TW-02", "E004", "Squeaky Plush Duck", 299, 180, 7, 0.00),
    ("TW-03", "E004", "Feather Wand Teaser", 249, 150, 2, 0.00),
    ("TW-04", "E004", "Adjustable Harness Medium", 599, 360, 2.5, 0.00),
    ("TW-05", "E004", "Printed Bandana Set", 199, 110, 1.5, 0.00),
    ("TW-06", "E004", "Collapsible Travel Bowl", 249, 140, 9, 0.00),
    ("LT-01", "E005", "Clumping Bentonite Unscented 10 kg", 699, 480, 26, 0.00),
    ("LT-02", "E005", "Clumping Bentonite Lavender 10 kg", 729, 500, 15, 0.00),
    ("LT-03", "E005", "Tofu Litter Original 6 L", 549, 380, 12, 0.00),
    ("LT-04", "E005", "Activated Carbon Clumping 5 kg", 449, 310, 11, 0.00),
    ("LT-05", "E005", "Clumping Bentonite 5 kg", 399, 275, 28, 0.00),
    ("LT-06", "E005", "Litter Scoop Metal", 149, 85, 8, 0.00),
    ("GW-01", "E006", "Oatmeal Pet Shampoo 250 ml", 349, 190, 14, 0.00),
    ("GW-02", "E006", "Deshedding Brush", 449, 250, 9, 0.00),
    ("GW-03", "E006", "Paw Balm 50 g", 249, 130, 13, 0.00),
    ("GW-04", "E006", "Nail Clipper", 199, 105, 8, 0.00),
    ("GW-05", "E006", "Ear Cleaner 100 ml", 299, 160, 6, 0.00),
    ("GW-06", "E006", "Tick & Flea Comb", 179, 90, 7, 0.00),
]

# Target days of cover on hand today (None = healthy default drawn from the rng)
COVER_TARGET = {
    "NP-03": 0.4,  # PLANTED: hero SKU about to run out, balance of its PO is still a week and a half away
    "PL-01": 6.0,  # PLANTED: low cover while the vendor's fill rate is falling
    "TW-01": 28.0, "TW-02": 24.0, "TW-06": 30.0,
    "TW-03": 150.0, "TW-04": 140.0, "TW-05": 260.0,  # PLANTED: slow movers, ageing inventory
    "LT-05": 5.0,  # E005's PO is past due: cover is tightening
}

AGED_BATCHES = {  # PLANTED ageing: extra batches received long ago (days ago, share of stock)
    "TW-03": [(130, 0.6), (75, 0.25)],
    "TW-04": [(118, 0.55), (66, 0.3)],
    "TW-05": [(150, 0.7), (95, 0.2)],
}

RETURN_REASONS = ["damaged in transit", "wrong item sent", "customer changed mind", "quality not as expected", "packaging leaked", "expired or near expiry"]


def rnd(rng: random.Random):
    return rng.random()


def daterange(start: date, n: int):
    for i in range(n):
        yield start + timedelta(days=i)


def write_csv(path: str, header: list[str], rows: list[list]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------------------------------------------------------------- sales
def gen_sales(rng: random.Random):
    rows = []
    daily: dict[str, dict[date, int]] = {}
    for code, vendor, _name, mrp, _cost, base, trend in SKUS:
        sell = round(mrp * 0.92)  # selling price a little under MRP
        series = {}
        for i, d in enumerate(daterange(START, DAYS)):
            week = i // 7
            level = base * (1 + trend * week)
            day = DAYS - 1 - i  # 0 = last day
            if code == "BK-02" and day < 7:
                level *= 1.9  # PLANTED: promo-driven spike in the review week
            if code == "GW-03" and day < 7:
                level *= 0.45  # PLANTED: sales fall off in the review week
            if code == "NP-03" and day < 2:
                level *= [0.12, 0.35][day]  # stock nearly gone: sales choke in the last two days
            units = max(0, round(level * WEEKDAY[d.weekday()] * rng.gauss(1.0, 0.06) + rng.gauss(0, 0.4)))
            series[d] = units
            rows.append([d.isoformat(), code, units, units * sell])
        daily[code] = series
    return rows, daily


# ---------------------------------------------------------------- inventory
def gen_inventory(rng: random.Random, daily):
    rows = []
    on_hand: dict[str, int] = {}
    for code, _v, _n, _mrp, _cost, base, _t in SKUS:
        recent = sum(daily[code][d] for d in daterange(DATA_END - timedelta(days=27), 28)) / 28
        cover = COVER_TARGET.get(code)
        if cover is None:
            cover = 18 + rnd(rng) * 22  # healthy: 18 to 40 days
        units = max(0, round(recent * cover))
        if code == "NP-03":
            units = 22
        on_hand[code] = units
        splits = AGED_BATCHES.get(code)
        if splits:
            remaining = units
            for age, share in splits:
                part = round(units * share)
                rows.append([code, (AS_OF - timedelta(days=age)).isoformat(), part])
                remaining -= part
            rows.append([code, (AS_OF - timedelta(days=20)).isoformat(), max(remaining, 0)])
        elif units:
            first = round(units * 0.7)
            rows.append([code, (AS_OF - timedelta(days=int(5 + rnd(rng) * 20))).isoformat(), first])
            rows.append([code, (AS_OF - timedelta(days=int(32 + rnd(rng) * 20))).isoformat(), units - first])
    return rows, on_hand


# ---------------------------------------------------------------- purchase orders
# Fill-rate profile by promised-week index (0 oldest .. 12 latest) per vendor: (fill, late-days maximum)
def profile(vendor: str, week: int, rng: random.Random):
    if vendor == "E002":  # PLANTED: falling fill rate and slipping dates
        fill = 0.98 if week < 8 else {8: 0.91, 9: 0.84, 10: 0.78, 11: 0.72, 12: 0.68}[week]
        late = 1 if week < 8 else 3 + (week - 8)
    elif vendor == "E003":
        fill, late = 0.95, 1
    elif vendor == "E004":
        fill, late = 0.97, 3  # reliable fill, often late
    else:
        fill, late = 0.985, 1
    return min(1.0, max(0.0, fill + rng.gauss(0, 0.012))), late


def line_fill(vendor: str, week: int, fill: float, rng: random.Random) -> float:
    if vendor == "E002" and week >= 8:
        return min(1.0, max(0.0, fill + rng.gauss(0, 0.03)))
    if rnd(rng) < (0.8 if vendor == "E003" else 0.9):
        return 1.0
    return rng.uniform(0.85, 0.97)


def gen_pos(rng: random.Random):
    """Closed PO lines, plus planted open POs. Returns (rows, po meta list)."""
    rows = []
    skus_by_vendor: dict[str, list[tuple]] = {}
    for s in SKUS:
        skus_by_vendor.setdefault(s[1], []).append(s)
    seq = {v[0]: 0 for v in VENDORS}
    for vid, _n, _b, _c, _e, _cat, lead in VENDORS:
        cadence = 7 if vid == "E002" else 9 if vid in ("E001", "E003") else 12
        promised = START + timedelta(days=lead + 2)
        while promised < AS_OF - timedelta(days=4):
            po_date = promised - timedelta(days=lead)
            week = min(WEEKS - 1, (promised - START).days // 7)
            fill, late = profile(vid, week, rng)
            seq[vid] += 1
            po_id = f"PO-{vid}-{seq[vid]:04d}"
            chosen = rng.sample(skus_by_vendor[vid], 3)
            if vid == "E004":
                delay = 0 if rnd(rng) < 0.75 else 2 + int(rnd(rng) * late)
            else:
                delay = int(rnd(rng) * (late + 1))
            actual = promised + timedelta(days=delay)
            if actual >= AS_OF:  # still open: handled by the planted open POs below
                promised += timedelta(days=cadence)
                seq[vid] -= 1
                continue
            for s in chosen:
                base_qty = max(40, round(s[5] * 28 / 10) * 10)
                got = round(base_qty * line_fill(vid, week, fill, rng))
                rows.append([po_id, vid, s[0], base_qty, got, po_date.isoformat(), promised.isoformat(), actual.isoformat(), "closed"])
            promised += timedelta(days=cadence)
    return rows, seq


def open_pos(seq: dict[str, int]):
    """PLANTED open POs. One row each: po, vendor, sku, ordered, received so far, po date, promised, actual, status."""
    def nxt(v: str) -> str:
        seq[v] += 1
        return f"PO-{v}-{seq[v]:04d}"

    d = lambda s: date.fromisoformat(s).isoformat()  # noqa: E731
    rows = []
    # E001: on track, confirmed by the vendor
    po = nxt("E001")
    rows += [[po, "E001", "BK-01", 400, 0, d("2026-10-20"), d("2026-10-29"), "", "open"], [po, "E001", "BK-05", 1200, 0, d("2026-10-20"), d("2026-10-29"), "", "open"]]
    # E002: overdue two days, transporter excuse, falling fill rate; PL-01 cover is tight
    po = nxt("E002")
    rows += [[po, "E002", "PL-01", 500, 0, d("2026-10-14"), d("2026-10-24"), "", "open"], [po, "E002", "PL-05", 1400, 0, d("2026-10-14"), d("2026-10-24"), "", "open"]]
    # E003: hero SKU, partial shipment received, balance promised for 3 Nov (PLANTED stock-out)
    po = nxt("E003")
    rows += [[po, "E003", "NP-03", 900, 300, d("2026-10-14"), d("2026-10-20"), "", "open"], [po, "E003", "NP-01", 700, 700, d("2026-10-14"), d("2026-10-20"), d("2026-10-23"), "closed"]]
    # E004: reply promises a later date than the PO (5-6 working days)
    po = nxt("E004")
    rows += [[po, "E004", "TW-06", 300, 0, d("2026-10-12"), d("2026-10-27"), "", "open"], [po, "E004", "TW-02", 200, 0, d("2026-10-12"), d("2026-10-27"), "", "open"]]
    # E005: PLANTED past due a week, two vague replies
    po = nxt("E005")
    rows += [[po, "E005", "LT-05", 700, 0, d("2026-10-10"), d("2026-10-19"), "", "open"], [po, "E005", "LT-01", 600, 0, d("2026-10-10"), d("2026-10-19"), "", "open"]]
    # E006: not due yet, no reply needed
    po = nxt("E006")
    rows += [[po, "E006", "GW-01", 350, 0, d("2026-10-22"), d("2026-10-31"), "", "open"]]
    return rows


# ---------------------------------------------------------------- returns, ratings
def gen_returns(rng: random.Random, daily):
    rows = []
    for code, *_ in SKUS:
        rate = 0.012
        if code == "GW-02":
            rate = 0.012
        for i, d in enumerate(daterange(START, DAYS)):
            week = i // 7
            r = rate
            if code == "GW-02" and week >= 9:
                r = 0.11  # PLANTED: returns jump for four weeks (leaking / damaged)
            n = sum(1 for _ in range(daily[code][d]) if rnd(rng) < r)
            if n:
                reason = "packaging leaked" if code == "GW-02" and week >= 9 else rng.choice(RETURN_REASONS)
                rows.append([d.isoformat(), code, n, reason])
    return rows


def gen_ratings(rng: random.Random):
    rows = []
    for code, *_ in SKUS:
        level = 4.0 + rnd(rng) * 0.5
        for w in range(WEEKS):
            val = level + rng.gauss(0, 0.03)
            if code == "GW-02" and w >= 9:
                val = level - 0.2 * (w - 8)  # PLANTED: rating slides with the returns
            if code == "PL-04" and w >= 10:
                val = level - 0.1 * (w - 9)
            rows.append([(START + timedelta(days=7 * w + 6)).isoformat(), code, f"{round(min(5.0, val), 2):.2f}"])
    return rows


# ---------------------------------------------------------------- vendor replies (messy free text)
REPLIES = [
    {
        "id": "R001", "po_id": "PO-E001-%s", "vendor_id": "E001", "received_at": "2026-10-22T10:14:00",
        "from": "Anil Rao <orders@barkley.example>", "subject": "RE: PO %s",
        "body": "Hi team,\n\nPO received and confirmed. We will deliver on 29th Oct as per PO, qty 400 bags BK-01 and 1200 pouches BK-05 as ordered.\n\nRegards\nAnil Rao\nBarkley Foods",
    },
    {
        "id": "R002", "po_id": "PO-E002-%s", "vendor_id": "E002", "received_at": "2026-10-26T09:41:00",
        "from": "Rakesh Shah <dispatch@purrline.example>", "subject": "RE: Re: PO %s - delay??",
        "body": "Dear Sir/Madam,\n\nSorry for delay, our transporter had strike in Pune since Friday and truck could not move. Truck is loaded now and left tonite. Will reach by Thursday for sure. Only 350 pcs of PL-01 can be sent in this lot, remaining we are short of raw material (fish meal supplier problem). Pls bear with us.\n\nThanks & regards\nRakesh Shah\nPurrline Nutrition LLP",
    },
    {
        "id": "R003", "po_id": "PO-E003-%s", "vendor_id": "E003", "received_at": "2026-10-23T17:05:00",
        "from": "Meera Iyer <supply@nutripaws.example>", "subject": "NP-03 shipment update",
        "body": "Hello,\n\nDispatched 300 units of NP-03 today via Delhivery (docket DL88213). Balance 600 units is still under production, oven line was down 3 days. We will ship the balance by 3rd Nov. Kindly adjust.\n\nBest,\nMeera",
    },
    {
        "id": "R004", "po_id": "PO-E004-%s", "vendor_id": "E004", "received_at": "2026-10-22T12:30:00",
        "from": "Vikram Sethi <sales@tailwindplay.example>", "subject": "RE: PO %s",
        "body": "PO acknowledged. Fabric for plush duck is awaited from mill so dispatch will take approx 5-6 working days from today. Bowls are ready. Will update.\n\nVikram\nTailwind Play",
    },
    {
        "id": "R005", "po_id": "PO-E005-%s", "vendor_id": "E005", "received_at": "2026-10-14T15:20:00",
        "from": "Sanjay Kulkarni <ops@litterly.example>", "subject": "RE: PO %s",
        "body": "Dear Sir, we have received your PO and processing. Dispatch will be done next week. Thank you.\n\nSanjay",
    },
    {
        "id": "R006", "po_id": "PO-E005-%s", "vendor_id": "E005", "received_at": "2026-10-23T11:02:00",
        "from": "Sanjay Kulkarni <ops@litterly.example>", "subject": "RE: RE: PO %s - URGENT",
        "body": "Dear Sir,\n\nMaterial is under dispatch preparation and will be sent shortly. Some issue with packing material but we are working on it. Will revert with tracking details soon. Thank you for your patience.\n\nRegards\nSanjay Kulkarni\nLitterly Products",
    },
    {
        "id": "R007", "po_id": "PO-E006-%s", "vendor_id": "E006", "received_at": "2026-10-23T09:00:00",
        "from": "Neha Bhatt <care@groomwell.example>", "subject": "PO acknowledgement",
        "body": "Hi, PO noted for 350 shampoo bottles. Everything on track, ready by 31st Oct.\n\nNeha",
    },
]


def main() -> None:
    rng = random.Random(SEED)
    sales_rows, daily = gen_sales(rng)
    inv_rows, _ = gen_inventory(rng, daily)
    po_rows, seq = gen_pos(rng)
    po_rows += open_pos(seq)
    ret_rows = gen_returns(rng, daily)
    rating_rows = gen_ratings(rng)

    write_json(os.path.join(OUT, "meta.json"), {
        "as_of": AS_OF.isoformat(),
        "data_start": START.isoformat(),
        "data_end": DATA_END.isoformat(),
        "weeks": WEEKS,
        "currency": "INR",
        "note": "Synthetic. Generated by data/generate_ops.py (seed 42).",
    })
    write_json(os.path.join(OUT, "vendors.json"), [
        {"id": v[0], "company_name": v[1], "brand": v[2], "contact_name": v[3], "contact_email": v[4], "category": v[5], "lead_time_days": v[6]}
        for v in VENDORS
    ])
    write_csv(os.path.join(OUT, "skus.csv"), ["sku_code", "vendor_id", "name", "mrp", "cost", "selling_price"],
              [[s[0], s[1], s[2], s[3], s[4], round(s[3] * 0.92)] for s in SKUS])
    write_csv(os.path.join(OUT, "sales_daily.csv"), ["date", "sku_code", "units", "gmv"], sales_rows)
    write_csv(os.path.join(OUT, "inventory_batches.csv"), ["sku_code", "received_date", "units"], inv_rows)
    write_csv(os.path.join(OUT, "purchase_orders.csv"),
              ["po_id", "vendor_id", "sku_code", "ordered_qty", "received_qty", "po_date", "promised_date", "actual_date", "status"], po_rows)
    write_csv(os.path.join(OUT, "returns.csv"), ["date", "sku_code", "units", "reason"], ret_rows)
    write_csv(os.path.join(OUT, "ratings.csv"), ["date", "sku_code", "rating"], rating_rows)

    open_ids = {}
    for r in po_rows:
        if r[8] == "open":
            open_ids.setdefault(r[1], r[0])
    replies = []
    for r in REPLIES:
        po = open_ids[r["vendor_id"]]
        replies.append({**r, "po_id": po, "subject": r["subject"] % po if "%s" in r["subject"] else r["subject"]})
    write_json(os.path.join(OUT, "vendor_replies.json"), replies)
    print(f"ops data written to {OUT}: {len(sales_rows)} sales rows, {len(po_rows)} PO lines, {len(replies)} replies")


if __name__ == "__main__":
    main()
