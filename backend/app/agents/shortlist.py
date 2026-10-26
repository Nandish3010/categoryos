"""Shortlist view over a research result: effective verdicts (engine plus human overrides), the lever at the research
levers, and the verdict table mirrored on the `shortlist` stage."""

from typing import Any

from app.metrics import apply_levers, build_base
from app.schemas import LeverResponse, SkuMetrics, StageResult


def research_lever(vendor_id: str, research: StageResult) -> LeverResponse:
    lv = research.data.get("lever", {})
    return apply_levers(build_base(vendor_id), float(lv.get("target_margin_pct_offset", 0)), lv.get("moq"))


def effective_verdicts(research: StageResult, lever: LeverResponse) -> dict[str, str]:
    verdicts = {s.code: s.verdict for s in lever.skus}
    for row in research.data.get("rationale_per_sku", []):
        if row.get("edited_by_human") and row["code"] in verdicts:
            verdicts[row["code"]] = row["verdict"]
    return verdicts


def shortlisted(lever: LeverResponse, verdicts: dict[str, str], *, only: str | None = None) -> list[SkuMetrics]:
    wanted = {only} if only else {"list", "negotiate"}
    return [s for s in lever.skus if verdicts.get(s.code) in wanted]


def verdict_table(lever: LeverResponse, verdicts: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "code": s.code,
            "name": s.name,
            "verdict": verdicts[s.code],
            "engine_verdict": s.verdict,
            "edited_by_human": verdicts[s.code] != s.verdict,
            "margin_pct": s.margin_pct,
            "target_pct": s.target_pct,
            "fit_score": s.fit_score,
            "est_gmv": s.est_gmv,
            "alloc_units": s.alloc_units,
            "reasons": s.reasons,
        }
        for s in lever.skus
    ]


def shortlist_stage(research: StageResult, vendor_id: str, *, done: bool) -> StageResult:
    """The `shortlist` StageResult: mirrors research's verdict table; `done` once research is approved."""
    lever = research_lever(vendor_id, research)
    verdicts = effective_verdicts(research, lever)
    table = verdict_table(lever, verdicts)
    counts = {v: sum(1 for r in table if r["verdict"] == v) for v in ("list", "negotiate", "reject", "needs_data")}
    short = counts["list"] + counts["negotiate"]
    return StageResult(
        stage="shortlist",
        status="done" if done else "review",
        summary=f"{short} of {len(table)} SKUs shortlisted ({counts['list']} list, {counts['negotiate']} negotiate)",
        data={"verdict_table": table, "counts": counts, "shortlisted": short, "approved": done, "source_stage": "research"},
        metrics_hash=lever.metrics_hash,
    )
