"""Impact meter: measured review time, edits, baselines from the playbook, and the team arithmetic."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import impact, policy, replay, store
from app.main import app

T0 = datetime(2026, 10, 27, 9, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self, monkeypatch):
        self.now = T0
        monkeypatch.setattr(store, "now_iso", lambda: self.now.isoformat(timespec="milliseconds"))

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def start(client, vendor_id):
    run_id = client.post(f"/api/vendors/{vendor_id}/runs").json()["run_id"]
    with client.stream("GET", f"/api/runs/{run_id}/events") as res:
        for _ in res.iter_lines():
            pass
    return run_id


def research_hash(client, run_id):
    return client.get(f"/api/runs/{run_id}").json()["stages"]["research"]["narrative_hash"]


def at(seconds):
    return (T0 + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


RUN = {"run_id": "run_x", "vendor_id": "V001", "mode": "mock"}


# ---------- baselines ----------


def test_baseline_scales_per_sku_tasks_and_sums_the_playbook_minutes():
    rows = {t["task"]: t for t in impact.tasks(7)}
    assert rows["catalog_listing_per_sku"]["total_minutes"] == 7 * 20 and rows["catalog_listing_per_sku"]["per_sku"] is True
    assert rows["jbp_draft"]["total_minutes"] == 120 and rows["jbp_draft"]["per_sku"] is False
    assert impact.baseline_minutes(7) == 855  # 30+120+90 + 90+60+140+70 + 60+120+30+45
    assert impact.baseline_minutes(0) == 855 - 7 * 30


def test_every_task_sits_behind_exactly_one_gate_and_gates_cover_all_baselines():
    assert set(impact.TASK_GATE.values()) == set(impact.GATES)
    names = set(type(policy.get().impact.baseline_minutes).model_fields)
    assert names == set(impact.TASK_GATE)


def test_changing_the_playbook_changes_the_baseline():
    policy.save_overrides({"impact": {"baseline_minutes": {"jbp_draft": 240}}})
    try:
        assert impact.baseline_minutes(7) == 855 + 120
    finally:
        policy.reset()


def test_baselines_are_placeholders_until_the_playbook_says_otherwise():
    assert policy.get().impact.baseline_status == "placeholder"
    hints = policy.schema_hints()
    assert "placeholder" in hints["impact.baseline_minutes"]["help"].lower()
    assert hints["impact.baseline_minutes.screening"]["unit"] == "min"
    assert hints["verifier.max_self_corrections"]["max"] == 5
    block = impact.for_run(RUN, [], [], [], 7)
    assert block["baseline_status"] == "placeholder"


# ---------- per run ----------


def test_nothing_measured_until_a_person_approves():
    block = impact.for_run(RUN, [], [{"stage": "research", "kind": "review_started", "created_at": at(0)}], [], 7)
    assert block["basis"] == "baseline_estimate" and block["measured_gates"] == 0 and block["reduction_pct"] is None
    assert block["complete"] is False and block["human_minutes"] == 0
    assert [g["status"] for g in block["gates"]] == ["pending"] * 3


def test_review_time_runs_from_review_started_to_approve_and_the_reduction_is_on_measured_gates_only():
    marks = [{"stage": "research", "kind": "review_started", "created_at": at(0)}]
    approvals = [{"stage": "research", "action": "approve", "created_at": at(600)}]
    block = impact.for_run(RUN, approvals, marks, [], 7)
    gate = block["gates"][0]
    assert gate["review_seconds"] == 600 and gate["counted_minutes"] == 10 and gate["baseline_minutes"] == 240
    assert block["measured_gates"] == 1 and block["basis"] == "measured" and block["complete"] is False
    assert block["baseline_measured_minutes"] == 240 and block["human_minutes"] == 10
    assert block["reduction_pct"] == 95.8  # 1 - 10/240
    assert block["baseline_minutes"] == 855


def test_a_long_gap_is_capped_and_says_so():
    marks = [{"stage": "research", "kind": "review_started", "created_at": at(0)}]
    approvals = [{"stage": "research", "action": "approve", "created_at": at(5 * 3600)}]
    gate = impact.for_run(RUN, approvals, marks, [], 7)["gates"][0]
    assert gate["capped"] is True and gate["counted_minutes"] == 120 and gate["review_seconds"] == 5 * 3600


def test_edits_are_overrides_plus_replans():
    marks = [{"stage": "research", "kind": "replan", "created_at": at(5)}, {"stage": "research", "kind": "replan", "created_at": at(6)}]
    overrides = [{"stage": "research", "sku_code": "HP-D03"}, {"stage": "research", "sku_code": "HP-D04"}]
    block = impact.for_run(RUN, [], marks, overrides, 7)
    assert (block["overrides"], block["replans"], block["edits"]) == (2, 2, 4)


def test_complete_run_sums_every_gate():
    marks = [{"stage": g, "kind": "review_started", "created_at": at(0)} for g in impact.GATES]
    approvals = [{"stage": g, "action": "approve", "created_at": at(300)} for g in impact.GATES]
    block = impact.for_run(RUN, approvals, marks, [], 7)
    assert block["complete"] is True and block["human_minutes"] == 15 and block["baseline_minutes"] == 855
    assert block["reduction_pct"] == round(100 * (1 - 15 / 855), 1)


# ---------- team rollup ----------


def test_rollup_without_measurements_uses_the_assumed_share_and_says_so():
    out = impact.rollup([], {"V001": 600, "V002": 600})
    assert out["basis"] == "baseline_estimate" and out["measured_runs"] == 0 and out["baseline_status"] == "placeholder"
    assert out["human_share_pct"] == 10.0 and out["baseline_hours_per_vendor"] == 10.0
    assert out["demand_hours_per_month"] == 80.0  # 8 vendors x 10 h
    assert out["hours_saved_per_month"] == 72.0  # x (1 - 10%)
    assert out["workload_hours_per_month"] == 1039.2  # 6 managers x 40 h x 4.33 weeks
    assert out["pct_of_workload"] == 6.9 and out["pct_of_task_time"] == 90.0
    assert out["task_capacity_hours_per_month"] == 467.6 and out["demand_vs_capacity_pct"] == 17.1
    assert out["target_pct"] == 33.3 and out["meets_target"] is False
    assert "vendors per month" in out["formula"]


def test_rollup_uses_measured_runs_when_there_are_complete_ones():
    marks = [{"stage": g, "kind": "review_started", "created_at": at(0)} for g in impact.GATES]
    approvals = [{"stage": g, "action": "approve", "created_at": at(2400)} for g in impact.GATES]  # 40 min a gate
    block = impact.for_run(RUN, approvals, marks, [], 7)
    partial = impact.for_run({**RUN, "run_id": "run_y", "vendor_id": "V002"}, approvals[:1], marks[:1], [], 7)
    out = impact.rollup([block, partial], {"V001": 855, "V002": 855})
    assert out["basis"] == "measured" and out["measured_runs"] == 1 and out["partly_measured_runs"] == 1
    assert out["human_share_pct"] == round(100 * 120 / 855, 2)
    assert out["hours_saved_per_month"] == round(8 * 14.25 * (1 - 120 / 855), 1)


def test_rollup_can_meet_the_target_with_other_team_numbers():
    policy.save_overrides({"impact": {"team": {"vendors_onboarded_per_month": 30, "category_managers": 3}}})
    try:
        out = impact.rollup([], {"V001": 855})
    finally:
        policy.reset()
    assert out["demand_hours_per_month"] == 30 * 14.25 and out["workload_hours_per_month"] == round(3 * 40 * 4.33, 1)
    assert out["meets_target"] is True and out["demand_vs_capacity_pct"] > 100


# ---------- through the API ----------


def test_run_view_carries_the_impact_block_and_the_clock_starts_at_review(client, clock):
    run_id = start(client, "V001")
    clock.advance(600)
    view = client.get(f"/api/runs/{run_id}").json()
    assert view["impact"]["measured_gates"] == 0 and view["impact"]["basis"] == "baseline_estimate"
    ok = client.post(f"/api/runs/{run_id}/stages/research/approve", json={"metrics_hash": research_hash(client, run_id)})
    assert ok.status_code == 200
    gate = client.get(f"/api/runs/{run_id}").json()["impact"]["gates"][0]
    assert gate["status"] == "measured" and gate["review_seconds"] == 600 and gate["counted_minutes"] == 10


def test_overrides_and_replans_during_review_count_as_edits(client, clock):
    run_id = start(client, "V001")
    clock.advance(30)
    assert client.post(f"/api/runs/{run_id}/stages/research/override", json={"sku_code": "HP-D03", "verdict": "list"}).status_code == 200
    res = client.post("/api/vendors/V001/decide/replan", json={"run_id": run_id, "target_margin_pct_offset": 2, "moq": 150})
    assert res.status_code == 200
    block = client.get(f"/api/runs/{run_id}").json()["impact"]
    assert (block["overrides"], block["replans"], block["edits"]) == (1, 1, 2)


def test_a_replan_does_not_restart_the_review_clock(client, clock):
    run_id = start(client, "V001")
    clock.advance(100)
    res = client.post("/api/vendors/V001/decide/replan", json={"run_id": run_id, "target_margin_pct_offset": 2, "moq": 150})
    new_hash = res.json()["narrative_hash"]
    clock.advance(200)
    assert client.post(f"/api/runs/{run_id}/stages/research/approve", json={"metrics_hash": new_hash}).status_code == 200
    assert client.get(f"/api/runs/{run_id}").json()["impact"]["gates"][0]["review_seconds"] == 300


def test_team_endpoint_before_any_run_is_a_baseline_estimate(client):
    out = client.get("/api/impact").json()
    assert out["basis"] == "baseline_estimate" and out["measured_runs"] == 0 and out["vendors"] == []
    assert out["baseline_status"] == "placeholder" and out["mode"] == "mock"
    assert out["baseline_hours_per_vendor"] > 0 and out["pct_of_workload"] is not None


def test_team_endpoint_lists_runs_with_measurements(client, clock):
    run_id = start(client, "V001")
    clock.advance(120)
    client.post(f"/api/runs/{run_id}/stages/research/approve", json={"metrics_hash": research_hash(client, run_id)})
    out = client.get("/api/impact").json()
    assert [v["vendor_id"] for v in out["vendors"]] == ["V001"] and out["vendors"][0]["measured_gates"] == 1
    assert out["basis"] == "baseline_estimate" and out["partly_measured_runs"] == 1  # one gate is not a finished run


def test_replay_sessions_record_the_same_marks():
    store_ = replay.ReplayStore()

    async def go():
        await store_.create_run("run_r", "V001", "replay")
        await store_.add_mark("run_r", "research", "review_started")
        return await store_.list_marks("run_r")

    marks = asyncio.run(go())
    assert marks[0]["kind"] == "review_started" and marks[0]["stage"] == "research"
