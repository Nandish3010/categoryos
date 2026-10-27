"""Run: the HTTP API, the approval queue (sending is simulated), the playbook section and replay."""

import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import policy
from app.config import settings
from app.main import app
from app.ops import api as ops_api
from app.ops import outbox

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(autouse=True)
def fresh():
    ops_api.reset()
    yield
    ops_api.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def typed(body: dict) -> None:
    assert {"code", "problem", "cause", "fix"} <= set(body) and all(body[k] for k in ("code", "problem", "cause", "fix"))


# ---------- read endpoints ----------


def test_review_endpoint(client):
    out = client.get("/api/ops/review").json()
    assert out["mode"] == "mock" and out["degraded"] is False
    assert out["category"]["vendor_count"] == 6 and len(out["vendors"]) == 6
    assert out["verification"]["rejected"] == 0 and out["unclaimed_numbers"] == []
    assert out["actions"][0]["title"].startswith("Expedite replenishment of Peanut Butter Biscuits")
    assert out["trace"][0]["type"] == "stage_started" and any(t["type"] == "tool_call" for t in out["trace"])
    assert {d["kind"] for d in out["drafts"]} == {"vendor_review"} and len(out["drafts"]) == 5
    assert {"weekly_review_mis"} == {out["impact_coverage"]["module"]}


def test_pos_endpoint(client):
    out = client.get("/api/ops/pos").json()
    assert [p["po_id"] for p in out["pos"]][:2] == ["PO-E005-0008", "PO-E003-0010"]
    assert out["verification"]["rejected"] == 0 and out["corrected"] == ["reply:R004:0"]
    assert {d["kind"] for d in out["drafts"]} == {"po_followup"}
    assert [r["name"] for r in out["ladder"]] == ["Nudge", "Chase", "Escalate", "Formal notice"]


def test_vendor_endpoint(client):
    out = client.get("/api/ops/vendors/E005").json()
    assert out["vendor"]["brand"] == "Litterly" and out["scorecard"]["fill_rate_recent"] < 0.7
    assert out["email"]["vendor_id"] == "E005" and [p["po_id"] for p in out["pos"]] == ["PO-E005-0008"]
    assert {r["reply_id"] for r in out["readings"]} == {"R005", "R006"}
    assert out["drafts"][0]["po_id"] == "PO-E005-0008" and out["claims"]


def test_unknown_vendor_is_a_typed_404(client):
    res = client.get("/api/ops/vendors/E099")
    assert res.status_code == 404 and res.json()["code"] == "unknown_ops_vendor"
    typed(res.json())


def test_results_are_cached_per_playbook_but_inject_is_never_cached(client):
    first = client.get("/api/ops/review").json()
    assert client.get("/api/ops/review").json()["trace"] == first["trace"]  # same run, not regenerated
    bad = client.get("/api/ops/review?inject=1").json()
    assert bad["verification"]["rejected"] == 1
    assert client.get("/api/ops/review").json()["verification"]["rejected"] == 0


def test_inject_on_pos_is_caught(client):
    assert client.get("/api/ops/pos?inject=1").json()["verification"]["rejected"] == 1


# ---------- the approval queue ----------


