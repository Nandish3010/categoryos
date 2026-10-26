"""Replay mode: golden runs served as ephemeral in-memory sessions; fixture validation; the record command."""

import asyncio
import hashlib
import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import persist, record, replay, runner, store
from app.config import settings
from app.constants import ALLOWED_VENDORS
from app.main import app
from app.metrics import apply_levers, build_base
from app.schemas import StageResult

SETTLED = {"done", "review", "failed", "locked"}


@pytest.fixture(autouse=True)
def replay_mode(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "replay")

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(replay, "sleep", no_sleep)
    runner.reset_state()  # also forgets the loaded golden registry


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def stages_of(client, run_id):
    return client.get(f"/api/runs/{run_id}").json()["stages"]


def wait_for(client, run_id, wanted, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        stages = stages_of(client, run_id)
        if all(stages[s]["status"] in SETTLED for s in wanted):
            return stages
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {wanted}")


def wait_done(run_id, count, timeout=15.0):
    """Wait until the session has emitted `count` done events."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sum(e.type == "done" for e in replay.session_store.events[run_id]) >= count:
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for done #{count}")


def sse_events(client, run_id, last_id=None):
    headers = {"Last-Event-ID": str(last_id)} if last_id else {}
    events = []
    with client.stream("GET", f"/api/runs/{run_id}/events", headers=headers) as res:
        for line in res.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if events[-1]["type"] == "done":
                    break
    return events


def start(client, vendor_id):
    run_id = client.post(f"/api/vendors/{vendor_id}/runs").json()["run_id"]
    return run_id, wait_for(client, run_id, ["intake", "research"])


def approve(client, run_id, stage, stages):
    res = client.post(f"/api/runs/{run_id}/stages/{stage}/approve", json={"metrics_hash": stages[stage]["narrative_hash"]})
    assert res.status_code == 200, res.text
    return res.json()


def test_session_emits_golden_events_in_order_and_ends_done(client):
    golden = replay.load_golden("V001")
    run_id, _ = start(client, "V001")
    events = sse_events(client, run_id)
    expected = golden.phase_events("start")
    assert [e["type"] for e in events[:-1]] == [e.type for e in expected]
    assert [e["stage"] for e in events[:-1]] == [e.stage for e in expected]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert all(e["run_id"] == run_id for e in events)
    assert events[-1]["type"] == "done"
    assert all(e["payload"]["mode"] == "replay" for e in events if e["type"] == "model_call")
    # a reconnect resumes after Last-Event-ID
    tail = sse_events(client, run_id, last_id=events[-3]["seq"])
    assert [e["seq"] for e in tail] == [events[-2]["seq"], events[-1]["seq"]]
    assert client.get(f"/api/runs/{run_id}").json()["mode"] == "replay"
    assert client.get("/api/vendors/V001/runs/latest").json() == {"run_id": run_id}


def test_screen_failure_replays_locked_downstream(client):
    run_id, _ = start(client, "V004")
    stages = wait_for(client, run_id, ["intake", "po"])
    assert stages["intake"]["status"] == "failed" and stages["po"]["status"] == "locked"
    assert sse_events(client, run_id)[-1]["type"] == "done"


def test_full_session_never_touches_the_database(client, tmp_path):
    db = tmp_path / "must-not-exist.db"
    settings.db_path = db
    run_id, stages = start(client, "V001")
    assert stages["research"]["status"] == "review"
    approve(client, run_id, "research", stages)
    stages = wait_for(client, run_id, ["negotiate", "catalog"])
    assert stages["shortlist"]["status"] == "done"
    approve(client, run_id, "catalog", stages)
    wait_done(run_id, 3)
    stages = wait_for(client, run_id, ["marketing", "jbp", "po"])
    approve(client, run_id, "po", stages)
    final = stages_of(client, run_id)
    assert all(final[s]["status"] == "done" for s in ("intake", "research", "negotiate", "catalog", "po"))
    done = [e for e in replay.session_store.events[run_id] if e.type == "done"]
    assert [e.payload.get("phase") for e in done] == [None, "execute", "launch"]
    assert [a["action"] for a in replay.session_store.approvals[run_id]] == ["approve"] * 3
    assert client.get("/api/runs/run_unknown").status_code == 404
    assert not db.exists()


def test_override_and_reject_act_on_the_session_only(client, tmp_path):
    settings.db_path = tmp_path / "must-not-exist.db"
    run_id, stages = start(client, "V001")
    sku = stages["research"]["data"]["rationale_per_sku"][0]["code"]
    res = client.post(f"/api/runs/{run_id}/stages/research/override", json={"sku_code": sku, "verdict": "reject", "note": "n"})
    assert res.status_code == 200 and res.json()["data"]["overrides"][sku]["edited_by_human"] is True
    res = client.post("/api/vendors/V001/reject", json={"run_id": run_id, "reason": "terms"})
    assert res.json()["status"] == "rejected"
    stages = stages_of(client, run_id)
    assert stages["research"]["status"] == "failed" and stages["negotiate"]["status"] == "locked"
    assert not settings.db_path.exists()


@pytest.mark.parametrize("offset", [0, 2, 4])
def test_replan_presets_return_cached_narratives(client, offset):
    run_id, _ = start(client, "V001")
    moq = replay.default_moq("V001")
    res = client.post("/api/vendors/V001/decide/replan", json={"run_id": run_id, "target_margin_pct_offset": offset, "moq": moq})
    assert res.status_code == 200, res.text
    body = res.json()
    expected = apply_levers(build_base("V001"), offset, moq).metrics_hash
    assert body["data"]["replanned"] is True
    assert body["narrative_hash"] == body["metrics_hash"] == expected
    assert stages_of(client, run_id)["research"]["narrative_hash"] == expected
    assert sse_events(client, run_id)[-1]["type"] == "done"
    approve(client, run_id, "research", stages_of(client, run_id))  # the replanned narrative is what gets approved


@pytest.mark.parametrize("offset,moq_delta", [(3, 0), (2.5, 0), (0, 1), (-5, 0)])
def test_replan_non_preset_is_a_typed_error(client, offset, moq_delta):
    run_id, _ = start(client, "V001")
    moq = replay.default_moq("V001") + moq_delta
    res = client.post("/api/vendors/V001/decide/replan", json={"run_id": run_id, "target_margin_pct_offset": offset, "moq": moq})
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "narrative_unavailable"
    assert body["problem"] == "Narrative available in live mode"
    assert body["fix"] == "Use a preset (0, +2, +4) or run live"
    assert stages_of(client, run_id)["research"]["status"] == "review"  # untouched


def test_lever_metrics_stay_live_in_replay(client):
    res = client.get("/api/vendors/V001/decide/metrics", params={"target_margin_pct_offset": 3, "moq": 123})
    assert res.status_code == 200
    assert res.json()["metrics_hash"] == apply_levers(build_base("V001"), 3, 123).metrics_hash


def test_mode_reports_replay_health(client):
    body = client.get("/api/mode").json()
    assert body["mode"] == "replay" and body["degraded"] is False
    assert set(body["replay"]["vendors"].values()) == {"ok"}


# ---------- fixture validation ----------


@pytest.fixture
def broken_fixtures(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    shutil.copytree(settings.fixtures_dir, fixtures, ignore=shutil.ignore_patterns("assets"))
    monkeypatch.setattr(settings, "fixtures_dir", fixtures)
    monkeypatch.setattr(settings, "db_path", tmp_path / "degraded.db")
    runner.reset_state()
    return fixtures / "golden" / "runs"


def test_checksum_mismatch_serves_mock_degraded(broken_fixtures):
    path = broken_fixtures / "V001.json"
    path.write_text(path.read_text().replace('"source": "mock"', '"source":  "mock"'))
    with TestClient(app) as client:
        mode = client.get("/api/mode").json()
        assert mode["degraded"] is True
        assert "checksum mismatch" in mode["replay"]["vendors"]["V001"]
        assert mode["replay"]["vendors"]["V002"] == "ok"
        run_id = client.post("/api/vendors/V001/runs").json()["run_id"]
        stages = wait_for(client, run_id, ["intake", "research"])
        assert stages["research"]["status"] == "review"  # served by the mock fixtures through the normal pipeline
        assert any(e["type"] == "degraded" for e in sse_events(client, run_id))
        assert not replay.has_session(run_id)
        other = client.post("/api/vendors/V002/runs").json()["run_id"]  # other vendors still replay their golden run
        assert replay.has_session(other)


def test_schema_version_mismatch_is_invalid(broken_fixtures):
    path = broken_fixtures / "V002.json"
    raw = json.loads(path.read_text())
    raw["meta"]["schema_version"] = 99
    data = (json.dumps(raw, indent=1, sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    replay.checksum_path(path).write_text(hashlib.sha256(data).hexdigest())  # checksum is fine; the version is not
    with pytest.raises(replay.GoldenInvalid, match="schema_version"):
        replay.load_golden("V002")
    assert "V002" in replay.load_all()


def test_missing_golden_file_is_degraded(broken_fixtures):
    (broken_fixtures / "V003.json").unlink()
    assert "V003" in replay.load_all()


@pytest.mark.parametrize("vendor_id", ALLOWED_VENDORS)
def test_golden_schema_parity_and_metrics_drift(vendor_id):
    """Every committed golden run validates against the current models and the current engine output."""
    golden = replay.load_golden(vendor_id)  # checksum, schema_version, parser_version, pydantic models, metrics_hash
    assert golden.meta.metrics_hash == apply_levers(build_base(vendor_id)).metrics_hash
    assert all(isinstance(r, StageResult) for r in golden.stages.values())
    assert [e.seq for e in golden.events] == list(range(1, len(golden.events) + 1))
    assert golden.events[-1].type == "done"
    moq = replay.default_moq(vendor_id)
    for key, cached in golden.replans.items():
        expected = apply_levers(build_base(vendor_id), cached.offset, moq).metrics_hash
        assert cached.metrics_hash == expected and cached.research.narrative_hash == expected, key
    if vendor_id != "V004":
        assert set(golden.replans) == {"0", "2", "4"}


# ---------- record ----------


def _without_recorded_at(path: Path) -> dict:
    raw = json.loads(path.read_text())
    raw["meta"]["recorded_at"] = ""
    return raw


def test_record_is_deterministic_and_matches_committed_goldens(tmp_path):
    stamp = "2026-10-27T00:00:00+00:00"
    for vendor_id in ("V001", "V004"):
        first = asyncio.run(record.record_vendor(vendor_id, tmp_path / "a", recorded_at=stamp))
        second = asyncio.run(record.record_vendor(vendor_id, tmp_path / "b", recorded_at=stamp))
        assert first.read_bytes() == second.read_bytes()
        assert replay.checksum_path(first).read_text() == replay.checksum_path(second).read_text()
        committed = replay.golden_dir() / f"{vendor_id}.json"
        assert _without_recorded_at(first) == _without_recorded_at(committed), (
            f"{vendor_id} golden run is stale: run `make record`"
        )


def test_rerecording_unchanged_content_keeps_the_timestamp(tmp_path):
    first = asyncio.run(record.record_vendor("V004", tmp_path, recorded_at="2026-10-27T00:00:00+00:00"))
    before = first.read_bytes()
    again = asyncio.run(record.record_vendor("V004", tmp_path))
    assert again.read_bytes() == before


def test_record_does_not_leak_settings(tmp_path):
    before = (settings.model_mode, settings.db_path, settings.demo_today)
    asyncio.run(record.record_vendor("V004", tmp_path))
    assert (settings.model_mode, settings.db_path, settings.demo_today) == before


# ---------- persistence hook ----------


def test_persist_hook_fires_on_store_writes_and_is_inert_by_default():
    calls = []
    persist.notify()  # no hook: a no-op
    persist.set_hook(lambda: calls.append(1))
    try:
        asyncio.run(store.create_run("run_x", "V001", "mock"))
        assert calls
    finally:
        persist.set_hook(None)
