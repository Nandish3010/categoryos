"""Deal evaluator: the probability engine, valuation, decisions, counters, the verifier's recompute, quote checks,
the playbook knobs and the Negotiate integration (V002's contingent litter offer, V001's tiered rebate)."""

import asyncio
import math
from statistics import NormalDist

import pytest

from app import deals, policy
from app.agents import dealflow, negotiate
from app.agents.context import RunContext, Sequencer
from app.data_loader import load_application, load_transcript
from app.metrics import apply_levers, build_base
from app.schemas import Claim, DealCondition, DealTerm, DealTier, StageResult
from app.verify import verify_all, verify_claim

QUOTE_BASE = "For the litter I can do a base margin of 15 percent."
QUOTE_BONUS = "On top of that I will give you 20 percent marketing support on sales if you sell 2,000 units across the range within the first 90 days."
LITTER = ["MW-L01", "MW-L02", "MW-L03", "MW-L04", "MW-L05"]


def one_sku(monthly=100.0, price=100.0, cost=60.0, alloc=50, target=30.0, code="X1", category="treats"):
    return deals.SkuFact(code, category, monthly, price, cost, alloc, target)


def term(**over):
    base = {"id": "t2", "kind": "conditional", "term": "marketing_pct", "value": 20, "unit": "pct", "quote": "q", "turn": 1,
            "condition": DealCondition(metric="units", threshold=2000, window_days=90)}
    base.update(over)
    return DealTerm(**base)


def base_term(value=15.0, **over):
    return DealTerm(**{"id": "t1", "kind": "base", "term": "margin_pct", "value": value, "unit": "pct", "quote": "q", "turn": 1, **over})


def v002():
    lever = apply_levers(build_base("V002"))
    return lever, deals.Context(deals.sku_facts(lever), 21.0, 21.0, 500.0)


def v001():
    lever = apply_levers(build_base("V001"))
    return lever, deals.Context(deals.sku_facts(lever), 34.0, 45.0, 150.0)


def v002_offer(threshold=2000, window=90, base_value=15.0):
    base = base_term(base_value, scope=LITTER)
    bonus = term(base_of="t1", condition=DealCondition(metric="units", threshold=threshold, window_days=window))
    return base, bonus


# ---------- the probability engine ----------


def test_window_factor_follows_the_ramp_and_repeats_the_last_month():
    ramp = (0.5, 0.75, 0.9, 1.0)
    assert deals.window_factor(90, ramp) == pytest.approx(2.15)
    assert deals.window_factor(120, ramp) == pytest.approx(3.15)
    assert deals.window_factor(45, ramp) == pytest.approx(0.5 + 0.5 * 0.75)
    assert deals.window_factor(360, ramp) == pytest.approx(0.5 + 0.75 + 0.9 + 9)


@pytest.mark.parametrize("threshold", [150, 215, 300, 450])
def test_monte_carlo_matches_the_lognormal_closed_form(threshold):
    """One SKU: units over the window are lognormal with mean = monthly x ramp and sigma^2 = ln(1 + cv^2)."""
    sku = (one_sku(),)
    mean = 100 * 2.15
    sigma = math.sqrt(math.log(1 + 0.45**2))
    exact = 1 - NormalDist().cdf((math.log(threshold) - (math.log(mean) - sigma**2 / 2)) / sigma)
    got = deals.prob_at_least(deals.sim_for(sku, 90).values("units"), threshold)
    assert got == pytest.approx(exact, abs=0.012)


def test_simulation_is_deterministic_and_the_seed_matters():
    sku = (one_sku(),)
    a = deals.sim_for(sku, 90).values("units")
    deals._sim.cache_clear()
    deals.noise_for.cache_clear()
    b = deals.sim_for(sku, 90).values("units")
    assert a == b
    policy.save_overrides({"negotiation": {"forecast": {"seed": 7}}})
    assert deals.sim_for(sku, 90).values("units") != a


