"""Verifier eval: deterministic, no model. Plants known error classes in claims about a synthetic vendor sheet and call
transcript, runs them through the real verifier (``verify_claim`` plus the row-ownership rule the Decide agent applies),
and reports recall and precision per class.

Each class has N planted errors and N matched correct controls (same field, same shape, no error), so precision is
per class: of the claims the verifier flagged in that class, how many were really wrong.

Recall is reported twice: over every planted error, and over those whose error is larger than the playbook tolerance
for that unit. The verifier is built to accept anything within tolerance (rupee claims within ₹1, percentages within
1 point), so a transposition on a ₹12.50 item can pass; the second number says how much of the gap that explains."""

import random
from collections.abc import Callable
from dataclasses import dataclass

from app import policy
from app.agents import negotiate
from app.parsing import PARSER_VERSION
from app.schemas import Claim, Commitment, Evidence, NegotiateFinal, SourceRef
from app.verify import check_row_owner, file_sha256, verify_claim
from eval.sheets import (
    COST_HEADER,
    MRP_HEADER,
    PACK_HEADER,
    SHEET_REL,
    VENDOR,
    Row,
    Turn,
    World,
)

CLASSES = [
    ("digit_transposition", "Digit transposition"),
    ("decimal_shift", "Decimal shift"),
    ("unit_confusion", "kg vs g (or L vs ml)"),
    ("rs_vs_paise", "Rs vs paise"),
    ("wrong_row", "Wrong row"),
    ("wrong_column", "Wrong column"),
    ("rounding_beyond_tolerance", "Rounding beyond tolerance"),
    ("spelled_number", "Spelled-out number"),
]
LABEL = dict(CLASSES)


@dataclass
class Case:
    id: str
    klass: str
    claim: Claim
    code: str
    owner_row: int | None  # the sheet row that really owns the claimed SKU (None for transcript claims)
    planted: bool
    beyond_tolerance: bool  # the planted error is larger than the tolerance for its unit


def pipeline(case: Case) -> Claim:
    """What the agents do with a claim: verify it, then (sheet claims) check it cites its own SKU's row."""
    checked = verify_claim(case.claim)
    if case.owner_row is not None:
        checked = check_row_owner(checked, case.code, case.owner_row)
    return checked


def flagged(case: Case) -> bool:
    return pipeline(case).status != "verified"


# ---------- claim builders ----------


def _sheet_claim(row: Row, field: str, value: float, *, ev_row: int | None = None, ev_header: str | None = None) -> Claim:
    header = ev_header or {"cost": COST_HEADER, "mrp": MRP_HEADER, "pack_qty": PACK_HEADER}[field]
    return Claim(
        id=f"eval:{row.code}:{field}",
        text=f"{row.code} {field} is {value:g}",
        value=float(value),
        metric=field,
        unit="qty" if field == "pack_qty" else "inr",
        sku_key=f"{VENDOR}:{row.code}",
        source_ref=SourceRef(file=SHEET_REL, key=f"{VENDOR}:{row.code}", column=header),
        evidence=Evidence(
            row=ev_row or row.row, header=header, raw_value=None, normalized_value=float(value),
            parser_version=PARSER_VERSION, sha256=file_sha256(SHEET_REL),
        ),
        origin="model_extraction",
    )


def _truth(row: Row, field: str) -> float:
    return {"cost": row.cost, "mrp": row.mrp, "pack_qty": row.pack_qty or 0.0}[field]


def _tol(field: str) -> float:
    return policy.tol("qty" if field == "pack_qty" else "inr")


def _case(klass: str, i: int, row: Row, field: str, value: float, *, planted: bool, ev_row: int | None = None, ev_header: str | None = None) -> Case:
    claim = _sheet_claim(row, field, value, ev_row=ev_row, ev_header=ev_header)
    tag = "" if planted else "control:"
    return Case(f"{tag}{klass}:{i}", klass, claim, row.code, row.row, planted, planted and abs(value - _truth(row, field)) > _tol(field))


