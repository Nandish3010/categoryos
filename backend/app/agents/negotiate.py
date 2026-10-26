"""Negotiate agent (stage "negotiate"). The canonical call transcript JSON is the source of truth. Voice transcription
(when a call.wav exists and the voice stage is live) is a UX layer: it is stored and diffed against the canonical text,
never trusted.

The model extracts commitments, each with a verbatim transcript quote. Every commitment becomes a model_extraction
Claim; the verifier checks the quote appears verbatim in the canonical turn and states the committed number. Python
computes what we require and the gap (the Decide engine's targets), so the model never does arithmetic."""

import re
from pathlib import Path
from typing import Any

from app import llm, media, prompts_exec, tools
from app.agents import shortlist as sl
from app.agents.context import RunContext
from app.config import settings
from app.constants import (
    DEFECT_RETURN_MIN_DAYS,
    LAUNCH_DISCOUNT_MIN_PCT,
    MARKETING_MIN_PCT_OF_ORDER,
    MOQ_FACTOR,
)
from app.data_loader import load_application, load_benchmarks, load_transcript
from app.errors import CategoryOSError
from app.parsing import PARSER_VERSION
from app.schemas import (
    Claim,
    Evidence,
    LeverResponse,
    NegotiateFinal,
    SkuMetrics,
    SourceRef,
    StageResult,
)
from app.verify import file_sha256, verify_all

STAGE = "negotiate"
TERMS = ("margin_pct", "payment_days", "moq", "marketing_inr", "launch_discount_pct", "returns")
LABELS = {
    "margin_pct": "Margin offered to us",
    "payment_days": "Payment terms (days)",
    "moq": "First-order MOQ (units)",
    "marketing_inr": "Launch marketing support (₹)",
    "launch_discount_pct": "Launch discount (%)",
    "returns": "Defect return window (days)",
}
UNITS = {"margin_pct": "pct", "payment_days": "days", "moq": "units", "marketing_inr": "inr", "launch_discount_pct": "pct", "returns": "days"}
CLAIM_UNIT = {"margin_pct": "pct", "launch_discount_pct": "pct", "payment_days": "units", "moq": "units", "marketing_inr": "inr", "returns": "units"}
HIGHER_IS_BETTER = {"margin_pct": True, "payment_days": True, "moq": False, "marketing_inr": True, "launch_discount_pct": True, "returns": True}
_DAYS = re.compile(r"within\s+(\d+)\s+days", re.IGNORECASE)


def transcript_rel(vendor_id: str) -> str:
    return f"vendors/{vendor_id}/call_transcript.json"


def wav_path(vendor_id: str) -> Path:
    return Path(settings.data_dir) / "vendors" / vendor_id / "call.wav"


def required_terms(lever: LeverResponse, negotiate_skus: list[SkuMetrics], shortlisted: list[SkuMetrics]) -> dict[str, Any]:
    """What we require, from the Decide engine's targets. Pure arithmetic over the lever."""
    benchmarks = load_benchmarks()
    weight: dict[str, int] = {}
    for s in negotiate_skus:
        weight[s.category] = weight.get(s.category, 0) + max(s.alloc_units, 1)
    category = min(weight, key=lambda c: (-weight[c], c))
    bench = benchmarks[category]
    monthly = sum(s.est_monthly_units for s in shortlisted)
    order_value = sum(s.alloc_units * (s.selling_price or 0.0) for s in shortlisted)
    return {
        "category": category,
        "margin_pct": round(float(bench["target_margin_pct"]), 2),
        "margin_min_pct": float(bench["min_margin_pct"]),
        "payment_days": float(bench["typical_payment_terms_days"]),
        "moq": float(int(MOQ_FACTOR * monthly)),
        "marketing_inr": float(round(MARKETING_MIN_PCT_OF_ORDER * order_value)),
        "launch_discount_pct": LAUNCH_DISCOUNT_MIN_PCT,
        "returns": float(DEFECT_RETURN_MIN_DAYS),
    }


def application_terms(vendor_id: str) -> dict[str, float | None]:
    terms = load_application(vendor_id)["proposed_terms"]
    days = _DAYS.search(str(terms.get("returns_policy", "")))
    return {
        "margin_pct": terms.get("margin_offered_pct"),
        "payment_days": terms.get("payment_terms_days"),
        "moq": terms.get("moq_units"),
        "marketing_inr": terms.get("marketing_support_inr"),
        "launch_discount_pct": terms.get("launch_discount_pct"),
        "returns": float(days.group(1)) if days else None,
    }


