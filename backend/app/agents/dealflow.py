"""Deal evaluator step of Negotiate. The model only READS conditional / non-standard offers out of the call or the
application into DealTerms; each number of each term is a model_extraction Claim whose quote the verifier checks verbatim.
Python (app.deals) then values the verified terms: P(condition met), P10/P50/P90, risk-adjusted value, decision and
counters, each number an engine Claim. The model finally writes a talk track from those figures only; any sentence
stating a number the engine did not produce is struck."""

from dataclasses import dataclass, field
from typing import Any

from app import deals, llm, prompts_exec, tools
from app.agents.context import RunContext
from app.data_loader import load_application, load_transcript
from app.errors import CategoryOSError
from app.parsing import PARSER_VERSION
from app.schemas import (
    Claim,
    DealExtraction,
    DealTalk,
    DealTerm,
    Evidence,
    LeverResponse,
    SourceRef,
)
from app.verify import file_sha256, verify_all

STAGE = "negotiate"
_TERM_UNIT = {"pct": "pct", "inr": "inr"}
_THRESHOLD_UNIT = {"units": "units", "gmv_inr": "inr", "sell_through_pct": "pct"}


@dataclass
class DealsOutcome:
    data: dict[str, Any]
    claims: list[Claim] = field(default_factory=list)
    report: deals.DealReport | None = None


def additional_terms(vendor_id: str) -> list[str]:
    extra = load_application(vendor_id).get("proposed_terms", {}).get("additional_terms") or []
    return [str(x) for x in extra]


def has_source(vendor_id: str) -> bool:
    """Is there anything to read deal terms from: a call transcript or free-text additional terms in the application?"""
    return load_transcript(vendor_id) is not None or bool(additional_terms(vendor_id))


def term_numbers(term: DealTerm) -> list[tuple[str, float, str]]:
    """Every number of a term that must appear in its quote: (field, value as stated, claim unit)."""
    unit = _TERM_UNIT.get(term.unit, "units")
    metric = term.condition.metric if term.condition else "units"
    thr_unit = _THRESHOLD_UNIT[metric]
    out = [("value", term.value, unit)]
    if term.condition is not None:
        out += [("threshold", term.condition.threshold, thr_unit), ("window_days", float(term.condition.window_days), "units")]
    for i, tier in enumerate(sorted(term.tiers, key=lambda t: t.threshold)):
        out += [(f"tier{i}_threshold", tier.threshold, thr_unit), (f"tier{i}_value", tier.value, unit)]
    if term.days is not None:
        out.append(("days", term.days, "units"))
    if term.units is not None:
        out.append(("units", term.units, "units"))
    return out


def term_claims(vendor_id: str, terms: list[DealTerm]) -> list[tuple[DealTerm, Claim]]:
    claims = []
    for term in terms:
        rel = f"vendors/{vendor_id}/" + ("application.json" if term.source == "application" else "call_transcript.json")
        sha = file_sha256(rel)
        for field_name, value, unit in term_numbers(term):
            scaled = value / 100 if unit == "pct" else float(value)
            claims.append(
                (
                    term,
                    Claim(
                        id=f"{vendor_id}:dealterm:{term.id}:{field_name}",
                        text=f"{vendor_id} offer '{deals.describe(term, None)}': {field_name.replace('_', ' ')} {value:g}",
                        value=scaled,
                        metric=f"deal_term_{field_name}",
                        unit=unit,  # type: ignore[arg-type]
                        source_ref=SourceRef(file=rel, key=f"{'turn' if term.source == 'transcript' else 'additional_term'}:{term.turn}", column="text"),
                        evidence=Evidence(
                            row=term.turn,
                            header="text",
                            raw_value=term.quote,
                            normalized_value=scaled,
                            parser_version=PARSER_VERSION,
                            sha256=sha,
                        ),
                        origin="model_extraction",
                    ),
                )
            )
    return claims


