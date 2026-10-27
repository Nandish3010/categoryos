"""Existing-vendor price-increase requests: the quote check, the margin and elasticity maths, sweetener valuation,
the decision matrix, approval tiers, the API and the playbook knobs."""

import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import deals, policy, pricereq
from app.agents import pricereq as pa
from app.main import app
from app.pricereq import ExtractedLine, ExtractedSweetener, PriceRequestExtraction
from app.schemas import Claim, Evidence, SourceRef

RECEIVED = date(2026, 10, 26)
TODAY = date(2026, 10, 27)


@pytest.fixture(autouse=True)
def fresh():
    pa.reset_state()
    yield
    pa.reset_state()
    policy.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def run(coro):
    return asyncio.run(coro)


def evaluate_request(rid):
    return run(pa.evaluate(pa.get_request(rid)))


def ext(vendor_lines, effective="2026-12-01", sweeteners=()):
    return PriceRequestExtraction(
        effective_date=effective, effective_quote="x", reason="r", reason_quote="r",
        lines=[ExtractedLine(sku_code=c, old_cost=o, new_cost=n, quote=f"{c} {o} {n}") for c, o, n in vendor_lines],
        sweeteners=list(sweeteners),
    )


def ev_for(vendor, lines, effective="2026-12-01", sweeteners=(), received=RECEIVED):
    return pricereq.evaluate(vendor, ext(lines, effective, sweeteners), received, TODAY)


def line(ev, code):
    return next(r for r in ev.lines if r.sku_code == code)


def typed(body):
    assert all(body.get(k) for k in ("code", "problem", "cause", "fix"))


# ---------- extraction: the quote check ----------


def mk_claim(req, quote, value, metric="price_req_new_cost", unit="inr", source="price_list"):
    text = req.price_list if source == "price_list" else req.email
    import hashlib

    return Claim(
        id="t", text="t", value=value, metric=metric, unit=unit, origin="model_extraction",
        source_ref=SourceRef(file=f"price_requests/{req.id}/" + ("email.txt" if source == "email" else "price_list"), key="k"),
        evidence=Evidence(raw_value=quote, parser_version="1", sha256=hashlib.sha256(text.encode()).hexdigest()),
    )


def test_a_verbatim_quote_with_the_number_verifies_and_comma_joined_csv_cells_are_read_both_ways():
    req = pa.get_request("PR-001")
    row = next(r for r in req.price_list.splitlines() if r.startswith("GW-03"))
    assert pa.check_claim(mk_claim(req, row, 135.2), req).status == "verified"
    assert pa.check_claim(mk_claim(req, row, 130.0), req).status == "verified"  # old cost cell: "130" next to "135.20" in a CSV row
    quoted = next(r for r in req.price_list.splitlines() if r.startswith("GW-01"))  # '..., 250 ml,Rs. 190,197.60,...'
    assert pa.check_claim(mk_claim(req, quoted, 197.6), req).status == "verified"


def test_a_misquoted_or_wrong_number_is_rejected_with_a_reason():
    req = pa.get_request("PR-001")
    row = next(r for r in req.price_list.splitlines() if r.startswith("GW-03"))
    wrong = pa.check_claim(mk_claim(req, row, 153.2), req)
    assert wrong.status == "rejected" and "states" in (wrong.reason or "")
    invented = pa.check_claim(mk_claim(req, row.replace("Paw Balm", "Paw Butter"), 135.2), req)
    assert invented.status == "rejected" and "verbatim" in (invented.reason or "")
    assert pa.check_claim(mk_claim(req, "", 135.2), req).status == "rejected"


def test_a_word_number_and_a_date_in_the_quote_are_read():
    req = pa.get_request("PR-002")
    half = "we will absorb half of the revision across the range if you commit 1,500 units/month"
    assert pa.check_claim(mk_claim(req, half, 0.5, "price_req_share_pct", "pct", "email"), req).status == "verified"
    assert pa.check_claim(mk_claim(req, half, 1500.0, "price_req_threshold_units", "units", "email"), req).status == "verified"
    assert pa.check_claim(mk_claim(req, half, 30.0, "price_req_period", "units", "email"), req).status == "verified"  # "/month"
    assert pa.check_claim(mk_claim(req, half, 0.6, "price_req_share_pct", "pct", "email"), req).status == "rejected"
    when = "effective 1st Dec 2026"
    assert pa.check_claim(mk_claim(req, when, 20261201.0, "price_req_date", "units", "email"), req).status == "verified"
    assert pa.check_claim(mk_claim(req, when, 20261221.0, "price_req_date", "units", "email"), req).status == "rejected"


