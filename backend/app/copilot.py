"""Live negotiation copilot. One pipeline for every call, simulated or live:

    audio chunk (live) or canonical turn (simulate)
      -> transcription (muse-voice-transcribe-1.0; simulate uses the canonical text, the shape a perfect ASR returns)
      -> turn appended to the call
      -> incremental extraction on a vendor turn (muse-spark, task copilot_<VID>_t<n>): commitments, refusals, deal terms
      -> every quote verified verbatim against the call's own turns
      -> gap table + deal evaluator (app.deals) recomputed from the verified terms
      -> "next ask" from the playbook rules and the engine's numbers
      -> SSE `call` events to the UI.

A simulated call streams the recorded V002 transcript with realistic pacing through exactly these steps from the mock
fixtures, so mock and replay modes demonstrate it at $0. A live call needs live mode and the demo key, and each call has a
spend budget (config CALL_BUDGET_USD). Ending a live call makes its transcript the canonical one for the vendor, so the
Negotiate stage verifies commitments against it as it does for any transcript. Calls live in memory, like replay sessions."""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Literal

from app import deals, llm, media, policy, prompts_exec
from app.agents import dealflow, negotiate
from app.agents import shortlist as sl
from app.config import settings
from app.data_loader import load_application, load_transcript, set_transcript_override
from app.errors import (
    CallBudgetExceeded,
    CallEnded,
    CallNotAccepting,
    CallNotFound,
    CategoryOSError,
    ChunkTooLarge,
    LiveCallUnavailable,
    NoCallScript,
    UnsupportedAudio,
)
from app.metrics import apply_levers, build_base
from app.schemas import Claim, DealTerm, NegotiateFinal, TurnExtraction
from app.verify import verify_against_turns, verify_claim

log = logging.getLogger("categoryos.copilot")

STAGE = "negotiate"
MAX_CALLS = 50
CONTEXT_TURNS = 4
SIM_CPS = 15.0  # characters a speaker says per second when pacing a simulated call
SIM_MIN_S, SIM_MAX_S = 0.6, 4.0
MAX_EVENTS = 2000

Mode = Literal["simulate", "live"]


async def sleep(seconds: float) -> None:  # patched out in tests
    await asyncio.sleep(seconds)