def gap_table(application: dict[str, float | None], required: dict[str, Any], commitments: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per term. gap = offered - required; status is judged in the direction that is good for us."""
    rows = []
    for term in TERMS:
        commit = commitments.get(term)
        offered = commit["offered"] if commit else None
        need = required[term]
        gap = round(offered - need, 4) if offered is not None else None
        if offered is None:
            status = "not_stated"
        else:
            ok = offered >= need if HIGHER_IS_BETTER[term] else offered <= need
            status = "met" if ok else "gap"
        rows.append(
            {
                "term": term,
                "label": LABELS[term],
                "unit": UNITS[term],
                "direction": "higher" if HIGHER_IS_BETTER[term] else "lower",
                "application": application.get(term),
                "offered": offered,
                "required": need,
                "gap": gap,
                "status": status,
                "turn": commit["turn"] if commit else None,
                "quote": commit["transcript_quote"] if commit else None,
                "claim_id": commit["claim_id"] if commit else None,
                "verification": commit["status"] if commit else None,
            }
        )
    return rows


def commitment_claims(vendor_id: str, final: NegotiateFinal) -> list[Claim]:
    rel = transcript_rel(vendor_id)
    sha = file_sha256(rel)
    claims = []
    for i, c in enumerate(final.commitments):
        unit = CLAIM_UNIT[c.term]
        value = c.offered / 100 if unit == "pct" else c.offered
        claims.append(
            Claim(
                id=f"{vendor_id}:commit:{c.term}:{c.turn}:{i}",
                text=f"{vendor_id} commits to {LABELS[c.term].lower()}: {c.offered:g} (turn {c.turn})",
                value=float(value),
                metric=f"commit_{c.term}",
                unit=unit,  # type: ignore[arg-type]
                source_ref=SourceRef(file=rel, key=f"turn:{c.turn}", column="text"),
                evidence=Evidence(
                    row=c.turn,
                    header="text",
                    raw_value=c.transcript_quote,
                    normalized_value=float(value),
                    parser_version=PARSER_VERSION,
                    sha256=sha,
                ),
                origin="model_extraction",
            )
        )
    return claims


def _refusal_checked(vendor_id: str, refusal: dict[str, Any]) -> dict[str, Any]:
    turns = load_transcript(vendor_id) or []
    turn = next((t for t in turns if t["turn"] == refusal.get("turn")), None)
    quote = " ".join(str(refusal.get("transcript_quote", "")).split())
    verified = bool(turn and quote and quote in " ".join(turn["text"].split()))
    return {**refusal, "quote_verified": verified}


def _no_negotiation(lever: LeverResponse) -> StageResult:
    return StageResult(
        stage=STAGE,
        status="done",
        summary="No negotiation needed",
        data={
            "gap_table": [],
            "refusals": [],
            "counter_offer": {"asks": [], "email_draft": ""},
            "transcript": None,
            "transcript_source": "canonical",
            "negotiated_skus": [],
        },
        metrics_hash=lever.metrics_hash,
    )


async def _asr(ctx: RunContext, vendor_id: str, canonical: str) -> dict[str, Any] | None:
    """Live voice layer: transcribe call.wav and diff it against the canonical text. Failures degrade, never block."""
    path = wav_path(vendor_id)
    if not path.exists() or llm.resolve_mode(STAGE) != "live":
        return None
    try:
        result = await media.transcribe(path.read_bytes())
    except CategoryOSError as exc:
        ctx.emit("degraded", STAGE, {"reason": f"voice transcription failed ({exc.code}); using the canonical transcript"})
        return None
    ctx.emit(
        "model_call",
        STAGE,
        {"task": "transcribe", "mode": "live", "input_tokens": 0, "output_tokens": 0, "tool_steps": 0, "audio_hours": round(result.hours, 6)},
        model=result.spend.model,
        cost_usd=result.spend.cost_usd,
    )
    diff = media.diff_transcripts(canonical, result.text)
    return {"text": result.text, "similarity_pct": diff.similarity_pct, "changes": diff.changes, "audio_hours": round(result.hours, 6)}


async def run(ctx: RunContext, research: StageResult) -> StageResult:
    vendor_id = ctx.vendor_id
    lever = sl.research_lever(vendor_id, research)
    verdicts = sl.effective_verdicts(research, lever)
    negotiate_skus = sl.shortlisted(lever, verdicts, only="negotiate")
    if not negotiate_skus:
        return _no_negotiation(lever)
    short = sl.shortlisted(lever, verdicts)
    required = required_terms(lever, negotiate_skus, short)
    application = application_terms(vendor_id)
    canonical = load_transcript(vendor_id)
    ctx.emit(
        "tool_call",
        STAGE,
        {
            "tool": "required_terms",
            "args": {"vendor_id": vendor_id, "negotiate_skus": [s.code for s in negotiate_skus]},
            "result_summary": f"category={required['category']}, margin>={required['margin_pct']:g}%, moq<={required['moq']:g}",
            "deterministic": True,
        },
    )
    names = [s.code for s in negotiate_skus]
    if canonical is None:
        table = gap_table(application, required, {})
        return StageResult(
            stage=STAGE,
            status="done",
            summary="No call transcript on file: the gap table compares the application terms with what we require",
            data={
                "gap_table": table,
                "application_terms": application,
                "refusals": [],
                "counter_offer": {"asks": [], "email_draft": ""},
                "transcript": None,
                "transcript_source": "canonical",
                "negotiated_skus": names,
                "required": required,
                "verification": {"total": 0, "verified": 0, "rejected": 0, "unverifiable": 0},
            },
            metrics_hash=lever.metrics_hash,
        )

    canonical_text = " ".join(t["text"] for t in canonical)
    asr = await _asr(ctx, vendor_id, canonical_text)
    brand = load_application(vendor_id)["brand_name"]
    res = await llm.run_tools(
        STAGE,
        f"negotiate_{vendor_id}",
        prompts_exec.negotiate_messages(vendor_id, brand),
        tools.select(tools.NEGOTIATE_TOOLS),
        max_steps=5,
        schema=NegotiateFinal,
        on_step=ctx.step_emitter(STAGE),
    )
    ctx.emit(
        "model_call",
        STAGE,
        {"task": "negotiate", "mode": res.mode, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": len(res.steps)},
        model=res.model,
        latency_ms=res.latency_ms,
        cost_usd=res.cost_usd,
    )
    if res.degraded:
        ctx.emit("degraded", STAGE, {"reason": "no recorded run for this vendor; served the mock fixture"})
    final = res.parsed
    assert isinstance(final, NegotiateFinal)

    summary = verify_all(commitment_claims(vendor_id, final))
    for claim in summary.claims:
        ctx.emit("claim_checked", STAGE, {"claim": claim.model_dump(mode="json")})
    commitments: dict[str, dict[str, Any]] = {}
    commit_out = []
    for c, claim in zip(final.commitments, summary.claims):
        row = {**c.model_dump(), "claim_id": claim.id, "status": claim.status, "reason": claim.reason}
        commit_out.append(row)
        if claim.status == "verified":
            commitments[c.term] = row  # the last verified statement of a term wins

    table = gap_table(application, required, commitments)
    met = sum(1 for r in table if r["status"] == "met")
    gaps = sum(1 for r in table if r["status"] == "gap")
    rejected = summary.rejected
    data: dict[str, Any] = {
        "gap_table": table,
        "application_terms": application,
        "required": required,
        "commitments": commit_out,
        "refusals": [_refusal_checked(vendor_id, r.model_dump()) for r in final.refusals],
        "counter_offer": final.counter_offer.model_dump(),
        "transcript": {"turns": canonical, "asr_text": asr["text"] if asr else None, "similarity_pct": asr["similarity_pct"] if asr else None, "changes": asr["changes"] if asr else [], "audio_hours": asr["audio_hours"] if asr else None},
        "transcript_source": "asr" if asr else "canonical",
        "negotiated_skus": names,
        "verification": {"total": summary.total, "verified": summary.verified, "rejected": summary.rejected, "unverifiable": summary.unverifiable},
        "mode": res.mode,
    }
    text = f"{met} of {len(table)} terms meet our requirement, {gaps} fall short"
    if rejected:
        text += f"; {rejected} commitment(s) failed verification and were not counted"
    return StageResult(stage=STAGE, status="done", summary=text, data=data, claims=summary.claims, metrics_hash=lever.metrics_hash)