def test_messy_dates_are_parsed():
    ref = date(2026, 10, 26)
    assert pricereq.parse_dates("w.e.f. 01.12.2026", ref) == [date(2026, 12, 1)]
    assert pricereq.parse_dates("from 10th Nov", ref) == [date(2026, 11, 10)]
    assert pricereq.parse_dates("01-Dec-2026 and 2027-01-15", ref) == [date(2027, 1, 15), date(2026, 12, 1)]
    assert pricereq.parse_dates("15 market stalls", ref) == []  # "mar" is not March


def test_a_planted_transposition_is_caught_and_the_agent_corrects_it():
    a, ev = evaluate_request("PR-003")
    claim = next(c for c in a.claims if c.id.endswith("line:NP-02:new_cost"))
    assert claim.status == "verified" and len(claim.attempts) == 2 and claim.attempts[0].status == "rejected"
    assert claim.attempts[0].value == 819.75 and claim.value == 189.75
    kinds = [e["type"] for e in a.events]
    assert "claim_rejected" in kinds and "self_correction" in kinds and "claim_verified" in kinds
    assert len(ev.lines) == 4


def test_with_self_correction_off_the_wrong_line_is_dropped_not_guessed():
    policy.save_overrides({"verifier": {"max_self_corrections": 0}})
    a, ev = evaluate_request("PR-003")
    assert [r["id"] for r in a.rejected] == ["NP-02"] and "819.75" in a.rejected[0]["reasons"][0]
    assert {r.sku_code for r in ev.lines} == {"NP-01", "NP-04", "NP-05"}


# ---------- margin maths ----------


def test_new_margin_needed_retail_and_gap_follow_from_the_ops_numbers():
    # GW-01: price 321, cost 190; +10% -> cost 209, margin (321 - 209) / 321
    ev = ev_for("E006", [("GW-01", 190, 209)])
    r = line(ev, "GW-01")
    assert r.current_margin_pct == pytest.approx((321 - 190) / 321 * 100, abs=1e-3)
    assert r.new_margin_pct == pytest.approx((321 - 209) / 321 * 100, abs=1e-3)
    assert r.margin_drop_pts == pytest.approx(r.current_margin_pct - r.new_margin_pct, abs=1e-3)
    # grooming target 38%: we are above it today, so the retail price defending 38% is cost / (1 - 0.38)
    assert r.target_margin_pct == 38.0
    assert r.needed_retail == pytest.approx(209 / 0.62, abs=0.01)
    assert r.needed_retail_for_target == r.needed_retail
    assert r.retail_rise_pct == pytest.approx((209 / 0.62 / 321 - 1) * 100, abs=1e-3)
    assert r.gap_if_passed_pct == pytest.approx(r.retail_rise_pct, abs=1e-3)  # competitor median = our price today


def test_a_sku_already_under_target_defends_its_current_margin_not_the_target():
    r = line(ev_for("E004", [("TW-01", 210, 220.5)]), "TW-01")  # toys: target 40%, today 34.6%
    assert r.current_margin_pct < r.target_margin_pct
    assert r.needed_retail == pytest.approx(220.5 / (1 - r.current_margin_pct / 100), abs=0.01)
    assert r.retail_rise_pct == pytest.approx(5.0, abs=0.01)  # a 5% cost rise needs a 5% price rise to hold the margin
    assert r.needed_retail_for_target > r.needed_retail


def test_a_cost_decrease_is_accepted_and_a_stated_old_cost_that_differs_from_the_file_is_flagged():
    assert line(ev_for("E006", [("GW-01", 190, 180)]), "GW-01").decision == "accept"
    r = line(ev_for("E006", [("GW-01", 200, 208)]), "GW-01")  # file says 190; the vendor says 200 -> +4%
    assert r.old_cost_mismatch and r.pct_change == pytest.approx(4.0) and any("on file" in x for x in r.reasons)
    unknown = line(ev_for("E006", [("GW-99", 10, 12)]), "GW-99")
    assert unknown.status == "unmatched" and unknown.decision == "needs_review"