def verified_terms(terms: list[DealTerm], checked: list[tuple[DealTerm, Claim]]) -> tuple[list[DealTerm], list[dict[str, Any]]]:
    """Terms whose every extracted number was verified against the quote; the rest are dropped with the reason."""
    bad: dict[str, list[str]] = {}
    for term, claim in checked:
        if claim.status != "verified":
            bad.setdefault(term.id, []).append(f"{claim.metric.removeprefix('deal_term_')}: {claim.reason or claim.status}")
    keep = [t for t in terms if t.id not in bad]
    dropped = [{"id": t.id, "label": deals.describe(t, None), "reasons": bad[t.id]} for t in terms if t.id in bad]
    return keep, dropped


def _dedupe(terms: list[DealTerm]) -> list[DealTerm]:
    seen: set[str] = set()
    out = []
    for t in terms:
        if t.id not in seen:
            seen.add(t.id)
            out.append(t)
    return out


def template_talk(report: deals.DealReport) -> dict[str, str]:
    """Deterministic fallback when no model text is available: the engine's own call and counters."""
    lines = [a.call for a in report.assessments if a.decision != "accept"] or [a.call for a in report.assessments]
    options = [f"- {c.kind.replace('_', ' ')}: {c.text}" for a in report.assessments for c in a.counters]
    return {"talk_track": " ".join(lines), "email_paragraph": " ".join(lines) + ("\n" + "\n".join(options) if options else "")}