def test_same_sku_sees_the_same_noise_in_any_scope():
    both = deals.noise_for((one_sku(code="A"), one_sku(code="B")), 0.45, (), 0.5, 2000, 42)
    alone = deals.noise_for((one_sku(code="A"),), 0.45, (), 0.5, 2000, 42)
    assert both.factors[0] == alone.factors[0]


def test_correlation_widens_the_distribution_of_a_basket():
    basket = (one_sku(code="A"), one_sku(code="B"), one_sku(code="C"))
    spread = {}
    for rho in (0.0, 1.0):
        policy.save_overrides({"negotiation": {"forecast": {"sku_correlation": rho}}})
        s = deals.sim_for(basket, 90).values("units")
        spread[rho] = deals.quantile(s, 0.9) - deals.quantile(s, 0.1)
    assert spread[1.0] > spread[0.0] * 1.4


def test_threshold_for_inverts_prob_at_least():
    s = deals.sim_for((one_sku(),), 90).values("units")
    t = deals.threshold_for(s, 0.6)
    assert deals.prob_at_least(s, t) >= 0.6
    assert deals.prob_at_least(s, t + 5) < 0.6 + 0.005


def test_sell_through_is_capped_by_the_first_order():
    sim = deals.sim_for((one_sku(monthly=1000, alloc=50),), 90)  # demand far above the order: everything sells
    assert deals.quantile(sim.values("sell_through_pct"), 0.1) == pytest.approx(100.0)
    thin = deals.sim_for((one_sku(monthly=1, alloc=500, code="Z"),), 90)
    assert deals.quantile(thin.values("sell_through_pct"), 0.5) < 5


def test_playbook_cv_and_category_override_change_the_spread():
    sku = (one_sku(),)
    wide = deals.sim_for(sku, 90).values("units")
    policy.save_overrides({"negotiation": {"forecast": {"cv": 0.1}}})
    narrow = deals.sim_for(sku, 90).values("units")
    assert deals.quantile(narrow, 0.9) - deals.quantile(narrow, 0.1) < (deals.quantile(wide, 0.9) - deals.quantile(wide, 0.1)) / 3
    policy.save_overrides({"negotiation": {"forecast": {"cv": 0.45, "cv_by_category": {"treats": 0.1}}}})
    by_cat = deals.sim_for(sku, 90).values("units")
    assert deals.quantile(by_cat, 0.9) - deals.quantile(by_cat, 0.1) == pytest.approx(deals.quantile(narrow, 0.9) - deals.quantile(narrow, 0.1), rel=0.01)


# ---------- V002: the contingent litter offer ----------


def test_unrealistic_target_is_rejected_with_counters():
    _, ctx = v002()
    report = deals.assess([*v002_offer()], ctx)
    a = report.assessments[0]
    assert report.decision == "reject_structure" and a.decision == "reject_structure"
    assert a.probability < 0.001 and a.tiers[0].counted is False
    assert a.base_pts == 15 and a.required_pts == 22 and a.counted_pts == 15 and a.expected_pts == 15
    assert a.counted_bonus_pts == 0 and a.face_pts == 35 and a.shortfall_pts == -7
    d = a.distribution
    assert d.p10 < d.p50 < d.p90 < 2000 and d.window_days == 90
    kinds = [c.kind for c in a.counters]
    assert kinds[0] == "threshold" and "convert_to_base" in kinds
    thr = a.counters[0]
    assert thr.probability >= 0.6 and 150 < thr.threshold < d.p50 and thr.meets_requirement and thr.threshold % 10 == 0
    conv = next(c for c in a.counters if c.kind == "convert_to_base")
    assert conv.uplift_pts == 7 and conv.required_base_pts == 22 and conv.fair_conversion_pts == 0
    assert a.recommended_counter == 0 and "Counter:" in a.call


def test_a_reachable_target_is_accepted_and_counts_probability_times_bonus():
    _, ctx = v002()
    a = deals.assess([*v002_offer(threshold=200)], ctx).assessments[0]
    assert a.probability >= 0.6 and a.decision == "accept" and a.tiers[0].counted
    assert a.counted_bonus_pts == pytest.approx(a.probability * 20, abs=1e-3)
    assert a.counted_pts == pytest.approx(15 + a.probability * 20, abs=1e-3)
    assert a.guaranteed_pts == 15 and a.expected_pts == a.counted_pts and not a.counters