# ---------- elasticity and impact ----------


def test_volume_change_uses_the_categorys_elasticity_and_sets_the_risk_band():
    r = line(ev_for("E004", [("TW-01", 210, 235.2)]), "TW-01")  # +12% -> price +12%
    assert r.elasticity == policy.get().price_requests.elasticity.by_category["toys"] == -1.9
    assert r.volume_change_pct == pytest.approx(((1.12) ** -1.9 - 1) * 100, abs=0.01)
    assert r.elasticity_risk == "high"
    low = line(ev_for("E006", [("GW-01", 190, 197.6)]), "GW-01")
    assert low.elasticity_risk == "low" and low.volume_change_pct == 0.0  # absorbed: no price change, no volume change


def test_elasticity_knobs_change_the_risk_and_the_decision():
    base = line(ev_for("E003", [("NP-01", 150, 156)]), "NP-01")  # +4%: justified (ceiling 5), too thin to absorb
    assert base.decision == "pass_through" and base.elasticity_risk == "medium"  # 4% x -1.8 = about -6.8% units
    policy.save_overrides({"price_requests": {"elasticity": {"risk_medium_loss_pct": 8, "risk_high_loss_pct": 12}}})
    assert line(ev_for("E003", [("NP-01", 150, 156)]), "NP-01").elasticity_risk == "low"
    policy.save_overrides({"price_requests": {"elasticity": {"by_category": {"treats": -4.0}}}})
    steep = line(ev_for("E003", [("NP-01", 150, 156)]), "NP-01")
    assert steep.elasticity == -4.0 and steep.elasticity_risk == "high"
    assert steep.decision == "accept_partial" and steep.counter_basis == "pass_through" and steep.counter_pct < 4.0  # the volume cap now limits the pass-through


def test_the_ninety_day_impact_compares_absorbing_passing_on_and_the_recommendation():
    _a, ev = evaluate_request("PR-002")
    imp = ev.impact
    assert imp["horizon_days"] == 90 and imp["baseline_gmv"] > 0
    assert imp["absorb"]["gmv_delta"] == 0 and imp["absorb"]["margin_delta"] < imp["recommended"]["margin_delta"] < 0
    assert imp["pass_through"]["gmv_delta"] < imp["recommended"]["gmv_delta"] < 0  # passing everything on loses more units
    one = line(ev, "TW-01")
    labels = [s.label for s in one.scenarios]
    assert labels[0] == "status quo" and one.recommended in labels
    q = one.scenarios[0]
    assert q.units == pytest.approx(one.scenarios[1].units)  # absorbing keeps the units
    policy.save_overrides({"price_requests": {"horizon_days": 30}})
    assert evaluate_request("PR-002")[1].impact["baseline_gmv"] == pytest.approx(imp["baseline_gmv"] / 3, rel=1e-3)


# ---------- commodity justification ----------


def test_justification_compares_the_asked_rise_with_the_index_plus_tolerance():
    ok = line(ev_for("E006", [("GW-01", 190, 197.6)]), "GW-01")  # 4% against index 3 + 2
    assert ok.justified is True and ok.justified_ceiling_pct == 5.0
    bad = line(ev_for("E006", [("GW-01", 190, 209)]), "GW-01")  # 10%
    assert bad.justified is False and bad.decision == "accept_partial" and bad.counter_pct == 5.0 and bad.counter_basis == "absorb"
    policy.save_overrides({"price_requests": {"justification": {"index_change_pct": 9.0}}})
    assert line(ev_for("E006", [("GW-01", 190, 209)]), "GW-01").justified is True
    policy.save_overrides({"price_requests": {"justification": {"index_change_pct": None}}})
    off = line(ev_for("E006", [("GW-01", 190, 197.6)]), "GW-01")
    assert off.justified is None and off.justified_ceiling_pct is None  # no index: the largest increase without escalation applies
    assert any("No input index" in x for x in off.reasons)


# ---------- sweeteners ----------


def absorb(threshold, window=30, share=50.0):
    return ExtractedSweetener(id="s1", kind="absorb_if_volume", share_pct=share, threshold_units=threshold, window_days=window, quote="q")