def test_approving_marks_sent_simulated_and_touches_no_network(client, monkeypatch):
    client.get("/api/ops/pos")

    def no_network(*a, **kw):
        raise AssertionError("approving a draft must not open a connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    res = client.post("/api/ops/outbox/DR-PO-E003-0010/approve").json()
    assert res["status"] == "sent_simulated" and res["simulated"] is True and res["decided_at"]
    box = client.get("/api/ops/outbox").json()
    assert box["simulated"] is True and box["pending"] == 3


def test_a_decided_draft_cannot_be_decided_again(client):
    client.get("/api/ops/pos")
    assert client.post("/api/ops/outbox/DR-PO-E003-0010/reject", json={"note": "will call instead"}).json()["status"] == "rejected"
    again = client.post("/api/ops/outbox/DR-PO-E003-0010/approve")
    assert again.status_code == 409 and again.json()["code"] == "draft_not_pending"
    typed(again.json())
    assert client.post("/api/ops/outbox/NOPE/approve").json()["code"] == "unknown_draft"


def test_a_decided_draft_survives_the_next_generation(client):
    client.get("/api/ops/pos")
    client.post("/api/ops/outbox/DR-PO-E002-0012/approve")
    ops_api._cache.clear()
    out = client.get("/api/ops/pos").json()
    assert next(d for d in out["drafts"] if d["id"] == "DR-PO-E002-0012")["status"] == "sent_simulated"


def test_an_edited_message_is_rechecked_for_numbers_without_a_claim(client):
    client.get("/api/ops/pos")
    res = client.post("/api/ops/outbox/DR-PO-E004-0007/approve", json={"body": "Hi Vikram, please ship 250 units by Thursday."}).json()
    assert res["edited"] and res["status"] == "sent_simulated" and res["warnings"] == ["number without a claim: 250"]


def test_a_draft_with_a_rejected_figure_cannot_be_approved_until_it_is_fixed(client):
    outbox.put(
        {
            "id": "DR-X", "kind": "vendor_review", "vendor_id": "E002", "po_id": None, "channel": "email", "subject": "s", "source": "agent",
            "body": "Your fill rate is 45% this month.", "figures": [{"claim_id": "c1", "shown": "45%", "status": "rejected", "reason": "engine recomputed 0.54"}],
            "claim_ids": ["c1"],
        }
    )
    assert outbox.get("DR-X")["blocked_by"] == ["45%"]
    blocked = client.post("/api/ops/outbox/DR-X/approve")
    assert blocked.status_code == 409 and blocked.json()["code"] == "draft_has_unverified_numbers"
    typed(blocked.json())
    fixed = client.post("/api/ops/outbox/DR-X/approve", json={"body": "Your fill rate dropped this month."}).json()
    assert fixed["status"] == "sent_simulated" and fixed["blocked_by"] == []


def test_outbox_filter(client):
    client.get("/api/ops/review")
    client.get("/api/ops/pos")
    assert len(client.get("/api/ops/outbox?kind=vendor_review").json()["drafts"]) == 5
    assert len(client.get("/api/ops/outbox?kind=po_followup").json()["drafts"]) == 4


# ---------- the playbook ----------


def test_operations_section_is_in_the_playbook_with_schema_hints(client):
    snap = client.get("/api/policy").json()
    assert snap["policy"]["operations"]["scorecard"]["fill_rate_floor_pct"] == 90
    hints = snap["schema_hints"]
    for path in ("operations.scorecard.fill_rate_floor_pct", "operations.scorecard.otif_target_pct", "operations.scorecard.stock_cover_alert_days",
                 "operations.scorecard.ageing_buckets_days", "operations.anomaly.growth_z_threshold", "operations.po_followup.ladder", "operations.actions.priority_weights"):
        assert path in hints and hints[path]["label"], path
    assert hints["operations.po_followup.ladder"]["kind"] == "table"
    assert hints["operations.scorecard.fill_rate_floor_pct"]["unit"] == "%"


def test_editing_a_threshold_changes_what_gets_flagged(client):
    flagged = {a["id"] for a in client.get("/api/ops/review").json()["anomalies"]}
    assert "fill_rate:E003" in flagged and "stockout:LT-05" in flagged
    res = client.put("/api/policy", json={"operations": {"scorecard": {"fill_rate_floor_pct": 80, "fill_rate_drop_pp": 20, "stock_cover_alert_days": 4}}})
    assert res.status_code == 200
    after = {a["id"] for a in client.get("/api/ops/review").json()["anomalies"]}
    assert "fill_rate:E003" not in after and "stockout:LT-05" not in after  # recent fill 89% is above 80%; 5 days of cover is above 4
    assert "stockout:NP-03" in after


def test_invalid_thresholds_are_typed_422s(client):
    res = client.put("/api/policy", json={"operations": {"scorecard": {"fill_rate_floor_pct": 150}}})
    assert res.status_code == 422 and res.json()["path"] == "operations.scorecard.fill_rate_floor_pct"
    typed(res.json())


def test_the_ladder_edit_changes_the_chase_queue(client):
    ladder = [{"name": "Only", "days_overdue": 5, "channel": "email", "owner": "category manager", "tone": "firm"}]
    client.put("/api/policy", json={"operations": {"po_followup": {"ladder": ladder}}})
    out = client.get("/api/ops/pos").json()
    assert {p["po_id"] for p in out["pos"] if p["needs_chase"]} == {"PO-E005-0008", "PO-E003-0010"}  # only the POs at least 5 days late


# ---------- impact meter ----------


def test_modules_are_registered_as_shipped_in_the_impact_rollup(client):
    out = client.get("/api/impact").json()
    status = {m["key"]: m["status"] for m in out["modules"]}
    assert status["weekly_review_mis"] == "shipped" and status["po_followup"] == "shipped"
    assert out["saved_pct"] > 8.8  # more than the onboarding-only baseline
    mods = client.get("/api/ops/impact").json()["modules"]
    assert [m["module"] for m in mods] == ["weekly_review_mis", "po_followup"] and all(m["registered"] for m in mods)


# ---------- replay ----------


def test_golden_fixtures_match_the_mock_fixtures():
    for f in sorted((FIXTURES / "mock" / "ops").glob("*.json")):
        golden = FIXTURES / "golden" / "ops" / f.name
        assert golden.exists(), f"missing golden for {f.name}: copy it from the mock fixtures"
        assert json.loads(golden.read_text())["content"] == json.loads(f.read_text())["content"]


def test_replay_serves_the_recorded_runs_without_degrading(client, monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "replay")
    out = client.get("/api/ops/review").json()
    assert out["mode"] == "replay" and out["degraded"] is False and out["verification"]["rejected"] == 0
    pos = client.get("/api/ops/pos").json()
    assert pos["mode"] == "replay" and pos["unresolved"] == []
    assert not any(t["type"] == "degraded" for t in pos["trace"])


def test_replay_falls_back_to_the_mock_fixture_and_says_so(client, monkeypatch, tmp_path):
    import shutil

    fx = tmp_path / "fixtures"
    shutil.copytree(FIXTURES / "mock", fx / "mock")
    monkeypatch.setattr(settings, "fixtures_dir", fx)
    monkeypatch.setattr(settings, "model_mode", "replay")
    out = client.get("/api/ops/review").json()
    assert out["degraded"] is True


def test_reset_needs_the_demo_key_when_one_is_set(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_key", "secret")
    assert client.post("/api/ops/reset").status_code == 403
    assert client.post("/api/ops/reset", headers={"X-Demo-Key": "secret"}).json() == {"ok": True}


def test_live_generation_is_gated_by_the_demo_key(client, monkeypatch):
    monkeypatch.setattr(settings, "model_mode", "live")
    monkeypatch.setattr(settings, "model_api_key", "k")
    monkeypatch.setattr(settings, "demo_key", "secret")
    res = client.get("/api/ops/review")
    assert res.status_code == 403 and res.json()["code"] == "demo_key_required"


def test_policy_hash_changes_with_operations_edits():
    before = policy.policy_hash()
    policy.save_overrides({"operations": {"anomaly": {"growth_z_threshold": 3.5}}})
    assert policy.policy_hash() != before
