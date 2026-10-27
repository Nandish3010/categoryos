"""Inventory health review: engine, planted issues, playbook thresholds, verifier, API and impact roll-up."""

import pytest
from fastapi.testclient import TestClient

from app import impact, policy
from app.main import app
from app.ops import api as ops_api
from app.ops.inventory_health import claims as ic
from app.ops.inventory_health import engine
from app.ops.runclaims import strike
from app.ops.schemas import Figure
from app.verify import verify_claim


@pytest.fixture(autouse=True)
def clean():
    ops_api.reset()
    yield
    policy.reset()
    ops_api.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def action(sku: str) -> dict:
    return next(a for a in engine.analyse()["actions"] if a["sku_code"] == sku)


def has_action(sku: str) -> bool:
    return any(a["sku_code"] == sku for a in engine.analyse()["actions"])


def test_planted_stock_outs_are_caught():
    np03 = action("NP-03")
    assert np03["kind"] == "stock_out" and np03["recommendation"] == "reorder" and np03["severity"] == "critical"
    assert np03["reorder"]["qty"] >= np03["reorder"]["moq_units"] == 600 and np03["reorder"]["lead_time_days"] > 0
    for sku in ("LT-05", "PL-01"):  # the late PO is the problem, more stock is not
        assert action(sku)["kind"] == "stock_out" and action(sku)["recommendation"] == "expedite_po"


def test_planted_dead_aged_and_overbuy_are_caught():
    assert action("TW-05")["recommendation"] == "return_to_vendor" and action("TW-05")["clear"]["rtv"]["urgent"]
    assert action("TW-03")["recommendation"] == "liquidate" and not action("TW-03")["clear"]["rtv"]["open"]  # window lapsed
    assert action("TW-04")["recommendation"] == "liquidate" and action("TW-04")["clear"]["rtv"] is None  # no return terms
    tw06 = action("TW-06")
    assert tw06["kind"] == "overbuy" and tw06["recommendation"] == "pause_po" and tw06["pause"]["moq_driven"]
    assert tw06["pause"]["cover_without_po_days"] <= engine.analyse()["skus"]["TW-06"]["band"]["max_days"]
    assert action("NP-91")["kind"] == "dead" and action("NP-91")["recommendation"] == "return_to_vendor"
    assert action("GW-91")["kind"] == "dead" and action("GW-91")["recommendation"] == "liquidate"


def test_healthy_skus_get_no_action():
    r = engine.analyse()
    healthy = [s for s in r["skus"].values() if s["band_state"] == "in" and s["aged_units"] == 0 and not s["landings"]]
    assert healthy and not any(has_action(s["sku_code"]) for s in healthy[:5])
    assert r["counts"]["legacy_lots"] == 2 and r["counts"]["skus"] == 38


def test_liquidation_price_respects_the_floor_and_rounding():
    for a in engine.analyse()["actions"]:
        if a.get("clear"):
            res = engine.analyse()["skus"][a["sku_code"]]
            assert a["clear"]["liquidate"]["price_inr"] >= res["cost"] * 0.6 - 1


def test_playbook_thresholds_move_the_answer():
    policy.save_overrides({"inventory_health": {"rtv": {"allow": False}}})
    assert action("TW-05")["recommendation"] == "liquidate"
    policy.reset()
    policy.save_overrides({"inventory_health": {"ageing": {"dead_no_sale_days": 365}}})
    assert not has_action("GW-91") or action("GW-91")["kind"] != "dead"
    policy.reset()
    policy.save_overrides({"inventory_health": {"stock_out": {"critical_days": 0}}})
    assert action("NP-03")["severity"] != "critical"
    policy.reset()
    policy.save_overrides({"inventory_health": {"moq": {"overbuy_ratio": 50}}})
    assert not action("TW-06")["pause"]["moq_driven"]


def test_category_band_overrides_the_default():
    cat = engine.analyse()["skus"]["NP-03"]["category"]
    policy.save_overrides({"inventory_health": {"cover": {"by_category": {cat: {"min_days": 1, "target_days": 5, "max_days": 10}}}}})
    assert engine.analyse()["skus"]["NP-03"]["band"] == {"min_days": 1.0, "target_days": 5.0, "max_days": 10.0}


