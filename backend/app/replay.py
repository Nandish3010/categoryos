"""Replay mode: golden runs and the in-memory session store.

A golden run (``fixtures/golden/runs/<VID>.json``) is one complete recorded run: every TraceEvent in order (all phases,
each ending with a ``done``), the final StageResults, the approvals taken at default levers, and the cached re-plan
narratives for the lever presets. ``<VID>.json.sha256`` sits next to it. In replay mode ``POST /runs`` creates an
ephemeral session (no DB writes) that the runner feeds from these events; approve / override / reject / replan act on the
session only.
"""

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import settings
from app.constants import ALLOWED_VENDORS
from app.metrics import apply_levers, build_base
from app.parsing import PARSER_VERSION
from app.schemas import StageResult, TraceEvent

log = logging.getLogger("categoryos.replay")

GOLDEN_SCHEMA_VERSION = 1
PRESET_OFFSETS = (0, 2, 4)
MAX_GAP_S = 1.5
REPLAN_GAP_S = 0.05
MAX_SESSIONS = 200
PHASES = ("start", "execute", "launch")  # golden events are split on `done` events, in this order


# ---------- golden models ----------


class GoldenMeta(BaseModel):
    schema_version: int
    parser_version: str
    recorded_at: str
    source: Literal["mock", "live"]
    metrics_hash: str


class GoldenApproval(BaseModel):
    stage: str
    metrics_hash: str


class GoldenReplan(BaseModel):
    offset: float
    moq: int
    metrics_hash: str
    events: list[TraceEvent]
    research: StageResult


class GoldenRun(BaseModel):
    meta: GoldenMeta
    vendor_id: str
    events: list[TraceEvent]
    stages: dict[str, StageResult]
    approvals: list[GoldenApproval] = Field(default_factory=list)
    replans: dict[str, GoldenReplan] = Field(default_factory=dict)

    def phase_events(self, phase: str) -> list[TraceEvent]:
        """Events of one phase, without its closing `done` (the runner emits that itself)."""
        index = PHASES.index(phase)
        out: list[list[TraceEvent]] = [[]]
        for event in self.events:
            if event.type == "done":
                out.append([])
            else:
                out[-1].append(event)
        return out[index] if index < len(out) else []


class GoldenInvalid(Exception):
    pass


# ---------- files ----------


def golden_dir() -> Path:
    return Path(settings.fixtures_dir) / "golden" / "runs"