def test_min_probability_knob_flips_the_decision():
    _, ctx = v002()
    offer = v002_offer(threshold=200)
    p = deals.assess([*offer], ctx).assessments[0].probability
    assert deals.assess([*offer], ctx).assessments[0].decision == "accept"
    policy.save_overrides({"negotiation": {"contingent": {"min_probability": min(p + 0.05, 1.0)}}})
    assert deals.assess([*offer], ctx).assessments[0].decision == "reject_structure"


def test_guaranteed_only_value_basis_counts_no_conditional_bonus():
    _, ctx = v002()
    offer = v002_offer(threshold=100)
    assert deals.assess([*offer], ctx).assessments[0].decision == "accept"
    policy.save_overrides({"negotiation": {"contingent": {"value_basis": "guaranteed_only"}}})
    a = deals.assess([*offer], ctx).assessments[0]
    assert a.decision == "reject_structure" and a.counted_bonus_pts == 0 and a.counted_pts == 15 and a.expected_bonus_pts > 0
    assert [c.kind for c in a.counters] == ["convert_to_base"]  # no probabilistic counter is offered when nothing probabilistic counts


def test_ramp_and_cv_assumptions_move_the_probability():
    _, ctx = v002()
    offer = v002_offer(threshold=300)
    base_p = deals.assess([*offer], ctx).assessments[0].probability
    policy.save_overrides({"negotiation": {"forecast": {"ramp_by_month": [1.0]}}})
    assert deals.assess([*offer], ctx).assessments[0].probability > base_p + 0.1


def test_window_counter_lengthens_the_window_until_the_vendor_target_is_likely():
    _, ctx = v002()
    a = deals.assess([*v002_offer(threshold=700)], ctx).assessments[0]
    window = next(c for c in a.counters if c.kind == "window")
    assert window.window_days > 90 and window.probability >= 0.6 and window.threshold == 700


def test_no_viable_window_is_not_offered():
    _, ctx = v002()
    a = deals.assess([*v002_offer()], ctx).assessments[0]
    assert not any(c.kind == "window" for c in a.counters)  # 2,000 units is out of reach in any window up to a year


def test_base_without_a_stated_base_uses_the_margin_already_counted():
    _, ctx = v002()
    a = deals.assess([term(base_of=None, condition=DealCondition(metric="units", threshold=2000, window_days=90))], ctx).assessments[0]
    assert a.base_assumed and a.base_pts == 21


def test_unreadable_or_out_of_scope_conditions_are_not_assessable():
    _, ctx = v002()
    no_cond = deals.assess([term(condition=None)], ctx).assessments[0]
    assert no_cond.decision == "not_assessable"
    gone = deals.assess([term(condition=DealCondition(metric="units", threshold=10, window_days=30, scope=["NOPE"]))], ctx).assessments[0]
    assert gone.decision == "not_assessable"
    assert deals.assess([term()], deals.Context(())).assessments[0].decision == "not_assessable"


# ---------- V001: the tiered slab ----------


def tiered(**over):
    fields = {
        "id": "t1", "kind": "tiered", "term": "back_margin_pct", "value": 2, "base_of": None, "source": "application",
        "condition": DealCondition(metric="gmv_inr", threshold=500000, window_days=90),
        "tiers": [DealTier(threshold=500000, value=2), DealTier(threshold=1000000, value=4)],
    }
    return term(**{**fields, **over})


def test_tiered_rebate_is_accepted_and_each_tier_has_its_own_probability():
    _, ctx = v001()
    a = deals.assess([tiered()], ctx).assessments[0]
    t1, t2 = a.tiers
    assert a.decision == "accept" and t1.probability > 0.6 > t2.probability and t1.counted and not t2.counted
    assert t1.incremental_pts == 2 and t2.incremental_pts == 2 and t2.bonus_pts == 4
    assert a.expected_bonus_pts == pytest.approx(2 * t1.probability + 2 * t2.probability, abs=1e-3)
    assert a.counted_bonus_pts == pytest.approx(2 * t1.probability, abs=1e-3)  # tier 2 is under the bar
    assert a.counted_pts == pytest.approx(34 + 2 * t1.probability, abs=1e-3) and a.required_pts < 34


