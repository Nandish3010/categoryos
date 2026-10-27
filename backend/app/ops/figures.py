"""Turning the numbers an agent wrote in prose into Claims, and checking that no number is left without one."""

import math
import re
import uuid
from datetime import date
from typing import Any

from app.agents.context import RunContext, Sequencer
from app.errors import CategoryOSError
from app.ops import claims as oc
from app.ops.data import load
from app.ops.schemas import Figure
from app.ops.verify import unclaimed_numbers
from app.parsing import PARSER_VERSION
from app.schemas import Claim, Evidence, SourceRef
from app.verify import VerifySummary, verify_all

STAGE = "ops"
_SHOWN = re.compile(r"^\s*([+-]?)\s*₹?\s*([+-]?)(\d[\d,]*(?:\.\d+)?)\s*(%|lakh|crore|k(?![a-z]))?", re.IGNORECASE)
_SCALE = {"lakh": 1e5, "crore": 1e7, "k": 1e3}


def parse_shown(shown: str, unit: str) -> tuple[float, float] | None:
    """(value in the claim's unit, half a unit of the last displayed digit) for a number as written in prose."""
    match = _SHOWN.match(shown)
    if not match:
        return None
    sign = -1.0 if "-" in (match.group(1) + match.group(2)) else 1.0
    digits = match.group(3).replace(",", "")
    suffix = (match.group(4) or "").lower()
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    number = float(digits)
    ulp = 0.5 * 10**-decimals
    if suffix == "%":
        return (sign * number / 100, ulp / 100) if unit == "pct" else None
    if unit == "pct":
        return None
    scale = _SCALE.get(suffix, 1.0)
    return sign * number * scale, ulp * scale + 1e-9


def figure_claim(fig: Figure, claim_id: str) -> Claim:
    """The claim for one figure. If the prose number disagrees with the engine, the prose number is what gets checked."""
    value = fig.value
    try:
        unit = oc.unit_of(fig.metric)
    except CategoryOSError:
        unit = "ratio"
    if fig.metric in oc.METRICS:
        parsed = parse_shown(fig.shown, unit)
        if parsed is not None:
            try:
                engine = oc.compute(fig.metric, fig.key)
            except (CategoryOSError, ValueError):
                engine = None
            signed = bool(re.match(r"^\s*[+-]", fig.shown)) or "-" in fig.shown.split(" ")[0]
            shown_value = parsed[0] if signed or engine is None else math.copysign(abs(parsed[0]), fig.value)  # "down 0.74 stars" has no sign in prose
            if engine is not None and abs(shown_value - engine) > parsed[1]:
                value = shown_value  # the prose says something the engine does not
        return oc.engine_claim(fig.metric, fig.key, fig.text, value=value, claim_id=claim_id)
    return Claim(  # an unregistered metric: kept so the verifier reports it unverifiable
        id=claim_id,
        text=fig.text,
        value=fig.value,
        metric=fig.metric,
        unit=unit,  # type: ignore[arg-type]
        source_ref=SourceRef(file=oc.SALES, key=fig.key, column=fig.metric),
        evidence=Evidence(parser_version=PARSER_VERSION, sha256=oc.data_sha()),
        origin="engine",
    )


def check_text(blocks: list[str], figures: list[Figure]) -> list[str]:
    """Numbers in the prose that no figure covers."""
    shown = [f.shown for f in figures]
    names = [s.name for s in load().skus.values()]
    found: list[str] = []
    for block in blocks:
        found += unclaimed_numbers(block, shown, names)
    return found


def summarize(claims: list[Claim]) -> dict[str, int]:
    s = verify_all(claims)
    return {"total": s.total, "verified": s.verified, "rejected": s.rejected, "unverifiable": s.unverifiable}


def counts(claims: list[Claim]) -> VerifySummary:
    def n(status: str) -> int:
        return sum(1 for c in claims if c.status == status)

    return VerifySummary(total=len(claims), verified=n("verified"), rejected=n("rejected"), unverifiable=n("unverifiable"), claims=claims)


# ---------- run context and trace ----------


def new_ctx(label: str, today: date) -> RunContext:
    return RunContext(run_id=f"ops-{label}-{uuid.uuid4().hex[:6]}", vendor_id="ops", today=today.isoformat(), sequencer=Sequencer())


def drain(ctx: RunContext) -> list[dict[str, Any]]:
    out = []
    while not ctx.queue.empty():
        e = ctx.queue.get_nowait()
        out.append(
            {
                "seq": e.seq,
                "t_rel_ms": e.t_rel_ms,
                "type": e.type,
                "stage": e.stage,
                "model": e.model,
                "latency_ms": e.latency_ms,
                "cost_usd": e.cost_usd,
                "payload": e.payload,
            }
        )
    return out


def emit_model_call(ctx: RunContext, task: str, res: Any) -> None:
    ctx.emit(
        "model_call",
        STAGE,
        {"task": task, "mode": res.mode, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": len(getattr(res, "steps", []))},
        model=res.model,
        latency_ms=res.latency_ms,
        cost_usd=res.cost_usd,
    )
    if res.degraded:
        ctx.emit("degraded", STAGE, {"reason": f"no recorded run for {task}; served the mock fixture"})
