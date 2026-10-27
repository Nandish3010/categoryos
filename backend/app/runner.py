"""Run orchestration. ``run_stage`` is a pure async generator of TraceEvents; the wrapper around it persists each
event (monotonic seq), publishes it to live SSE subscribers, and drives the stage FSM
pending -> running -> review | done | failed | locked. In-process only (max_containers=1)."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app import copilot, impact, registry, replay, store
from app.agents import catalog, decide, launch, negotiate, screen
from app.agents import shortlist as sl
from app.agents.context import RunContext, Sequencer
from app.config import settings
from app.constants import ALLOWED_VENDORS, STAGE_META
from app.data_loader import check_vendor, clear_transcript_overrides
from app.errors import (
    CategoryOSError,
    NarrativeUnavailable,
    RunNotFound,
    StageLocked,
    StageNotReviewable,
    StaleApproval,
    UnknownSku,
    UnknownStage,
)
from app.metrics import apply_levers, build_base
from app.schemas import StageResult, TraceEvent

log = logging.getLogger("categoryos.runner")

STAGE_IDS = [s["id"] for s in STAGE_META]
Agent = Callable[[RunContext], Awaitable[StageResult]]
MultiAgent = Callable[[RunContext], Awaitable[dict[str, StageResult]]]
_END = object()


@dataclass
class RunState:
    run_id: str
    vendor_id: str
    sequencer: Sequencer
    subscribers: list[asyncio.Queue[TraceEvent]] = field(default_factory=list)
    done: bool = False
    busy: bool = False
    db: Any = store  # app.store, or the in-memory replay session store
    golden: replay.GoldenRun | None = None  # set for replay sessions


_states: dict[str, RunState] = {}
_tasks: set[asyncio.Task] = set()


def _db(run_id: str) -> Any:
    """The persistence backend of a run: the in-memory store for replay sessions, SQLite otherwise."""
    return replay.session_store if replay.has_session(run_id) else store


def today() -> str:
    return settings.demo_today or date.today().isoformat()


def reset_state() -> None:
    """Forget in-memory run state (tests, admin reset). Running tasks are cancelled."""
    for task in list(_tasks):
        task.cancel()
    _tasks.clear()
    _states.clear()
    replay.reset_sessions()
    replay.forget()
    copilot.reset()
    clear_transcript_overrides()


# ---------- the pure generator ----------


async def _drain(ctx: RunContext, task: asyncio.Future) -> AsyncIterator[TraceEvent]:
    """Yield what the agent emits until it returns."""
    task.add_done_callback(lambda _t: ctx.queue.put_nowait(_END))
    while True:
        item = await ctx.queue.get()
        if item is _END:
            break
        yield item


def _crash_result(stage_id: str, exc: BaseException, ctx: RunContext) -> tuple[TraceEvent, StageResult]:
    if isinstance(exc, CategoryOSError):
        event = ctx.emit("error", stage_id, exc.to_dict(ctx.run_id))
        return event, StageResult(stage=stage_id, status="failed", summary=exc.problem, data={"error": exc.to_dict(ctx.run_id)})
    log.error("stage %s crashed", stage_id, exc_info=exc)
    event = ctx.emit("error", stage_id, {"code": "internal_error", "problem": "The stage crashed", "cause": repr(exc)[:300]})
    return event, StageResult(stage=stage_id, status="failed", summary="The stage crashed", data={"error": repr(exc)[:300]})


async def run_stage(ctx: RunContext, stage_id: str, agent: Agent) -> AsyncIterator[TraceEvent]:
    """Yield the TraceEvents of one stage: stage_started, whatever the agent emits, stage_result.
    The StageResult is also available as ``ctx.result`` after the generator is exhausted."""
    ctx.emit("stage_started", stage_id, {"stage": stage_id})
    task = asyncio.ensure_future(agent(ctx))
    async for item in _drain(ctx, task):
        yield item
    try:
        result = task.result()
    except Exception as exc:  # noqa: BLE001
        event, result = _crash_result(stage_id, exc, ctx)
        yield event
    ctx.result = result
    yield ctx.emit("stage_result", stage_id, result.model_dump(mode="json"))
    while not ctx.queue.empty():  # events emitted after the agent returned (none today)
        item = ctx.queue.get_nowait()
        if item is not _END:
            yield item


async def run_stages(ctx: RunContext, stage_ids: tuple[str, ...], agent: MultiAgent) -> AsyncIterator[TraceEvent]:
    """One agent, several stages (the Launch packet). ``ctx.results`` maps stage id -> StageResult afterwards."""
    for sid in stage_ids:
        ctx.emit("stage_started", sid, {"stage": sid})
    task = asyncio.ensure_future(agent(ctx))
    async for item in _drain(ctx, task):
        yield item
    results: dict[str, StageResult]
    try:
        results = task.result()
    except Exception as exc:  # noqa: BLE001
        event, failed = _crash_result(stage_ids[0], exc, ctx)
        yield event
        results = {sid: failed.model_copy(update={"stage": sid}) for sid in stage_ids}
    ctx.results = results
    for sid in stage_ids:
        yield ctx.emit("stage_result", sid, results[sid].model_dump(mode="json"))
    while not ctx.queue.empty():
        item = ctx.queue.get_nowait()
        if item is not _END:
            yield item


# ---------- persistence and pub/sub ----------


async def _persist_publish(state: RunState, event: TraceEvent) -> None:
    await state.db.append_event(event)
    for queue in state.subscribers:
        queue.put_nowait(event)


async def _mark_review(db: Any, run_id: str, result: StageResult) -> None:
    """Start the human-review clock the first time a stage waits on a person (impact meter)."""
    if result.status != "review" or not result.needs_approval:
        return
    if any(m["stage"] == result.stage and m["kind"] == "review_started" for m in await db.list_marks(run_id)):
        return
    await db.add_mark(run_id, result.stage, "review_started")


async def _drive_stage(
    state: RunState, stage_id: str, agent: Agent, before_save: Callable[[StageResult], Awaitable[None]] | None = None
) -> StageResult:
    """Run one stage and persist its result. ``before_save`` runs just before the result is stored, so anything that must
    be visible no later than this stage (research's shortlist mirror) is never missing when a reader sees the result."""
    ctx = RunContext(state.run_id, state.vendor_id, today(), state.sequencer)
    await state.db.save_stage(state.run_id, StageResult(stage=stage_id, status="running", summary="Running"))
    async for event in run_stage(ctx, stage_id, agent):
        await _persist_publish(state, event)
    result = ctx.result
    assert result is not None
    if before_save is not None:
        await before_save(result)
    await state.db.save_stage(state.run_id, result)
    await _mark_review(state.db, state.run_id, result)
    return result


async def _drive_multi(state: RunState, stage_ids: tuple[str, ...], agent: MultiAgent) -> dict[str, StageResult]:
    ctx = RunContext(state.run_id, state.vendor_id, today(), state.sequencer)
    for sid in stage_ids:
        await state.db.save_stage(state.run_id, StageResult(stage=sid, status="running", summary="Running"))
    async for event in run_stages(ctx, stage_ids, agent):
        await _persist_publish(state, event)
    for result in ctx.results.values():
        await state.db.save_stage(state.run_id, result)
        await _mark_review(state.db, state.run_id, result)
    return ctx.results


async def _mirror_shortlist(state: RunState, research: StageResult, *, done: bool, emit: bool = True) -> None:
    """The `shortlist` stage mirrors research's verdict table; it is done once research is approved."""
    result = sl.shortlist_stage(research, state.vendor_id, done=done)
    await state.db.save_stage(state.run_id, result)
    if emit:
        ctx = RunContext(state.run_id, state.vendor_id, today(), state.sequencer)
        await _persist_publish(state, ctx.emit("stage_result", "shortlist", result.model_dump(mode="json")))


def _spawn(state: RunState, phase: str, work: Callable[[RunState], Awaitable[None]]) -> None:
    """Run a post-approval phase in the background. It ends with a `done` event carrying {phase}."""
    state.done = False
    state.busy = True

    async def go() -> None:
        try:
            await work(state)
        except Exception:
            log.exception("run %s phase %s crashed", state.run_id, phase)
        finally:
            state.busy = False
            await _finish(state, {"phase": phase})

    task = asyncio.create_task(go())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _phase_execute(state: RunState) -> None:
    """After research is approved: Negotiate, then Catalog."""
    research = await get_stage(state.run_id, "research")
    await _mirror_shortlist(state, research, done=True)

    async def run_negotiate(ctx: RunContext) -> StageResult:
        return await negotiate.run(ctx, research)

    async def run_catalog(ctx: RunContext) -> StageResult:
        return await catalog.run(ctx, research)

    await _drive_stage(state, "negotiate", run_negotiate)
    await _drive_stage(state, "catalog", run_catalog)


async def _phase_launch(state: RunState) -> None:
    """After the catalog is approved: the Launch packet (marketing, jbp, po)."""
    research = await get_stage(state.run_id, "research")
    neg = await get_stage(state.run_id, "negotiate")

    async def run_launch(ctx: RunContext) -> dict[str, StageResult]:
        return await launch.run(ctx, research, neg if neg.status == "done" else None)

    await _drive_multi(state, launch.STAGES, run_launch)


async def _finish(state: RunState, payload: dict | None = None) -> None:
    ctx = RunContext(state.run_id, state.vendor_id, today(), state.sequencer)
    event = ctx.emit("done", None, payload or {})
    await _persist_publish(state, event)
    state.done = True


# ---------- replay sessions ----------


async def _play(state: RunState, events: list[TraceEvent], *, cap_s: float = replay.MAX_GAP_S) -> None:
    """Re-emit recorded events on this session with the recorded gaps (each capped at ``cap_s``), updating the session's
    stage results as stage_started / stage_result events go by. seq and t_rel_ms are re-stamped on the session clock."""
    prev_ms: float | None = None
    for src in events:
        gap = 0.2 if prev_ms is None else max(src.t_rel_ms - prev_ms, 0.0) / 1000
        prev_ms = src.t_rel_ms
        await replay.sleep(min(gap, cap_s))
        payload = src.payload
        if src.type == "model_call" and "mode" in payload:
            payload = {**payload, "mode": "replay"}
        event = src.model_copy(
            update={
                "run_id": state.run_id,
                "seq": state.sequencer.next(),
                "t_rel_ms": state.sequencer.t_rel_ms(),
                "payload": payload,
            }
        )
        if event.type == "stage_started" and event.stage:
            current = (await state.db.get_stages(state.run_id)).get(event.stage)
            if current is None or current.status not in {"review", "done"}:
                await state.db.save_stage(state.run_id, StageResult(stage=event.stage, status="running", summary="Running"))
        elif event.type == "stage_result" and event.stage:
            played = StageResult.model_validate(event.payload)
            await state.db.save_stage(state.run_id, played)
            await _mark_review(state.db, state.run_id, played)
        await _persist_publish(state, event)


async def _replay_start(state: RunState) -> None:
    assert state.golden is not None
    try:
        await _play(state, state.golden.phase_events("start"))
    except Exception:
        log.exception("replay %s crashed", state.run_id)
    finally:
        await _finish(state)


def _replay_phase(phase: str) -> Callable[[RunState], Awaitable[None]]:
    async def work(state: RunState) -> None:
        assert state.golden is not None
        await _play(state, state.golden.phase_events(phase))

    return work


async def _lock_downstream(state: RunState, first_failed: StageResult) -> None:
    ctx = RunContext(state.run_id, state.vendor_id, today(), state.sequencer)
    reason = f"Screening failed: {first_failed.locked_reason or first_failed.summary}"
    for stage_id in STAGE_IDS[1:]:
        locked = StageResult(stage=stage_id, status="locked", summary="Locked", locked_reason=reason)
        await state.db.save_stage(state.run_id, locked)
        await _persist_publish(state, ctx.emit("stage_result", stage_id, locked.model_dump(mode="json")))


async def _execute(state: RunState) -> None:
    with registry.scoped(state.vendor_id):  # a sandbox vendor runs under its own playbook, market data and model mode
        await _execute_scoped(state)


async def _execute_scoped(state: RunState) -> None:
    try:
        screened = await _drive_stage(state, "intake", screen.run)
        if screened.status == "failed":
            await _lock_downstream(state, screened)
        else:

            async def mirror(research: StageResult) -> None:
                # research and its shortlist mirror appear together: a reader that sees research in review also sees
                # shortlist in review (saving research first left a window where the shortlist was still pending)
                if research.status == "review":
                    await _mirror_shortlist(state, research, done=False)

            await _drive_stage(state, "research", decide.run, before_save=mirror)
    except Exception:
        log.exception("run %s crashed", state.run_id)
    finally:
        await _finish(state)


async def create_run(vendor_id: str) -> str:
    check_vendor(vendor_id)
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    golden = replay.golden_for(vendor_id)
    if golden is not None:  # replay mode: an ephemeral in-memory session, no database writes
        await replay.session_store.create_run(run_id, vendor_id, "replay")
        state = RunState(run_id, vendor_id, Sequencer(), db=replay.session_store, golden=golden)
        work = _replay_start(state)
    else:
        meta = registry.read_meta(vendor_id) if registry.is_sandbox_id(vendor_id) else None
        await store.create_run(run_id, vendor_id, meta["llm_mode"] if meta else settings.effective_mode)
        state = RunState(run_id, vendor_id, Sequencer())
        work = _execute(state)
    _states[run_id] = state
    task = asyncio.create_task(work)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return run_id


async def get_state(run_id: str) -> RunState | None:
    """In-memory state for a run, rebuilt from the store after a restart. None if the run is unknown."""
    state = _states.get(run_id)
    if state is not None:
        return state
    if replay.pure_replay():  # sandbox runs live in the database even in replay mode, so look once
        run = await store.get_run(run_id) if run_id.startswith("run_") else None
        if run is None or not registry.is_sandbox_id(run["vendor_id"]):
            return None
    run = await store.get_run(run_id)
    if run is None:
        return None
    seq, t_rel = await store.last_event(run_id)
    state = RunState(run_id, run["vendor_id"], Sequencer(seq, t_rel), done=True)
    _states[run_id] = state
    return state


async def latest_run(vendor_id: str) -> str | None:
    if replay.pure_replay() and not registry.is_sandbox_id(vendor_id):
        return await replay.session_store.latest_run(vendor_id)
    return await store.latest_run(vendor_id) or await replay.session_store.latest_run(vendor_id)


async def require_run(run_id: str) -> dict:
    if not replay.has_session(run_id) and replay.pure_replay() and run_id not in _states:
        raise RunNotFound(run_id)  # replay mode never opens the database (sandbox runs are in _states)
    run = await _db(run_id).get_run(run_id)
    if run is None:
        raise RunNotFound(run_id)
    return run


async def get_run_view(run_id: str) -> dict:
    run = await require_run(run_id)
    stored = await _db(run_id).get_stages(run_id)
    stages = {
        sid: (stored.get(sid) or StageResult(stage=sid, status="pending")).model_dump(mode="json") for sid in STAGE_IDS
    }
    prov = replay.provenance(run["vendor_id"]) if run.get("mode") == "replay" else None
    return {**run, "stages": stages, "impact": await run_impact(run_id), "provenance": prov}


# ---------- impact meter ----------


def _shortlisted(vendor_id: str) -> int:
    return apply_levers(build_base(vendor_id)).summary.shortlisted


async def run_impact(run_id: str) -> dict:
    """The run's impact block: baseline hours vs the human review time recorded so far (see app.impact)."""
    run = await require_run(run_id)
    db = _db(run_id)
    stages = await db.get_stages(run_id)
    short = stages.get("shortlist")
    n_skus = int(short.data["shortlisted"]) if short is not None and "shortlisted" in short.data else _shortlisted(run["vendor_id"])
    return impact.for_run(run, await db.list_approvals(run_id), await db.list_marks(run_id), await db.list_overrides(run_id), n_skus)


async def team_impact() -> dict:
    """GET /api/impact: the team rollup over every vendor's latest run."""
    blocks = []
    for vendor_id in ALLOWED_VENDORS:
        run_id = await latest_run(vendor_id)
        if run_id is not None:
            blocks.append(await run_impact(run_id))
    return {**impact.rollup(blocks), "mode": "replay" if replay.pure_replay() else settings.effective_mode}


def check_stage(stage: str) -> str:
    if stage not in STAGE_IDS:
        raise UnknownStage(stage)
    return stage


async def get_stage(run_id: str, stage: str) -> StageResult:
    await require_run(run_id)
    check_stage(stage)
    stored = await _db(run_id).get_stages(run_id)
    return stored.get(stage) or StageResult(stage=stage, status="pending")


# ---------- actions ----------


async def replan(run_id: str, vendor_id: str, offset: float, moq: int) -> StageResult:
    run = await require_run(run_id)
    check_vendor(vendor_id)
    if run["vendor_id"] != vendor_id:
        raise RunNotFound(run_id)
    current = await get_stage(run_id, "research")
    if current.status == "locked":
        raise StageLocked(cause=current.locked_reason or "the stage did not run")
    if current.status not in {"review", "done"}:
        raise StageNotReviewable(cause=f"research is {current.status}")
    stages = await _db(run_id).get_stages(run_id)
    if (stages.get("negotiate") or StageResult(stage="negotiate", status="pending")).status != "pending":
        raise StageNotReviewable(cause="research is already approved and later stages have started")
    state = await get_state(run_id)
    assert state is not None
    if state.busy:
        raise StageNotReviewable(cause="a re-plan is already running for this run")
    if state.golden is not None:
        return await _replan_replay(state, offset, moq)
    state.busy = True
    try:
        async def agent(ctx: RunContext) -> StageResult:
            return await decide.run(ctx, offset=offset, moq=moq, replan=True)

        result = await _drive_stage(state, "research", agent)
        if result.status == "review":
            await _mirror_shortlist(state, result, done=False)
        await state.db.add_mark(run_id, "research", "replan")
        await _finish(state, {"replan": True})
        return result
    finally:
        state.busy = False


async def _replan_replay(state: RunState, offset: float, moq: int) -> StageResult:
    """Replay: serve the cached narrative for a lever preset (offset 0, +2, +4 at the vendor's default MOQ)."""
    assert state.golden is not None
    key = replay.preset_key(offset, moq, state.vendor_id)
    cached = state.golden.replans.get(key) if key is not None else None
    if cached is None:
        raise NarrativeUnavailable()
    state.busy = True
    try:
        await state.db.save_stage(state.run_id, StageResult(stage="research", status="running", summary="Running"))
        await _play(state, [e for e in cached.events if e.type != "done"], cap_s=replay.REPLAN_GAP_S)
        await state.db.add_mark(state.run_id, "research", "replan")
        await _finish(state, {"replan": True})
        return (await state.db.get_stages(state.run_id))["research"]
    finally:
        state.busy = False


async def approve(run_id: str, stage: str, metrics_hash: str) -> StageResult:
    result = await get_stage(run_id, stage)
    if result.status == "locked":
        raise StageLocked(cause=result.locked_reason or f"{stage} is locked")
    if result.status not in {"review", "done"} or result.narrative_hash is None:
        raise StageNotReviewable(cause=f"{stage} is {result.status}" + ("" if result.narrative_hash else " and has no narrative to approve"))
    if metrics_hash != result.narrative_hash:
        raise StaleApproval(
            cause=(
                f"approval was for metrics {metrics_hash[:12]}, the narrative was generated for "
                f"{result.narrative_hash[:12]}"
            )
        )
    approved = result.model_copy(update={"status": "done", "needs_approval": False})
    await _db(run_id).save_stage(run_id, approved)
    await _db(run_id).add_approval(run_id, stage, "approve", metrics_hash)
    if result.status == "review":  # first approval only: a repeat approve never re-runs the next phase
        state = await get_state(run_id)
        assert state is not None
        if stage == "research" and not state.busy and registry.is_sandbox_id(state.vendor_id):
            await _db(run_id).save_stage(run_id, sl.shortlist_stage(approved, state.vendor_id, done=True))
            for later in STAGE_IDS[3:]:  # sandbox vendors are decided at Screen and Decide; the rest needs recorded fixtures
                await _db(run_id).save_stage(run_id, StageResult(stage=later, status="locked", summary="Locked", locked_reason="Sandbox vendors run Screen and Decide only; the later stages are available on the built-in vendors"))
        elif stage == "research" and not state.busy:
            await _db(run_id).save_stage(run_id, sl.shortlist_stage(approved, state.vendor_id, done=True))
            _spawn(state, "execute", _replay_phase("execute") if state.golden else _phase_execute)
        elif stage == "catalog" and not state.busy:
            _spawn(state, "launch", _replay_phase("launch") if state.golden else _phase_launch)
    return approved


async def override(run_id: str, stage: str, sku_code: str, verdict: str, note: str | None) -> StageResult:
    result = await get_stage(run_id, stage)
    if result.status not in {"review", "done"}:
        raise StageNotReviewable(cause=f"{stage} is {result.status}")
    data = dict(result.data)
    rows = [dict(r) for r in data.get("rationale_per_sku", [])]
    row = next((r for r in rows if r["code"] == sku_code), None)
    if row is None:
        raise UnknownSku(sku_code)
    original = row.get("original_verdict", row["verdict"])
    row.update(verdict=verdict, edited_by_human=True, original_verdict=original, note=note)
    data["rationale_per_sku"] = rows
    data["overrides"] = {**data.get("overrides", {}), sku_code: {"verdict": verdict, "original_verdict": original, "note": note, "edited_by_human": True}}
    updated = result.model_copy(update={"data": data})
    await _db(run_id).save_stage(run_id, updated)
    await _db(run_id).add_override(run_id, stage, sku_code, verdict, note)
    return updated


async def reject(run_id: str, vendor_id: str, reason: str) -> dict:
    run = await require_run(run_id)
    check_vendor(vendor_id)
    if run["vendor_id"] != vendor_id:
        raise RunNotFound(run_id)
    current = await get_stage(run_id, "research")
    if current.status in {"locked", "pending", "running"}:
        raise StageNotReviewable(cause=f"research is {current.status}")
    rejected = current.model_copy(
        update={"status": "failed", "needs_approval": False, "summary": f"Rejected by the category manager: {reason}",
                "data": {**current.data, "rejected": True, "reject_reason": reason}}
    )
    await _db(run_id).save_stage(run_id, rejected)
    for stage_id in STAGE_IDS[2:]:
        await _db(run_id).save_stage(run_id, StageResult(stage=stage_id, status="locked", summary="Locked", locked_reason=f"Vendor rejected: {reason}"))
    await _db(run_id).add_approval(run_id, "research", "reject", None, reason)
    return {"run_id": run_id, "vendor_id": vendor_id, "status": "rejected", "reason": reason}


async def reset() -> None:
    reset_state()
    if not replay.pure_replay():
        await store.reset()
