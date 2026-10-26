"""Record golden runs: ``uv run python -m app.record --vendor V001|all`` (``make record``).

Drives the real pipeline in-process, end to end (run -> approve research -> approve catalog -> approve the launch
packet at default levers), captures every TraceEvent and StageResult, and records the re-plan narratives for the lever
presets. Output: ``fixtures/golden/runs/<VID>.json`` plus ``<VID>.json.sha256``.

* ``MODEL_MODE=mock`` (the default here): mock fixtures; timings are synthesised so the output is deterministic.
* ``MODEL_MODE=live RECORD=1``: real model calls (costs credits, honours MAX_SPEND_USD); real timings are kept.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app import replay, runner, store
from app.config import settings
from app.constants import ALLOWED_VENDORS
from app.parsing import PARSER_VERSION
from app.schemas import StageResult, TraceEvent

RECORD_TODAY = "2026-10-27"  # the frozen clock golden runs are recorded against
APPROVABLE = ("research", "catalog", "marketing", "jbp", "po")
# Synthetic gaps (ms) for mock recordings, so replay "flows" like a real run and the output is deterministic.
MOCK_GAP_MS = {"stage_started": 300, "tool_call": 700, "model_call": 1100, "claim_checked": 120, "stage_result": 400,
               "degraded": 300, "error": 300, "done": 500}
MOCK_LATENCY_MS = {"tool_call": 180.0, "model_call": 900.0}
PLACEHOLDER_RUN_ID = "run_recorded"


class RecordError(Exception):
    pass


@contextmanager
def _recording_settings(workdir: Path) -> Iterator[str]:
    """Isolated settings: throwaway database (and, in mock, ledger and assets); frozen clock. Yields the source."""
    live = settings.effective_mode == "live"
    saved = {k: getattr(settings, k) for k in ("model_mode", "db_path", "ledger_path", "assets_dir", "demo_today")}
    settings.model_mode = "live" if live else "mock"  # replay never records: it would only record itself
    settings.db_path = workdir / "record.db"
    if not live:
        settings.ledger_path = workdir / "ledger.json"
        settings.assets_dir = workdir / "assets"
    settings.demo_today = settings.demo_today or RECORD_TODAY
    runner.reset_state()
    try:
        yield "live" if live else "mock"
    finally:
        runner.reset_state()
        for key, value in saved.items():
            setattr(settings, key, value)


async def _settled(state: runner.RunState, timeout: float = 600.0) -> None:
    async def wait() -> None:
        while not state.done or state.busy:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout)


def _normalise(events: list[TraceEvent], source: str) -> list[TraceEvent]:
    """Placeholder run id; for mock recordings, synthetic deterministic timings (live keeps the real ones)."""
    out, t = [], 0.0
    for event in events:
        update: dict = {"run_id": PLACEHOLDER_RUN_ID}
        if source == "mock":
            t += MOCK_GAP_MS.get(event.type, 300)
            update["t_rel_ms"] = float(t)
            if event.latency_ms is not None:
                update["latency_ms"] = MOCK_LATENCY_MS.get(event.type, 100.0)
        out.append(event.model_copy(update=update))
    return out


async def _record_main(vendor_id: str, source: str) -> tuple[list[TraceEvent], dict[str, StageResult], list[replay.GoldenApproval]]:
    run_id = await runner.create_run(vendor_id)
    state = await runner.get_state(run_id)
    assert state is not None
    await _settled(state)
    approvals: list[replay.GoldenApproval] = []
    # research -> (negotiate, catalog) -> catalog -> launch packet -> the packet's stages, each at its default levers
    for stage in APPROVABLE:
        result = (await store.get_stages(run_id)).get(stage)
        if result is None or result.status != "review" or not result.narrative_hash:
            continue
        await runner.approve(run_id, stage, result.narrative_hash)
        approvals.append(replay.GoldenApproval(stage=stage, metrics_hash=result.narrative_hash))
        await _settled(state)
    events = await store.events_after(run_id, 0)
    stages = await store.get_stages(run_id)
    return _normalise(events, source), stages, approvals


async def _record_replans(vendor_id: str, source: str) -> dict[str, replay.GoldenReplan]:
    run_id = await runner.create_run(vendor_id)
    state = await runner.get_state(run_id)
    assert state is not None
    await _settled(state)
    research = (await store.get_stages(run_id)).get("research")
    if research is None or research.status != "review":
        return {}
    moq = replay.default_moq(vendor_id)
    out: dict[str, replay.GoldenReplan] = {}
    for offset in replay.PRESET_OFFSETS:
        before, _ = await store.last_event(run_id)
        result = await runner.replan(run_id, vendor_id, float(offset), moq)
        events = _normalise(await store.events_after(run_id, before), source)
        out[str(offset)] = replay.GoldenReplan(
            offset=float(offset), moq=moq, metrics_hash=result.metrics_hash or "", events=events, research=result
        )
    return out


def _build(vendor_id: str, source: str, recorded_at: str, events, stages, approvals, replans) -> replay.GoldenRun:
    return replay.GoldenRun(
        meta=replay.GoldenMeta(
            schema_version=replay.GOLDEN_SCHEMA_VERSION,
            parser_version=PARSER_VERSION,
            recorded_at=recorded_at,
            source=source,  # type: ignore[arg-type]
            metrics_hash=replay.current_metrics_hash(vendor_id),
        ),
        vendor_id=vendor_id,
        events=events,
        stages=stages,
        approvals=approvals,
        replans=replans,
    )


def _stable_recorded_at(vendor_id: str, out_dir: Path, run: replay.GoldenRun, explicit: str | None) -> str:
    """Re-recording identical content keeps the old timestamp, so unchanged runs produce no diff."""
    if explicit:
        return explicit
    path = out_dir / f"{vendor_id}.json"
    if path.exists():
        try:
            old = json.loads(path.read_text())
            probe = replay.GoldenRun.model_validate({**old, "meta": {**old["meta"], "recorded_at": run.meta.recorded_at}})
            if replay.serialize(probe) == replay.serialize(run):
                return old["meta"]["recorded_at"]
        except Exception:  # noqa: BLE001, S110 - an unreadable old file is simply replaced
            pass
    return run.meta.recorded_at


async def record_vendor(vendor_id: str, out_dir: Path | None = None, *, recorded_at: str | None = None) -> Path:
    out_dir = out_dir or replay.golden_dir()
    with tempfile.TemporaryDirectory(prefix="categoryos-record-") as tmp, _recording_settings(Path(tmp)) as source:
        events, stages, approvals = await _record_main(vendor_id, source)
        replans = await _record_replans(vendor_id, source)
    now = recorded_at or os.environ.get("RECORDED_AT") or datetime.now(UTC).isoformat(timespec="seconds")
    run = _build(vendor_id, source, now, events, stages, approvals, replans)
    run = run.model_copy(
        update={"meta": run.meta.model_copy(update={"recorded_at": _stable_recorded_at(vendor_id, out_dir, run, recorded_at or os.environ.get("RECORDED_AT"))})}
    )
    return replay.write_golden(run, out_dir)


async def record_all(vendors: list[str], out_dir: Path | None = None, *, recorded_at: str | None = None) -> list[Path]:
    return [await record_vendor(v, out_dir, recorded_at=recorded_at) for v in vendors]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record golden runs for replay mode")
    parser.add_argument("--vendor", default="all", help="V001..V004 or all")
    parser.add_argument("--out", type=Path, default=None, help="output directory (default fixtures/golden/runs)")
    args = parser.parse_args(argv)
    vendors = list(ALLOWED_VENDORS) if args.vendor == "all" else [args.vendor]
    if any(v not in ALLOWED_VENDORS for v in vendors):
        print(f"unknown vendor {args.vendor!r}; use one of {', '.join(ALLOWED_VENDORS)} or all", file=sys.stderr)
        return 2
    if settings.effective_mode == "live":
        print("RECORDING LIVE: real model calls, costs credits (cap: MAX_SPEND_USD)", file=sys.stderr)
    for path in asyncio.run(record_all(vendors, args.out)):
        print(f"recorded {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