def test_tier_probabilities_are_monotone():
    _, ctx = v001()
    probs = [t.probability for t in deals.assess([tiered()], ctx).assessments[0].tiers]
    assert probs == sorted(probs, reverse=True)


def test_a_bonus_the_base_does_not_need_is_upside_only():
    _, ctx = v001()
    a = deals.assess([tiered(tiers=[DealTier(threshold=5_000_000, value=2)], condition=DealCondition(metric="gmv_inr", threshold=5_000_000, window_days=90))], ctx).assessments[0]
    assert a.decision == "accept" and a.counted_bonus_pts == 0 and "upside" in a.call


# ---------- valuation conversions and trades ----------


def test_points_conversions():
    skus = (one_sku(price=100, cost=60, alloc=50),)
    assert deals.cost_ratio(skus) == pytest.approx(0.6)
    assert deals.to_pts("margin_pct", 15, skus) == 15
    assert deals.to_pts("discount_pct", 5, skus) == pytest.approx(3.0)
    assert deals.to_pts("marketing_inr", 500, skus) == pytest.approx(500 / 5000 * 100)  # first-order GMV 50 x 100
    assert deals.to_pts("free_goods_pct", 10, skus) == pytest.approx(10 / 110 * 100 * 0.6)


def payment_trade(discount=2.0, days=15):
    return DealTerm(id="p1", kind="payment_for_discount", term="discount_pct", value=discount, unit="pct", days=days, quote="q", turn=1)


def test_payment_terms_trade_uses_the_cost_of_capital():
    _, ctx = v001()  # base payment 45 days
    a = deals.assess([payment_trade()], ctx).assessments[0]
    ratio = deals.cost_ratio(ctx.skus)
    expected = (2.0 - 14 * 30 / 365) * ratio
    assert a.net_pts == pytest.approx(expected, abs=1e-3) and a.decision == "accept"
    policy.save_overrides({"negotiation": {"cost_of_capital_pct_annual": 60}})
    flipped = deals.assess([payment_trade()], ctx).assessments[0]
    assert flipped.net_pts < 0 and flipped.decision == "reject_structure"


def test_moq_for_discount_charges_carrying_and_dead_stock():
    _, ctx = v002()
    offer = DealTerm(id="m1", kind="moq_for_discount", term="discount_pct", value=3.0, unit="pct", units=1500, quote="q", turn=1)
    small = deals.assess([offer.model_copy(update={"units": 500})], ctx).assessments[0]  # no extra stock: the whole discount
    big = deals.assess([offer], ctx).assessments[0]
    assert small.net_pts == pytest.approx(3.0 * deals.cost_ratio(ctx.skus), abs=0.05)
    assert big.net_pts < small.net_pts and big.decision == "reject_structure"
    policy.save_overrides({"negotiation": {"inventory_carrying_pct_monthly": 0, "contingent": {"dead_stock_writeoff_pct": 0}}})
    free = deals.assess([offer], ctx).assessments[0]
    assert free.net_pts == pytest.approx(3.0 * deals.cost_ratio(ctx.skus), abs=0.05) and free.decision == "accept"


def test_exclusivity_is_never_auto_accepted():
    _, ctx = v002()
    a = deals.assess([DealTerm(id="e1", kind="exclusivity", term="exclusivity_months", value=12, unit="months", scope=["MW-L01"], quote="q", turn=1)], ctx).assessments[0]
    assert a.decision == "needs_human" and "cat litter" in a.call and "a month" in a.call
    assert deals.assess([DealTerm(id="e1", kind="exclusivity", term="exclusivity_months", value=12, unit="months", quote="q", turn=1)], ctx).decision == "needs_human"


