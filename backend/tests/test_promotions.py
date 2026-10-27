"""Promotions and event planner: engine, planted cases, funding offers, verifier, API and playbook knobs."""

import pytest
from fastapi.testclient import TestClient

from app import impact, policy
from app.main import app
from app.ops import api as ops_api
from app.ops.promotions import claims as pc
from app.ops.promotions import engine
from app.schemas import Claim
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


def row(event: str, sku: str) -> dict:
    return next(r for r in engine.plan(event)["rows"] if r["sku_code"] == sku)


def test_the_calendar_comes_from_the_playbook():
    assert [e.id for e in engine.events()] == ["festive", "payday"]
    policy.save_overrides({"promotions": {"events": [{"id": "diwali", "name": "Diwali", "start": "2026-11-08", "end": "2026-11-09", "traffic_lift_pct": 5, "banner_slots": 1}]}})
    assert engine.event("diwali").name == "Diwali"


def test_unknown_event_is_a_typed_error(client):
    r = client.get("/api/ops/promotions/nope")
    assert r.status_code == 404 and r.json()["code"] == "unknown_promo_event"


def test_deep_discount_that_would_stock_out_is_capped():
    r = row("festive", "PL-02")  # Purrline cannot restock in time (10 day lead, event in 11)
    assert r["status"] == "planned" and r["capped_by_stock"] and r["stock_up"] is None
    deep = r["deep_option"]
    assert deep["stockout_day"] is not None and deep["stockout_day"] < 7  # runs out before the event ends
    assert deep["depth"] > r["discount_pct"] and r["stock_ok"]
    assert "lead time" in r["deep_option"]["why"] or r["stock_up_blocked"]


def test_restockable_sku_gets_a_stock_up_po_instead_of_a_shallower_discount():
    r = row("festive", "BK-06")
    assert r["stock_up"] and r["stock_up"]["qty"] > 0 and not r["capped_by_stock"]
    po = next(p for p in engine.plan("festive")["pos"] if p["vendor_id"] == "E001")
    assert po["qty"] >= r["stock_up"]["qty"] and po["arrives"] <= "2026-11-04"


def test_cannibalisation_flags_near_duplicates():
    r = row("festive", "PL-02")
    assert r["cannibalisation"] and r["cannibalisation"]["siblings"][0]["sku_code"] == "PL-01"
    policy.save_overrides({"promotions": {"cannibalisation": {"cannibalised_share_pct": 100}}})
    assert row("festive", "BK-01")["status"] in ("planned", "excluded")


def test_margin_after_funding_holds_the_promo_floor():
    for r in engine.plan("festive")["rows"]:
        if r["status"] == "planned":
            assert r["margin_at_ask_pct"] + 1e-6 >= r["floor_promo_pct"]
            assert r["funding_ask_share"] <= policy.get().promotions.funding.max_ask_share_pct / 100 + 1e-9


def test_knobs_move_the_plan():
    base = engine.plan("festive")["totals"]["planned_skus"]
    policy.save_overrides({"promotions": {"discount": {"max_pct": 10}}})
    capped = engine.plan("festive")
    assert all(r["discount_pct"] <= 0.11 for r in capped["rows"] if r["status"] == "planned")
    policy.reset()
    policy.save_overrides({"promotions": {"candidates": {"max_skus_per_event": 5}}})
    assert engine.plan("festive")["totals"]["planned_skus"] == 5 < base


def test_unrealistic_conditional_offer_has_low_probability_and_is_countered():
    plan = engine.plan("festive")
    v = engine.value_offer(engine.event("festive"), plan["rows"], "E001", {"share_pct": 50, "threshold_units": 3400, "banner_top_n": 3, "scope": []})
    assert v["probability"] < 0.1 and v["counted_inr"] == 0 and v["decision"] == "reject_structure"
    assert engine.counter_for(next(b for b in plan["vendors"] if b["vendor_id"] == "E001"), v)["kind"] == "counter"


def test_realistic_and_flat_offers_are_valued_differently():
    plan = engine.plan("festive")
    ev = engine.event("festive")
    flat = engine.value_offer(ev, plan["rows"], "E004", {"share_pct": 40, "scope": ["TW-01", "TW-02"]})
    assert flat["decision"] == "accept" and abs(flat["counted_inr"] - flat["face_inr"]) < 0.01
    cond = engine.value_offer(ev, plan["rows"], "E003", {"share_pct": 35, "threshold_units": 1150, "scope": []})
    assert cond["probability"] > 0.6 and 0 < cond["counted_inr"] < cond["face_inr"]
    assert engine.value_offer(ev, plan["rows"], "E006", {"share_pct": 25, "banner_top_n": 9, "scope": []})["decision"] == "reject_structure"


def test_every_table_claim_verifies_and_a_tampered_one_is_rejected():
    plan = engine.plan("festive")
    claims = [c for r in plan["rows"] if r["status"] == "planned" for c in pc.row_claims("festive", r)] + pc.event_claims("festive")
    assert len(claims) > 300 and all(verify_claim(c).status == "verified" for c in claims)
    bad = claims[5].model_copy(update={"value": claims[5].value * 1.5 + 3})
    assert verify_claim(bad).status == "rejected"


