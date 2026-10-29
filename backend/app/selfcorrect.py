"""Self-correction loop. When the verifier rejects a ``model_extraction`` claim (a cost read off the vendor sheet, a
commitment quoted from the call, a catalog attribute), the agent is told what the source says and may try again, up to
the playbook's ``verifier.max_self_corrections`` times. The verifier stays the judge: a corrected answer is checked
exactly like the first one, and a claim that is still wrong after the last retry is left rejected ("unresolved") so the
caller falls back to its old behaviour (strike the sentence, use the sheet value).

Trace events per claim: ``claim_rejected`` -> ``self_correction`` -> ``claim_verified`` (or ``claim_unresolved``).

Escalation: a claim the verifier still rejects after the last normal retry gets one more re-read by a stronger model
(``Settings.escalation_model``, default ``muse-wonder-1.0``; an empty string turns it off), checked by the same verifier.
It is traced as one more ``self_correction`` event carrying ``escalated: true`` and the model, and the claim's last
``attempts`` entry has ``escalated: true``. A claim that is still wrong is left unresolved, exactly as before. In mock and
replay the escalation reads the scripted fixture ``<task>__esc.json``; with none it is not answered, so the old behaviour
(the claim is removed) stands.

Live shape (assumed, unverified): the retry is one more chat completion with the original messages, the agent's previous
final answer as an assistant message and the verifier feedback as a user message, replying ``{"fixes": [...]}`` (see
``FixFinal``). In mock and replay it reads the scripted fixture ``<task>__fix<attempt>.json``; with none, the claim
stays unresolved.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from app import llm, policy
from app.agents.context import RunContext
from app.config import settings
from app.errors import CategoryOSError
from app.schemas import Claim, ClaimAttempt, ClaimFix, FixFinal
from app.verify import VerifySummary

Ask = Callable[[list[Claim], int], Awaitable[tuple[dict[str, ClaimFix] | None, str | None]]]  # (rejected, attempt) -> fixes
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
        quoted = claim.metric.startswith(("commit_", "deal_term_"))  # figures quoted from a call turn, not read off a sheet row
        cited = f"the evidence cites {'turn' if quoted else 'sheet row'} {ev.row}" + (f" '{ev.header}'" if ev.header and not quoted else "")
    parts = [f"Claim {claim.id} rejected: you said {shown_value(claim)}"]
    if cited:
        parts.append(cited)
    detail = f"Verifier: {claim.reason}" if claim.reason else "Verifier: the value does not match the source"
    return "; ".join(parts) + f". {detail}. Re-read and correct."


def _attempt(n: int, claim: Claim, *, escalated: bool = False) -> ClaimAttempt:
    return ClaimAttempt(
        attempt=n, value=claim.value, status=claim.status, reason=claim.reason, recomputed=claim.recomputed, escalated=escalated
    )


async def _ask(
    ctx: RunContext,
    stage: str,
    task: str,
    messages: list[dict[str, Any]],
    previous: str,
    pending: list[Claim],
    attempt: int,
    *,
    model: str | None = None,
    provider: Literal["meta", "baseten"] = "meta",
    escalated: bool = False,
) -> tuple[dict[str, ClaimFix] | None, str | None]:
    notes = "\n".join(feedback(c) for c in pending)
    if escalated:
        notes = f"Earlier corrections of these claims were rejected too. Read the source again with care.\n{notes}"
    ask = (
        f"{notes}\nReply with only a JSON object {{\"fixes\": [{{\"claim_id\", \"value\", and where it applies "
        "\"row\", \"header\", \"turn\", \"transcript_quote\"}}]}} with one entry per rejected claim."
    )
    msgs = [*messages, {"role": "assistant", "content": previous}, {"role": "user", "content": ask}]
    name = f"{task}__esc" if escalated else f"{task}__fix{attempt}"
    try:
        res = await llm.call(stage, msgs, task=name, schema=FixFinal, model=model, provider=provider)
    except CategoryOSError as exc:  # no scripted fixture, no credits, provider down: stay unresolved, never block
        return None, f"{exc.code}: no corrected answer available"
    ctx.emit(
        "model_call",
        stage,
        {"task": name, "mode": res.mode, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "tool_steps": 0},
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
    ask: Ask | None = None,
    escalate: Ask | None = None,
    escalation_model: str | None = None,
    model: str | None = None,
    provider: Literal["meta", "baseten"] = "meta",
) -> list[Claim]:
    """Return ``claims`` (same order and ids) with every rejected model extraction given its chance to be corrected.

    ``claims`` are already verified. ``rebuild`` turns a claim plus the agent's fix into a new unverified claim and
    ``check`` verifies it; the caller keeps whatever other state (narrative, structured output) it needs in those two
    closures. Corrected claims carry their ``attempts`` timeline. ``ask`` replaces the model call (the eval harness drives
    its own agents through the same loop); ``model`` / ``provider`` pick which model is asked.

    Escalation runs once, after the last retry, for the claims still rejected. ``escalation_model`` overrides
    ``Settings.escalation_model`` (empty: off). With a custom ``ask`` there is no escalation unless ``escalate`` (the same
    shape as ``ask``) is given."""
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
    retried = False  # at least one normal retry was answered and checked, so a rejection after it is "twice"
    while attempt < limit and (todo := pending()):
        attempt += 1
        if ask is not None:
            fixes, note = await ask(todo, attempt)
        else:
            fixes, note = await _ask(ctx, stage, task, messages, previous, todo, attempt, model=model, provider=provider)
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
        retried = True
        for new in check(rebuilt):
            out[index[new.id]] = new
            history[new.id].append(_attempt(attempt, new))
            if new.status == "verified":
                ctx.emit("claim_verified", stage, {"claim": new.model_dump(mode="json"), "attempt": attempt})
            else:
                ctx.emit("claim_rejected", stage, {"claim": new.model_dump(mode="json"), "attempt": attempt})

    esc_model = settings.escalation_model.strip() if escalation_model is None else escalation_model.strip()
    if retried and esc_model and (todo := pending()) and (escalate is not None or ask is None):
        attempt += 1
        if escalate is not None:
            fixes, note = await escalate(todo, attempt)
        else:
            fixes, note = await _ask(ctx, stage, task, messages, previous, todo, attempt, model=esc_model, provider="meta", escalated=True)
        ctx.emit(
            "self_correction",
            stage,
            {
                "attempt": attempt,
                "of": limit,
                "escalated": True,
                "model": esc_model,
                "claim_ids": [c.id for c in todo],
                "feedback": [feedback(c) for c in todo],
                "answered": fixes is not None,
                **({"note": note} if note else {}),
            },
        )
        rebuilt = [new for c in todo if fixes is not None and c.id in fixes and (new := rebuild(c, fixes[c.id])) is not None]
        for new in check(rebuilt) if rebuilt else []:
            out[index[new.id]] = new
            history[new.id].append(_attempt(attempt, new, escalated=True))
            kind = "claim_verified" if new.status == "verified" else "claim_rejected"
            ctx.emit(kind, stage, {"claim": new.model_dump(mode="json"), "attempt": attempt, "escalated": True})

    for claim in pending():
        ctx.emit("claim_unresolved", stage, {"claim": claim.model_dump(mode="json"), "attempts": attempt})
    for cid, tries in history.items():
        i = index[cid]
        out[i] = out[i].model_copy(update={"attempts": tries})
    return out


def corrected(claims: list[Claim]) -> list[Claim]:
    """Claims the verifier first rejected and the agent then got right."""
    return [c for c in claims if c.status == "verified" and len(c.attempts) > 1]


def escalated(claims: list[Claim]) -> list[Claim]:
    """Claims that were escalated to the stronger model (whether or not it got them right)."""
    return [c for c in claims if any(a.escalated for a in c.attempts)]


def fixed_by_escalation(claims: list[Claim]) -> list[Claim]:
    """Claims the normal retries could not fix and the escalation then got right."""
    return [c for c in claims if c.status == "verified" and c.attempts and c.attempts[-1].escalated]


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