def test_every_table_number_verifies_and_a_wrong_one_is_rejected():
    r = engine.analyse()
    claims = [c for a in r["actions"] for c in ic.action_claims(a)] + [c for v in r["vendors"] for c in ic.vendor_claims(v)]
    assert len(claims) > 100 and all(verify_claim(c).status == "verified" for c in claims)
    bad = claims[3].model_copy(update={"value": claims[3].value + 50})
    assert verify_claim(bad).status == "rejected"


def test_unknown_metric_is_unverifiable_and_stale_evidence_rejected():
    c = ic.action_claims(action("NP-03"))[0]
    assert verify_claim(c.model_copy(update={"metric": "ih_nonsense"})).status in ("unverifiable", "rejected")
    stale = c.model_copy(update={"evidence": c.evidence.model_copy(update={"sha256": "0" * 64})})
    assert verify_claim(stale).status == "rejected"


def test_strike_removes_unverified_or_unclaimed_numbers():
    figs = [Figure(metric="ih_reorder_qty", key="E003:NP-03", value=600, shown="600", text="x")]
    kept, struck = strike("Order 600 units. Cover is 12 days.", figs, [True])
    assert kept == "Order 600 units." and len(struck) == 1


def test_api_review_is_fully_verified_and_vendor_mail_is_queued(client):
    d = client.get("/api/ops/inventory-health").json()
    assert d["verification"]["rejected"] == 0 and d["verification"]["verified"] == d["verification"]["total"] > 100
    assert d["mode"] == "mock" and d["counts"]["stock_out"] >= 3 and d["counts"]["legacy_lots"] == 2
    assert {x["id"] for x in d["drafts"]} >= {"DR-IH-E003", "DR-IH-E004", "DR-IH-E005", "DR-IH-E002"} and all(x["status"] == "pending" for x in d["drafts"])
    assert d["impact_coverage"]["module"] == "inventory_health_module" and d["impact_coverage"]["status"] == "shipped"
    assert all(a["note"] is not None or a["recommendation"] in ("reorder", "expedite_po", "pause_po", "return_to_vendor", "liquidate") for a in d["actions"])


def test_inject_fault_is_caught(client):
    assert client.get("/api/ops/inventory-health?inject=1").json()["verification"]["rejected"] >= 1


def test_approving_actions_is_simulated(client):
    client.get("/api/ops/inventory-health")
    r = client.post("/api/ops/inventory-health/actions/ih:stock_out:NP-03/approve", json={}).json()
    assert r["simulated"] and r["effect"]["type"] == "po_draft" and r["effect"]["qty"] == action("NP-03")["reorder"]["qty"]
    v = client.post("/api/ops/inventory-health/actions/ih:aged:TW-05/approve", json={}).json()
    assert v["effect"]["type"] == "vendor_message" and v["effect"]["draft_status"] == "sent_simulated"
    q = client.post("/api/ops/inventory-health/actions/ih:aged:TW-04/approve", json={}).json()
    assert q["effect"]["type"] == "promo_nomination"
    again = client.post("/api/ops/inventory-health/actions/ih:stock_out:NP-03/approve", json={})
    assert again.status_code == 409 and again.json()["code"] == "inventory_action_decided"
    err = client.post("/api/ops/inventory-health/actions/ih:aged:NOPE/approve", json={})
    assert err.status_code == 404 and err.json()["code"] == "unknown_inventory_action" and {"problem", "cause", "fix"} <= set(err.json())
    client.post("/api/ops/inventory-health/actions/ih:dead:GW-91/reject", json={})
    assert {x["status"] for x in client.get("/api/ops/inventory-health").json()["decisions"]} == {"approved", "rejected"}


def test_struck_sentences_when_the_playbook_moves_the_numbers(client):
    # a different forecast window changes the demand, so the fixture's prose numbers stop verifying and are struck, never shown
    policy.save_overrides({"inventory_health": {"forecast": {"window_days": 14}}})
    d = client.get("/api/ops/inventory-health").json()
    assert d["struck"] or any(x["struck"] for x in d["drafts"]) or d["verification"]["rejected"] > 0


def test_rollup_rises_above_the_goal_when_the_module_ships():
    shipped = impact.rollup([])["saved_pct"]
    assert shipped > 33.3
    policy.save_overrides({"impact": {"modules": {"inventory_health_module": {"status": "not_built"}}}})
    assert impact.rollup([])["saved_pct"] < shipped