def test_extraction_claim_needs_the_quote_and_the_number():
    from app.ops.promotions import data as pdata
    from app.parsing import PARSER_VERSION
    from app.schemas import Evidence, SourceRef

    def mk(value: float, quote: str) -> Claim:
        return Claim(
            id="x", text="t", value=value, metric="promo_ext_share_pct", unit="pct", source_ref=SourceRef(file=pdata.REPLIES, key="F003", column="body"),
            evidence=Evidence(row=pdata.position("F003"), header="body", raw_value=quote, normalized_value=value, parser_version=PARSER_VERSION, sha256=pdata.file_sha256()), origin="model_extraction",
        )

    quote = "NutriPaws can support 35% of the discount cost across our range"
    assert verify_claim(mk(0.35, quote)).status == "verified"
    wrong = verify_claim(mk(0.53, quote))
    assert wrong.status == "rejected" and "35" in (wrong.reason or "")
    assert verify_claim(mk(0.35, "NutriPaws will fund 35% of everything")).status == "rejected"


def test_api_plan_self_corrects_the_planted_misreading_and_queues_emails(client):
    d = client.get("/api/ops/promotions/festive").json()
    assert d["verification"]["rejected"] == 0 and d["mode"] == "mock" and d["unresolved"] == []
    assert d["corrected"] == ["promo:F003:t0:share"]
    claim = next(c for c in d["claims"] if c["id"] == "promo:F003:t0:share")
    assert claim["attempts"][0]["value"] == 0.53 and claim["value"] == 0.35 and claim["status"] == "verified"
    by = {v["vendor_id"]: v["offer"] for v in d["vendors"]}
    assert by["E001"]["decision"] == "reject_structure" and by["E005"]["decision"] == "declined" and by["E004"]["decision"] == "accept"
    assert len(d["drafts"]) == len(d["vendors"]) and all(x["kind"] == "promo_funding" and x["status"] == "pending" for x in d["drafts"])
    assert d["impact_coverage"]["module"] == "promotions_planner"
    assert d["pos"] and d["totals"]["stock_up_inr"] > 0


def test_unreadable_extraction_is_dropped_not_valued(client, monkeypatch):
    monkeypatch.setattr(policy.get().verifier, "max_self_corrections", 0)  # no retry: the wrong share stays rejected
    policy.save_overrides({"verifier": {"max_self_corrections": 0}})
    d = client.get("/api/ops/promotions/festive").json()
    assert d["unresolved"] == ["promo:F003:t0:share"]
    assert next(v for v in d["vendors"] if v["vendor_id"] == "E003")["offer"] is None


def test_moved_playbook_strikes_prose_numbers_that_no_longer_verify(client):
    policy.save_overrides({"promotions": {"funding": {"target_share_pct": 20}}})
    d = client.get("/api/ops/promotions/festive").json()
    assert d["struck"] or d["verification"]["rejected"] > 0


def test_inject_fault_is_caught(client):
    assert client.get("/api/ops/promotions/payday?inject=1").json()["verification"]["rejected"] >= 1


def test_approve_plan_queues_simulated_pos_once(client):
    ev = client.get("/api/ops/promotions").json()["events"]
    assert [e["id"] for e in ev] == ["festive", "payday"] and ev[0]["planned_skus"] > 0
    out = client.post("/api/ops/promotions/festive/approve", json={}).json()
    assert out["simulated"] and out["status"] == "approved" and out["pos"] and all(p["status"] == "queued_simulated" for p in out["pos"])
    assert any(p["to_price"] < p["from_price"] for p in out["prices"])
    again = client.post("/api/ops/promotions/festive/approve", json={})
    assert again.status_code == 409 and again.json()["code"] == "promo_plan_decided"
    assert client.get("/api/ops/promotions/festive").json()["decision"]["status"] == "approved"
    assert client.post("/api/ops/promotions/payday/approve", json={"sku_codes": ["ZZ-99"]}).json()["code"] == "promo_plan_empty"
    assert client.post("/api/ops/promotions/payday/reject", json={}).json()["status"] == "rejected"


def test_funding_email_approval_uses_the_shared_outbox(client):
    d = client.get("/api/ops/promotions/festive").json()
    draft = d["drafts"][0]
    r = client.post(f"/api/ops/outbox/{draft['id']}/approve", json={})
    assert r.status_code == 200 and r.json()["status"] == "sent_simulated"


def test_rollup_moves_when_the_module_ships():
    shipped = impact.rollup([])
    policy.save_overrides({"impact": {"modules": {"promotions_planner": {"status": "not_built"}}}})
    assert impact.rollup([])["saved_pct"] < shipped["saved_pct"]


def test_default_rollup_with_every_module_shipped():
    out = impact.rollup([])
    mods = {m["key"]: m for m in out["modules"]}
    assert mods["promotions_planner"]["status"] == "shipped" and mods["competitor_monitor"]["status"] == "shipped"
    assert out["saved_pct"] == 34.6 and out["potential_saved_pct"] == 34.6  # every module is shipped