def test_free_goods_sale_or_return_and_price_protection():
    _, ctx = v002()
    free = deals.assess([DealTerm(id="f1", kind="free_goods", term="free_goods_pct", value=10, unit="pct", quote="q", turn=1)], ctx).assessments[0]
    assert free.decision == "accept" and free.net_pts == pytest.approx(10 / 110 * 100 * deals.cost_ratio(ctx.skus), abs=1e-3)
    sor = deals.assess([DealTerm(id="s1", kind="sell_or_return", term="returnable_pct", value=100, unit="pct", days=90, quote="q", turn=1)], ctx).assessments[0]
    assert sor.decision == "accept" and sor.net_pts > 0
    pp = deals.assess([DealTerm(id="p1", kind="price_protection", term="price_protection_days", value=180, unit="days", quote="q", turn=1)], ctx).assessments[0]
    assert pp.decision == "accept" and pp.counted_pts == 0


def test_conditional_free_goods_go_through_the_probability_path():
    _, ctx = v002()
    a = deals.assess([DealTerm(id="f1", kind="free_goods", term="free_goods_pct", value=10, unit="pct", condition=DealCondition(metric="units", threshold=5000, window_days=90), quote="q", turn=1)], ctx).assessments[0]
    assert a.probability is not None and a.probability < 0.001


def test_sell_through_condition_and_scope_counter():
    _, ctx = v002()
    cond = DealCondition(metric="sell_through_pct", threshold=95, window_days=90)
    a = deals.assess([term(condition=cond, base_of=None)], ctx).assessments[0]
    assert a.distribution.metric == "sell_through_pct" and 0 <= a.probability <= 1
    assert a.distribution.p10 <= a.distribution.p50 <= a.distribution.p90 <= 100


# ---------- claims and the verifier ----------


def claims_of(threshold=2000):
    lever, ctx = v002()
    base, bonus = v002_offer(threshold=threshold)
    bonus = bonus.model_copy(update={"quote": QUOTE_BONUS, "turn": 18})
    report = deals.assess([base, bonus], ctx)
    return lever, ctx, bonus, base, report.assessments[0]


def test_every_number_is_an_engine_claim_the_verifier_recomputes():
    lever, ctx, bonus, base, a = claims_of()
    claims = deals.claims_for("V002", lever, ctx, bonus, base, a)
    metrics = {(c.metric, c.source_ref.column) for c in claims}
    assert {("deal_probability", "tier:0"), ("deal_percentile", "p10"), ("deal_percentile", "p50"), ("deal_percentile", "p90"),
            ("deal_pts", "base"), ("deal_pts", "expected"), ("deal_pts", "counted"), ("deal_pts", "required"),
            ("deal_counter", "threshold:0"), ("deal_counter", "uplift:1")} <= metrics
    assert all(c.origin == "engine" for c in claims)
    summary = verify_all(claims)
    assert summary.rejected == 0 and summary.verified == len(claims), [c.reason for c in summary.claims if c.status != "verified"]


def test_a_tampered_probability_or_value_is_rejected():
    lever, ctx, bonus, base, a = claims_of()
    claims = deals.claims_for("V002", lever, ctx, bonus, base, a)
    prob = next(c for c in claims if c.metric == "deal_probability")
    assert verify_claim(prob.model_copy(update={"value": 0.07})).status == "rejected"
    counted = next(c for c in claims if c.source_ref.column == "counted")
    bad = verify_claim(counted.model_copy(update={"value": 22.0}))
    assert bad.status == "rejected" and "recomputed 15" in bad.reason
    thr = next(c for c in claims if c.metric == "deal_counter")
    assert verify_claim(thr.model_copy(update={"value": thr.value + 100})).status == "rejected"


def test_the_claim_carries_its_own_inputs_so_a_changed_playbook_is_caught():
    lever, ctx, bonus, base, a = claims_of(threshold=300)
    claims = deals.claims_for("V002", lever, ctx, bonus, base, a)
    prob = next(c for c in claims if c.metric == "deal_probability")
    assert verify_claim(prob).status == "verified"
    policy.save_overrides({"negotiation": {"forecast": {"cv": 0.9}}})
    assert verify_claim(prob).status == "rejected"


