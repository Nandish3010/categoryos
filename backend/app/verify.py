"""Claim verifier. Never imports llm. Engine claims are recomputed by the metrics engine;
model-extraction claims are checked against a freshly parsed RAW sheet cell, never against the
model's own evidence.raw_value."""

import hashlib
import posixpath
import re
from pathlib import Path

from pydantic import BaseModel

from app.config import settings
from app.constants import ALLOWED_VENDORS, GST_RATE, TOL
from app.data_loader import load_sheet, load_transcript
from app.errors import CategoryOSError
from app.metrics import METRIC_UNITS, apply_levers, build_base, compute_metric
from app.parsing import PARSER_VERSION, map_columns, parse_pack, parse_price
from app.schemas import Claim, Evidence, LeverResponse, SourceRef
from app.util import fmt_inr, fmt_pct

VENDOR_METRICS = {"capital_at_risk_inr": "inr", "po_total": "inr", "po_grand_total": "inr"}
COMMIT_METRICS = {
    "commit_margin_pct": "pct",
    "commit_payment_days": "units",
    "commit_moq": "units",
    "commit_marketing_inr": "inr",
    "commit_launch_discount_pct": "pct",
    "commit_returns": "units",
}
EXTRACTION_METRICS = {"pack_qty": "qty"}
_TRANSCRIPT = re.compile(r"^vendors/(V00[1-4])/call_transcript\.json$")
_VENDOR_SHEET = re.compile(r"^vendors/(V00[1-4])/sku_sheet\.csv$")
_PCT_CELL = re.compile(r"(\d+(?:\.\d+)?)\s*%")

METRIC_FILE = {
    "price_gap_pct": "market/competitor_listings.csv",
    "demand_score": "market/search_demand.csv",
    "overlap": "platform_catalog.csv",
}


class VerifySummary(BaseModel):
    total: int
    verified: int
    rejected: int
    unverifiable: int
    claims: list[Claim]


def allowed_sources() -> frozenset[str]:
    files = {
        "category_benchmarks.json",
        "platform_catalog.csv",
        "market/competitor_listings.csv",
        "market/search_demand.csv",
        "market/reviews.json",
    }
    for vid in ALLOWED_VENDORS:
        files.add(f"vendors/{vid}/sku_sheet.csv")
        files.add(f"vendors/{vid}/application.json")
        files.add(f"vendors/{vid}/call_transcript.json")
    return frozenset(files)


def _normalize(file: str) -> str:
    return posixpath.normpath(file.replace("\\", "/"))


def _resolve(file: str) -> Path | None:
    norm = _normalize(file)
    if norm not in allowed_sources():
        return None
    return Path(settings.data_dir) / norm