def test_an_improbable_volume_sweetener_is_valued_by_the_probability_engine_at_zero():
    _a, ev = evaluate_request("PR-002")
    s = ev.sweeteners[0]
    assert s.engine == "deals" and s.assessment is not None
    assert s.probability is not None and s.probability < 0.1
    assert s.counted_pts == 0.0 and s.counted_share_pct == 0.0 and s.value_pts > 0  # face value is not counted
    assert s.assessment["distribution"]["metric"] == "units" and s.assessment["tiers"][0]["counted"] is False
    assert [r.effective_pct for r in ev.lines] == [r.pct_change for r in ev.lines]  # nothing absorbed
    assert {c["kind"] for c in s.assessment["counters"]} >= {"threshold", "convert_to_base"}
    assert "volume commitment were lowered" in " ".join(ev.counter_offer["sweetener_asks"])


def test_a_likely_sweetener_counts_and_lowers_the_effective_rise():
    lines = [("TW-01", 210, 235.2), ("TW-02", 180, 198.0)]
    none = ev_for("E004", lines)
    likely = ev_for("E004", lines, sweeteners=[absorb(300)])  # we sell about 700 a month across the range
    s = likely.sweeteners[0]
    assert s.probability is not None and s.probability >= policy.get().negotiation.contingent.min_probability
    assert s.counted_share_pct and 0 < s.counted_share_pct <= 50
    assert line(likely, "TW-01").effective_pct < line(none, "TW-01").effective_pct == 12.0
    assert any("counts as absorbing" in x for x in line(likely, "TW-01").reasons)


def test_the_sweetener_bar_is_the_playbooks_min_probability():
    lines = [("TW-01", 210, 235.2)]
    mid = ev_for("E004", lines, sweeteners=[absorb(700)])
    p = mid.sweeteners[0].probability
    assert p is not None and 0.1 < p < 0.95
    policy.save_overrides({"negotiation": {"contingent": {"min_probability": min(p + 0.05, 0.99)}}})
    assert ev_for("E004", lines, sweeteners=[absorb(700)]).sweeteners[0].counted_pts == 0.0
    policy.save_overrides({"negotiation": {"contingent": {"min_probability": max(p - 0.05, 0.01)}}})
    assert ev_for("E004", lines, sweeteners=[absorb(700)]).sweeteners[0].counted_pts > 0.0


def test_acceptance_linked_support_is_certain_and_netted_against_the_margin_lost():
    _a, ev = evaluate_request("PR-001")
    s = ev.sweeteners[0]
    assert s.engine == "acceptance" and s.probability == 1.0 and s.value_pts == 2.0
    drop = sum(r.margin_drop_pts for r in ev.lines) / len(ev.lines)
    assert s.net_pts == pytest.approx(2.0 - drop, abs=0.5)
    assert ev.impact["recommended"]["margin_delta"] > ev.impact["pass_through"]["margin_delta"] - 1  # support credit is in the maths


def test_the_deal_engine_values_an_existing_listing_at_steady_state_not_as_a_new_listing_ramp():
    facts = pricereq.vendor_facts("E004")
    sk = pricereq.deal_facts(facts)
    ctx_new = deals.Context(sk, base_margin_pct=30.0)
    ctx_old = deals.Context(sk, base_margin_pct=30.0, ramp=(1.0,))
    term = deals.DealTerm if False else None  # noqa: F841
    from app.schemas import DealCondition, DealTerm

    t = DealTerm(id="t", kind="conditional", term="margin_pct", value=3.0, condition=DealCondition(metric="units", threshold=700, window_days=30), quote="q", turn=1)
    assert deals.assess_one(t, None, ctx_old).probability > deals.assess_one(t, None, ctx_new).probability  # new-listing ramp halves month 1


# ---------- the decision matrix ----------


def test_the_three_planted_requests_decide_as_designed():
    _a1, e1 = evaluate_request("PR-001")
    assert e1.decision == "accept" and e1.counts == {"accept": 5} and e1.approval.tier.role == "category_executive"
    _a2, e2 = evaluate_request("PR-002")
    assert e2.decision == "accept_partial" and all(r.counter_pct and 4 <= r.counter_pct <= 5 for r in e2.lines)
    assert e2.approval.asked_pct == 12.0 and e2.approval.tier.role == "category_manager"  # the counter relies on raising our prices
    _a3, e3 = evaluate_request("PR-003")
    assert e3.decision == "delay" and {r.then_decision for r in e3.lines} == {"accept_partial"}
    assert all(r.gap_if_passed_pct == pytest.approx(15.0, abs=0.05) for r in e3.lines)  # passing 15% on = 15% above competitors
    assert {r.ask_effective_date for r in e3.lines} == {"2026-11-25"} and all(r.notice_days == 15 for r in e3.lines)