async def talk_track(vendor_id: str, report: deals.DealReport, emit: Any = None) -> dict[str, Any] | None:
    """The agent's plain-English call and email paragraph, from the engine's figures only. Numbers are checked.
    None when every offer is acceptable (nothing to counter)."""
    if not any(a.decision in ("reject_structure", "needs_human") for a in report.assessments):
        return None
    try:
        res = await llm.call(
            STAGE,
            prompts_exec.deal_talk_messages(vendor_id, deals.talk_facts(report)),
            task=f"deals_talk_{vendor_id}",
            schema=DealTalk,
            max_tokens=900,
        )
    except CategoryOSError as exc:
        if emit:
            emit("degraded", STAGE, {"reason": f"deal talk track unavailable ({exc.code}); showing the evaluator's own wording"})
        return {**template_talk(report), "source": "rules", "struck": []}
    if emit:
        emit(
            "model_call",
            STAGE,
            {"task": "deal_talk", "mode": res.mode, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": 0},
            model=res.model,
            latency_ms=res.latency_ms,
            cost_usd=res.cost_usd,
        )
    out = res.parsed
    assert isinstance(out, DealTalk)
    track, struck_a = deals.strike_unverified_numbers(out.talk_track, report)
    email, struck_b = deals.strike_unverified_numbers(out.email_paragraph, report)
    if not track and not email:
        return {**template_talk(report), "source": "rules", "struck": [*struck_a, *struck_b]}
    return {"talk_track": track, "email_paragraph": email, "source": "model", "struck": [*struck_a, *struck_b]}


def outcome_data(
    vendor_id: str, terms: list[DealTerm], dropped: list[dict[str, Any]], report: deals.DealReport, talk: dict[str, Any] | None,
    extraction_summary: dict[str, int], model_mode: str,
) -> dict[str, Any]:
    return {
        "decision": report.decision,
        "headline": report.headline,
        "assessments": [a.model_dump(mode="json") for a in report.assessments],
        "base_terms": [t.model_dump(mode="json") for t in terms if t.kind == "base"],
        "rejected_terms": dropped,
        "assumptions": report.assumptions,
        "talk": talk,
        "verification": extraction_summary,
        "mode": model_mode,
    }


def evaluate_terms(
    vendor_id: str, lever: LeverResponse, terms: list[DealTerm], dctx: deals.Context
) -> tuple[deals.DealReport, list[Claim]]:
    """Value verified terms and emit (verified) engine claims for every number."""
    report = deals.assess(terms, dctx)
    by_id = {t.id: t for t in terms}
    engine: list[Claim] = []
    for a in report.assessments:
        term = by_id[a.term_id]
        base = by_id.get(term.base_of) if term.base_of else None
        engine.extend(deals.claims_for(vendor_id, lever, dctx, term, base, a))
    return report, engine


async def extract(ctx: RunContext, vendor_id: str) -> tuple[list[DealTerm], Any] | None:
    """The model's read of the call and application. Failure degrades (no deal valuation); it never blocks Negotiate."""
    brand = load_application(vendor_id)["brand_name"]
    try:
        res = await llm.run_tools(
            STAGE,
            f"deals_{vendor_id}",
            prompts_exec.deals_messages(vendor_id, brand),
            tools.select(tools.NEGOTIATE_TOOLS),
            max_steps=5,
            schema=DealExtraction,
            on_step=ctx.step_emitter(STAGE),
        )
    except CategoryOSError as exc:
        ctx.emit("degraded", STAGE, {"reason": f"deal terms could not be read ({exc.code}); conditional offers are not valued"})
        return None
    ctx.emit(
        "model_call",
        STAGE,
        {"task": "deal_terms", "mode": res.mode, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": len(res.steps)},
        model=res.model,
        latency_ms=res.latency_ms,
        cost_usd=res.cost_usd,
    )
    extraction = res.parsed
    assert isinstance(extraction, DealExtraction)
    return _dedupe(extraction.terms), res


async def run(
    ctx: RunContext, vendor_id: str, lever: LeverResponse, shortlist_codes: set[str], *,
    base_margin_pct: float | None, base_payment_days: float | None,
) -> DealsOutcome | None:
    """Read, verify, value and explain a vendor's conditional offers. None when there is nothing to read."""
    if not has_source(vendor_id):
        return None
    got = await extract(ctx, vendor_id)
    if got is None:
        return None
    terms, res = got
    if not terms:
        return DealsOutcome(data={"decision": "none", "headline": "No conditional terms", "assessments": [], "base_terms": [], "rejected_terms": [], "assumptions": deals.assumptions(), "talk": None, "verification": {"total": 0, "verified": 0, "rejected": 0, "unverifiable": 0}, "mode": res.mode})
    checked_pairs = term_claims(vendor_id, terms)
    summary = verify_all([c for _, c in checked_pairs])
    checked = [(t, c) for (t, _), c in zip(checked_pairs, summary.claims)]
    for claim in summary.claims:
        ctx.emit("claim_checked", STAGE, {"claim": claim.model_dump(mode="json")})
    ok_terms, dropped = verified_terms(terms, checked)
    dctx = deals.Context(
        deals.sku_facts(lever, shortlist_codes), base_margin_pct, base_payment_days, float(sum(s.alloc_units for s in lever.skus if s.code in shortlist_codes))
    )
    report, engine_claims = evaluate_terms(vendor_id, lever, ok_terms, dctx)
    engine_summary = verify_all(engine_claims)
    for claim in engine_summary.claims:
        ctx.emit("claim_checked", STAGE, {"claim": claim.model_dump(mode="json")})
    ctx.emit(
        "tool_call",
        STAGE,
        {
            "tool": "assess_deals",
            "args": {"vendor_id": vendor_id, "terms": [t.id for t in ok_terms]},
            "result_summary": "; ".join(f"{a.term_id}: {a.decision}" + (f" (P {deals.fmt_prob(a.probability)})" if a.probability is not None else "") for a in report.assessments) or "no conditional terms",
            "deterministic": True,
        },
    )
    talk = await talk_track(vendor_id, report, emit=ctx.emit)
    claims = [*summary.claims, *engine_summary.claims]
    totals = {
        "total": summary.total + engine_summary.total,
        "verified": summary.verified + engine_summary.verified,
        "rejected": summary.rejected + engine_summary.rejected,
        "unverifiable": summary.unverifiable + engine_summary.unverifiable,
    }
    data = outcome_data(vendor_id, ok_terms, dropped, report, talk, totals, res.mode)
    return DealsOutcome(data=data, claims=claims, report=report)
