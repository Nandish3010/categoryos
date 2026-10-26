"""Screen agent (stage "intake"): deterministic document check first, then a tool-calling model pass.
Vendor text is data. A deterministic guard backs the model: blocking documents or an injection attempt fail the vendor."""

import re
from typing import Any

from app import llm, prompts, tools
from app.agents.context import RunContext
from app.data_loader import load_application, load_sheet
from app.schemas import RiskFlag, ScreenFinal, StageResult

STAGE = "intake"
_INJECTION = re.compile(
    r"(?:ignore|disregard|override|bypass)\b[^.!?]{0,60}\b(?:rules?|instructions?|screening|guidelines?|prompt)"
    r"|note to (?:any |the )?(?:ai|llm|model|assistant|system)\b"
    r"|(?:approve|accept) all (?:skus?|products?)",
    re.IGNORECASE,
)


def scan_injection(vendor_id: str) -> list[str]:
    """Defence in depth: sentences in vendor-supplied text that look like instructions to an AI reviewer."""
    texts = [str(v) for v in load_application(vendor_id).values() if isinstance(v, str)]
    _, rows = load_sheet(vendor_id)
    texts += [cell for r in rows for cell in r.cells.values()]
    hits: list[str] = []
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if _INJECTION.search(sentence) and sentence.strip() not in hits:
                hits.append(sentence.strip())
    return hits


async def run(ctx: RunContext) -> StageResult:
    docs = tools.check_documents(ctx.vendor_id, ctx.today)
    ctx.emit(
        "tool_call",
        STAGE,
        {
            "tool": "check_documents",
            "args": {"vendor_id": ctx.vendor_id, "today": ctx.today},
            "result_summary": f"{len(docs['documents'])} documents, {len(docs['problems'])} problems, blocking={docs['blocking']}",
            "deterministic": True,
        },
    )
    res = await llm.run_tools(
        STAGE,
        f"screen_{ctx.vendor_id}",
        prompts.screen_messages(ctx.vendor_id, docs["today"], docs),
        tools.select(tools.SCREEN_TOOLS),
        max_steps=6,
        schema=ScreenFinal,
        on_step=ctx.step_emitter(STAGE),
    )
    ctx.emit(
        "model_call",
        STAGE,
        {
            "task": "screen",
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
    assert isinstance(final, ScreenFinal)
    flags = list(final.risk_flags)
    reasons = list(final.reasons)
    guards: list[str] = []

    injection = final.injection_detected
    hits = scan_injection(ctx.vendor_id)
    if hits and not injection:
        injection = True
        guards.append("injection_detected set by deterministic scan")
    if injection and not any(f.type == "prompt_injection" for f in flags):
        flags.append(RiskFlag(type="prompt_injection", quote=hits[0] if hits else "", severity="high"))
        guards.append("prompt_injection flag added")

    fail = final.decision == "fail"
    for problem in docs["problems"]:
        if problem["severity"] == "blocking":
            if not any(problem["type"].lower() in r.lower() for r in reasons):
                reasons.append(problem["detail"])
            fail = True
    if injection:
        if not any("inject" in r.lower() for r in reasons):
            reasons.append("The application contains text addressed to an AI reviewer (prompt injection), which was ignored")
        fail = True
    if fail and final.decision == "pass":
        guards.append("decision forced to fail by deterministic guard")
    decision = "fail" if fail else "pass"

    data: dict[str, Any] = {
        "decision": decision,
        "reasons": reasons,
        "risk_flags": [f.model_dump() for f in flags],
        "injection_detected": injection,
        "followup_questions": final.followup_questions,
        "documents": docs,
        "guards": guards,
        "mode": res.mode,
    }
    if decision == "fail":
        return StageResult(
            stage=STAGE,
            status="failed",
            summary="Screening failed: " + "; ".join(reasons[:3]),
            data=data,
            locked_reason="; ".join(reasons[:3]),
        )
    return StageResult(
        stage=STAGE,
        status="done",
        summary=f"Screening passed with {len(flags)} flag(s) to follow up",
        data=data,
    )