def checksum_path(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def default_moq(vendor_id: str) -> int:
    return apply_levers(build_base(vendor_id)).summary.moq


def current_metrics_hash(vendor_id: str) -> str:
    return apply_levers(build_base(vendor_id)).metrics_hash


def serialize(run: GoldenRun) -> bytes:
    return (json.dumps(run.model_dump(mode="json"), indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode()


def write_golden(run: GoldenRun, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run.vendor_id}.json"
    data = serialize(run)
    path.write_bytes(data)
    checksum_path(path).write_text(hashlib.sha256(data).hexdigest() + "\n")
    return path


def load_golden(vendor_id: str, directory: Path | None = None, *, check_drift: bool = True) -> GoldenRun:
    """Load and validate one golden run. Raises GoldenInvalid with a human reason on any problem."""
    path = (directory or golden_dir()) / f"{vendor_id}.json"
    if not path.exists():
        raise GoldenInvalid(f"no golden run at {path.name}")
    sum_path = checksum_path(path)
    if not sum_path.exists():
        raise GoldenInvalid(f"missing checksum file {sum_path.name}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sum_path.read_text().strip():
        raise GoldenInvalid(f"checksum mismatch for {path.name}")
    try:
        raw = json.loads(data)
        version = raw.get("meta", {}).get("schema_version")
        if version != GOLDEN_SCHEMA_VERSION:
            raise GoldenInvalid(f"schema_version {version!r}, expected {GOLDEN_SCHEMA_VERSION}")
        run = GoldenRun.model_validate(raw)
    except GoldenInvalid:
        raise
    except Exception as exc:
        raise GoldenInvalid(f"{path.name} does not match the current models: {str(exc)[:200]}") from exc
    if run.vendor_id != vendor_id:
        raise GoldenInvalid(f"{path.name} is for vendor {run.vendor_id}")
    if run.meta.parser_version != PARSER_VERSION:
        raise GoldenInvalid(f"parser_version {run.meta.parser_version!r}, expected {PARSER_VERSION!r}")
    if check_drift and run.meta.metrics_hash != current_metrics_hash(vendor_id):
        raise GoldenInvalid("metrics_hash drift: the engine output changed since this run was recorded")
    return run


# ---------- registry ----------

_goldens: dict[str, GoldenRun] = {}
_problems: dict[str, str] = {}
_loaded = False


def load_all() -> dict[str, str]:
    """Validate every vendor's golden run. Returns {vendor_id: problem} for the ones that failed (they are served from
    the mock fixtures, flagged degraded)."""
    global _loaded
    _goldens.clear()
    _problems.clear()
    for vendor_id in ALLOWED_VENDORS:
        try:
            _goldens[vendor_id] = load_golden(vendor_id)
        except GoldenInvalid as exc:
            _problems[vendor_id] = str(exc)
            log.warning("replay: golden run for %s unusable (%s); serving mock fixtures, degraded", vendor_id, exc)
    _loaded = True
    return dict(_problems)


def _ensure() -> None:
    if not _loaded:
        load_all()


def forget() -> None:
    global _loaded
    _loaded = False
    _goldens.clear()
    _problems.clear()


def golden_for(vendor_id: str) -> GoldenRun | None:
    if settings.model_mode != "replay":
        return None
    _ensure()
    return _goldens.get(vendor_id)


def problems() -> dict[str, str]:
    if settings.model_mode != "replay":
        return {}
    _ensure()
    return dict(_problems)


def pure_replay() -> bool:
    """Replay mode with every golden run valid: the database is never touched."""
    return settings.model_mode == "replay" and not problems()


def status() -> dict[str, Any]:
    found = problems()
    return {"vendors": {v: found.get(v, "ok") for v in ALLOWED_VENDORS}}


# ---------- in-memory session store (same async API as app.store) ----------


def _now() -> str:
    from app.store import now_iso

    return now_iso()


class ReplayStore:
    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self.runs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.events: dict[str, list[TraceEvent]] = {}
        self.stages: dict[str, dict[str, StageResult]] = {}
        self.approvals: dict[str, list[dict[str, Any]]] = {}
        self.overrides: dict[str, list[dict[str, Any]]] = {}
        self.marks: dict[str, list[dict[str, Any]]] = {}
        self.latest: dict[str, str] = {}

    def has(self, run_id: str) -> bool:
        return run_id in self.runs

    async def init(self) -> None:
        return None

    async def reset(self) -> None:
        self.clear()

    async def create_run(self, run_id: str, vendor_id: str, mode: str) -> str:
        created = _now()
        self.runs[run_id] = {"run_id": run_id, "vendor_id": vendor_id, "mode": mode, "created_at": created}
        self.events[run_id], self.stages[run_id] = [], {}
        self.approvals[run_id], self.overrides[run_id], self.marks[run_id] = [], [], []
        self.latest[vendor_id] = run_id
        while len(self.runs) > MAX_SESSIONS:
            old, meta = self.runs.popitem(last=False)
            for table in (self.events, self.stages, self.approvals, self.overrides, self.marks):
                table.pop(old, None)
            if self.latest.get(meta["vendor_id"]) == old:
                self.latest.pop(meta["vendor_id"], None)
        return created

    async def append_event(self, event: TraceEvent) -> None:
        self.events[event.run_id].append(event)

    async def events_after(self, run_id: str, after_seq: int = 0) -> list[TraceEvent]:
        return [e for e in self.events.get(run_id, []) if e.seq > after_seq]

    async def last_event(self, run_id: str) -> tuple[int, float]:
        events = self.events.get(run_id) or []
        return (events[-1].seq, events[-1].t_rel_ms) if events else (0, 0.0)

    async def save_stage(self, run_id: str, result: StageResult) -> None:
        self.stages[run_id][result.stage] = result

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.get(run_id)

    async def latest_run(self, vendor_id: str) -> str | None:
        return self.latest.get(vendor_id)

    async def get_stages(self, run_id: str) -> dict[str, StageResult]:
        return dict(self.stages.get(run_id, {}))

    async def add_approval(
        self, run_id: str, stage: str, action: str, metrics_hash: str | None = None, note: str | None = None
    ) -> None:
        rows = self.approvals[run_id]
        rows.append(
            {"id": len(rows) + 1, "run_id": run_id, "stage": stage, "action": action, "metrics_hash": metrics_hash,
             "note": note, "created_at": _now()}
        )

    async def add_override(self, run_id: str, stage: str, sku_code: str, verdict: str, note: str | None = None) -> None:
        rows = self.overrides[run_id]
        rows.append(
            {"id": len(rows) + 1, "run_id": run_id, "stage": stage, "sku_code": sku_code, "verdict": verdict,
             "note": note, "created_at": _now()}
        )

    async def add_mark(self, run_id: str, stage: str, kind: str) -> None:
        rows = self.marks[run_id]
        rows.append({"id": len(rows) + 1, "run_id": run_id, "stage": stage, "kind": kind, "created_at": _now()})

    async def list_marks(self, run_id: str) -> list[dict[str, Any]]:
        return list(self.marks.get(run_id, []))

    async def list_approvals(self, run_id: str) -> list[dict[str, Any]]:
        return list(self.approvals.get(run_id, []))

    async def list_overrides(self, run_id: str) -> list[dict[str, Any]]:
        return list(self.overrides.get(run_id, []))


session_store = ReplayStore()


def has_session(run_id: str) -> bool:
    return session_store.has(run_id)


def reset_sessions() -> None:
    session_store.clear()


def preset_key(offset: float, moq: int, vendor_id: str) -> str | None:
    """The golden re-plan key for these lever values, or None when it is not a preset."""
    if moq != default_moq(vendor_id) or offset != int(offset) or int(offset) not in PRESET_OFFSETS:
        return None
    return str(int(offset))


async def sleep(seconds: float) -> None:  # patched out in tests
    await asyncio.sleep(seconds)