def test_matrix_branches():
    # absorbable and justified -> accept
    assert line(ev_for("E006", [("GW-01", 190, 195)]), "GW-01").decision == "accept"
    # under target after the rise, pass-through allowed and within the gap/volume rules -> pass on
    assert line(ev_for("E006", [("GW-01", 190, 197.6)]), "GW-01").decision == "accept"  # still 38.4% >= 38%
    assert line(ev_for("E006", [("GW-02", 250, 260)]), "GW-02").decision == "pass_through"  # 39.5% -> 37.0%: under the 38% target
    # excessive -> counter at the justified ceiling
    r = line(ev_for("E006", [("GW-06", 90, 99)]), "GW-06")
    assert r.decision == "accept_partial" and r.counter_pct == 5.0
    # nothing absorbable and passing on is switched off -> delist / find an alternate
    policy.save_overrides({"price_requests": {"pass_through": {"allow": False}}})
    d = line(ev_for("E003", [("NP-02", 165, 173.25)]), "NP-02")  # NP-02 sits under its floor already
    assert d.decision == "delist" and d.counter_pct is None
    policy.reset()
    # a short notice turns an acceptable line into a delay that remembers what it would accept
    s = line(ev_for("E006", [("GW-01", 190, 195)], effective="2026-11-05"), "GW-01")
    assert s.decision == "delay" and s.then_decision == "accept" and s.short_notice and s.ask_effective_date == "2026-11-25"


def test_overall_decision_is_the_most_serious_line():
    ev = ev_for("E006", [("GW-01", 190, 195), ("GW-06", 90, 99)])
    assert {r.decision for r in ev.lines} == {"accept", "accept_partial"} and ev.decision == "accept_partial"
    assert "accept partial" in ev.headline


# ---------- playbook knobs change decisions ----------


def test_notice_period_knob_moves_a_delay_to_a_counter():
    assert evaluate_request("PR-003")[1].decision == "delay"
    policy.save_overrides({"price_requests": {"notice_period_days": 10}})
    ev = evaluate_request("PR-003")[1]
    assert ev.decision == "accept_partial" and not any(r.short_notice for r in ev.lines)


def test_max_acceptable_increase_knob_changes_the_counter_when_no_index_is_set():
    policy.save_overrides({"price_requests": {"justification": {"index_change_pct": None}}})
    assert line(ev_for("E006", [("GW-06", 90, 99)]), "GW-06").counter_pct == 5.0
    policy.save_overrides({"price_requests": {"max_acceptable_increase_pct": 8}})
    assert line(ev_for("E006", [("GW-06", 90, 99)]), "GW-06").counter_pct == 8.0


def test_pass_through_rules_knob_lets_the_big_increase_through():
    policy.save_overrides({"price_requests": {"justification": {"index_change_pct": 14.0}, "pass_through": {"max_competitor_gap_pct": 20, "max_volume_loss_pct": 40}}})
    ev = evaluate_request("PR-003")[1]
    assert {r.then_decision for r in ev.lines} == {"pass_through"}  # 15% is justified now and passing it on is allowed
    policy.save_overrides({"price_requests": {"notice_period_days": 5}})
    assert evaluate_request("PR-003")[1].decision == "pass_through"


def test_min_counter_knob_turns_a_small_counter_into_a_delist():
    assert evaluate_request("PR-002")[1].decision == "accept_partial"
    policy.save_overrides({"price_requests": {"min_counter_pct": 6}})
    assert evaluate_request("PR-002")[1].decision == "delist"


# ---------- approval tiers ----------


def test_tier_boundaries_follow_the_matrix():
    assert pricereq.tier_for(0).role == "category_executive"
    assert pricereq.tier_for(5).role == "category_executive"  # "above 5" means strictly above
    assert pricereq.tier_for(5.1).role == "category_manager"
    assert pricereq.tier_for(10).role == "category_manager"
    assert pricereq.tier_for(10.1).role == "head_of_category"


