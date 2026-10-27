import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import runner, store
from app.agents import screen
from app.config import settings
from app.main import app
from app.metrics import apply_levers, build_base
from app.schemas import StageResult

STAGE_IDS = ["intake", "research", "shortlist", "negotiate", "catalog", "marketing", "jbp", "po"]


@pytest.fixture
def client():
    with TestClient(app) as c:  # one event loop for the whole test, so background run tasks keep running
        yield c


def parse_sse(lines):
    events, cur = [], {}
    for line in lines:
        if line == "":
            if cur:
                events.append(cur)
            cur = {}
        elif line.startswith(":"):
            events.append({"comment": line})
        else:
            key, _, value = line.partition(": ")
            cur[key] = value
    return events


def stream(client, run_id, **headers):
    with client.stream("GET", f"/api/runs/{run_id}/events", headers=headers) as res:
        assert res.status_code == 200
        return res, parse_sse(res.iter_lines())


def trace_events(raw):
    return [json.loads(e["data"]) for e in raw if "data" in e]


def start(client, vendor_id):
    res = client.post(f"/api/vendors/{vendor_id}/runs")
    assert res.status_code == 202
    run_id = res.json()["run_id"]
    _, raw = stream(client, run_id)  # consuming the stream waits for the run to finish
    return run_id, trace_events(raw)


# ---------- start, read, latest ----------


def test_post_run_returns_202_and_open_in_mock_mode(client):
    res = client.post("/api/vendors/V001/runs")
    assert res.status_code == 202 and set(res.json()) == {"run_id"}
    assert client.post("/api/vendors/V999/runs").status_code == 404


def test_latest_run(client):
    assert client.get("/api/vendors/V001/runs/latest").json() == {"run_id": None}
    first, _ = start(client, "V001")
    second, _ = start(client, "V001")
    assert first != second
    assert client.get("/api/vendors/V001/runs/latest").json() == {"run_id": second}
    assert client.get("/api/vendors/V002/runs/latest").json() == {"run_id": None}


def test_get_run_has_all_eight_stages(client):
    run_id, _ = start(client, "V001")
    body = client.get(f"/api/runs/{run_id}").json()
    assert set(body) == {"run_id", "vendor_id", "mode", "created_at", "stages", "impact", "provenance"}
    assert body["run_id"] == run_id and body["vendor_id"] == "V001" and body["mode"] == "mock"
    assert list(body["stages"]) == STAGE_IDS
    stages = body["stages"]
    assert stages["intake"]["status"] == "done"
    research = stages["research"]
    assert research["status"] == "review" and research["needs_approval"] is True
    assert research["metrics_hash"] == research["narrative_hash"] == apply_levers(build_base("V001")).metrics_hash
    assert research["claims"] and research["data"]["headline"]
    assert stages["shortlist"]["status"] == "review" and stages["shortlist"]["data"]["verdict_table"]
    for sid in STAGE_IDS[3:]:
        assert stages[sid]["status"] == "pending" and stages[sid]["locked_reason"] is None
    assert client.get("/api/runs/run_nope").status_code == 404


@pytest.mark.parametrize("vendor_id", ["V001", "V002", "V003"])
def test_clean_vendors_reach_review(client, vendor_id):
    run_id, _ = start(client, vendor_id)
    stages = client.get(f"/api/runs/{run_id}").json()["stages"]
    assert stages["intake"]["status"] == "done" and stages["research"]["status"] == "review"


def test_v004_fails_screening_and_locks_every_later_stage(client):
    run_id, events = start(client, "V004")
    stages = client.get(f"/api/runs/{run_id}").json()["stages"]
    assert stages["intake"]["status"] == "failed"
    assert stages["intake"]["data"]["injection_detected"] is True and stages["intake"]["data"]["decision"] == "fail"
    assert stages["intake"]["locked_reason"]
    for sid in STAGE_IDS[1:]:
        assert stages[sid]["status"] == "locked", sid
        assert stages[sid]["locked_reason"].startswith("Screening failed")
    assert not any(e["stage"] == "research" and e["type"] == "stage_started" for e in events)
    assert events[-1]["type"] == "done"
    # a locked stage cannot be approved or re-planned
    assert client.post(f"/api/runs/{run_id}/stages/research/approve", json={"metrics_hash": "x"}).status_code == 409
    res = client.post("/api/vendors/V004/decide/replan", json={"run_id": run_id, "target_margin_pct_offset": 0, "moq": 100})
    assert res.status_code == 409 and res.json()["code"] == "stage_locked"