def swap_digits(rng: random.Random, value: float) -> float | None:
    """Swap two adjacent different digits of the number as written with two decimals: 956.50 -> 965.50."""
    digits = list(f"{value:.2f}".replace(".", ""))
    spots = [i for i in range(len(digits) - 1) if digits[i] != digits[i + 1]]
    if not spots:
        return None
    i = rng.choice(spots)
    digits[i], digits[i + 1] = digits[i + 1], digits[i]
    text = "".join(digits)
    out = float(f"{text[:-2]}.{text[-2:]}")
    return out if abs(out - value) > 1e-9 else None


Plant = Callable[[random.Random, World, int], Case | None]


def _money_row(rng: random.Random, world: World) -> tuple[Row, str]:
    return rng.choice(world.rows), rng.choice(["cost", "mrp"])


def plant_transposition(rng: random.Random, world: World, i: int) -> Case | None:
    row, field = _money_row(rng, world)
    wrong = swap_digits(rng, _truth(row, field))
    return None if wrong is None else _case("digit_transposition", i, row, field, wrong, planted=True)


def plant_decimal_shift(rng: random.Random, world: World, i: int) -> Case | None:
    row, field = _money_row(rng, world)
    wrong = round(_truth(row, field) * rng.choice([10, 0.1]), 2)
    return _case("decimal_shift", i, row, field, wrong, planted=True)


def plant_unit_confusion(rng: random.Random, world: World, i: int) -> Case | None:
    rows = [r for r in world.rows if r.pack_qty and r.pack_unit in ("grams", "ml")]
    row = rng.choice(rows)
    wrong = round(row.pack_qty / 1000, 4) if rng.random() < 0.6 else row.pack_qty * 1000  # type: ignore[operator]
    return _case("unit_confusion", i, row, "pack_qty", wrong, planted=True)


def plant_paise(rng: random.Random, world: World, i: int) -> Case | None:
    row, field = _money_row(rng, world)
    return _case("rs_vs_paise", i, row, field, round(_truth(row, field) * 100, 2), planted=True)


def plant_wrong_row(rng: random.Random, world: World, i: int) -> Case | None:
    row, field = _money_row(rng, world)
    other = rng.choice([r for r in world.rows if r.code != row.code])
    if rng.random() < 0.5:  # read the value off another row but cite this row
        return _case("wrong_row", i, row, field, _truth(other, field), planted=True)
    # cite another row (with its value): the cell is real, but it is not this SKU's
    case = _case("wrong_row", i, row, field, _truth(other, field), planted=True, ev_row=other.row)
    case.beyond_tolerance = True
    return case


def plant_wrong_column(rng: random.Random, world: World, i: int) -> Case | None:
    row, field = _money_row(rng, world)
    header = MRP_HEADER if field == "cost" else COST_HEADER
    case = _case("wrong_column", i, row, field, _truth(row, field), planted=True, ev_header=header)
    case.beyond_tolerance = abs(_truth(row, "mrp" if field == "cost" else "cost") - _truth(row, field)) > _tol(field)
    return case


def plant_rounding(rng: random.Random, world: World, i: int) -> Case | None:
    row, field = _money_row(rng, world)
    truth = _truth(row, field)
    step = 10 if truth >= 100 else 5
    wrong = float(round(truth / step) * step)
    if abs(wrong - truth) <= _tol(field):  # this class is rounding BEYOND tolerance; smaller roundings are the controls
        return None
    return _case("rounding_beyond_tolerance", i, row, field, wrong, planted=True)


def _commitment(turn: Turn, offered: float) -> Claim:
    final = NegotiateFinal(commitments=[Commitment(term=turn.term, offered=offered, transcript_quote=turn.quote, turn=turn.turn)])  # type: ignore[arg-type]
    claim = negotiate.commitment_claims("V002", final)[0]
    return claim.model_copy(update={"id": f"eval:turn{turn.turn}:{turn.term}"})


def plant_spelled(rng: random.Random, world: World, i: int) -> Case | None:
    turn = rng.choice([t for t in world.turns if t.spelled and t.value >= 10])
    wrong = swap_digits(rng, float(turn.value))
    wrong_int = None if wrong is None else round(wrong)
    if wrong_int is None or wrong_int == turn.value or not 10 <= wrong_int <= 99:
        return None
    tol = policy.tol("pct") * 100 if turn.term == "margin_pct" else policy.tol("units")
    return Case(f"spelled_number:{i}", "spelled_number", _commitment(turn, wrong_int), "turn", None, True, abs(wrong_int - turn.value) > tol)


