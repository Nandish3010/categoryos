"""Competitor price monitor: engine, planted cases, verifier, API and playbook knobs."""

import pytest
from fastapi.testclient import TestClient

from app import impact, policy
from app.main import app
from app.ops import api as ops_api
from app.ops.pricewatch import claims as pc
from app.ops.pricewatch import engine
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


def action(sku: str, kind: str | None = None) -> dict:
    return next(a for a in engine.analyse()["actions"] if a["sku_code"] == sku and (kind is None or a["kind"] == kind))


def test_planted_cases_get_the_right_answer():
    assert action("GW-01")["recommendation"] == "match"  # healthy margin, sustained 9% undercut
    assert action("BK-01")["recommendation"] == "ask_vendor_funding"  # matching breaks the floor
    breach = action("LT-01", "breach")
    assert breach["recommendation"] == "flag_breach" and breach["vendor"]["parity_breach"] and breach["vendor"]["map_breach"]
    assert 0.11 < breach["vendor"]["gap_below_pct"] < 0.13  # the vendor sells about 12% under us
    assert action("TW-02")["kind"] == "trend" and action("TW-02")["recommendation"] == "hold"


def test_one_day_blip_is_never_matched():
    a = action("NP-04")
    assert a["kind"] == "blip" and a["recommendation"] == "hold"
    assert a["competitor"]["state"] == "blip" and a["competitor"]["margin_impact_inr"] < 0  # matching would have cost margin
    assert not any(x["sku_code"] == "NP-04" and x["recommendation"] == "match" for x in engine.analyse()["actions"])


def test_blip_becomes_sustained_when_the_playbook_says_one_day_is_enough():
    policy.save_overrides({"price_watch": {"undercut": {"min_sustained_days": 1}}})
    assert action("NP-04")["kind"] == "undercut"


def test_threshold_and_match_knobs_move_the_answer():
    policy.save_overrides({"price_watch": {"match": {"allow": False}}})
    assert action("GW-01")["recommendation"] == "hold"
    policy.reset()
    policy.save_overrides({"price_watch": {"match": {"max_cut_pct": 5}}})
    assert action("GW-01")["recommendation"] == "escalate"
    policy.reset()
    policy.save_overrides({"price_watch": {"parity": {"tolerance_pct": 20, "enforce_map": False}}})
    assert not any(a["kind"] == "breach" for a in engine.analyse()["actions"])


def test_every_table_number_verifies_and_a_wrong_one_is_rejected():
    claims = [c for a in engine.analyse()["actions"] for c in pc.action_claims(a)]
    assert claims and all(verify_claim(c).status == "verified" for c in claims)
    bad = claims[3].model_copy(update={"value": claims[3].value + 50})
    assert verify_claim(bad).status == "rejected"


def test_unknown_metric_is_unverifiable_and_stale_evidence_rejected():
    c = pc.action_claims(action("GW-01"))[0]
    assert verify_claim(c.model_copy(update={"metric": "pw_nonsense"})).status in ("unverifiable", "rejected")
    stale = c.model_copy(update={"evidence": c.evidence.model_copy(update={"sha256": "0" * 64})})
    assert verify_claim(stale).status == "rejected"


def test_strike_removes_sentences_with_unverified_or_unclaimed_numbers():
    figs = [Figure(metric="pw_below_pct", key="E003:NP-04?mp=MarketC", value=0.139, shown="13.9%", text="x"), Figure(metric="pw_our_price", key="E003:NP-04", value=101, shown="₹101", text="y")]
    text = "It dipped 13.9% under us. Our price is ₹101. We guess 77% more."
    kept, struck = strike(text, figs, [True, False])
    assert kept == "It dipped 13.9% under us." and len(struck) == 2


def test_api_sweep_is_fully_verified_and_planted_vendor_mail_is_queued(client):
    d = client.get("/api/ops/price-watch").json()
    assert d["verification"]["rejected"] == 0 and d["verification"]["verified"] == d["verification"]["total"] > 40
    assert d["mode"] == "mock" and d["counts"]["blips"] == 1 and d["counts"]["breaches"] == 1
    assert {x["id"] for x in d["drafts"]} == {"DR-PW-E005", "DR-PW-E001"} and all(x["status"] == "pending" for x in d["drafts"])
    assert d["impact_coverage"]["module"] == "competitor_monitor" and d["impact_coverage"]["status"] == "shipped"


def test_inject_fault_is_caught(client):
    d = client.get("/api/ops/price-watch?inject=1").json()
    assert d["verification"]["rejected"] >= 1


def test_approving_actions_is_simulated(client):
    client.get("/api/ops/price-watch")
    m = client.post("/api/ops/price-watch/actions/pw:undercut:GW-01/approve", json={}).json()
    assert m["simulated"] and m["effect"]["type"] == "price_change" and m["effect"]["to_price"] == 292
    b = client.post("/api/ops/price-watch/actions/pw:breach:LT-01/approve", json={}).json()
    assert b["effect"]["type"] == "vendor_message" and b["effect"]["draft_status"] == "sent_simulated"
    again = client.post("/api/ops/price-watch/actions/pw:undercut:GW-01/approve", json={})
    assert again.status_code == 409 and again.json()["code"] == "price_watch_action_decided"
    assert client.post("/api/ops/price-watch/actions/pw:undercut:NOPE/approve", json={}).json()["code"] == "unknown_price_watch_action"
    client.post("/api/ops/price-watch/actions/pw:blip:NP-04/reject", json={})
    assert {x["status"] for x in client.get("/api/ops/price-watch").json()["decisions"]} == {"approved", "rejected"}


def test_struck_sentences_when_the_playbook_moves_the_numbers(client):
    # a different margin buffer changes the engine's margins, so the fixture's prose numbers stop verifying and are struck, never shown
    policy.save_overrides({"price_watch": {"match": {"margin_buffer_pp": 3}}})
    d = client.get("/api/ops/price-watch").json()
    assert d["struck"] or any(x["struck"] for x in d["drafts"]) or d["verification"]["rejected"] > 0
    assert all("sent" not in x["status"] for x in d["drafts"])


def test_rollup_moves_when_the_module_ships():
    shipped = impact.rollup([])["saved_pct"]
    policy.save_overrides({"impact": {"modules": {"competitor_monitor": {"status": "not_built"}}}})
    assert impact.rollup([])["saved_pct"] < shipped
