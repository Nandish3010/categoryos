"""Decide agent (one engine run covering research, shortlist and negotiate; StageResult.stage is "research").

Python decides the numbers (metrics.apply_levers); the model reads the messy sheet, explains verdicts and drafts a
counter-offer. Every number the model extracts from the sheet becomes a model_extraction Claim and is verified
against the raw cell. A rejected extraction strikes the sentence that used it from the narrative."""

import re
from typing import Any

from app import llm, prompts, tools
from app.agents.context import RunContext
from app.data_loader import load_sheet
from app.metrics import apply_levers, build_base
from app.parsing import PARSER_VERSION
from app.schemas import (
    Claim,
    DecideFinal,
    Evidence,
    LeverResponse,
    SkuMetrics,
    SourceRef,
    StageResult,
)
from app.util import fmt_inr
from app.verify import engine_claims, file_sha256, verify_all

STAGE = "research"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _engine_why(sku: SkuMetrics) -> str:
    text = "; ".join(sku.reasons) if sku.reasons else sku.verdict
    return text[:1].upper() + text[1:] + "."


def _number_re(value: float) -> re.Pattern[str]:
    forms = {f"{value:g}", f"{value:.1f}", f"{value:.2f}", f"{value:,.1f}", f"{value:,.2f}"}
    if float(value).is_integer():
        forms |= {f"{value:.0f}", f"{value:,.0f}"}
    alt = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    return re.compile(rf"(?<![\d.,])(?:{alt})(?!\d|[.,]\d)")


def _strike(text: str, pattern: re.Pattern[str], must_contain: str | None) -> tuple[str, list[str]]:
    kept, removed = [], []
    for sentence in _SENTENCE_SPLIT.split(text):
        if pattern.search(sentence) and (must_contain is None or must_contain in sentence):
            removed.append(sentence)
        else:
            kept.append(sentence)
    return " ".join(kept), removed


def reconcile(narrative: dict[str, Any], lever: LeverResponse, *, regenerate_headline: bool) -> list[dict[str, Any]]:
    """Make the narrative agree with the engine, in place. Returns a log of corrections.

    The engine owns verdicts: a model verdict that disagrees is replaced (with the engine's reasons as the
    explanation); missing SKUs are added; unknown codes are dropped; counter-offer terms for SKUs that are no
    longer negotiable are removed."""
    by_code = {r["code"]: r for r in narrative["rationale_per_sku"]}
    corrections: list[dict[str, Any]] = []
    out = []
    for sku in lever.skus:
        row = by_code.get(sku.code)
        if row is None:
            out.append({"code": sku.code, "verdict": sku.verdict, "why": _engine_why(sku)})
            corrections.append({"code": sku.code, "kind": "added", "engine_verdict": sku.verdict})
        elif row["verdict"] != sku.verdict:
            out.append({"code": sku.code, "verdict": sku.verdict, "why": _engine_why(sku)})
            corrections.append(
                {"code": sku.code, "kind": "verdict", "model_verdict": row["verdict"], "engine_verdict": sku.verdict}
            )
        else:
            out.append(row)
    narrative["rationale_per_sku"] = out
    negotiable = {s.code for s in lever.skus if s.verdict == "negotiate"}
    terms = narrative["counter_offer"]["terms"]
    narrative["counter_offer"]["terms"] = [t for t in terms if t.get("sku_code") is None or t["sku_code"] in negotiable]
    if regenerate_headline:
        c = lever.summary.counts
        narrative["headline"] = (
            f"{c['list']} list, {c['negotiate']} negotiate and {c['reject']} reject out of {len(lever.skus)} SKUs "
            f"at a {lever.target_margin_pct_offset:+g} pp margin offset; capital at risk is "
            f"{fmt_inr(lever.summary.capital_at_risk_inr)} at MOQ {lever.summary.moq}."
        )
    return corrections


def extraction_claims(vendor_id: str, lever: LeverResponse, extractions: list[dict[str, Any]]) -> list[Claim]:
    rel = f"vendors/{vendor_id}/sku_sheet.csv"
    sha = file_sha256(rel)
    _, rows = load_sheet(vendor_id)
    cells = {r.row: r.cells for r in rows}
    claims = []
    for ex in extractions:
        sku_key = f"{vendor_id}:{ex['sku_code']}"
        raw = cells.get(ex["row"], {}).get(ex["header"])
        claims.append(
            Claim(
                id=f"{sku_key}:{ex['field']}:extracted",
                text=f"{ex['sku_code']} {ex['field']} is ₹{ex['value']:g} (sheet row {ex['row']}, {ex['header']})",
                value=float(ex["value"]),
                metric=ex["field"],
                unit="inr",
                sku_key=sku_key,
                source_ref=SourceRef(file=rel, key=sku_key, column=ex["header"]),
                evidence=Evidence(
                    row=ex["row"],
                    header=ex["header"],
                    raw_value=raw,
                    normalized_value=float(ex["value"]),
                    parser_version=PARSER_VERSION,
                    sha256=sha,
                ),
                origin="model_extraction",
            )
        )
    return claims


def _wrong_row(claim: Claim, lever: LeverResponse) -> Claim:
    """The cell may exist and parse, but if the model cited another SKU's row the extraction is still wrong."""
    sku = next((s for s in lever.skus if s.sku_key == claim.sku_key), None)
    ev = claim.evidence
    if claim.status != "verified" or ev is None:
        return claim
    if sku is None:
        return claim.model_copy(update={"status": "rejected", "reason": f"{claim.sku_key} is not a SKU in this vendor's sheet"})
    if ev.row != sku.sheet_row:
        reason = f"row {ev.row} is not {sku.code}'s row (it is row {sku.sheet_row})"
        return claim.model_copy(update={"status": "rejected", "reason": reason})
    return claim