@dataclass
class CallSession:
    call_id: str
    vendor_id: str
    mode: Mode
    speed: float
    started_at: float = field(default_factory=time.monotonic)
    turns: list[dict[str, Any]] = field(default_factory=list)
    commitments: list[dict[str, Any]] = field(default_factory=list)
    refusals: list[dict[str, Any]] = field(default_factory=list)
    terms: list[DealTerm] = field(default_factory=list)
    term_ok: dict[str, bool] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: list[asyncio.Queue[dict[str, Any]]] = field(default_factory=list)
    spend_usd: float = 0.0
    public_ip: str = ""  # set when the call is live on the public live budget (no demo key): the caller's IP bucket
    ended: bool = False
    task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    state: dict[str, Any] = field(default_factory=dict)
    _seq: int = 0

    def emit(self, type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        event = {"seq": self._seq, "call_id": self.call_id, "type": type_, "t_ms": round((time.monotonic() - self.started_at) * 1000), "payload": payload}
        self.events.append(event)
        del self.events[:-MAX_EVENTS]
        for q in self.subscribers:
            q.put_nowait(event)
        return event


_calls: OrderedDict[str, CallSession] = OrderedDict()


def reset() -> None:
    for s in _calls.values():
        if s.task is not None:
            s.task.cancel()
    _calls.clear()


def get(call_id: str, vendor_id: str | None = None) -> CallSession:
    s = _calls.get(call_id)
    if s is None or (vendor_id is not None and s.vendor_id != vendor_id):
        raise CallNotFound(call_id)
    return s


# ---------- starting and ending ----------


def start(vendor_id: str, mode: Mode, speed: float = 1.0, public_ip: str = "") -> CallSession:
    """``public_ip`` (an IP bucket key) marks a live call that runs on the public live budget instead of the demo key."""
    if mode == "live" and not public_ip and llm.resolve_mode(STAGE) != "live":
        raise LiveCallUnavailable()
    if mode == "simulate" and load_transcript(vendor_id) is None:
        raise NoCallScript()
    session = CallSession(f"call_{uuid.uuid4().hex[:10]}", vendor_id, mode, max(speed, 0.1) * settings.copilot_sim_speed)
    session.public_ip = public_ip if mode == "live" else ""
    _calls[session.call_id] = session
    while len(_calls) > MAX_CALLS:
        _, old = _calls.popitem(last=False)
        if old.task is not None:
            old.task.cancel()
    session.state = compute_state(session)
    session.emit("started", {"mode": mode, "vendor_id": vendor_id, "state": session.state, "budget_usd": settings.call_budget_usd if mode == "live" else 0.0, "public": bool(session.public_ip)})
    if mode == "simulate":
        session.task = asyncio.create_task(_simulate(session))
    return session


async def end(session: CallSession) -> dict[str, Any]:
    """Finish the call. A live transcript becomes the canonical one, so Negotiate verifies commitments against it."""
    async with session.lock:
        if session.ended:
            return session.state
        session.ended = True
        canonical = session.mode == "live" and len(session.turns) >= 2 and not session.public_ip  # a public visitor's call never rewrites the shared transcript
        if canonical:
            set_transcript_override(session.vendor_id, [{"turn": t["turn"], "speaker": t["speaker"], "text": t["text"]} for t in session.turns])
        session.state = compute_state(session)
        session.emit("ended", {"turns": len(session.turns), "canonical": canonical or session.mode == "simulate", "spend_usd": round(session.spend_usd, 6), "state": session.state})
    return session.state


# ---------- turns ----------


def _delay(text: str, speed: float) -> float:
    return min(max(len(text) / SIM_CPS, SIM_MIN_S), SIM_MAX_S) / speed


async def _simulate(session: CallSession) -> None:
    """Stream the canonical call turn by turn through the same ASR -> extraction -> evaluation pipeline."""
    try:
        for t in load_transcript(session.vendor_id) or []:
            await sleep(_delay(t["text"], session.speed))
            text = await transcribe(session, None, t["text"])
            await ingest(session, t["speaker"], text, "simulated")
        await end(session)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("simulated call %s crashed", session.call_id)
        session.emit("error", {"code": "internal_error", "problem": "The simulated call crashed", "cause": repr(exc)[:300]})
        await end(session)


def _check_budget(session: CallSession) -> None:
    if session.mode == "live" and session.spend_usd >= settings.call_budget_usd:
        raise CallBudgetExceeded(cause=f"This call has spent ${session.spend_usd:.2f} of its ${settings.call_budget_usd:.2f} budget")


async def transcribe(session: CallSession, wav: bytes | None, canonical_text: str | None = None) -> str:
    """Audio -> text. A simulated call has no audio: the canonical turn text is what a perfect ASR returns."""
    if wav is None:
        assert canonical_text is not None
        return canonical_text
    _check_budget(session)
    result = await media.transcribe(wav)
    session.spend_usd += result.spend.cost_usd
    return result.text


async def ingest_chunk(session: CallSession, wav: bytes, speaker: str) -> dict[str, Any] | None:
    if session.mode != "live":
        raise CallNotAccepting()
    if session.ended:
        raise CallEnded()
    if len(wav) > settings.call_chunk_max_bytes:
        raise ChunkTooLarge()
    if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise UnsupportedAudio()
    text = (await transcribe(session, wav)).strip()
    if not text:
        return None
    return await ingest(session, speaker, text, "asr")


async def ingest_text(session: CallSession, speaker: str, text: str) -> dict[str, Any]:
    if session.mode != "live":
        raise CallNotAccepting()
    if session.ended:
        raise CallEnded()
    return await ingest(session, speaker, text.strip(), "typed")


def _speaker(session: CallSession, hint: str) -> str:
    if hint in ("buyer", "vendor"):
        return hint
    return "vendor" if session.turns and session.turns[-1]["speaker"] == "buyer" else "buyer"  # alternate, buyer first


async def ingest(session: CallSession, speaker: str, text: str, source: str) -> dict[str, Any]:
    async with session.lock:
        if session.ended:
            raise CallEnded()
        speaker = _speaker(session, speaker)
        turn = {"turn": len(session.turns) + 1, "speaker": speaker, "text": text, "source": source}
        session.turns.append(turn)
        session.emit("turn", {"turn": turn})
        before = session.state
        if speaker == "vendor":
            await _extract(session, turn)
        session.state = compute_state(session)
        session.emit("state", {"state": session.state, "changed": changed(before, session.state), "turn": turn["turn"]})
        return turn


# ---------- incremental extraction ----------


def state_summary(session: CallSession) -> str:
    done = [f"{c['term']}={c['offered']:g}" for c in session.commitments if c["status"] == "verified"]
    offers = [deals.describe(t, None) for t in session.terms if session.term_ok.get(t.id)]
    return json.dumps({"commitments": done, "conditional_offers": offers})


def _remap(terms: list[DealTerm], turn: int) -> list[DealTerm]:
    """Term ids are per extraction (t1, t2...); namespace them by turn so later turns cannot collide."""
    ids = {t.id for t in terms}
    return [t.model_copy(update={"id": f"{t.id}-{turn}", "base_of": f"{t.base_of}-{turn}" if t.base_of in ids else t.base_of}) for t in terms]


async def _extract(session: CallSession, turn: dict[str, Any]) -> None:
    vendor_id = session.vendor_id
    brand = load_application(vendor_id)["brand_name"]
    context = session.turns[-1 - CONTEXT_TURNS : -1]
    try:
        _check_budget(session)
        res = await llm.call(
            STAGE,
            prompts_exec.copilot_messages(vendor_id, brand, context, state_summary(session), turn),
            task=f"copilot_{vendor_id}_t{turn['turn']}",
            schema=TurnExtraction,
            max_tokens=1200,
        )
    except CategoryOSError as exc:
        session.emit("error", {**exc.to_dict(), "turn": turn["turn"]})
        return
    session.spend_usd += res.cost_usd
    out = res.parsed
    assert isinstance(out, TurnExtraction)
    session.emit("extraction", {"turn": turn["turn"], "model": res.model, "mode": res.mode, "cost_usd": res.cost_usd, "latency_ms": res.latency_ms})
    # commitments: verified against the call's own turns
    final = NegotiateFinal(commitments=out.commitments)
    for c, claim in zip(final.commitments, negotiate.commitment_claims(vendor_id, final)):
        checked = verify_against_turns(claim, session.turns)
        session.claims[checked.id] = checked
        session.commitments.append({**c.model_dump(), "claim_id": checked.id, "status": checked.status, "reason": checked.reason})
    for r in out.refusals:
        session.refusals.append({**r.model_dump(), "quote_verified": _quote_in_turn(session, r.turn, r.transcript_quote)})
    # conditional terms: every number checked against the quote
    new = [t for t in _remap(out.deal_terms, turn["turn"]) if not _duplicate(session, t)]
    if new:
        pairs = dealflow.term_claims(vendor_id, new)
        checked_pairs = []
        for term, claim in pairs:
            checked = verify_against_turns(claim, session.turns)
            session.claims[checked.id] = checked
            checked_pairs.append((term, checked))
        keep, _ = dealflow.verified_terms(new, checked_pairs)
        ok = {t.id for t in keep}
        for t in new:
            session.terms.append(t)
            session.term_ok[t.id] = t.id in ok


def _quote_in_turn(session: CallSession, turn: int | None, quote: str) -> bool:
    t = next((x for x in session.turns if x["turn"] == turn), None)
    q = " ".join(quote.split())
    return bool(t and q and q in " ".join(t["text"].split()))


def _signature(t: DealTerm) -> str:
    d = t.model_dump(mode="json", exclude={"id", "base_of", "quote", "turn"})
    return json.dumps(d, sort_keys=True)


def _duplicate(session: CallSession, t: DealTerm) -> bool:
    """A vendor restating an offer is not a second offer."""
    return any(_signature(t) == _signature(x) for x in session.terms)


# ---------- state ----------


def compute_state(session: CallSession) -> dict[str, Any]:
    """Everything the UI shows, shaped like the Negotiate stage's `data` so the same views render it."""
    vendor_id = session.vendor_id
    lever = apply_levers(build_base(vendor_id))
    verdicts = {s.code: s.verdict for s in lever.skus}
    negotiate_skus = sl.shortlisted(lever, verdicts, only="negotiate")
    short = sl.shortlisted(lever, verdicts)
    application = negotiate.application_terms(vendor_id)
    required = negotiate.required_terms(lever, negotiate_skus, short, vendor_id) if negotiate_skus else None
    commitments: dict[str, dict[str, Any]] = {}
    for row in session.commitments:
        if row["status"] == "verified":
            commitments[row["term"]] = row  # the last verified statement wins
    table = negotiate.gap_table(application, required, commitments) if required else []
    ok_terms = [t for t in session.terms if session.term_ok.get(t.id)]
    deals_data = None
    claims = list(session.claims.values())
    if ok_terms:
        margin = commitments["margin_pct"]["offered"] if "margin_pct" in commitments else application.get("margin_pct")
        days = commitments["payment_days"]["offered"] if "payment_days" in commitments else application.get("payment_days")
        dctx = deals.Context(deals.sku_facts(lever, {s.code for s in short}), margin, days, float(sum(s.alloc_units for s in short)))
        report, engine = dealflow.evaluate_terms(vendor_id, lever, ok_terms, dctx)
        engine = [verify_claim(c) for c in engine]
        claims += engine
        rejected = [{"id": t.id, "label": deals.describe(t, None), "reasons": ["not every number was stated in the quote"]} for t in session.terms if not session.term_ok.get(t.id)]
        tc = [c for c in claims if ":dealterm:" in c.id or ":deal:" in c.id]
        deals_data = {
            "decision": report.decision,
            "headline": report.headline,
            "assessments": [a.model_dump(mode="json") for a in report.assessments],
            "base_terms": [t.model_dump(mode="json") for t in ok_terms if t.kind == "base"],
            "rejected_terms": rejected,
            "assumptions": report.assumptions,
            "talk": None,
            "claim_status": {c.id: c.status for c in tc},
            "verification": _tally(tc),
        }
    state = {
        "gap_table": table,
        "application_terms": application,
        "required": required,
        "commitments": session.commitments,
        "refusals": session.refusals,
        "counter_offer": {"asks": [], "email_draft": ""},
        "transcript": {"turns": [{"turn": t["turn"], "speaker": t["speaker"], "text": t["text"]} for t in session.turns]},
        "transcript_source": "asr" if any(t["source"] == "asr" for t in session.turns) else "canonical",
        "negotiated_skus": [s.code for s in negotiate_skus],
        "deals": deals_data,
        "verification": _tally(claims),
        "spend_usd": round(session.spend_usd, 6),
    }
    state["next_ask"] = next_ask(state, lever, {s.code for s in short}, ended=session.ended)
    return state


def _tally(claims: list[Claim]) -> dict[str, int]:
    return {
        "total": len(claims),
        "verified": sum(1 for c in claims if c.status == "verified"),
        "rejected": sum(1 for c in claims if c.status == "rejected"),
        "unverifiable": sum(1 for c in claims if c.status == "unverifiable"),
    }


def changed(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[str]]:
    """What moved since the last state, so the UI can flash those rows."""
    old = {r["term"]: (r["offered"], r["status"]) for r in before.get("gap_table", [])}
    gap = [r["term"] for r in after.get("gap_table", []) if old.get(r["term"]) != (r["offered"], r["status"])]
    old_d = {a["term_id"]: a["decision"] for a in (before.get("deals") or {}).get("assessments", [])}
    new = [a["term_id"] for a in (after.get("deals") or {}).get("assessments", []) if old_d.get(a["term_id"]) != a["decision"]]
    return {"gap_terms": gap, "deal_ids": new}


# ---------- the next ask ----------


def next_ask(state: dict[str, Any], lever: Any, short_codes: set[str], *, ended: bool = False) -> dict[str, Any]:
    """The buyer's next line and why, from the playbook's rules and the engine's numbers (no model, no invented figure)."""
    for a in (state.get("deals") or {}).get("assessments", []):
        if a["decision"] == "reject_structure" and a.get("counters"):
            rec = a["counters"][a["recommended_counter"] or 0]
            p = deals.fmt_prob(a["probability"]) if a.get("probability") is not None else None
            d = a.get("distribution") or {}
            if rec["kind"] == "threshold":
                line = f"Can you set the target at {deals.fmt_metric(d.get('metric', 'units'), rec['threshold'])} in {d.get('window_days', '')} days instead?"
            elif rec["kind"] == "window":
                line = f"Can we keep the target but allow {rec['window_days']:g} days?"
            else:
                line = f"Can you guarantee {rec['required_base_pts']:g}% instead of tying it to volume?"
            reason = f"Don't accept {a['label']}: " + (f"{p} chance of hitting it. " if p else "") + f"It counts as {a['counted_pts']:g}% against {a['required_pts']:g}% required."
            return {"kind": "reject_conditional", "line": line, "reason": reason, "term": a["term"], "deal_id": a["term_id"]}
        if a["decision"] == "needs_human":
            return {"kind": "hold", "line": "Let me take that away and come back to you.", "reason": a["call"], "term": a["term"], "deal_id": a["term_id"]}
    gaps = [r for r in state.get("gap_table", []) if r["status"] == "gap"]
    if gaps:
        def severity(r: dict[str, Any]) -> float:
            return abs(r["gap"]) / abs(r["required"]) if r["required"] else 0.0

        r = max(gaps, key=severity)
        return _gap_ask(r, state, lever, short_codes)
    unheard = [r for r in state.get("gap_table", []) if r["status"] == "not_stated"]
    if unheard:
        r = unheard[0]
        return {"kind": "ask_term", "line": f"What can you offer on {r['label'].lower()}?", "reason": f"We have not heard a position on {r['label'].lower()} yet; we need {_fmt(r['required'], r['unit'])}.", "term": r["term"]}
    if state.get("gap_table"):
        return {"kind": "done", "line": "That works for us. Please confirm these terms in writing.", "reason": "Every term meets our requirement." if not ended else "The call is over.", "term": None}
    return {"kind": "listen", "line": "Ask where they can get to on margin.", "reason": "Nothing has been agreed yet.", "term": None}


def _fmt(v: float | None, unit: str) -> str:
    if v is None:
        return "-"
    return {"pct": f"{v:g}%", "days": f"{v:g} days", "units": f"{v:g} units", "inr": f"₹{v:,.0f}"}.get(unit, f"{v:g}")


def _gap_ask(r: dict[str, Any], state: dict[str, Any], lever: Any, short_codes: set[str]) -> dict[str, Any]:
    term = r["term"]
    off, req, gap = r["offered"], r["required"], abs(r["gap"])
    if term == "margin_pct":
        app = state.get("application_terms") or {}
        need_days = (state.get("required") or {}).get("payment_days")
        want_days = app.get("payment_days")
        line = f"Can you move margin from {off:g}% toward {req:g}%?"
        reason = f"Margin is still {gap:g} pts short of our {req:g}% target."
        if want_days is not None and need_days is not None and want_days < need_days:
            n = policy.get().negotiation
            skus = deals.sku_facts(lever, short_codes)
            cost = n.cost_of_capital_pct_annual * (need_days - want_days) / 365 * deals.cost_ratio(skus)
            reason += f" They asked for {want_days:g}-day payment; paying {need_days - want_days:g} days sooner costs us {cost:.1f} pts at {n.cost_of_capital_pct_annual:g}% a year, so trade it for margin."
            line = f"We can pay in {want_days:g} days if margin moves from {off:g}% toward {req:g}%. Can you do that?"
        return {"kind": "gap", "line": line, "reason": reason, "term": term}
    verbs = {
        "payment_days": f"Can you extend payment to {req:g} days?",
        "moq": f"Can you bring the first order down from {off:g} to {req:g} units, or phase it?",
        "marketing_inr": f"Can you lift launch marketing support to {_fmt(req, 'inr')}?",
        "launch_discount_pct": f"Can you fund a {req:g}% launch discount?",
        "returns": f"Can you extend the defect-return window to {req:g} days?",
    }
    return {"kind": "gap", "line": verbs.get(term, f"Can you improve {r['label'].lower()}?"), "reason": f"{r['label']} is {_fmt(off, r['unit'])} against {_fmt(req, r['unit'])} required.", "term": term}


# ---------- helpers for the API ----------


def snapshot(session: CallSession) -> dict[str, Any]:
    return {
        "call_id": session.call_id,
        "vendor_id": session.vendor_id,
        "mode": session.mode,
        "ended": session.ended,
        "turns": session.turns,
        "state": session.state,
        "last_seq": session._seq,
        "spend_usd": round(session.spend_usd, 6),
        "public": bool(session.public_ip),
    }


def transcript_hash(session: CallSession) -> str:
    return hashlib.sha256(json.dumps(session.turns, sort_keys=True).encode()).hexdigest()
