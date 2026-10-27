"""Self-correction loop. When the verifier rejects a ``model_extraction`` claim (a cost read off the vendor sheet, a
commitment quoted from the call, a catalog attribute), the agent is told what the source says and may try again, up to
the playbook's ``verifier.max_self_corrections`` times. The verifier stays the judge: a corrected answer is checked
exactly like the first one, and a claim that is still wrong after the last retry is left rejected ("unresolved") so the
caller falls back to its old behaviour (strike the sentence, use the sheet value).

Trace events per claim: ``claim_rejected`` -> ``self_correction`` -> ``claim_verified`` (or ``claim_unresolved``).

Live shape (assumed, unverified): the retry is one more chat completion with the original messages, the agent's previous
final answer as an assistant message and the verifier feedback as a user message, replying ``{"fixes": [...]}`` (see
``FixFinal``). In mock and replay it reads the scripted fixture ``<task>__fix<attempt>.json``; with none, the claim
stays unresolved.
"""

from collections.abc import Callable
from typing import Any

from app import llm, policy
from app.agents.context import RunContext
from app.errors import CategoryOSError
from app.schemas import Claim, ClaimAttempt, ClaimFix, FixFinal
from app.verify import VerifySummary

Rebuild = Callable[[Claim, ClaimFix], Claim | None]  # claim carrying the corrected answer, still unverified (same id)
Check = Callable[[list[Claim]], list[Claim]]  # verify them (the verifier plus any extra rule the stage applies)


def shown_value(claim: Claim) -> str:
    if claim.unit == "inr":
        return f"₹{claim.value:,.2f}"
    if claim.unit == "pct":
        return f"{claim.value * 100:g}%"
    return f"{claim.value:g}"


def feedback(claim: Claim) -> str:
    """The message the agent gets for one rejected claim. Everything in it comes from the verifier's own re-read."""
    ev = claim.evidence
    cited = ""
    if ev is not None and ev.row is not None:
        cited = f"the evidence cites {'turn' if claim.metric.startswith('commit_') else 'sheet row'} {ev.row}" + (
            f" '{ev.header}'" if ev.header and not claim.metric.startswith("commit_") else ""
        )
    parts = [f"Claim {claim.id} rejected: you said {shown_value(claim)}"]
    if cited:
        parts.append(cited)
    detail = f"Verifier: {claim.reason}" if claim.reason else "Verifier: the value does not match the source"
    return "; ".join(parts) + f". {detail}. Re-read and correct."


def _attempt(n: int, claim: Claim) -> ClaimAttempt:
    return ClaimAttempt(attempt=n, value=claim.value, status=claim.status, reason=claim.reason, recomputed=claim.recomputed)


async def _ask(
    ctx: RunContext,
    stage: str,
    task: str,
    messages: list[dict[str, Any]],
    previous: str,
    pending: list[Claim],
    attempt: int,
) -> tuple[dict[str, ClaimFix] | None, str | None]:
    notes = "\n".join(feedback(c) for c in pending)
    ask = (
        f"{notes}\nReply with only a JSON object {{\"fixes\": [{{\"claim_id\", \"value\", and where it applies "
        "\"row\", \"header\", \"turn\", \"transcript_quote\"}}]}} with one entry per rejected claim."
    )
    msgs = [*messages, {"role": "assistant", "content": previous}, {"role": "user", "content": ask}]
    try:
        res = await llm.call(stage, msgs, task=f"{task}__fix{attempt}", schema=FixFinal)
    except CategoryOSError as exc:  # no scripted fixture, no credits, provider down: stay unresolved, never block
        return None, f"{exc.code}: no corrected answer available"
    ctx.emit(
        "model_call",
        stage,
        {"task": f"{task}__fix{attempt}", "mode": res.mode, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": 0},
        model=res.model,
        latency_ms=res.latency_ms,
        cost_usd=res.cost_usd,
    )
    assert isinstance(res.parsed, FixFinal)
    return {f.claim_id: f for f in res.parsed.fixes}, None


async def self_correct(
    ctx: RunContext,
    stage: str,
    claims: list[Claim],
    *,
    task: str,
    messages: list[dict[str, Any]],
    previous: str,
    rebuild: Rebuild,
    check: Check,
) -> list[Claim]:
    """Return ``claims`` (same order and ids) with every rejected model extraction given its chance to be corrected.

    ``claims`` are already verified. ``rebuild`` turns a claim plus the agent's fix into a new unverified claim and
    ``check`` verifies it; the caller keeps whatever other state (narrative, structured output) it needs in those two
    closures. Corrected claims carry their ``attempts`` timeline."""
    limit = policy.get().verifier.max_self_corrections
    out = list(claims)
    index = {c.id: i for i, c in enumerate(out)}

    def pending() -> list[Claim]:
        return [c for c in out if c.origin == "model_extraction" and c.status == "rejected"]

    history: dict[str, list[ClaimAttempt]] = {}
    for claim in pending():
        history[claim.id] = [_attempt(0, claim)]
        ctx.emit("claim_rejected", stage, {"claim": claim.model_dump(mode="json"), "attempt": 0})

    attempt = 0
    while attempt < limit and (todo := pending()):
        attempt += 1
        fixes, note = await _ask(ctx, stage, task, messages, previous, todo, attempt)
        ctx.emit(
            "self_correction",
            stage,
            {
                "attempt": attempt,
                "of": limit,
                "claim_ids": [c.id for c in todo],
                "feedback": [feedback(c) for c in todo],
                "answered": fixes is not None,
                **({"note": note} if note else {}),
            },
        )
        if fixes is None:
            break
        rebuilt = [new for c in todo if c.id in fixes and (new := rebuild(c, fixes[c.id])) is not None]
        if not rebuilt:
            break
        for new in check(rebuilt):
            out[index[new.id]] = new
            history[new.id].append(_attempt(attempt, new))
            if new.status == "verified":
                ctx.emit("claim_verified", stage, {"claim": new.model_dump(mode="json"), "attempt": attempt})
            else:
                ctx.emit("claim_rejected", stage, {"claim": new.model_dump(mode="json"), "attempt": attempt})

    for claim in pending():
        ctx.emit("claim_unresolved", stage, {"claim": claim.model_dump(mode="json"), "attempts": attempt})
    for cid, tries in history.items():
        i = index[cid]
        out[i] = out[i].model_copy(update={"attempts": tries})
    return out


def corrected(claims: list[Claim]) -> list[Claim]:
    """Claims the verifier first rejected and the agent then got right."""
    return [c for c in claims if c.status == "verified" and len(c.attempts) > 1]


def unresolved(claims: list[Claim]) -> list[Claim]:
    return [c for c in claims if c.origin == "model_extraction" and c.status == "rejected"]


def summarize(claims: list[Claim]) -> VerifySummary:
    def count(status: str) -> int:
        return sum(1 for c in claims if c.status == status)

    return VerifySummary(
        total=len(claims), verified=count("verified"), rejected=count("rejected"), unverifiable=count("unverifiable"), claims=claims
    )


def revalue(claim: Claim, value: float) -> Claim:
    """The same claim carrying a new value, back to unverified. For stages whose claim text is just the value in prose."""
    ev = claim.evidence.model_copy(update={"normalized_value": value}) if claim.evidence else None
    text = claim.text.replace(f"{claim.value:g}", f"{value:g}")
    return claim.model_copy(update={"value": value, "text": text, "evidence": ev, "status": "pending", "reason": None, "recomputed": None})