def test_approval_tier_uses_the_outcome_and_the_decision_floor():
    ev = ev_for("E006", [("GW-06", 90, 99)])  # asked 10%, countered at 5% by absorbing
    assert ev.approval.asked_tier.role == "category_manager" and ev.approval.tier.role == "category_executive"
    big = ev_for("E006", [("GW-01", 190, 215)], sweeteners=[])  # 13.2% asked and countered: the counter is the ceiling
    assert big.approval.asked_tier.role == "head_of_category" and big.approval.tier.role == "category_executive"
    policy.save_overrides({"price_requests": {"justification": {"index_change_pct": 14.0}, "pass_through": {"max_competitor_gap_pct": 30, "max_volume_loss_pct": 60}}})
    wide = ev_for("E004", [("TW-01", 210, 235.2)])  # 12% justified, passed on -> head of category by size
    assert wide.lines[0].decision == "pass_through" and wide.approval.tier.role == "head_of_category"


def test_approval_matrix_is_validated_and_editable():
    with pytest.raises(Exception) as exc:
        policy.save_overrides({"price_requests": {"approval": {"matrix": [{"above_pct": 3, "approver": "x", "label": "x"}]}}})
    assert "start at 0" in str(exc.value) or "must start" in getattr(exc.value, "problem", str(exc.value))
    policy.save_overrides({"price_requests": {"approval": {"matrix": [{"above_pct": 0, "approver": "category_executive", "label": "CE"}, {"above_pct": 3, "approver": "category_manager", "label": "CM"}, {"above_pct": 10, "approver": "head_of_category", "label": "Head"}]}}})
    assert evaluate_request("PR-001")[1].approval.tier.role == "category_manager"  # 4% is now above 3


# ---------- the reply: engine numbers only ----------


def test_the_mock_reply_uses_only_engine_numbers():
    for rid in ("PR-001", "PR-002", "PR-003"):
        _a, ev = evaluate_request(rid)
        r = run(pa.reply_for(pa.get_request(rid), ev))
        assert r["source"] == "model" and r["struck"] == [], (rid, r["struck"])


def test_a_sentence_with_a_number_the_engine_did_not_state_is_struck():
    _a, ev = evaluate_request("PR-003")
    text = "We can accept 4.7% on NP-01.\nWe will also give you a 12.3% rebate on the next order.\nRegards."
    kept, struck = pricereq.strike_unsupported(text, ev)
    assert "4.7%" in kept and "12.3" not in kept and struck == ["We will also give you a 12.3% rebate on the next order."]
    assert "NP-01" in kept  # a SKU code is not a number


def test_a_changed_playbook_strikes_the_fixture_sentences_it_no_longer_supports():
    policy.save_overrides({"price_requests": {"pass_through": {"max_competitor_gap_pct": 7, "max_volume_loss_pct": 12}}})
    _a, ev = evaluate_request("PR-003")
    r = run(pa.reply_for(pa.get_request("PR-003"), ev))
    assert r["struck"] and "4.7" not in r["body"]  # the canned 4.7% is no longer an engine number


def test_the_template_reply_is_built_from_the_engine():
    _a, ev = evaluate_request("PR-002")
    t = pricereq.template_reply(ev, "Tailwind Play", "Vikram")
    _kept, struck = pricereq.strike_unsupported(t.body, ev)
    assert struck == [] and "₹219.24" in t.body and "chance of reaching it is 2.8%" in t.body


# ---------- the API ----------


def test_inbox_and_detail(client):
    inbox = client.get("/api/price-requests").json()["requests"]
    assert [r["id"] for r in inbox] == ["PR-001", "PR-002", "PR-003"] and inbox[0]["brand"] == "Groomwell" and inbox[0]["status"] == "pending"
    body = client.get("/api/price-requests/PR-002").json()
    assert body["evaluation"]["decision"] == "accept_partial" and body["deals"]["assessments"][0]["probability"] < 0.1
    assert body["reply"]["source"] == "model" and "Dear Vikram" in body["reply"]["body"]
    assert body["verification"]["rejected"] == 0 and body["verification"]["total"] >= 12
    assert body["email"].startswith("From:") and body["evaluation"]["approval"]["tier"]["role"] == "category_manager"
    assert body["mode"] == "mock" and body["effective_date"] == "2026-12-01"
    assert client.get("/api/price-requests/PR-003").json()["verification"]["self_corrected"] == 1