# ---------- SSE ----------


def test_sse_events_have_increasing_ids_and_end_with_done(client):
    run_id, _ = start(client, "V001")
    res, raw = stream(client, run_id)
    assert res.headers["content-type"].startswith("text/event-stream")
    assert res.headers["cache-control"] == "no-cache" and res.headers["x-accel-buffering"] == "no"
    data = [e for e in raw if "data" in e]
    ids = [int(e["id"]) for e in data]
    assert ids == list(range(1, len(ids) + 1)), "ids are the monotonic seq"
    assert all(e["event"] == "trace" for e in data)
    events = trace_events(raw)
    assert [e["seq"] for e in events] == ids and events[-1]["type"] == "done"
    assert all(e["run_id"] == run_id for e in events)
    t = [e["t_rel_ms"] for e in events]
    assert t == sorted(t)
    types = [e["type"] for e in events]
    assert types[0] == "stage_started" and {"tool_call", "model_call", "claim_checked", "stage_result"} <= set(types)
    assert set(events[0]) == {"seq", "run_id", "t_rel_ms", "type", "stage", "model", "latency_ms", "cost_usd", "payload"}
    model_call = next(e for e in events if e["type"] == "model_call")
    assert model_call["model"] and model_call["latency_ms"] is not None and model_call["cost_usd"] == 0
    tool = next(e for e in events if e["type"] == "tool_call" and e["payload"].get("tool") == "get_sku_rows")
    assert tool["payload"]["result_summary"] and tool["payload"]["args"] == {"vendor_id": "V001"}
    stage_results = {e["stage"]: e["payload"] for e in events if e["type"] == "stage_result"}
    assert stage_results["research"]["status"] == "review"


