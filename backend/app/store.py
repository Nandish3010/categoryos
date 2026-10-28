"""SQLite persistence (stdlib sqlite3, run in a worker thread). One short-lived connection per call,
so it is safe across threads. Tables: runs, events, stage_results, approvals, overrides, marks (review clock, re-plans),
policy_changes (the playbook change log) and visitor_playbooks (a public visitor's own playbook overrides). The last two are not
in TABLES: ``reset`` is the demo reset for runs, and the change log is an audit trail that must survive it."""

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app import persist
from app.config import settings
from app.schemas import StageResult, TraceEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    t_rel_ms REAL NOT NULL,
    type TEXT NOT NULL,
    stage TEXT,
    body TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS stage_results (
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, stage)
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    action TEXT NOT NULL,
    metrics_hash TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    sku_code TEXT NOT NULL,
    verdict TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policy_changes (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    visitor TEXT NOT NULL,
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    body TEXT NOT NULL,
    touched TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS limit_anchors (
    visitor TEXT NOT NULL,
    path TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (visitor, path)
);
CREATE INDEX IF NOT EXISTS policy_changes_visitor ON policy_changes (visitor, seq);
CREATE TABLE IF NOT EXISTS visitor_playbooks (
    visitor TEXT PRIMARY KEY,
    overrides TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""
TABLES = ("runs", "events", "stage_results", "approvals", "overrides", "marks")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _connect() -> sqlite3.Connection:
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.executescript(SCHEMA)
    return conn


def _exec(sql: str, params: tuple[Any, ...] = ()) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute(sql, params)
    persist.notify()


def _rows(sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    with closing(_connect()) as conn:
        return conn.execute(sql, params).fetchall()


# ---------- sync implementations ----------


def _init() -> None:
    _connect().close()


def _reset() -> None:
    with closing(_connect()) as conn, conn:
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence")


def _create_run(run_id: str, vendor_id: str, mode: str) -> str:
    created = now_iso()
    _exec("INSERT INTO runs (run_id, vendor_id, mode, created_at) VALUES (?, ?, ?, ?)", (run_id, vendor_id, mode, created))
    return created


def _append_event(event: TraceEvent) -> None:
    _exec(
        "INSERT OR REPLACE INTO events (run_id, seq, t_rel_ms, type, stage, body) VALUES (?, ?, ?, ?, ?, ?)",
        (event.run_id, event.seq, event.t_rel_ms, event.type, event.stage, event.model_dump_json()),
    )


def _events_after(run_id: str, after_seq: int) -> list[TraceEvent]:
    rows = _rows("SELECT body FROM events WHERE run_id = ? AND seq > ? ORDER BY seq", (run_id, after_seq))
    return [TraceEvent.model_validate_json(r[0]) for r in rows]


def _last_event(run_id: str) -> tuple[int, float]:
    rows = _rows("SELECT seq, t_rel_ms FROM events WHERE run_id = ? ORDER BY seq DESC LIMIT 1", (run_id,))
    return (int(rows[0][0]), float(rows[0][1])) if rows else (0, 0.0)


def _save_stage(run_id: str, result: StageResult) -> None:
    _exec(
        "INSERT OR REPLACE INTO stage_results (run_id, stage, body, updated_at) VALUES (?, ?, ?, ?)",
        (run_id, result.stage, result.model_dump_json(), now_iso()),
    )


def _get_run(run_id: str) -> dict[str, Any] | None:
    rows = _rows("SELECT run_id, vendor_id, mode, created_at FROM runs WHERE run_id = ?", (run_id,))
    if not rows:
        return None
    return dict(zip(("run_id", "vendor_id", "mode", "created_at"), rows[0]))


def _latest_run(vendor_id: str) -> str | None:
    rows = _rows("SELECT run_id FROM runs WHERE vendor_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (vendor_id,))
    return rows[0][0] if rows else None


def _get_stages(run_id: str) -> dict[str, StageResult]:
    rows = _rows("SELECT stage, body FROM stage_results WHERE run_id = ?", (run_id,))
    return {stage: StageResult.model_validate(json.loads(body)) for stage, body in rows}


def _add_approval(run_id: str, stage: str, action: str, metrics_hash: str | None, note: str | None) -> None:
    _exec(
        "INSERT INTO approvals (run_id, stage, action, metrics_hash, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, stage, action, metrics_hash, note, now_iso()),
    )


def _add_override(run_id: str, stage: str, sku_code: str, verdict: str, note: str | None) -> None:
    _exec(
        "INSERT INTO overrides (run_id, stage, sku_code, verdict, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, stage, sku_code, verdict, note, now_iso()),
    )


def _add_mark(run_id: str, stage: str, kind: str) -> None:
    _exec("INSERT INTO marks (run_id, stage, kind, created_at) VALUES (?, ?, ?, ?)", (run_id, stage, kind, now_iso()))


def _list_table(table: str, run_id: str) -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table} WHERE run_id = ? ORDER BY id", (run_id,))]


# ---------- playbook change log (visitor "" is the real local playbook, anything else a public visitor's sandbox) ----------
# Plain sync functions, no async twins: the rules service runs its whole read, check, write step in one worker thread under a lock.


def save_change(visitor: str, change_id: str, at: str, status: str, body: dict[str, Any], *, bump: bool = False) -> None:
    """Insert or update one change. ``bump`` moves it to the top of the log (a decision was just made on it)."""
    with closing(_connect()) as conn, conn:
        if bump:
            conn.execute("DELETE FROM policy_changes WHERE id = ?", (change_id,))
        conn.execute(
            "INSERT INTO policy_changes (id, visitor, at, status, body, touched) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET status = excluded.status, body = excluded.body, touched = excluded.touched",
            (change_id, visitor, at, status, json.dumps(body), now_iso()),
        )
    persist.notify()


def get_change(visitor: str, change_id: str) -> dict[str, Any] | None:
    rows = _rows("SELECT body FROM policy_changes WHERE id = ? AND visitor = ?", (change_id, visitor))
    return json.loads(rows[0][0]) if rows else None


def list_changes(visitor: str, limit: int) -> list[dict[str, Any]]:
    """Newest first. Previews that were never applied or discarded (status "proposed") are drafts, not log entries."""
    rows = _rows("SELECT body FROM policy_changes WHERE visitor = ? AND status != 'proposed' ORDER BY seq DESC LIMIT ?", (visitor, limit))
    return [json.loads(r[0]) for r in rows]


def count_changes(visitor: str, status: str) -> int:
    return int(_rows("SELECT COUNT(*) FROM policy_changes WHERE visitor = ? AND status = ?", (visitor, status))[0][0])


def delete_change(visitor: str, change_id: str) -> None:
    _exec("DELETE FROM policy_changes WHERE id = ? AND visitor = ?", (change_id, visitor))


def trim_changes(visitor: str, keep: int, draft_cutoff: str, max_drafts: int) -> None:
    """Retention for one playbook: drafts older than ``draft_cutoff`` go and at most ``max_drafts`` newest stay; only the newest
    ``keep`` settled entries stay (pending requests are never trimmed, they are capped where they are created)."""
    with closing(_connect()) as conn, conn:
        conn.execute("DELETE FROM policy_changes WHERE visitor = ? AND status = 'proposed' AND touched < ?", (visitor, draft_cutoff))
        conn.execute(
            "DELETE FROM policy_changes WHERE visitor = ? AND status = 'proposed' AND seq NOT IN "
            "(SELECT seq FROM policy_changes WHERE visitor = ? AND status = 'proposed' ORDER BY seq DESC LIMIT ?)",
            (visitor, visitor, max_drafts),
        )
        conn.execute(
            "DELETE FROM policy_changes WHERE visitor = ? AND status NOT IN ('proposed', 'pending_approval') AND seq NOT IN "
            "(SELECT seq FROM policy_changes WHERE visitor = ? AND status NOT IN ('proposed', 'pending_approval') ORDER BY seq DESC LIMIT ?)",
            (visitor, visitor, keep),
        )
    persist.notify()


def get_anchors(visitor: str) -> dict[str, Any]:
    """Per setting, the last value set without a limit applying (by someone unlimited, or approved by one): the baseline a limited
    role's cumulative drift is measured from."""
    return {path: json.loads(v) for path, v in _rows("SELECT path, value FROM limit_anchors WHERE visitor = ?", (visitor,))}


def set_anchors(visitor: str, anchors: dict[str, Any]) -> None:
    if not anchors:
        return
    with closing(_connect()) as conn, conn:
        conn.executemany(
            "INSERT INTO limit_anchors (visitor, path, value) VALUES (?, ?, ?) ON CONFLICT(visitor, path) DO UPDATE SET value = excluded.value",
            [(visitor, p, json.dumps(v)) for p, v in anchors.items()],
        )
    persist.notify()


def get_visitor_overrides(visitor: str) -> dict[str, Any]:
    rows = _rows("SELECT overrides FROM visitor_playbooks WHERE visitor = ?", (visitor,))
    return json.loads(rows[0][0]) if rows else {}


def set_visitor_overrides(visitor: str, overrides: dict[str, Any]) -> None:
    _exec(
        "INSERT INTO visitor_playbooks (visitor, overrides, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(visitor) DO UPDATE SET overrides = excluded.overrides, updated_at = excluded.updated_at",
        (visitor, json.dumps(overrides), now_iso()),
    )


def expire_visitors(cutoff: str, max_visitors: int) -> None:
    """Forget public visitors idle since ``cutoff`` (by last activity: a saved playbook, a preview, any decision) and, past
    ``max_visitors``, the least recently active ones, with their playbook, log and limit baselines. Draft-only visitors count."""
    with closing(_connect()) as conn, conn:
        last: dict[str, str] = {}
        for v, t in conn.execute("SELECT visitor, updated_at FROM visitor_playbooks"):
            last[v] = max(last.get(v, ""), t)
        for v, t in conn.execute("SELECT visitor, MAX(touched) FROM policy_changes WHERE visitor != '' GROUP BY visitor"):
            last[v] = max(last.get(v, ""), t or "")
        keep = {v for v, _ in sorted(last.items(), key=lambda kv: kv[1], reverse=True)[:max_visitors]}
        for v, t in last.items():
            if t < cutoff or v not in keep:
                for table in ("visitor_playbooks", "policy_changes", "limit_anchors"):
                    conn.execute(f"DELETE FROM {table} WHERE visitor = ?", (v,))
    persist.notify()


# ---------- async API ----------


async def init() -> None:
    await asyncio.to_thread(_init)


async def reset() -> None:
    """Idempotent: creates the tables if needed and empties them."""
    await asyncio.to_thread(_reset)


async def create_run(run_id: str, vendor_id: str, mode: str) -> str:
    return await asyncio.to_thread(_create_run, run_id, vendor_id, mode)


async def append_event(event: TraceEvent) -> None:
    await asyncio.to_thread(_append_event, event)


async def events_after(run_id: str, after_seq: int = 0) -> list[TraceEvent]:
    return await asyncio.to_thread(_events_after, run_id, after_seq)


async def last_event(run_id: str) -> tuple[int, float]:
    return await asyncio.to_thread(_last_event, run_id)


async def save_stage(run_id: str, result: StageResult) -> None:
    await asyncio.to_thread(_save_stage, run_id, result)


async def get_run(run_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_run, run_id)


async def latest_run(vendor_id: str) -> str | None:
    return await asyncio.to_thread(_latest_run, vendor_id)


async def get_stages(run_id: str) -> dict[str, StageResult]:
    return await asyncio.to_thread(_get_stages, run_id)


async def add_approval(run_id: str, stage: str, action: str, metrics_hash: str | None = None, note: str | None = None) -> None:
    await asyncio.to_thread(_add_approval, run_id, stage, action, metrics_hash, note)


async def add_override(run_id: str, stage: str, sku_code: str, verdict: str, note: str | None = None) -> None:
    await asyncio.to_thread(_add_override, run_id, stage, sku_code, verdict, note)


async def list_approvals(run_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_table, "approvals", run_id)


async def list_overrides(run_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_table, "overrides", run_id)


async def add_mark(run_id: str, stage: str, kind: str) -> None:
    """A timestamped note for the impact meter: kind is review_started or replan."""
    await asyncio.to_thread(_add_mark, run_id, stage, kind)


async def list_marks(run_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_table, "marks", run_id)