def test_unknown_request_and_bad_ids_are_typed_errors(client):
    for rid in ("PR-404", "PR-001x", "etc"):
        r = client.get(f"/api/price-requests/{rid}")
        assert r.status_code == 404 and r.json()["code"] == "price_request_not_found"
        typed(r.json())


def test_submitting_a_request_for_an_unknown_vendor_or_empty_email_is_typed(client):
    r = client.post("/api/price-requests", json={"vendor_id": "ZZ", "email": "hi"})
    assert r.status_code == 404 and r.json()["code"] == "unknown_ops_vendor"
    r = client.post("/api/price-requests", json={"vendor_id": "E001", "email": "  "})
    assert r.status_code == 422 and r.json()["code"] == "price_request_invalid"
    typed(r.json())


def test_a_submitted_request_joins_the_inbox_and_needs_a_model_reading(client):
    r = client.post("/api/price-requests", json={"vendor_id": "E001", "email": "Prices up 5% from 1 Dec", "price_list": "BK-01 760 798", "sender": "Anil <orders@barkley.example>"})
    assert r.status_code == 201 and r.json()["id"] == "PR-S001" and r.json()["submitted"] is True
    assert [x["id"] for x in client.get("/api/price-requests").json()["requests"]][-1] == "PR-S001"
    miss = client.get("/api/price-requests/PR-S001")  # mock mode has no recorded reading of a request nobody has seen
    assert miss.status_code == 500 and miss.json()["code"] == "fixture_missing"


def test_approval_waits_for_a_person_at_the_right_tier_and_sending_is_simulated(client):
    assert client.get("/api/price-requests/PR-002").json()["status"]["status"] == "pending"
    low = client.post("/api/price-requests/PR-002/approve", json={"role": "category_executive"})
    assert low.status_code == 403 and low.json()["code"] == "approval_tier_too_low" and "Category manager" in low.json()["problem"]
    typed(low.json())
    assert client.get("/api/price-requests").json()["requests"][1]["status"] == "pending"
    ok = client.post("/api/price-requests/PR-002/approve", json={"role": "head_of_category", "email_body": "Edited reply", "note": "ok"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert ok.json()["sent"]["simulated"] is True and ok.json()["sent"]["body"] == "Edited reply" and ok.json()["sent"]["to"].endswith("<sales@tailwindplay.example>")
    again = client.post("/api/price-requests/PR-002/approve", json={"role": "head_of_category"})
    assert again.status_code == 409 and again.json()["code"] == "price_request_decided"
    assert client.get("/api/price-requests").json()["requests"][1]["status"] == "approved"


def test_a_request_can_be_rejected_and_nothing_is_sent(client):
    r = client.post("/api/price-requests/PR-001/reject", json={"role": "category_executive", "note": "not now"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and "sent" not in r.json()
    assert client.post("/api/price-requests/PR-001/approve", json={"role": "category_manager"}).status_code == 409


def test_the_playbook_section_renders_and_the_module_is_registered(client):
    snap = client.get("/api/policy").json()
    hints = snap["schema_hints"]
    for path in ("price_requests.notice_period_days", "price_requests.elasticity.by_category", "price_requests.pass_through.max_competitor_gap_pct",
                 "price_requests.justification.tolerance_pp", "price_requests.approval.matrix"):
        assert path in hints and hints[path]["label"]
    impact = client.get("/api/impact").json()
    mod = next(m for m in impact["modules"] if m["key"] == "price_increase_evaluator")
    assert mod["status"] == "shipped" and mod["saved_pct"] == 2.3 and mod["tasks"][0]["task"] == "price_increase_requests"


def test_request_data_is_deterministic_and_covers_existing_vendors():
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    before = {p.name: p.read_bytes() for p in (root / "data" / "synthetic" / "price_requests").rglob("*") if p.is_file()}
    subprocess.run([sys.executable, str(root / "data" / "generate_price_requests.py")], check=True, capture_output=True)
    after = {p.name: p.read_bytes() for p in (root / "data" / "synthetic" / "price_requests").rglob("*") if p.is_file()}
    assert before == after
    idx = json.loads((root / "data" / "synthetic" / "price_requests" / "index.json").read_text())["requests"]
    assert [r["vendor_id"] for r in idx] == ["E006", "E004", "E003"]