def file_sha256(file: str) -> str:
    path = _resolve(file)
    if path is None:
        raise ValueError(f"not allowlisted: {file}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finish(claim: Claim, status: str, reason: str | None, recomputed: float | None = None) -> Claim:
    if claim.origin == "injected_test":
        reason = f"Injected test: {reason or 'value unexpectedly matched'}"
    return claim.model_copy(update={"status": status, "reason": reason, "recomputed": recomputed})


def _parse_cell(raw: str, unit: str) -> float | None:
    if unit == "pct":
        match = _PCT_CELL.search(raw)
        return float(match.group(1)) / 100 if match else None
    if unit == "units":
        units = parse_pack(raw).get("units")
        return float(units) if isinstance(units, int | float) else parse_price(raw)
    if unit == "inr":
        return parse_price(raw)
    if unit == "qty":
        pack = parse_pack(raw)
        for key in ("grams", "ml", "units"):
            if isinstance(pack.get(key), int | float):
                return float(pack[key])  # type: ignore[arg-type]
    return None


def _recompute_engine(claim: Claim) -> float:
    if claim.metric in VENDOR_METRICS:
        vendor, _, query = claim.source_ref.key.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        moq = int(params["moq"]) if "moq" in params else None
        lever = apply_levers(build_base(vendor), float(params.get("offset", 0)), moq)
        if claim.metric in {"po_total", "po_grand_total"}:
            codes = [c for c in params.get("skus", "").split(",") if c]
            subtotal = round(sum(s.alloc_units * (s.cost or 0.0) for s in lever.skus if s.code in codes), 2)
            return subtotal if claim.metric == "po_total" else round(subtotal * (1 + GST_RATE), 2)
        return lever.summary.capital_at_risk_inr
    sku_key = claim.sku_key or claim.source_ref.key
    return compute_metric(sku_key.split(":", 1)[0], claim.metric, sku_key)


def _verify_extraction(claim: Claim, rel_file: str) -> Claim:
    ev = claim.evidence
    if ev is None or ev.row is None or not ev.header:
        return _finish(claim, "rejected", "no evidence: row and header are required")
    match = _VENDOR_SHEET.match(rel_file)
    if not match:
        return _finish(claim, "unverifiable", "extraction claims are only checked against vendor sku sheets")
    if file_sha256(rel_file) != ev.sha256:
        return _finish(claim, "rejected", "source changed: evidence sha256 does not match the file")
    _, rows = load_sheet(match.group(1))
    row = next((r for r in rows if r.row == ev.row), None)
    if row is None or ev.header not in row.cells:
        return _finish(claim, "rejected", f"evidence cell not found (row {ev.row}, header {ev.header!r})")
    raw = row.cells[ev.header]  # re-read from the sheet; ev.raw_value is deliberately ignored
    parsed = _parse_cell(raw, claim.unit)
    if parsed is None:
        return _finish(claim, "rejected", f"cell {raw!r} could not be parsed as {claim.unit}")
    if abs(parsed - claim.value) <= TOL[claim.unit]:
        return _finish(claim, "verified", None, parsed)
    return _finish(claim, "rejected", f"sheet cell {raw!r} parses to {parsed:g}, claim says {claim.value:g}", parsed)


_WORD_ONES = {w: i for i, w in enumerate(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
)}
_WORD_TENS = {w: 10 * i for i, w in enumerate(["x", "x", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]) if w != "x"}
_NUM_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?|[a-z]+(?:-[a-z]+)?", re.IGNORECASE)


def numbers_in(text: str) -> list[float]:
    """Numbers stated in a quote: digits (commas allowed) and spelled-out 0-99 ('Twenty-one')."""
    out: list[float] = []
    for tok in _NUM_TOKEN.findall(text):
        low = tok.lower()
        if tok[0].isdigit():
            out.append(float(tok.replace(",", "")))
        elif low in _WORD_ONES:
            out.append(float(_WORD_ONES[low]))
        elif low in _WORD_TENS:
            out.append(float(_WORD_TENS[low]))
        elif "-" in low:
            tens, _, ones = low.partition("-")
            if tens in _WORD_TENS and ones in _WORD_ONES and 0 < _WORD_ONES[ones] < 10:
                out.append(float(_WORD_TENS[tens] + _WORD_ONES[ones]))
    return out


def _squash(text: str) -> str:
    return " ".join(text.split())


def _verify_commitment(claim: Claim, rel_file: str) -> Claim:
    """A negotiation commitment: the quote must appear verbatim in the canonical transcript at the claimed turn,
    and the claimed number must be one of the numbers stated in that quote."""
    ev = claim.evidence
    if ev is None or ev.row is None or not ev.raw_value:
        return _finish(claim, "rejected", "no evidence: a transcript turn and a verbatim quote are required")
    if file_sha256(rel_file) != ev.sha256:
        return _finish(claim, "rejected", "source changed: evidence sha256 does not match the file")
    vendor = _TRANSCRIPT.match(rel_file).group(1)  # type: ignore[union-attr]
    turns = load_transcript(vendor) or []
    turn = next((t for t in turns if t.get("turn") == ev.row), None)
    if turn is None:
        return _finish(claim, "rejected", f"the transcript has no turn {ev.row}")
    quote = _squash(ev.raw_value)
    if quote not in _squash(str(turn.get("text", ""))):
        return _finish(claim, "rejected", f"the quote does not appear verbatim in turn {ev.row} of the canonical transcript")
    stated = numbers_in(quote)
    value = claim.value * 100 if claim.unit == "pct" else claim.value
    tol = TOL["pct"] * 100 if claim.unit == "pct" else TOL.get(claim.unit, 0.0)
    if not any(abs(n - value) <= max(tol, 1e-9) for n in stated):
        shown = ", ".join(f"{n:g}" for n in stated) or "none"
        return _finish(claim, "rejected", f"the quote states {shown}; the commitment says {value:g}", stated[0] if stated else None)
    return _finish(claim, "verified", None, claim.value)


def verify_claim(claim: Claim) -> Claim:
    rel_file = _normalize(claim.source_ref.file)
    if _resolve(claim.source_ref.file) is None:
        return _finish(claim, "rejected", f"unknown source: {rel_file!r} is not an allowlisted data file")
    unit = (
        METRIC_UNITS.get(claim.metric)
        or VENDOR_METRICS.get(claim.metric)
        or COMMIT_METRICS.get(claim.metric)
        or EXTRACTION_METRICS.get(claim.metric)
    )
    if unit is None:
        return _finish(claim, "unverifiable", f"unknown metric {claim.metric!r}")
    if claim.origin == "model_extraction":
        if _TRANSCRIPT.match(rel_file):
            return _verify_commitment(claim, rel_file)
        return _verify_extraction(claim, rel_file)
    if claim.evidence is not None and claim.evidence.sha256 != file_sha256(rel_file):
        return _finish(claim, "rejected", "source changed: evidence sha256 does not match the file")
    try:
        recomputed = _recompute_engine(claim)
    except CategoryOSError as exc:
        return _finish(claim, "rejected", f"cannot recompute: {exc.problem}")
    if abs(recomputed - claim.value) <= TOL[unit]:
        return _finish(claim, "verified", None, recomputed)
    return _finish(claim, "rejected", f"engine recomputed {recomputed:g}, claim says {claim.value:g}", recomputed)


def verify_all(claims: list[Claim]) -> VerifySummary:
    out = [verify_claim(c) for c in claims]

    def count(status: str) -> int:
        return sum(1 for c in out if c.status == status)

    return VerifySummary(
        total=len(out),
        verified=count("verified"),
        rejected=count("rejected"),
        unverifiable=count("unverifiable"),
        claims=out,
    )


def engine_claims(vendor_id: str, lever_response: LeverResponse) -> list[Claim]:
    sheet = f"vendors/{vendor_id}/sku_sheet.csv"
    sha = file_sha256(sheet)
    headers, _ = load_sheet(vendor_id)
    mrp_header = map_columns(headers).get("mrp")
    claims: list[Claim] = []
    for sku in lever_response.skus:
        if sku.verdict not in {"list", "negotiate"}:
            continue
        code = sku.code
        evidence = Evidence(
            row=sku.sheet_row,
            header=mrp_header,
            raw_value=sku.raw.get(mrp_header) if mrp_header else None,
            normalized_value=sku.mrp,
            parser_version=PARSER_VERSION,
            sha256=sha,
        )
        specs: list[tuple[str, float | None, str]] = [
            ("margin_pct", sku.margin_pct, f"{code} margin is {fmt_pct(sku.margin_pct or 0)}"),
            ("price_gap_pct", sku.price_gap_pct, f"{code} MRP is {fmt_pct(sku.price_gap_pct or 0)} vs competitors"),
            ("demand_score", sku.demand_score, f"{code} demand score is {sku.demand_score:.2f}"),
            ("overlap", sku.overlap, f"{code} catalog overlap is {sku.overlap:.2f}"),
        ]
        for metric, value, text in specs:
            if value is None:
                continue
            claims.append(
                Claim(
                    id=f"{sku.sku_key}:{metric}",
                    text=text,
                    value=float(value),
                    metric=metric,
                    unit=METRIC_UNITS[metric],  # type: ignore[arg-type]
                    sku_key=sku.sku_key,
                    source_ref=SourceRef(file=METRIC_FILE.get(metric, sheet), key=sku.sku_key, column=mrp_header),
                    evidence=None if metric in METRIC_FILE else evidence,
                    origin="engine",
                )
            )
    moq = lever_response.summary.moq
    capital = lever_response.summary.capital_at_risk_inr
    key = f"{vendor_id}?offset={lever_response.target_margin_pct_offset:g}&moq={moq}"
    claims.append(
        Claim(
            id=f"{vendor_id}:capital_at_risk_inr",
            text=f"Capital at risk for {vendor_id} is {fmt_inr(capital)} at MOQ {moq}",
            value=float(capital),
            metric="capital_at_risk_inr",
            unit="inr",
            source_ref=SourceRef(file=f"vendors/{vendor_id}/application.json", key=key, column="proposed_terms.moq_units"),
            origin="engine",
        )
    )
    return claims


def _transpose(value: float, unit: str) -> float:
    """Swap the first two digits of the displayed number: 31.36% -> 13.36%, 4999 -> 9499."""
    scaled = value * 100 if unit == "pct" else value
    chars = list(f"{abs(scaled):.2f}")
    if len(chars) > 1 and chars[1].isdigit() and chars[0] != chars[1]:
        chars[0], chars[1] = chars[1], chars[0]
        new = float("".join(chars))
    else:
        new = abs(scaled) + 7.0
    new = -new if scaled < 0 else new
    return round(new / 100, 4) if unit == "pct" else round(new, 2)


def inject_fault(claims: list[Claim], metric: str | None = None) -> list[Claim]:
    """Flip exactly one claim to a realistic wrong value (transposed digits; 0-1 ratios shift by 0.17).

    With ``metric`` set, the first eligible claim of that metric is flipped instead of the first overall."""
    out = list(claims)
    for i, claim in enumerate(out):
        if claim.unit not in ("pct", "inr", "ratio") or claim.origin != "engine":
            continue
        if metric is not None and claim.metric != metric:
            continue
        if claim.unit == "ratio":
            wrong = claim.value + 0.17 if claim.value <= 0.8 else claim.value - 0.17
        else:
            wrong = _transpose(claim.value, claim.unit)
        if abs(wrong - claim.value) <= 2 * TOL[claim.unit]:
            wrong = claim.value + (0.07 if claim.unit == "pct" else 111.0)
        text = claim.text
        if claim.unit == "ratio":
            text = text.replace(f"{claim.value:.2f}", f"{wrong:.2f}")
        elif claim.unit == "pct":
            text = text.replace(fmt_pct(claim.value), fmt_pct(wrong))
        elif claim.metric == "capital_at_risk_inr":
            text = text.replace(fmt_inr(claim.value), fmt_inr(wrong))
        out[i] = claim.model_copy(update={"value": round(wrong, 4), "origin": "injected_test", "text": text})
        break
    return out
