"""Synthetic vendor world for the eval: a messy SKU sheet and a call transcript with known ground truth.

The files are written under a throwaway data root that is swapped into ``settings.data_dir``, so the real verifier
(``app.verify``) reads them exactly as it reads the shipped data, hash check included."""

import csv
import json
import random
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.parsing import parse_pack, parse_price

VENDOR = "V001"
CALL_VENDOR = "V002"
HEADERS = ["Code", "Product Name", "Pack", "MRP", "Cost to Us"]
COST_HEADER, MRP_HEADER, PACK_HEADER = "Cost to Us", "MRP", "Pack"
SHEET_REL = f"vendors/{VENDOR}/sku_sheet.csv"
TRANSCRIPT_REL = f"vendors/{CALL_VENDOR}/call_transcript.json"

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}


def spell(n: int) -> str:
    """0-99 in words, the way a transcript spells it: 'twenty-one'."""
    if n < 20:
        return _ONES[n]
    tens, ones = (n // 10) * 10, n % 10
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


@dataclass(frozen=True)
class Row:
    row: int  # 1-based sheet row; the header is row 1
    code: str
    cost: float
    mrp: float
    pack_qty: float | None
    cost_cell: str
    mrp_cell: str
    pack_cell: str
    pack_unit: str  # grams | ml | units


@dataclass(frozen=True)
class Turn:
    turn: int
    term: str  # margin_pct | payment_days | returns
    value: int
    spelled: bool
    quote: str


@dataclass
class World:
    root: Path
    rows: list[Row]
    turns: list[Turn]
    by_code: dict[str, Row] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.by_code = {r.code: r for r in self.rows}


def _price_cell(rng: random.Random, value: float) -> str:
    style = rng.choice(["rs", "plain", "rupee", "inr", "fixed"])
    if style == "rs":
        return f"Rs. {value:.2f}"
    if style == "rupee":
        return f"₹{value:,.2f}".replace(".00", "")
    if style == "inr":
        return f"INR {value:g}"
    if style == "fixed":
        return f"{value:,.2f}"
    return f"{value:g}"


def _pack_cell(rng: random.Random) -> str:
    kind = rng.choice(["kg", "g", "ml", "l", "pack"])
    if kind == "kg":
        return f"{rng.choice([0.5, 1, 1.5, 2, 3, 5, 10, 15]):g}kg"
    if kind == "g":
        return f"{rng.choice([70, 85, 150, 200, 400, 500, 1000, 6000])} g"
    if kind == "ml":
        return f"{rng.choice([100, 200, 250, 500, 750])} ml"
    if kind == "l":
        return f"{rng.choice([1, 2, 5])} L"
    return f"Pack of {rng.choice([2, 3, 4, 6, 12])}"


def _rows(rng: random.Random, n: int) -> list[Row]:
    rows = []
    for i in range(n):
        tier = rng.random()
        cost = round(rng.uniform(8, 60) * 2) / 2 if tier < 0.1 else round(rng.uniform(1500, 6000) * 2) / 2 if tier < 0.3 else round(rng.uniform(80, 1500) * 2) / 2
        mrp = round(cost * rng.uniform(1.2, 2.2))
        cost_cell, mrp_cell, pack_cell = _price_cell(rng, cost), _price_cell(rng, float(mrp)), _pack_cell(rng)
        pack = parse_pack(pack_cell)
        unit = "grams" if "grams" in pack else "ml" if "ml" in pack else "units"
        qty = pack.get(unit)
        rows.append(
            Row(
                row=i + 2,
                code=f"EV-{i + 1:03d}",
                cost=parse_price(cost_cell) or cost,
                mrp=parse_price(mrp_cell) or float(mrp),
                pack_qty=float(qty) if isinstance(qty, int | float) else None,
                cost_cell=cost_cell,
                mrp_cell=mrp_cell,
                pack_cell=pack_cell,
                pack_unit=unit,
            )
        )
    return rows


_TEMPLATES = {
    "margin_pct": ["We can offer {n} percent margin on the full range.", "I can move to {n} percent if you take everything."],
    "payment_days": ["We can give you {n} days of credit on the first order.", "Payment in {n} days works for us."],
    "returns": ["Defective units can be returned within {n} days.", "We accept defect returns for {n} days after delivery."],
}


def _turns(rng: random.Random, n: int) -> list[Turn]:
    turns = []
    for i in range(n):
        term = rng.choice(list(_TEMPLATES))
        value = rng.choice([10, 12, 14, 15, 18, 21, 24, 25, 28, 30, 32, 35, 36, 42, 45, 48, 52, 60, 64, 75, 90])
        spelled = rng.random() < 0.6
        text = rng.choice(_TEMPLATES[term]).format(n=spell(value) if spelled else value)
        turns.append(Turn(turn=i + 1, term=term, value=value, spelled=spelled, quote=text))
    return turns


def build_world(root: Path, seed: int = 42, n_rows: int = 80, n_turns: int = 80) -> World:
    rng = random.Random(seed)
    rows, turns = _rows(rng, n_rows), _turns(rng, n_turns)
    sheet = root / SHEET_REL
    sheet.parent.mkdir(parents=True, exist_ok=True)
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADERS)
        for r in rows:
            writer.writerow([r.code, f"Eval product {r.code}", r.pack_cell, r.mrp_cell, r.cost_cell])
    call = root / TRANSCRIPT_REL
    call.parent.mkdir(parents=True, exist_ok=True)
    call.write_text(
        json.dumps([{"turn": t.turn, "speaker": "vendor", "text": t.quote} for t in turns], ensure_ascii=False), encoding="utf-8"
    )
    return World(root=root, rows=rows, turns=turns)


@contextmanager
def data_root(tmp: Path, seed: int = 42, **kw: int) -> Iterator[World]:
    """Build the world under ``tmp`` and point the verifier's data directory at it for the duration."""
    saved = settings.data_dir
    world = build_world(tmp, seed, **kw)
    settings.data_dir = tmp
    try:
        yield world
    finally:
        settings.data_dir = saved