def apply_strikes(narrative: dict[str, Any], rejected: list[tuple[Claim, dict[str, Any]]], lever: LeverResponse) -> list[dict[str, Any]]:
    """Remove every sentence that cites a rejected extraction's number for its SKU. Returns the struck log."""
    struck: list[dict[str, Any]] = []
    engine_why = {s.code: _engine_why(s) for s in lever.skus}
    for claim, ex in rejected:
        code, pattern = ex["sku_code"], _number_re(ex["value"])
        removed_where: list[tuple[str, str]] = []
        for row in narrative["rationale_per_sku"]:
            if row["code"] == code:
                row["why"], removed = _strike(row["why"], pattern, None)
                removed_where += [(f"rationale:{code}", s) for s in removed]
                if removed and not row["why"].strip():
                    row["why"] = engine_why.get(code, "")
        narrative["headline"], removed = _strike(narrative["headline"], pattern, code)
        removed_where += [("headline", s) for s in removed]
        offer = narrative["counter_offer"]
        offer["email_draft"], removed = _strike(offer["email_draft"], pattern, code)
        removed_where += [("email_draft", s) for s in removed]
        for term in offer["terms"]:
            if term.get("sku_code") == code and term.get("rationale"):
                term["rationale"], removed = _strike(term["rationale"], pattern, None)
                removed_where += [(f"term:{term['term']}", s) for s in removed]
        entry = {
            "claim_id": claim.id,
            "sku_code": code,
            "field": ex["field"],
            "claimed_value": ex["value"],
            "sheet_value": claim.recomputed,
            "reason": claim.reason,
        }
        if removed_where:
            struck += [{**entry, "where": where, "sentence": sentence} for where, sentence in removed_where]
        else:
            struck.append({**entry, "where": None, "sentence": None})
    return struck


async def run(ctx: RunContext, *, offset: float = 0.0, moq: int | None = None, replan: bool = False) -> StageResult:
    vendor_id = ctx.vendor_id
    base = build_base(vendor_id)
    lever = apply_levers(base, offset, moq)
    ctx.emit(
        "tool_call",
        STAGE,
        {
            "tool": "apply_levers",
            "args": {"vendor_id": vendor_id, "target_margin_pct_offset": offset, "moq": lever.summary.moq},
            "result_summary": f"counts={lever.summary.counts}, capital_at_risk_inr={lever.summary.capital_at_risk_inr:g}, "
            f"metrics_hash={lever.metrics_hash[:12]}",
            "deterministic": True,
        },
    )
    res = await llm.run_tools(
        STAGE,
        f"decide_{vendor_id}",
        prompts.decide_messages(vendor_id, base.brand, offset, lever.summary.moq, replan),
        tools.select(tools.DECIDE_TOOLS),
        max_steps=6,
        schema=DecideFinal,
        on_step=ctx.step_emitter(STAGE),
    )
    ctx.emit(
        "model_call",
        STAGE,
        {
            "task": "decide",
            "mode": res.mode,
            "input_tokens": res.input_tokens,
            "output_tokens": res.output_tokens,
            "tool_steps": len(res.steps),
        },
        model=res.model,
        latency_ms=res.latency_ms,
        cost_usd=res.cost_usd,
    )
    if res.degraded:
        ctx.emit("degraded", STAGE, {"reason": "no recorded run for this vendor; served the mock fixture"})

    final = res.parsed
    assert isinstance(final, DecideFinal)
    narrative = final.model_dump(exclude={"extractions"})
    extractions = [e.model_dump() for e in final.extractions]
    corrections = reconcile(narrative, lever, regenerate_headline=replan and res.mode != "live")

    ext_claims = extraction_claims(vendor_id, lever, extractions)
    summary = verify_all(engine_claims(vendor_id, lever) + ext_claims)
    claims = [_wrong_row(c, lever) if c.origin == "model_extraction" else c for c in summary.claims]
    for claim in claims:
        ctx.emit(
            "claim_checked",
            STAGE,
            {"claim": claim.model_dump(mode="json")},
        )

    by_id = {c.id: c for c in claims}
    rejected = [(by_id[f"{vendor_id}:{e['sku_code']}:{e['field']}:extracted"], e) for e in extractions]
    rejected = [(c, e) for c, e in rejected if c.status == "rejected"]
    struck = apply_strikes(narrative, rejected, lever)

    def count(status: str) -> int:
        return sum(1 for c in claims if c.status == status)

    ext_out = []
    for e in extractions:
        c = by_id[f"{vendor_id}:{e['sku_code']}:{e['field']}:extracted"]
        ext_out.append({**e, "claim_id": c.id, "status": c.status, "sheet_value": c.recomputed})

    data: dict[str, Any] = {
        **narrative,
        "extractions": ext_out,
        "struck": struck,
        "verdict_corrections": corrections,
        "lever": {"target_margin_pct_offset": offset, "moq": lever.summary.moq},
        "summary": lever.summary.model_dump(mode="json"),
        "verification": {
            "total": len(claims),
            "verified": count("verified"),
            "rejected": count("rejected"),
            "unverifiable": count("unverifiable"),
        },
        "replanned": replan,
        "mode": res.mode,
    }
    return StageResult(
        stage=STAGE,
        status="review",
        summary=narrative["headline"],
        data=data,
        needs_approval=True,
        claims=claims,
        metrics_hash=lever.metrics_hash,
        narrative_hash=lever.metrics_hash,
    )