PLANTERS: dict[str, Plant] = {
    "digit_transposition": plant_transposition,
    "decimal_shift": plant_decimal_shift,
    "unit_confusion": plant_unit_confusion,
    "rs_vs_paise": plant_paise,
    "wrong_row": plant_wrong_row,
    "wrong_column": plant_wrong_column,
    "rounding_beyond_tolerance": plant_rounding,
    "spelled_number": plant_spelled,
}


def control(rng: random.Random, world: World, klass: str, i: int) -> Case:
    """A correct claim shaped like the class it is matched to."""
    if klass == "spelled_number":
        turn = rng.choice(world.turns)
        return Case(f"control:{klass}:{i}", klass, _commitment(turn, float(turn.value)), "turn", None, False, False)
    if klass == "unit_confusion":
        row = rng.choice([r for r in world.rows if r.pack_qty])
        return _case(klass, i, row, "pack_qty", row.pack_qty, planted=False)  # type: ignore[arg-type]
    row, field = _money_row(rng, world)
    value = _truth(row, field)
    if klass == "rounding_beyond_tolerance":  # rounded, but inside the tolerance: the verifier must accept it
        value += rng.choice([-0.4, -0.2, 0.0, 0.3, 0.45])
    return _case(klass, i, row, field, value, planted=False)


def generate(world: World, seed: int = 42, per_class: int = 25) -> list[Case]:
    rng = random.Random(seed)
    cases: list[Case] = []
    for klass, _ in CLASSES:
        made = 0
        while made < per_class:
            case = PLANTERS[klass](rng, world, made)
            if case is not None:
                cases.append(case)
                made += 1
        cases += [control(rng, world, klass, n) for n in range(per_class)]
    return cases


# ---------- scoring ----------


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def run(world: World, seed: int = 42, per_class: int = 25) -> dict:
    cases = generate(world, seed, per_class)
    rows = []
    totals = {"planted": 0, "caught": 0, "beyond": 0, "caught_beyond": 0, "controls": 0, "fp": 0}
    for klass, label in CLASSES:
        planted = [c for c in cases if c.klass == klass and c.planted]
        controls = [c for c in cases if c.klass == klass and not c.planted]
        caught = [c for c in planted if flagged(c)]
        beyond = [c for c in planted if c.beyond_tolerance]
        caught_beyond = [c for c in beyond if flagged(c)]
        false_pos = [c for c in controls if flagged(c)]
        rows.append(
            {
                "class": klass,
                "label": label,
                "planted": len(planted),
                "caught": len(caught),
                "recall": _rate(len(caught), len(planted)),
                "beyond_tolerance": len(beyond),
                "caught_beyond_tolerance": len(caught_beyond),
                "recall_beyond_tolerance": _rate(len(caught_beyond), len(beyond)),
                "controls": len(controls),
                "false_positives": len(false_pos),
                "precision": _rate(len(caught), len(caught) + len(false_pos)),
                "missed": [c.id for c in planted if c not in caught][:5],
            }
        )
        for key, n in (("planted", len(planted)), ("caught", len(caught)), ("beyond", len(beyond)), ("caught_beyond", len(caught_beyond)), ("controls", len(controls)), ("fp", len(false_pos))):
            totals[key] += n
    return {
        "seed": seed,
        "per_class": per_class,
        "tolerances": policy.get().verifier.tolerances.model_dump(),
        "classes": rows,
        "overall": {
            "planted": totals["planted"],
            "caught": totals["caught"],
            "recall": _rate(totals["caught"], totals["planted"]),
            "recall_beyond_tolerance": _rate(totals["caught_beyond"], totals["beyond"]),
            "controls": totals["controls"],
            "false_positives": totals["fp"],
            "precision": _rate(totals["caught"], totals["caught"] + totals["fp"]),
        },
    }