def test_unknown_deal_column_is_rejected_not_crashing():
    lever, ctx, bonus, base, a = claims_of()
    prob = next(c for c in deals.claims_for("V002", lever, ctx, bonus, base, a) if c.metric == "deal_probability")
    broken = prob.model_copy(update={"source_ref": prob.source_ref.model_copy(update={"column": "tier:9"})})
    assert verify_claim(broken).status == "rejected"


# ---------- extraction: quotes are checked verbatim ----------


def checked(terms, vendor="V002"):
    pairs = dealflow.term_claims(vendor, terms)
    summary = verify_all([c for _, c in pairs])
    return list(zip([t for t, _ in pairs], summary.claims))


def litter_terms():
    base = base_term(15, scope=LITTER, quote=QUOTE_BASE, turn=18)
    bonus = term(base_of="t1", quote=QUOTE_BONUS, turn=18)
    return base, bonus


def test_faithful_terms_verify_every_number():
    base, bonus = litter_terms()
    out = checked([base, bonus])
    assert len(out) == 4 and all(c.status == "verified" for _, c in out)
    assert {c.metric for _, c in out} == {"deal_term_value", "deal_term_threshold", "deal_term_window_days"}


def test_a_changed_quote_number_or_turn_is_rejected():
    _, bonus = litter_terms()
    assert {c.status for _, c in checked([bonus.model_copy(update={"quote": QUOTE_BONUS.replace("2,000", "1,000")})])} == {"rejected"} or \
        any(c.status == "rejected" for _, c in checked([bonus.model_copy(update={"quote": QUOTE_BONUS.replace("2,000", "1,000")})]))
    wrong_number = bonus.model_copy(update={"condition": DealCondition(metric="units", threshold=200, window_days=90)})
    out = {c.metric: c for _, c in checked([wrong_number])}
    assert out["deal_term_threshold"].status == "rejected" and "states" in out["deal_term_threshold"].reason
    assert out["deal_term_value"].status == "verified"
    wrong_turn = bonus.model_copy(update={"turn": 16})
    assert all(c.status == "rejected" for _, c in checked([wrong_turn]))
    assert all(c.status == "rejected" for _, c in checked([bonus.model_copy(update={"turn": 99})]))


def test_verified_terms_drop_a_term_with_any_rejected_number():
    base, bonus = litter_terms()
    bad = bonus.model_copy(update={"condition": DealCondition(metric="units", threshold=200, window_days=90)})
    keep, dropped = dealflow.verified_terms([base, bad], checked([base, bad]))
    assert [t.id for t in keep] == ["t1"] and dropped[0]["id"] == "t2" and "threshold" in dropped[0]["reasons"][0]


def test_application_quotes_are_checked_against_the_additional_term():
    text = load_application("V001")["proposed_terms"]["additional_terms"][0]
    quote = "we add 2 points of back margin on all SKUs once your GMV on our range exceeds ₹5,00,000 in a 90-day period"
    assert quote in text
    t = tiered(quote=quote, tiers=[DealTier(threshold=500000, value=2)], turn=1)
    out = checked([t], "V001")
    assert all(c.status == "verified" for _, c in out), [(c.metric, c.reason) for _, c in out]
    assert all(c.status == "rejected" and "no additional term" in c.reason for _, c in checked([t.model_copy(update={"turn": 2})], "V001"))
    assert any(c.status == "rejected" for _, c in checked([t.model_copy(update={"quote": quote.replace("2 points", "3 points")})], "V001"))


def test_additional_terms_are_not_a_free_for_all_for_other_metrics():
    _, bonus = litter_terms()
    claim = dealflow.term_claims("V002", [bonus])[0][1]
    app_claim = claim.model_copy(update={"source_ref": claim.source_ref.model_copy(update={"file": "vendors/V002/application.json"}), "metric": "commit_margin_pct"})
    assert verify_claim(app_claim).status != "verified"  # a commitment must come from the transcript, not application text