def test_sse_last_event_id_resumes_with_only_later_events(client):
    run_id, events = start(client, "V001")
    cut = events[len(events) // 2]["seq"]
    _, raw = stream(client, run_id, **{"Last-Event-ID": str(cut)})
    resumed = trace_events(raw)
    assert [e["seq"] for e in resumed] == [e["seq"] for e in events if e["seq"] > cut]
    assert resumed[-1]["type"] == "done"
    # a bad header is ignored; resuming from the final id yields nothing new but terminates
    _, raw = stream(client, run_id, **{"Last-Event-ID": "banana"})
    assert len(trace_events(raw)) == len(events)
    _, raw = stream(client, run_id, **{"Last-Event-ID": str(events[-1]["seq"])})
    assert trace_events(raw) == [] or trace_events(raw)[-1]["type"] == "done"


def test_sse_unknown_run_is_404(client):
    assert client.get("/api/runs/run_nope/events").status_code == 404


def test_sse_heartbeat_while_a_stage_is_slow(client, monkeypatch):
    monkeypatch.setattr(settings, "sse_heartbeat_s", 0.05)

    async def slow(ctx):
        await asyncio.sleep(0.4)
        return StageResult(stage="intake", status="done", summary="slow but fine")

    monkeypatch.setattr(screen, "run", slow)
    run_id = client.post("/api/vendors/V001/runs").json()["run_id"]
    _, raw = stream(client, run_id)
    pings = [e for e in raw if e.get("comment") == ": ping"]
    assert len(pings) >= 2
    events = trace_events(raw)
    assert events[-1]["type"] == "done" and [e["seq"] for e in events] == sorted(e["seq"] for e in events)


def test_a_crashing_stage_ends_the_stream_cleanly(client, monkeypatch):
    async def boom(ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(screen, "run", boom)
    run_id = client.post("/api/vendors/V001/runs").json()["run_id"]
    _, raw = stream(client, run_id)
    events = trace_events(raw)
    assert any(e["type"] == "error" and e["stage"] == "intake" for e in events) and events[-1]["type"] == "done"
    assert client.get(f"/api/runs/{run_id}").json()["stages"]["intake"]["status"] == "failed"


# ---------- approve / override / replan / reject ----------


def research(client, run_id):
    return client.get(f"/api/runs/{run_id}").json()["stages"]["research"]


def test_approve_is_409_on_stale_hash_and_200_on_match(client):
    run_id, _ = start(client, "V001")
    narrative = research(client, run_id)["narrative_hash"]
    url = f"/api/runs/{run_id}/stages/research/approve"
    stale = client.post(url, json={"metrics_hash": "0" * 64})
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "stale_approval" and {"problem", "cause", "fix"} <= set(body) and "Re-plan" in body["fix"]
    assert research(client, run_id)["status"] == "review"
    # hash from moved levers (what the UI holds after the user drags a slider) is stale too
    moved = client.get("/api/vendors/V001/decide/metrics?target_margin_pct_offset=5&moq=300").json()["metrics_hash"]
    assert client.post(url, json={"metrics_hash": moved}).status_code == 409
    ok = client.post(url, json={"metrics_hash": narrative})
    assert ok.status_code == 200 and ok.json()["status"] == "done" and ok.json()["needs_approval"] is False
    assert research(client, run_id)["status"] == "done"
    approvals = asyncio.run(store.list_approvals(run_id))
    assert [a["action"] for a in approvals] == ["approve"]


def test_hash_is_the_same_whether_or_not_the_lever_params_are_sent(client):
    default = client.get("/api/vendors/V001/decide/metrics").json()["metrics_hash"]
    explicit = client.get("/api/vendors/V001/decide/metrics?target_margin_pct_offset=0").json()["metrics_hash"]
    run_id, _ = start(client, "V001")
    assert default == explicit == research(client, run_id)["narrative_hash"]


def test_approve_validation(client):
    run_id, _ = start(client, "V001")
    assert client.post(f"/api/runs/{run_id}/stages/nonsense/approve", json={"metrics_hash": "x"}).status_code == 404
    assert client.post(f"/api/runs/{run_id}/stages/research/approve", json={}).status_code == 422
    assert client.post("/api/runs/run_nope/stages/research/approve", json={"metrics_hash": "x"}).status_code == 404
    assert client.post(f"/api/runs/{run_id}/stages/catalog/approve", json={"metrics_hash": "x"}).status_code == 409


def test_replan_changes_narrative_hash_and_approval_follows(client):
    run_id, events_before = start(client, "V002")
    before = research(client, run_id)
    res = client.post("/api/vendors/V002/decide/replan", json={"run_id": run_id, "target_margin_pct_offset": -10, "moq": 500})
    assert res.status_code == 200
    body = res.json()
    new_hash = apply_levers(build_base("V002"), -10, 500).metrics_hash
    assert body["narrative_hash"] == body["metrics_hash"] == new_hash != before["narrative_hash"]
    assert body["data"]["replanned"] is True and body["data"]["lever"] == {"target_margin_pct_offset": -10.0, "moq": 500}
    assert body["status"] == "review" and body["needs_approval"] is True
    assert research(client, run_id)["narrative_hash"] == new_hash
    # the old hash is now stale, the new one approves
    url = f"/api/runs/{run_id}/stages/research/approve"
    assert client.post(url, json={"metrics_hash": before["narrative_hash"]}).status_code == 409
    assert client.post(url, json={"metrics_hash": new_hash}).status_code == 200
    # replan events were appended to the same run's event log, after the original done
    _, raw = stream(client, run_id, **{"Last-Event-ID": str(events_before[-1]["seq"])})
    later = trace_events(raw)
    assert later and later[0]["seq"] > events_before[-1]["seq"] and later[-1]["type"] == "done"


def test_replan_validation(client):
    run_id, _ = start(client, "V001")
    ok = {"run_id": run_id, "target_margin_pct_offset": 0, "moq": 100}
    assert client.post("/api/vendors/V001/decide/replan", json={**ok, "target_margin_pct_offset": 99}).status_code == 422
    assert client.post("/api/vendors/V001/decide/replan", json={**ok, "run_id": "run_nope"}).status_code == 404
    assert client.post("/api/vendors/V002/decide/replan", json=ok).status_code == 404  # run belongs to V001
    assert client.post("/api/vendors/V999/decide/replan", json=ok).status_code == 404


def test_override_tags_sku_edited_by_human(client):
    run_id, _ = start(client, "V001")
    url = f"/api/runs/{run_id}/stages/research/override"
    res = client.post(url, json={"sku_code": "HP-D03", "verdict": "list", "note": "Strategic flavour for the launch"})
    assert res.status_code == 200
    row = next(r for r in res.json()["data"]["rationale_per_sku"] if r["code"] == "HP-D03")
    assert row["verdict"] == "list" and row["edited_by_human"] is True and row["original_verdict"] == "reject"
    assert row["note"] == "Strategic flavour for the launch"
    untouched = next(r for r in res.json()["data"]["rationale_per_sku"] if r["code"] == "HP-D01")
    assert "edited_by_human" not in untouched
    assert research(client, run_id)["data"]["overrides"]["HP-D03"]["edited_by_human"] is True
    assert research(client, run_id)["narrative_hash"] == res.json()["narrative_hash"]  # override does not stale the narrative
    assert [o["sku_code"] for o in asyncio.run(store.list_overrides(run_id))] == ["HP-D03"]
    assert client.post(url, json={"sku_code": "NOPE", "verdict": "list"}).status_code == 404
    assert client.post(url, json={"sku_code": "HP-D03", "verdict": "maybe"}).status_code == 422


def test_reject_vendor(client):
    run_id, _ = start(client, "V003")
    res = client.post("/api/vendors/V003/reject", json={"run_id": run_id, "reason": "Margins too thin"})
    assert res.status_code == 200 and res.json()["reason"] == "Margins too thin"
    stages = client.get(f"/api/runs/{run_id}").json()["stages"]
    assert stages["research"]["status"] == "failed" and stages["shortlist"]["status"] == "locked"
    assert "Margins too thin" in stages["po"]["locked_reason"]
    assert client.post("/api/vendors/V001/reject", json={"run_id": run_id, "reason": "x"}).status_code == 404


# ---------- reset, keys ----------


def test_admin_reset_clears_the_store(client, monkeypatch):
    run_id, _ = start(client, "V001")
    assert client.post("/api/admin/reset").status_code == 403  # always needs the demo key
    monkeypatch.setattr(settings, "demo_key", "s3cret")
    assert client.post("/api/admin/reset", headers={"X-Demo-Key": "wrong"}).status_code == 403
    assert client.post("/api/admin/reset", headers={"X-Demo-Key": "s3cret"}).json() == {"ok": True}
    assert client.post("/api/admin/reset", headers={"X-Demo-Key": "s3cret"}).status_code == 200  # idempotent
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert client.get("/api/vendors/V001/runs/latest").json() == {"run_id": None}
    again, _ = start(client, "V001")  # and the store works afterwards
    assert client.get(f"/api/runs/{again}").status_code == 200


def test_store_reset_is_idempotent_on_a_fresh_db():
    asyncio.run(store.reset())
    asyncio.run(store.reset())
    assert asyncio.run(store.latest_run("V001")) is None


def test_demo_key_required_only_when_a_stage_is_live(client, monkeypatch):
    called = []

    async def fake_create(vendor_id):
        called.append(vendor_id)
        return "run_fake"

    monkeypatch.setattr(runner, "create_run", fake_create)
    # mock / replay: open
    for mode in ("mock", "replay"):
        monkeypatch.setattr(settings, "model_mode", mode)
        assert client.post("/api/vendors/V001/runs").status_code == 202
    # live (with a key configured): the demo key is required
    monkeypatch.setattr(settings, "model_mode", "live")
    monkeypatch.setattr(settings, "model_api_key", "test-not-a-real-key")
    monkeypatch.setattr(settings, "demo_key", "s3cret")
    denied = client.post("/api/vendors/V001/runs")
    assert denied.status_code == 403 and denied.json()["code"] == "demo_key_required"
    assert client.post("/api/vendors/V001/runs", headers={"X-Demo-Key": "wrong"}).status_code == 403
    assert client.post("/api/vendors/V001/runs", headers={"X-Demo-Key": "s3cret"}).status_code == 202
    body = {"run_id": "run_fake", "target_margin_pct_offset": 0, "moq": 100}
    assert client.post("/api/vendors/V001/decide/replan", json=body).status_code == 403
    # any single live stage is enough to need the key
    monkeypatch.setattr(settings, "live_stages", "research")
    assert client.post("/api/vendors/V001/runs").status_code == 403
    # live_stages naming no pipeline stage means nothing runs live: open
    monkeypatch.setattr(settings, "live_stages", "no_such_stage")
    assert client.post("/api/vendors/V001/runs").status_code == 202
    assert called == ["V001"] * 4
    # live configured but no API key: effective mode degrades to mock, so open
    monkeypatch.setattr(settings, "live_stages", "")
    monkeypatch.setattr(settings, "model_api_key", None)
    assert client.post("/api/vendors/V001/runs").status_code == 202
