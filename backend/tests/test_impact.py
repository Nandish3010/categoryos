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
    assert rows["catalog_listing_per_sku"]["total_minutes"] == 7 * 25 and rows["catalog_listing_per_sku"]["per_sku"] is True
    assert rows["marketing_jbp_draft"]["total_minutes"] == 60 and rows["marketing_jbp_draft"]["per_sku"] is False
    assert impact.baseline_minutes(7) == 785  # 45+140+30 + 60+110+30+175+70+35 + 60+30
    assert impact.baseline_minutes(0) == 785 - 7 * 60


def test_the_research_report_totals_1085_minutes_for_a_twelve_sku_vendor():
    assert impact.baseline_minutes(12) == 1085


def test_every_task_sits_behind_exactly_one_gate_and_gates_cover_all_baselines():
    assert set(impact.TASK_GATE.values()) == set(impact.GATES)
    names = set(type(policy.get().impact.baseline_minutes).model_fields)
    assert names == set(impact.TASK_GATE)


def test_changing_the_playbook_changes_the_baseline():
    policy.save_overrides({"impact": {"baseline_minutes": {"marketing_jbp_draft": 240}}})
    try:
        assert impact.baseline_minutes(7) == 785 + 180
    finally:
        policy.reset()


def test_baselines_are_labelled_research_estimates_and_cite_the_report():
    assert policy.get().impact.baseline_status == "research_estimate"
    hints = policy.schema_hints()
    for path in ("impact.baseline_minutes", "impact.baseline_minutes.screening", "impact.team", "impact.workload"):
        assert "Research estimate (not measured)" in hints[path]["help"] or "research_estimate" in hints[path]["help"] or "docs/research/category-manager-workload.md" in hints[path]["help"]
    assert "docs/research/category-manager-workload.md" in hints["impact.baseline_minutes.screening"]["help"]
    assert hints["impact.baseline_minutes.screening"]["unit"] == "min"
    assert hints["verifier.max_self_corrections"]["max"] == 5
    block = impact.for_run(RUN, [], [], [], 7)
    assert block["baseline_status"] == "research_estimate"


def test_a_coverage_row_must_name_a_registered_module_and_task():
    with pytest.raises(Exception, match="unknown module"):
        policy.save_overrides({"impact": {"coverage": [{"module": "nope", "task": "reporting_mis", "in_scope_pct": 50}]}})
    with pytest.raises(Exception, match="unknown task"):
        policy.save_overrides({"impact": {"coverage": [{"module": "weekly_review_mis", "task": "nope", "in_scope_pct": 50}]}})


# ---------- per run ----------


def test_nothing_measured_until_a_person_approves():
    block = impact.for_run(RUN, [], [{"stage": "research", "kind": "review_started", "created_at": at(0)}], [], 7)
    assert block["basis"] == "research_estimate" and block["measured_gates"] == 0 and block["reduction_pct"] is None
    assert block["complete"] is False and block["human_minutes"] == 0
    assert [g["status"] for g in block["gates"]] == ["pending"] * 3


def test_review_time_runs_from_review_started_to_approve_and_the_reduction_is_on_measured_gates_only():
    marks = [{"stage": "research", "kind": "review_started", "created_at": at(0)}]
    approvals = [{"stage": "research", "action": "approve", "created_at": at(600)}]
    block = impact.for_run(RUN, approvals, marks, [], 7)
    gate = block["gates"][0]
    assert gate["review_seconds"] == 600 and gate["counted_minutes"] == 10 and gate["baseline_minutes"] == 215
    assert block["measured_gates"] == 1 and block["basis"] == "measured" and block["complete"] is False
    assert block["baseline_measured_minutes"] == 215 and block["human_minutes"] == 10
    assert block["reduction_pct"] == 95.3  # 1 - 10/215
    assert block["baseline_minutes"] == 785


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
    assert block["complete"] is True and block["human_minutes"] == 15 and block["baseline_minutes"] == 785
    assert block["reduction_pct"] == round(100 * (1 - 15 / 785), 1)


# ---------- team rollup ----------


def module(out, key):
    return next(m for m in out["modules"] if m["key"] == key)


def test_rollup_reproduces_the_research_reports_coverage_numbers():
    out = impact.rollup([])
    assert out["basis"] == "research_estimate" and out["measured_runs"] == 0 and out["baseline_status"] == "research_estimate"
    cm, ce = out["roles"]
    assert (cm["in_scope_pct"], cm["saved_pct"]) == (17.8, 8.2)  # report: about 18% in scope, about 8% saved
    assert (ce["in_scope_pct"], ce["saved_pct"]) == (18.8, 9.1)  # about 19%, about 9%
    assert out["in_scope_pct"] == 18.5 and out["saved_pct"] == 8.8  # team: about 19% in scope, about 9% saved
    assert out["meets_target"] is False and out["target_pct"] == 33.3
    assert out["potential_saved_pct"] == 34.6  # every module built: the report's "about 34%"
    assert out["team_hours_per_month"] == round(3 * 45 * 4.33, 1) and "share of the week" in out["formula"]
    assert out["onboarding"]["baseline_hours_per_vendor"] == 18.1 and out["onboarding"]["saved_pct_basis"] == "research_estimate"
    assert out["onboarding"]["demand_hours_per_month"] == 57.9 and out["onboarding"]["human_share_pct"] is None