# ---------- the talk track: only the engine's numbers ----------


def test_sentences_with_numbers_the_engine_did_not_state_are_struck():
    _, ctx = v002()
    report = deals.assess([*v002_offer()], ctx)
    good = "The 15.0% base is 7.0 points short of the 22.0% we need."
    bad = "We expect 640 units in 90 days."
    kept, struck = deals.strike_unverified_numbers(f"{good} {bad} Please confirm.", report)
    assert good in kept and "Please confirm." in kept and struck == [bad]


def test_stated_figures_in_the_mock_talk_track_all_come_from_the_engine():
    result = run_negotiate("V002")
    talk = result.data["deals"]["talk"]
    assert talk["source"] == "model" and talk["struck"] == [] and "250 units" in talk["talk_track"]


# ---------- Negotiate integration ----------


def research_for(vendor_id):
    lever = apply_levers(build_base(vendor_id))
    return StageResult(
        stage="research", status="done",
        data={"lever": {"target_margin_pct_offset": 0, "moq": lever.summary.moq}, "rationale_per_sku": []},
        metrics_hash=lever.metrics_hash, narrative_hash=lever.metrics_hash,
    )


def run_negotiate(vendor_id):
    ctx = RunContext("run_t", vendor_id, "2026-10-27", Sequencer())
    return asyncio.run(negotiate.run(ctx, research_for(vendor_id)))


def test_v002_stays_negotiate_overall_and_the_new_structure_is_rejected_with_counters():
    assert apply_levers(build_base("V002")).summary.counts == {"list": 0, "negotiate": 4, "reject": 6, "needs_data": 0}
    result = run_negotiate("V002")
    d = result.data["deals"]
    assert d["decision"] == "reject_structure" and not d["rejected_terms"]
    (a,) = d["assessments"]
    assert a["decision"] == "reject_structure" and a["probability"] < 0.001
    assert a["counted_pts"] == 15 and a["required_pts"] == 22 and a["counters"][0]["kind"] == "threshold"
    assert a["source"] == "transcript" and a["turn"] == 18 and a["quote"] == QUOTE_BONUS
    assert d["base_terms"][0]["quote"] == QUOTE_BASE
    asks = result.data["counter_offer"]["asks"]
    assert any("Conditional offer" in x and "250 units" in x for x in asks)
    assert "conditional offer" in result.summary
    assert d["verification"]["rejected"] == 0 and d["verification"]["total"] == 14
    assert all(c.status == "verified" for c in result.claims)
    # the plain commitments are untouched by the conditional offer
    assert next(r for r in result.data["gap_table"] if r["term"] == "margin_pct")["offered"] == 21


def test_v001_tiered_rebate_is_accepted_as_likely():
    result = run_negotiate("V001")
    assert result.summary == "No negotiation needed" and result.data["gap_table"] == []
    d = result.data["deals"]
    (a,) = d["assessments"]
    assert d["decision"] == "accept" and a["decision"] == "accept" and a["source"] == "application"
    assert a["tiers"][0]["probability"] > 0.6 > a["tiers"][1]["probability"]
    assert d["talk"] is None and all(c.status == "verified" for c in result.claims)


def test_vendors_without_conditional_offers_have_no_deal_section():
    for vid in ("V003", "V004"):
        assert not dealflow.has_source(vid)
    assert "deals" not in run_negotiate("V003").data


def test_a_model_that_misquotes_a_term_gets_it_dropped_not_valued(monkeypatch):
    from app import llm

    real = llm.run_tools

    async def lying(*args, **kwargs):
        res = await real(*args, **kwargs)
        for t in getattr(res.parsed, "terms", []):
            if t.id == "t2":
                t.condition.threshold = 200  # the vendor said 2,000
        return res

    monkeypatch.setattr(llm, "run_tools", lying)
    d = run_negotiate("V002").data["deals"]
    assert d["assessments"] == [] and d["rejected_terms"][0]["id"] == "t2"
    assert "threshold" in d["rejected_terms"][0]["reasons"][0]


def test_a_misquoted_deal_number_is_sent_back_to_the_agent_and_corrected(monkeypatch):
    from app import llm
    from app.schemas import ClaimFix, FixFinal

    real_tools, real_call = llm.run_tools, llm.call

    async def lying(*args, **kwargs):
        res = await real_tools(*args, **kwargs)
        for t in getattr(res.parsed, "terms", []):
            if t.id == "t2":
                t.condition.threshold = 200
        return res

    async def fixer(stage, messages, *, task, **kwargs):
        if task == "deals_V002__fix1":
            fix = FixFinal(fixes=[ClaimFix(claim_id="V002:dealterm:t2:threshold", value=2000)])
            return llm.LlmResult(fix.model_dump_json(), fix, "muse-spark-1.3", "meta", "mock", 0, 0, 0.0, 1.0)
        return await real_call(stage, messages, task=task, **kwargs)

    monkeypatch.setattr(llm, "run_tools", lying)
    monkeypatch.setattr(llm, "call", fixer)
    result = run_negotiate("V002")
    d = result.data["deals"]
    assert d["rejected_terms"] == [] and d["assessments"][0]["decision"] == "reject_structure"
    fixed = next(c for c in result.claims if c.id == "V002:dealterm:t2:threshold")
    assert fixed.status == "verified" and [a.status for a in fixed.attempts] == ["rejected", "verified"]


def test_missing_extraction_fixture_degrades_instead_of_blocking(monkeypatch):
    from app import llm
    from app.errors import FixtureMissing

    real = llm.run_tools

    async def boom(stage, task, *args, **kwargs):
        if task.startswith("deals_"):
            raise FixtureMissing("no fixture")
        return await real(stage, task, *args, **kwargs)

    monkeypatch.setattr(llm, "run_tools", boom)
    result = run_negotiate("V002")
    assert "deals" not in result.data and result.status == "done"


def test_a_playbook_change_changes_the_decision_end_to_end():
    policy.save_overrides({"negotiation": {"contingent": {"min_probability": 0.2}}})
    result = run_negotiate("V002")
    a = result.data["deals"]["assessments"][0]
    assert a["decision"] == "reject_structure"  # 2,000 units is still unreachable
    assert a["counters"][0]["threshold"] > 250  # but a 20% bar allows a bolder counter


# ---------- data and playbook ----------


def test_the_v002_transcript_carries_the_contingent_exchange():
    turns = load_transcript("V002")
    assert len(turns) == 22 and [t["turn"] for t in turns] == list(range(1, 23))
    assert QUOTE_BASE in turns[17]["text"] and QUOTE_BONUS in turns[17]["text"] and turns[17]["speaker"] == "vendor"
    assert turns[20]["text"].startswith("Understood, we will evaluate that structure separately. To recap:")


def test_playbook_exposes_every_assumption_with_schema_hints():
    hints = policy.schema_hints()
    for path in (
        "negotiation.forecast.ramp_by_month", "negotiation.forecast.cv", "negotiation.forecast.cv_by_category",
        "negotiation.forecast.mc_draws", "negotiation.forecast.seed", "negotiation.contingent.min_probability",
        "negotiation.contingent.value_basis", "negotiation.cost_of_capital_pct_annual", "negotiation.inventory_carrying_pct_monthly",
        "verifier.tolerances.pts",
    ):
        assert path in hints and hints[path]["used_in"] == (["negotiate"] if path != "verifier.tolerances.pts" else hints[path]["used_in"])
    assert hints["negotiation.contingent.value_basis"]["options"] == ["risk_adjusted", "guaranteed_only"]
    assert policy.get().negotiation.contingent.min_probability == 0.6 and policy.get().negotiation.forecast.ramp_by_month == [0.5, 0.75, 0.9, 1.0]


def test_claims_are_plain_pydantic_claims():
    lever, ctx, bonus, base, a = claims_of()
    assert all(isinstance(c, Claim) for c in deals.claims_for("V002", lever, ctx, bonus, base, a))