def test_each_module_reports_whether_it_is_shipped_and_what_it_covers():
    out = impact.rollup([])
    status = {m["key"]: m["status"] for m in out["modules"]}
    assert status["new_vendor_onboarding"] == "shipped" and status["weekly_review_mis"] == "not_built"
    assert [m["key"] for m in out["modules"] if m["status"] == "shipped"] == ["new_vendor_onboarding", "conditional_offer_evaluator", "live_negotiation_copilot"]
    assert module(out, "weekly_review_mis")["saved_pct"] == 7.6  # the report's rank 1, team pts 7.6
    assert module(out, "price_increase_evaluator")["saved_pct"] == 2.3
    tasks = {t["task"] for t in module(out, "new_vendor_onboarding")["tasks"]}
    assert {"new_vendor_onboarding", "catalog_create_qc", "compliance"} <= tasks


def test_only_shipped_modules_count_and_registering_a_module_changes_the_total():
    policy.save_overrides({"impact": {"modules": {"weekly_review_mis": {"status": "shipped"}}}})
    try:
        out = impact.rollup([])
    finally:
        policy.reset()
    assert out["saved_pct"] == round(8.8 + 7.6, 1) or abs(out["saved_pct"] - 16.4) < 0.2
    assert module(out, "weekly_review_mis")["status"] == "shipped"


def test_a_new_module_registers_with_its_own_coverage():
    policy.save_overrides({
        "impact": {
            "modules": {"price_chaser": {"label": "Price chaser", "status": "shipped"}},
            "coverage": [*[c.model_dump() for c in policy.get().impact.coverage], {"module": "price_chaser", "task": "pricing_margin", "in_scope_pct": 50}],
        }
    })
    try:
        out = impact.rollup([])
    finally:
        policy.reset()
    assert module(out, "price_chaser")["status"] == "shipped" and module(out, "price_chaser")["saved_pct"] == round((6 + 2 * 5) / 3 * 0.5 * 0.25, 1)
    assert out["saved_pct"] > 8.8


def test_overlapping_modules_on_one_task_are_capped_at_the_whole_task():
    rows = [{"module": "new_vendor_onboarding", "task": "reporting_mis", "in_scope_pct": 80}, {"module": "weekly_review_mis", "task": "reporting_mis", "in_scope_pct": 80}]
    policy.save_overrides({"impact": {"modules": {"weekly_review_mis": {"status": "shipped"}}, "coverage": rows}})
    try:
        out = impact.rollup([])
    finally:
        policy.reset()
    assert out["in_scope_pct"] == round((8 + 2 * 9) / 3, 1)  # 100% of the reporting task, not 160%


def test_measured_runs_replace_the_estimate_for_modules_marked_measured_by_runs():
    marks = [{"stage": g, "kind": "review_started", "created_at": at(0)} for g in impact.GATES]
    approvals = [{"stage": g, "action": "approve", "created_at": at(2400)} for g in impact.GATES]  # 40 min a gate
    block = impact.for_run(RUN, approvals, marks, [], 7)
    partial = impact.for_run({**RUN, "run_id": "run_y", "vendor_id": "V002"}, approvals[:1], marks[:1], [], 7)
    out = impact.rollup([block, partial])
    assert out["basis"] == "measured" and out["measured_runs"] == 1 and out["partly_measured_runs"] == 1
    assert out["onboarding"]["human_share_pct"] == round(100 * 120 / 785, 1) and out["onboarding"]["saved_pct_basis"] == "measured"
    # onboarding now saves 1 - 120/785 of the covered time instead of the table's 45%
    assert out["saved_pct"] > impact.rollup([])["saved_pct"]


def test_the_target_comparison_follows_the_saving():
    policy.save_overrides({"impact": {"target_reduction_pct": 5}})
    try:
        assert impact.rollup([])["meets_target"] is True
    finally:
        policy.reset()


def test_the_workload_table_columns_each_sum_to_one_hundred():
    wl = policy.get().impact.workload
    assert round(sum(t.category_manager_pct for t in wl.values()), 6) == 100
    assert round(sum(t.category_executive_pct for t in wl.values()), 6) == 100


# ---------- through the API ----------


def test_run_view_carries_the_impact_block_and_the_clock_starts_at_review(client, clock):
    run_id = start(client, "V001")
    clock.advance(600)
    view = client.get(f"/api/runs/{run_id}").json()
    assert view["impact"]["measured_gates"] == 0 and view["impact"]["basis"] == "research_estimate"
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


def test_team_endpoint_before_any_run_is_a_research_estimate(client):
    out = client.get("/api/impact").json()
    assert out["basis"] == "research_estimate" and out["measured_runs"] == 0 and out["vendors"] == []
    assert out["baseline_status"] == "research_estimate" and out["mode"] == "mock"
    assert out["in_scope_pct"] == 18.5 and out["saved_pct"] == 8.8
    assert {m["status"] for m in out["modules"]} == {"shipped", "not_built"}


def test_team_endpoint_lists_runs_with_measurements(client, clock):
    run_id = start(client, "V001")
    clock.advance(120)
    client.post(f"/api/runs/{run_id}/stages/research/approve", json={"metrics_hash": research_hash(client, run_id)})
    out = client.get("/api/impact").json()
    assert [v["vendor_id"] for v in out["vendors"]] == ["V001"] and out["vendors"][0]["measured_gates"] == 1
    assert out["basis"] == "research_estimate" and out["partly_measured_runs"] == 1  # one gate is not a finished run


def test_replay_sessions_record_the_same_marks():
    store_ = replay.ReplayStore()

    async def go():
        await store_.create_run("run_r", "V001", "replay")
        await store_.add_mark("run_r", "research", "review_started")
        return await store_.list_marks("run_r")

    marks = asyncio.run(go())
    assert marks[0]["kind"] == "review_started" and marks[0]["stage"] == "research"
