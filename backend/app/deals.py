"""Deal evaluator: values vendor offers that are contingent on something we may not achieve.

A vendor says "15% base margin, plus 20% marketing support if you sell 2,000 units in 90 days". The model (Negotiate)
only READS that structure out of the call or application into ``DealTerm``s (quotes verified downstream). Everything
below is deterministic Python:

* demand: per SKU, monthly units from the Decide engine x the new-listing ramp, lognormal noise with the playbook's cv,
  a shared (correlated) factor, a FIXED-seed Monte Carlo -> P(condition met) and P10/P50/P90 of the metric;
* value: every term in effective margin points. expected = base + sum(p_i x bonus_i). A conditional bonus whose
  probability is under ``negotiation.contingent.min_probability`` counts as 0;
* decision: accept when the counted value meets what we require, else reject_structure with concrete counters
  (a threshold that is likely enough, converting the bonus into guaranteed base, a window or scope that is);
* trades (pay earlier for a discount, bigger MOQ for a discount, free goods, sale-or-return) are priced with the
  playbook's cost of capital, carrying cost and dead-stock assumptions; exclusivity is only flagged for a human.

Every number the evaluator states is also emitted as an engine Claim (``claims_for``) that the verifier recomputes
through ``recompute``. Never imports llm; the verifier imports this module."""

import bisect
import json
import math
import random
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import policy
from app.data_loader import load_catalog
from app.errors import MissingInput
from app.metrics import apply_levers, build_base
from app.schemas import Claim, DealTerm, DealTier, LeverResponse, SourceRef
from app.util import fmt_inr

Decision = Literal["accept", "reject_structure", "needs_human", "not_assessable"]
CONDITIONAL_KINDS = ("conditional", "tiered", "rebate")
# term -> how its value becomes margin points
POINTS_TERMS = ("margin_pct", "back_margin_pct", "marketing_pct")
METRIC_LABEL = {"units": "units", "gmv_inr": "GMV", "sell_through_pct": "sell-through"}
# claim unit and scale (claim.value = natural value x scale) for a condition metric
METRIC_CLAIM = {"units": ("units", 1.0), "gmv_inr": ("inr", 1.0), "sell_through_pct": ("pct", 0.01)}
HIST_BINS = 32


# ---------- facts about the SKUs being valued ----------


@dataclass(frozen=True)
class SkuFact:
    code: str
    category: str
    monthly_units: float
    price: float
    cost: float
    alloc: int
    target_pct: float  # percent


def sku_facts(lever: LeverResponse, codes: set[str] | None = None) -> tuple[SkuFact, ...]:
    """Shortlisted SKUs (list + negotiate) at the lever, or just ``codes`` (a human override can widen/narrow it)."""
    wanted = codes if codes is not None else {s.code for s in lever.skus if s.verdict in {"list", "negotiate"}}
    return tuple(
        SkuFact(
            s.code,
            s.category,
            float(s.est_monthly_units),
            float(s.selling_price or 0.0),
            float(s.landed_cost if s.landed_cost is not None else (s.cost or 0.0)),
            int(s.alloc_units),
            float(s.target_pct) * 100,
        )
        for s in sorted(lever.skus, key=lambda x: x.code)
        if s.code in wanted
    )


def pick(skus: tuple[SkuFact, ...], scope: list[str]) -> tuple[SkuFact, ...]:
    """SKUs a term applies to: ``scope`` codes (those on our shortlist), or every shortlisted SKU when empty."""
    if not scope:
        return skus
    wanted = {c.strip() for c in scope}
    return tuple(s for s in skus if s.code in wanted)


@dataclass(frozen=True)
class Context:
    skus: tuple[SkuFact, ...]
    base_margin_pct: float | None = None  # margin we are already counting for this vendor (committed or applied)
    base_payment_days: float | None = None
    base_moq: float | None = None
    ramp: tuple[float, ...] | None = None  # demand ramp override: (1.0,) values an EXISTING listing at steady state, not a new one


def first_order_gmv(skus: tuple[SkuFact, ...]) -> float:
    gmv = sum(s.alloc * s.price for s in skus)
    return gmv if gmv > 0 else sum(s.monthly_units * s.price for s in skus)


def cost_ratio(skus: tuple[SkuFact, ...]) -> float:
    """Landed cost as a share of selling price: a 1% invoice discount lifts retail margin by this many points."""
    gmv = sum(s.alloc * s.price for s in skus)
    if gmv > 0:
        return sum(s.alloc * s.cost for s in skus) / gmv
    gmv = sum(s.monthly_units * s.price for s in skus)
    return sum(s.monthly_units * s.cost for s in skus) / gmv if gmv > 0 else 0.0


def required_pts(skus: tuple[SkuFact, ...]) -> float:
    """What we require: the target margin of the SKUs involved, weighted by first-order units (else forecast units)."""
    weights = [s.alloc for s in skus]
    if sum(weights) <= 0:
        weights = [s.monthly_units for s in skus]
    total = sum(weights)
    if total <= 0:
        return sum(s.target_pct for s in skus) / len(skus) if skus else 0.0
    return sum(w * s.target_pct for w, s in zip(weights, skus)) / total


# ---------- demand: Monte Carlo ----------


def window_factor(window_days: float, ramp: tuple[float, ...]) -> float:
    """Months of steady-state demand a new listing delivers in ``window_days`` (ramp[i] is month i+1, the last repeats)."""
    full, rem = divmod(float(window_days), 30.0)
    total = sum(ramp[min(i, len(ramp) - 1)] for i in range(int(full)))
    if rem:
        total += rem / 30.0 * ramp[min(int(full), len(ramp) - 1)]
    return total


@dataclass(frozen=True)
class Params:
    """Everything that fixes a simulation besides the SKUs and the window (the playbook's forecast section)."""

    ramp: tuple[float, ...]
    cv: float
    cv_by_category: tuple[tuple[str, float], ...]
    correlation: float
    draws: int
    seed: int


def params() -> Params:
    f = policy.get().negotiation.forecast
    return Params(tuple(f.ramp_by_month), float(f.cv), tuple(sorted(f.cv_by_category.items())), float(f.sku_correlation), int(f.mc_draws), int(f.seed))


@lru_cache(maxsize=256)
def _normals(seed: int, key: str, draws: int) -> tuple[float, ...]:
    rng = random.Random(f"{seed}:{key}")
    return tuple(rng.gauss(0, 1) for _ in range(draws))


@dataclass(frozen=True)
class Noise:
    """Demand noise per draw and SKU with mean 1: exp(sigma z - sigma^2/2), z = sqrt(rho) z_common + sqrt(1-rho) z_own.
    Streams are seeded per SKU code and for the shared factor, so a SKU sees the same draws in any scope. The window only
    scales demand (months of ramped demand), so units and GMV for any window are this noise times a constant."""

    factors: tuple[tuple[float, ...], ...]  # [sku][draw]
    units0: tuple[float, ...]  # sorted draws of sum(monthly_i x f_i)
    gmv0: tuple[float, ...]  # sorted draws of sum(monthly_i x price_i x f_i)


@lru_cache(maxsize=128)
def noise_for(skus: tuple[SkuFact, ...], cv: float, cv_by_category: tuple[tuple[str, float], ...], correlation: float, draws: int, seed: int) -> Noise:
    overrides = dict(cv_by_category)
    zc = _normals(seed, "common", draws)
    a, b = math.sqrt(correlation), math.sqrt(1 - correlation)
    factors = []
    for s in skus:
        sig = math.sqrt(math.log(1 + overrides.get(s.category, cv) ** 2))
        own = _normals(seed, s.code, draws)
        factors.append(tuple(math.exp(sig * (a * c + b * o) - sig * sig / 2) for c, o in zip(zc, own)))
    units0 = [0.0] * draws
    gmv0 = [0.0] * draws
    for s, f in zip(skus, factors):
        for d, x in enumerate(f):
            units0[d] += s.monthly_units * x
            gmv0[d] += s.monthly_units * s.price * x
    return Noise(tuple(factors), tuple(sorted(units0)), tuple(sorted(gmv0)))


class Sim:
    """The simulated distribution of what we sell in one window, for a set of SKUs."""

    def __init__(self, skus: tuple[SkuFact, ...], window_days: float, p: Params) -> None:
        self.skus, self.window_days, self.p = skus, float(window_days), p
        self.months = window_factor(window_days, p.ramp)
        self.noise = noise_for(skus, p.cv, p.cv_by_category, p.correlation, p.draws, p.seed)
        self._cache: dict[str, Any] = {}

    def values(self, metric: str) -> tuple[float, ...]:
        """Sorted draws of ``units``, ``gmv_inr`` or ``sell_through_pct`` (0-100)."""
        if metric not in self._cache:
            if metric == "units":
                self._cache[metric] = tuple(x * self.months for x in self.noise.units0)
            elif metric == "gmv_inr":
                self._cache[metric] = tuple(x * self.months for x in self.noise.gmv0)
            elif metric == "sell_through_pct":
                self._cache[metric] = self._sell_through()
            else:
                raise ValueError(f"unknown metric {metric!r}")
        return self._cache[metric]

    def _sell_through(self) -> tuple[float, ...]:
        alloc = float(sum(s.alloc for s in self.skus))
        if alloc <= 0:
            return tuple(0.0 for _ in range(self.p.draws))
        sold = [0.0] * self.p.draws
        for s, f in zip(self.skus, self.noise.factors):
            m = s.monthly_units * self.months
            for d, x in enumerate(f):
                sold[d] += min(m * x, s.alloc)
        return tuple(sorted(100.0 * x / alloc for x in sold))

    def unsold(self) -> tuple[float, float]:
        """(mean unsold units, mean cost of unsold stock) of the first order at the end of the window."""
        if "unsold" not in self._cache:
            units = cost = 0.0
            for s, f in zip(self.skus, self.noise.factors):
                m = s.monthly_units * self.months
                left = sum(max(s.alloc - m * x, 0.0) for x in f) / self.p.draws
                units += left
                cost += left * s.cost
            self._cache["unsold"] = (units, cost)
        return self._cache["unsold"]


@lru_cache(maxsize=512)
def _sim(skus: tuple[SkuFact, ...], window_days: float, p: Params) -> Sim:
    return Sim(skus, window_days, p)


def sim_for(skus: tuple[SkuFact, ...], window_days: float, ramp: tuple[float, ...] | None = None) -> Sim:
    p = params()
    return _sim(skus, float(window_days), p if ramp is None else replace(p, ramp=tuple(ramp)))


def prob_at_least(samples: tuple[float, ...], threshold: float) -> float:
    """P(metric >= threshold) from the simulated draws."""
    if not samples:
        return 0.0
    return (len(samples) - bisect.bisect_left(samples, threshold)) / len(samples)


def quantile(samples: tuple[float, ...], q: float) -> float:
    return samples[min(len(samples) - 1, max(0, round(q * (len(samples) - 1))))]


def threshold_for(samples: tuple[float, ...], probability: float) -> float:
    """The largest threshold with P(metric >= threshold) >= probability."""
    k = min(len(samples) - 1, max(0, math.floor(len(samples) * (1 - probability))))
    return samples[k]


def round_down(metric: str, value: float) -> float:
    c = policy.get().negotiation.contingent
    step = {"units": c.threshold_round_units, "gmv_inr": c.threshold_round_inr, "sell_through_pct": c.threshold_round_pct}[metric]
    return math.floor(value / step + 1e-9) * step


# ---------- output models ----------


class TierProb(BaseModel):
    threshold: float
    bonus_pts: float  # total bonus once this tier is reached
    incremental_pts: float
    probability: float
    counted: bool


class Distribution(BaseModel):
    metric: str
    window_days: int
    mean: float
    p10: float
    p50: float
    p90: float
    threshold: float
    bins: list[float]  # bin edges (HIST_BINS + 1)
    density: list[float]  # share of draws per bin


class Counter(BaseModel):
    kind: Literal["threshold", "convert_to_base", "window", "scope"]
    text: str
    threshold: float | None = None
    window_days: float | None = None
    scope: list[str] = Field(default_factory=list)
    probability: float | None = None
    required_base_pts: float | None = None
    uplift_pts: float | None = None
    fair_conversion_pts: float | None = None
    counted_pts_after: float
    meets_requirement: bool


class DealAssessment(BaseModel):
    term_id: str
    kind: str
    term: str
    label: str
    source: str
    turn: int
    quote: str
    decision: Decision
    call: str
    reasoning: list[str] = Field(default_factory=list)
    base_pts: float = 0.0
    face_pts: float = 0.0  # base + the whole bonus if every condition were met
    expected_bonus_pts: float = 0.0
    counted_bonus_pts: float = 0.0
    expected_pts: float = 0.0  # base + expected bonus
    guaranteed_pts: float = 0.0  # base only
    counted_pts: float = 0.0  # what the decision rests on
    required_pts: float = 0.0
    shortfall_pts: float = 0.0  # counted - required (negative: short)
    probability: float | None = None  # of the first (lowest) tier
    tiers: list[TierProb] = Field(default_factory=list)
    distribution: Distribution | None = None
    counters: list[Counter] = Field(default_factory=list)
    recommended_counter: int | None = None
    net_pts: float | None = None  # trades: value after costs
    base_term_id: str | None = None
    base_assumed: bool = False


class DealReport(BaseModel):
    assessments: list[DealAssessment] = Field(default_factory=list)
    rejected_terms: list[dict[str, Any]] = Field(default_factory=list)
    decision: str = "none"
    headline: str = ""
    assumptions: dict[str, Any] = Field(default_factory=dict)


# ---------- formatting ----------


def fmt_prob(p: float) -> str:
    return "<0.1%" if p < 0.001 else f"{p * 100:.1f}%"


def fmt_pts(x: float) -> str:
    return f"{x:.1f}"


def fmt_metric(metric: str, value: float) -> str:
    if metric == "gmv_inr":
        return fmt_inr(value)
    if metric == "sell_through_pct":
        return f"{value:g}%"
    return f"{value:,.0f} units"


def _amount(term: DealTerm, value: float) -> str:
    unit = {"pct": "%", "inr": "", "units": " units", "days": " days", "months": " months"}[term.unit]
    return fmt_inr(value) if term.unit == "inr" else f"{value:g}{unit}"


NAMES = {
    "margin_pct": "margin",
    "back_margin_pct": "back margin",
    "discount_pct": "discount",
    "marketing_pct": "marketing support",
    "marketing_inr": "marketing support",
    "free_goods_pct": "free goods",
    "returnable_pct": "sale-or-return",
    "exclusivity_months": "exclusivity",
    "price_protection_days": "price protection",
}


def describe(term: DealTerm, base: DealTerm | None) -> str:
    """One line a buyer would say: '20% marketing support if 2,000 units in 90 days (on a 15% base)'."""
    text = f"{_amount(term, term.value)} {NAMES[term.term]}"
    c = term.condition
    if term.tiers and c:
        slabs = ", ".join(f"{_amount(term, t.value)} above {fmt_metric(c.metric, t.threshold)}" for t in sorted(term.tiers, key=lambda t: t.threshold))
        text = f"{NAMES[term.term]} slabs: {slabs} in {c.window_days} days"
    elif c:
        text += f" if {fmt_metric(c.metric, c.threshold)} in {c.window_days} days"
    elif term.kind == "payment_for_discount" and term.days is not None:
        text += f" for paying within {term.days:g} days"
    elif term.kind == "moq_for_discount" and term.units is not None:
        text += f" for a first order of {term.units:,.0f} units"
    elif term.kind == "sell_or_return" and term.days is not None:
        text = f"{term.value:g}% of unsold stock returnable after {term.days:g} days"
    elif term.kind == "exclusivity":
        text = f"{term.value:g} months of exclusivity"
    elif term.kind == "price_protection":
        text = f"price protection for {term.value:g} days"
    if base is not None:
        text += f" (on a {_amount(base, base.value)} {NAMES[base.term]} base)"
    return text


# ---------- valuation ----------


def to_pts(term_name: str, value: float, skus: tuple[SkuFact, ...]) -> float:
    """A term's value as margin points on retail."""
    if term_name in POINTS_TERMS:
        return value
    if term_name == "discount_pct":
        return value * cost_ratio(skus)
    if term_name == "free_goods_pct":
        return value / (100 + value) * 100 * cost_ratio(skus)
    if term_name == "marketing_inr":
        basis = first_order_gmv(skus)
        return value / basis * 100 if basis > 0 else 0.0
    return 0.0


def _distribution(sim: Sim, metric: str, window_days: int, threshold: float) -> Distribution:
    s = sim.values(metric)
    lo, hi = quantile(s, 0.005), quantile(s, 0.995)
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / HIST_BINS
    counts = [0] * HIST_BINS
    for v in s:
        if lo <= v < hi:
            counts[min(int((v - lo) / width), HIST_BINS - 1)] += 1
    n = len(s)
    return Distribution(
        metric=metric,
        window_days=int(window_days),
        mean=round(sum(s) / n, 4),
        p10=round(quantile(s, 0.1), 4),
        p50=round(quantile(s, 0.5), 4),
        p90=round(quantile(s, 0.9), 4),
        threshold=float(threshold),
        bins=[round(lo + i * width, 4) for i in range(HIST_BINS + 1)],
        density=[round(c / n, 5) for c in counts],
    )


def _counted(levels: list[tuple[float, float, float]], min_p: float, basis: str) -> float:
    """Sum of incremental x probability over the levels that are likely enough. levels: (threshold, incr, p)."""
    if basis == "guaranteed_only":
        return 0.0
    return sum(incr * p for _, incr, p in levels if p >= min_p)


def _assess_conditional(term: DealTerm, base: DealTerm | None, ctx: Context, a: DealAssessment) -> DealAssessment:
    pol = policy.get().negotiation.contingent
    cond = term.condition
    levels_in = sorted(term.tiers, key=lambda t: t.threshold) if term.tiers else []
    if cond is not None and not term.tiers:
        levels_in = [DealTier(threshold=cond.threshold, value=term.value)]
    if cond is None or not levels_in:
        return a.model_copy(update={"decision": "not_assessable", "call": "The condition could not be read, so the offer is not valued. Ask the vendor to state it.", "reasoning": ["No metric, threshold and window were extracted for this bonus."]})
    cond_skus = pick(ctx.skus, cond.scope)
    if not cond_skus:
        return a.model_copy(update={"decision": "not_assessable", "call": "None of the SKUs in the condition is on our shortlist, so the chance of hitting it cannot be estimated.", "reasoning": [f"Condition scope {cond.scope} has no shortlisted SKU."]})
    val_skus = pick(ctx.skus, base.scope if base is not None else term.scope) or ctx.skus
    sim = sim_for(cond_skus, cond.window_days, ctx.ramp)
    samples = sim.values(cond.metric)
    pts = [to_pts(term.term, t.value, val_skus) for t in levels_in]
    levels = []  # (threshold, incremental pts, probability)
    prev = 0.0
    for t, p_ in zip(levels_in, pts):
        levels.append((t.threshold, p_ - prev, prob_at_least(samples, t.threshold)))
        prev = p_
    expected_bonus = sum(incr * p for _, incr, p in levels)
    counted_bonus = _counted(levels, pol.min_probability, pol.value_basis)
    if base is not None and base.term in (*POINTS_TERMS, "discount_pct"):
        base_pts = to_pts(base.term, base.value, val_skus)
        assumed = False
    else:
        base_pts = float(ctx.base_margin_pct or 0.0)
        assumed = True
    required = required_pts(val_skus)
    counted_total = base_pts + counted_bonus
    ok = counted_total + 1e-9 >= required
    tiers = [
        TierProb(threshold=th, bonus_pts=round(p_, 4), incremental_pts=round(incr, 4), probability=round(p, 4), counted=pol.value_basis == "risk_adjusted" and p >= pol.min_probability)
        for (th, incr, p), p_ in zip(levels, pts)
    ]
    first_p = levels[0][2]
    label = describe(term, base)
    reasoning = [
        (
            f"Demand over {cond.window_days} days (ramped new listing, {fmt_pts(policy.get().negotiation.forecast.cv * 100)}% forecast uncertainty): "
            f"P10 {fmt_metric(cond.metric, quantile(samples, 0.1))}, P50 {fmt_metric(cond.metric, quantile(samples, 0.5))}, P90 {fmt_metric(cond.metric, quantile(samples, 0.9))}."
        ),
    ]
    for tp, (th, _, p) in zip(tiers, levels):
        reasoning.append(f"P({fmt_metric(cond.metric, th)} in {cond.window_days} days) = {fmt_prob(p)}; " + ("counts." if tp.counted else f"under the {pol.min_probability * 100:g}% bar, counts as 0."))
    if assumed:
        reasoning.append(f"No base margin was stated with this bonus, so the {fmt_pts(base_pts)}% margin already counted for this vendor is the base.")
    if pol.value_basis == "guaranteed_only":
        reasoning.append("Playbook value basis is guaranteed_only: conditional bonuses count as 0.")
    reasoning.append(f"Counted {fmt_pts(base_pts)} base + {fmt_pts(counted_bonus)} bonus = {fmt_pts(counted_total)} points against {fmt_pts(required)} required.")
    dist = _distribution(sim, cond.metric, cond.window_days, levels[0][0])
    out = a.model_copy(
        update={
            "label": label,
            "base_pts": round(base_pts, 4),
            "face_pts": round(base_pts + pts[-1], 4),
            "expected_bonus_pts": round(expected_bonus, 4),
            "counted_bonus_pts": round(counted_bonus, 4),
            "expected_pts": round(base_pts + expected_bonus, 4),
            "guaranteed_pts": round(base_pts, 4),
            "counted_pts": round(counted_total, 4),
            "required_pts": round(required, 4),
            "shortfall_pts": round(counted_total - required, 4),
            "probability": round(first_p, 4),
            "tiers": tiers,
            "distribution": dist,
            "base_term_id": base.id if base is not None else None,
            "base_assumed": assumed,
            "reasoning": reasoning,
        }
    )
    if ok:
        why = "" if counted_bonus > 0 else " The base alone meets what we require, so treat the bonus as upside we do not count."
        return out.model_copy(update={"decision": "accept", "call": f"Accept: counted {fmt_pts(counted_total)}% against {fmt_pts(required)}% required (P of the first target {fmt_prob(first_p)}).{why}"})
    counters = _counters(term, base, ctx, out, levels, levels_in, cond_skus, val_skus)
    rec = next((i for i, c in enumerate(counters) if c.meets_requirement), None)
    call = (
        f"Reject this structure and counter. The chance of {fmt_metric(cond.metric, levels[0][0])} in {cond.window_days} days is {fmt_prob(first_p)}, "
        f"so the bonus counts as {fmt_pts(counted_bonus)} points and the offer is worth {fmt_pts(counted_total)}% against {fmt_pts(required)}% required."
    )
    if rec is not None:
        call += f" Counter: {counters[rec].text}"
    return out.model_copy(update={"decision": "reject_structure", "call": call, "counters": counters, "recommended_counter": rec})


def _counters(
    term: DealTerm, base: DealTerm | None, ctx: Context, a: DealAssessment, levels: list[tuple[float, float, float]],
    levels_in: list[Any], cond_skus: tuple[SkuFact, ...], val_skus: tuple[SkuFact, ...],
) -> list[Counter]:
    pol = policy.get().negotiation.contingent
    cond = term.condition
    assert cond is not None
    metric, min_p = cond.metric, pol.min_probability
    required, base_pts = a.required_pts, a.base_pts
    samples = sim_for(cond_skus, cond.window_days, ctx.ramp).values(metric)
    out: list[Counter] = []

    def after(replace: int | None, p_new: float) -> float:
        lv = [(th, incr, p_new if i == replace else p) for i, (th, incr, p) in enumerate(levels)]
        return base_pts + _counted(lv, min_p, "risk_adjusted")

    if pol.value_basis == "risk_adjusted":
        # (a) a threshold the simulated distribution says we reach often enough, for each tier that is too ambitious
        for i, (th, _, p) in enumerate(levels):
            if p >= min_p:
                continue
            new = round_down(metric, threshold_for(samples, min_p))
            if new <= 0 or new >= th:
                continue
            p_new = prob_at_least(samples, new)
            if p_new < min_p:
                continue
            counted = after(i, p_new)
            tier = f"tier {i + 1} " if len(levels) > 1 else ""
            out.append(
                Counter(
                    kind="threshold",
                    threshold=new,
                    probability=round(p_new, 4),
                    counted_pts_after=round(counted, 4),
                    meets_requirement=counted + 1e-9 >= required,
                    text=f"set the {tier}target at {fmt_metric(metric, new)} in {cond.window_days} days (P = {fmt_prob(p_new)}); counted value becomes {fmt_pts(counted)}% against {fmt_pts(required)}% required.",
                )
            )
        # (c) a window long enough to make the vendor's own threshold likely
        for i, (th, _, p) in enumerate(levels):
            if p >= min_p:
                continue
            for w in sorted(set(pol.counter_window_days)):
                if w == cond.window_days:
                    continue
                p_w = prob_at_least(sim_for(cond_skus, w, ctx.ramp).values(metric), th)
                if p_w >= min_p:
                    counted = after(i, p_w)
                    out.append(
                        Counter(
                            kind="window",
                            window_days=w,
                            threshold=th,
                            probability=round(p_w, 4),
                            counted_pts_after=round(counted, 4),
                            meets_requirement=counted + 1e-9 >= required,
                            text=f"keep the {fmt_metric(metric, th)} target but allow {w:g} days (P = {fmt_prob(p_w)}); counted value becomes {fmt_pts(counted)}% against {fmt_pts(required)}% required.",
                        )
                    )
                    break
            break
        # (d) a narrower scope helps only for ratio conditions such as sell-through
        if metric == "sell_through_pct" and len(cond_skus) > 1:
            ranked = sorted(cond_skus, key=lambda s: -(s.monthly_units / s.alloc if s.alloc else 0.0))
            th = levels[0][0]
            for k in range(1, len(ranked)):
                sub = tuple(sorted(ranked[:k], key=lambda s: s.code))
                p_k = prob_at_least(sim_for(sub, cond.window_days, ctx.ramp).values(metric), th)
                if levels[0][2] < min_p <= p_k:
                    counted = after(0, p_k)
                    out.append(
                        Counter(
                            kind="scope",
                            scope=[s.code for s in sub],
                            threshold=th,
                            probability=round(p_k, 4),
                            counted_pts_after=round(counted, 4),
                            meets_requirement=counted + 1e-9 >= required,
                            text=f"measure sell-through on {', '.join(s.code for s in sub)} only (P = {fmt_prob(p_k)}).",
                        )
                    )
                    break
    # (b) turn the bonus into guaranteed base
    uplift = max(required - base_pts, 0.0)
    if uplift > 0:
        out.append(
            Counter(
                kind="convert_to_base",
                required_base_pts=round(base_pts + uplift, 4),
                uplift_pts=round(uplift, 4),
                fair_conversion_pts=a.expected_bonus_pts,
                counted_pts_after=round(base_pts + uplift, 4),
                meets_requirement=True,
                text=(
                    f"ask for a guaranteed base of {fmt_pts(base_pts + uplift)}% (+{fmt_pts(uplift)} points) in place of the volume-linked bonus, "
                    f"which is worth {fmt_pts(a.expected_bonus_pts)} points risk-adjusted."
                ),
            )
        )
    order = {"threshold": 0, "window": 1, "scope": 2, "convert_to_base": 3}
    return sorted(out, key=lambda c: order[c.kind])


# ---------- trades and qualitative terms ----------


def _trade_result(a: DealAssessment, net: float, label: str, reasoning: list[str], good: str, bad: str) -> DealAssessment:
    ok = net > 0
    return a.model_copy(
        update={
            "label": label,
            "net_pts": round(net, 4),
            "counted_pts": round(max(net, 0.0), 4),
            "expected_pts": round(net, 4),
            "reasoning": reasoning,
            "decision": "accept" if ok else "reject_structure",
            "call": (good if ok else bad) + f" Net value {net:+.1f} margin points after costs.",
        }
    )


def _assess_payment_trade(term: DealTerm, ctx: Context, a: DealAssessment) -> DealAssessment:
    n = policy.get().negotiation
    skus = pick(ctx.skus, term.scope) or ctx.skus
    base_days = float(ctx.base_payment_days if ctx.base_payment_days is not None else 0.0)
    pay_in = float(term.days if term.days is not None else base_days)
    brought_forward = max(base_days - pay_in, 0.0)
    carry = n.cost_of_capital_pct_annual * brought_forward / 365
    ratio = cost_ratio(skus)
    net = (to_pts(term.term, term.value, skus)) - carry * ratio
    reasoning = [
        f"Paying {brought_forward:g} days earlier (from {base_days:g} to {pay_in:g}) costs {carry:.2f}% of the invoice at {n.cost_of_capital_pct_annual:g}% a year.",
        f"The {term.value:g}% discount is worth {to_pts(term.term, term.value, skus):.2f} margin points; the capital cost is {carry * ratio:.2f} points.",
    ]
    return _trade_result(a, net, describe(term, None), reasoning, "Take the trade: the discount more than pays for the cash we bring forward.", "Decline the trade: the discount does not pay for paying earlier.")


def _assess_moq_trade(term: DealTerm, ctx: Context, a: DealAssessment) -> DealAssessment:
    n = policy.get().negotiation
    c = n.contingent
    skus = pick(ctx.skus, term.scope) or ctx.skus
    base_moq = float(ctx.base_moq if ctx.base_moq else sum(s.alloc for s in skus))
    want = float(term.units if term.units is not None else base_moq)
    if base_moq <= 0 or not skus:
        return a.model_copy(update={"decision": "not_assessable", "call": "There is no first order to scale, so the trade cannot be valued.", "reasoning": ["First-order units are zero."]})
    factor = max(want / base_moq, 1.0)
    scaled = tuple(SkuFact(s.code, s.category, s.monthly_units, s.price, s.cost, round(s.alloc * factor), s.target_pct) for s in skus)
    gmv = first_order_gmv(scaled)
    cost_value = sum(s.alloc * s.cost for s in scaled)
    discount_inr = term.value / 100 * cost_value
    extra_units = sum(s.alloc for s in scaled) - sum(s.alloc for s in skus)
    extra_cost = sum(s2.alloc * s2.cost - s1.alloc * s1.cost for s1, s2 in zip(skus, scaled))
    monthly = sum(s.monthly_units for s in skus)
    months_to_sell = min(extra_units / monthly, c.dead_stock_horizon_days / 30) if monthly > 0 else c.dead_stock_horizon_days / 30
    carrying_inr = extra_cost * n.inventory_carrying_pct_monthly / 100 * months_to_sell
    dead_now = sim_for(skus, c.dead_stock_horizon_days).unsold()[1]
    dead_new = sim_for(scaled, c.dead_stock_horizon_days).unsold()[1]
    dead_inr = max(dead_new - dead_now, 0.0) * c.dead_stock_writeoff_pct / 100
    net_inr = discount_inr - carrying_inr - dead_inr
    net = net_inr / gmv * 100 if gmv > 0 else 0.0
    reasoning = [
        f"A {term.value:g}% discount on a {want:,.0f}-unit order is worth {fmt_inr(discount_inr)}.",
        f"{extra_units:,.0f} extra units cost {fmt_inr(extra_cost)} and take {months_to_sell:.1f} months to sell: carrying cost {fmt_inr(carrying_inr)} at {n.inventory_carrying_pct_monthly:g}% a month.",
        f"Expected unsold stock after {c.dead_stock_horizon_days} days rises by {fmt_inr(max(dead_new - dead_now, 0.0))} at cost; written off at {c.dead_stock_writeoff_pct:g}%: {fmt_inr(dead_inr)}.",
        f"Net {fmt_inr(net_inr)} on {fmt_inr(gmv)} of sales.",
    ]
    return _trade_result(a, net, describe(term, None), reasoning, "Take the trade: the discount pays for the extra stock we would carry.", "Decline the trade: carrying and dead-stock risk on the extra units outweigh the discount.")


def _assess_free_goods(term: DealTerm, ctx: Context, a: DealAssessment) -> DealAssessment:
    skus = pick(ctx.skus, term.scope) or ctx.skus
    pts = to_pts("free_goods_pct", term.value, skus)
    if term.condition is not None:
        return _assess_conditional(term.model_copy(update={"kind": "conditional"}), None, ctx, a)
    reasoning = [f"{term.value:g}% extra units free lowers unit cost by {term.value / (100 + term.value) * 100:.1f}%, worth {pts:.2f} margin points."]
    return _trade_result(a, pts, describe(term, None), reasoning, "Take it: free goods are a guaranteed cost reduction.", "No value.")


def _assess_sell_or_return(term: DealTerm, ctx: Context, a: DealAssessment) -> DealAssessment:
    c = policy.get().negotiation.contingent
    skus = pick(ctx.skus, term.scope) or ctx.skus
    horizon = term.days if term.days else c.dead_stock_horizon_days
    sim = sim_for(skus, horizon)
    gmv = first_order_gmv(skus)
    unsold_units, unsold_cost = sim.unsold()
    saved = term.value / 100 * unsold_cost
    pts = saved / gmv * 100 if gmv > 0 else 0.0
    reasoning = [f"After {horizon:g} days we expect {unsold_units:,.0f} units unsold (cost {fmt_inr(unsold_cost)}); {term.value:g}% of that can go back, protecting {fmt_inr(saved)}."]
    return _trade_result(a, pts, describe(term, None), reasoning, "Take it: sale-or-return removes dead-stock risk.", "No value.")


def _assess_exclusivity(term: DealTerm, ctx: Context, a: DealAssessment) -> DealAssessment:
    skus = pick(ctx.skus, term.scope) or ctx.skus
    cats = {s.category for s in skus}
    rows = [r for r in load_catalog() if r.category in cats]
    monthly_gmv = sum(r.monthly_units * r.selling_price for r in rows)
    months = term.value
    reasoning = [
        f"We already sell {fmt_inr(monthly_gmv)} a month across {len(rows)} SKUs in {', '.join(sorted(cats))}; exclusivity for {months:g} months would shut other brands out of that range.",
        "Opportunity cost depends on strategy, so the agent does not value it.",
    ]
    return a.model_copy(
        update={
            "label": describe(term, None),
            "decision": "needs_human",
            "call": f"Needs a human: exclusivity for {months:g} months puts {fmt_inr(monthly_gmv)} a month of existing {', '.join(sorted(cats))} sales in play. Not auto-accepted.",
            "reasoning": reasoning,
        }
    )


def _assess_price_protection(term: DealTerm, ctx: Context, a: DealAssessment) -> DealAssessment:
    return a.model_copy(
        update={
            "label": describe(term, None),
            "decision": "accept",
            "call": f"Accept: price protection for {term.value:g} days costs us nothing. It adds no margin points, so it is not counted.",
            "reasoning": ["Protects the agreed cost from increases; not valued in margin points."],
        }
    )


def assess_one(term: DealTerm, base: DealTerm | None, ctx: Context) -> DealAssessment:
    a = DealAssessment(term_id=term.id, kind=term.kind, term=term.term, label=describe(term, base), source=term.source, turn=term.turn, quote=term.quote, decision="not_assessable", call="")
    if not ctx.skus:
        return a.model_copy(update={"call": "No SKU is shortlisted, so there is nothing to value the offer against.", "reasoning": ["The shortlist is empty."]})
    if term.kind in CONDITIONAL_KINDS:
        return _assess_conditional(term, base, ctx, a)
    if term.kind == "payment_for_discount":
        return _assess_payment_trade(term, ctx, a)
    if term.kind == "moq_for_discount":
        return _assess_moq_trade(term, ctx, a)
    if term.kind == "free_goods":
        return _assess_free_goods(term, ctx, a)
    if term.kind == "sell_or_return":
        return _assess_sell_or_return(term, ctx, a)
    if term.kind == "exclusivity":
        return _assess_exclusivity(term, ctx, a)
    if term.kind == "price_protection":
        return _assess_price_protection(term, ctx, a)
    return a.model_copy(update={"call": "A base term: it is compared in the gap table, not valued here."})


def assumptions() -> dict[str, Any]:
    n = policy.get().negotiation
    return {
        "min_probability": n.contingent.min_probability,
        "value_basis": n.contingent.value_basis,
        "ramp_by_month": list(n.forecast.ramp_by_month),
        "cv": n.forecast.cv,
        "cv_by_category": dict(n.forecast.cv_by_category),
        "sku_correlation": n.forecast.sku_correlation,
        "mc_draws": n.forecast.mc_draws,
        "seed": n.forecast.seed,
        "cost_of_capital_pct_annual": n.cost_of_capital_pct_annual,
        "inventory_carrying_pct_monthly": n.inventory_carrying_pct_monthly,
    }


def assess(terms: list[DealTerm], ctx: Context) -> DealReport:
    """Value every non-base term. ``terms`` must already be the verified ones."""
    by_id = {t.id: t for t in terms}
    out: list[DealAssessment] = []
    for t in terms:
        if t.kind == "base":
            continue
        base = by_id.get(t.base_of) if t.base_of else None  # no base: the bonus sits on the margin already counted for the vendor
        out.append(assess_one(t, base, ctx))
    rank = {"reject_structure": 3, "needs_human": 2, "not_assessable": 1, "accept": 0}
    top = max(out, key=lambda x: rank[x.decision]).decision if out else "none"
    heads = {
        "reject_structure": "Reject the conditional structure and counter",
        "needs_human": "A human must decide",
        "not_assessable": "Could not value the offer",
        "accept": "Offer is acceptable on a risk-adjusted basis",
        "none": "No conditional terms",
    }
    return DealReport(assessments=out, decision=top, headline=heads[top], assumptions=assumptions())


# ---------- claims: every stated number, recomputed by the verifier ----------

DEAL_METRICS = {"deal_probability": "ratio", "deal_percentile": None, "deal_pts": "pts", "deal_counter": None}


def spec_key(vendor_id: str, lever: LeverResponse, ctx: Context, term: DealTerm, base: DealTerm | None) -> str:
    """Everything the verifier needs to recompute: the lever and the verified terms and context, as compact JSON."""
    spec = {
        "term": term.model_dump(mode="json"),
        "base": base.model_dump(mode="json") if base is not None else None,
        "base_margin_pct": ctx.base_margin_pct,
        "base_payment_days": ctx.base_payment_days,
        "base_moq": ctx.base_moq,
        "codes": [s.code for s in ctx.skus],
    }
    return f"{vendor_id}?offset={lever.target_margin_pct_offset:g}&moq={lever.summary.moq}#" + json.dumps(spec, sort_keys=True, separators=(",", ":"))


def _field(a: DealAssessment, metric: str, column: str) -> float | None:
    """The number a (metric, column) pair names in an assessment, in claim scale. None if it does not exist."""
    d = a.distribution
    scale = METRIC_CLAIM[d.metric][1] if d else 1.0
    try:
        if metric == "deal_probability":
            return a.tiers[int(column.removeprefix("tier:"))].probability
        if metric == "deal_percentile":
            return round(getattr(d, column) * scale, 6) if d else None
        if metric == "deal_pts":
            return {
                "base": a.base_pts, "expected": a.expected_pts, "counted": a.counted_pts, "required": a.required_pts,
                "face": a.face_pts, "net": a.net_pts,
            }[column]
        if metric == "deal_counter":
            kind, _, idx = column.partition(":")
            c = a.counters[int(idx)]
            if kind == "threshold":
                return round((c.threshold or 0.0) * scale, 6)
            return {"uplift": c.uplift_pts, "base": c.required_base_pts, "after": c.counted_pts_after}[kind]
    except (IndexError, KeyError, ValueError):
        return None
    return None


def claims_for(vendor_id: str, lever: LeverResponse, ctx: Context, term: DealTerm, base: DealTerm | None, a: DealAssessment) -> list[Claim]:
    """Engine Claims for one assessment. The verifier re-runs the whole assessment from ``spec_key``."""
    file = f"vendors/{vendor_id}/" + ("application.json" if term.source == "application" else "call_transcript.json")
    key = spec_key(vendor_id, lever, ctx, term, base)
    d = a.distribution
    unit = METRIC_CLAIM[d.metric][0] if d else "units"
    out: list[Claim] = []

    def add(metric: str, column: str, text: str, claim_unit: str) -> None:
        value = _field(a, metric, column)
        if value is None:
            return
        out.append(
            Claim(
                id=f"{vendor_id}:deal:{term.id}:{metric}:{column}",
                text=text,
                value=float(value),
                metric=metric,
                unit=claim_unit,  # type: ignore[arg-type]
                source_ref=SourceRef(file=file, key=key, column=column),
                origin="engine",
            )
        )

    name = describe(term, base)
    for i, t in enumerate(a.tiers):
        add("deal_probability", f"tier:{i}", f"Chance of {fmt_metric(d.metric, t.threshold) if d else ''} in {d.window_days if d else ''} days for {name}: {fmt_prob(t.probability)}", "ratio")
    if d:
        for q in ("p10", "p50", "p90"):
            add("deal_percentile", q, f"{q.upper()} of {METRIC_LABEL[d.metric]} in {d.window_days} days for {name}: {fmt_metric(d.metric, getattr(d, q))}", unit)
    for col, text in (
        ("base", f"Guaranteed base for {name}: {fmt_pts(a.base_pts)} points"),
        ("expected", f"Risk-adjusted expected value of {name}: {fmt_pts(a.expected_pts)} points"),
        ("counted", f"Counted value of {name}: {fmt_pts(a.counted_pts)} points"),
        ("required", f"Required for {name}: {fmt_pts(a.required_pts)} points"),
    ):
        if a.distribution is not None or col == "net":
            add("deal_pts", col, text, "pts")
    if a.net_pts is not None:
        add("deal_pts", "net", f"Net value of {name}: {a.net_pts:+.1f} points", "pts")
    for i, c in enumerate(a.counters):
        if c.kind == "threshold":
            add("deal_counter", f"threshold:{i}", f"Counter threshold for {name}: {fmt_metric(d.metric, c.threshold or 0.0) if d else ''}", unit)
        elif c.kind == "convert_to_base":
            add("deal_counter", f"uplift:{i}", f"Counter base uplift for {name}: +{fmt_pts(c.uplift_pts or 0.0)} points", "pts")
    return out


def recompute(claim: Claim) -> float:
    """Verifier entry: rebuild the lever, terms and context from the claim's source_ref key and re-run the assessment."""
    try:
        head, _, blob = claim.source_ref.key.partition("#")
        vendor, _, query = head.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        spec = json.loads(blob)
        lever = apply_levers(build_base(vendor), float(params.get("offset", 0)), int(params["moq"]) if "moq" in params else None)
        ctx = Context(sku_facts(lever, set(spec["codes"])), spec.get("base_margin_pct"), spec.get("base_payment_days"), spec.get("base_moq"))
        term = DealTerm.model_validate(spec["term"])
        base = DealTerm.model_validate(spec["base"]) if spec.get("base") else None
    except (ValueError, KeyError, TypeError) as exc:
        raise MissingInput("the deal claim's inputs could not be read", cause=str(exc)[:160]) from exc
    value = _field(assess_one(term, base, ctx), claim.metric, claim.source_ref.column or "")
    if value is None:
        raise MissingInput(f"{claim.metric}:{claim.source_ref.column} does not exist in the recomputed assessment")
    return float(value)


# ---------- the narrative: every number must be one the engine stated ----------

_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def numbers_in_text(text: str) -> list[float]:
    return [float(m.group(0).replace(",", "")) for m in _NUM.finditer(text)]


def fact_numbers(report: DealReport) -> set[float]:
    """Every number the evaluator itself computed or was given, in the forms a sentence would use."""
    out: set[float] = set()

    def add(x: float | None) -> None:
        if x is None:
            return
        for v in (x, x * 100):
            out.add(round(v, 4))

    for a in report.assessments:
        for v in (a.base_pts, a.face_pts, a.expected_bonus_pts, a.counted_bonus_pts, a.expected_pts, a.guaranteed_pts, a.counted_pts, a.required_pts, a.shortfall_pts, abs(a.shortfall_pts), a.net_pts, a.probability):
            add(v)
        for t in a.tiers:
            for v in (t.threshold, t.bonus_pts, t.probability):
                add(v)
        if a.distribution:
            d = a.distribution
            for v in (d.p10, d.p50, d.p90, d.mean, d.threshold, d.window_days):
                add(v)
        for c in a.counters:
            for v in (c.threshold, c.window_days, c.probability, c.required_base_pts, c.uplift_pts, c.fair_conversion_pts, c.counted_pts_after):
                add(v)
        out.update(numbers_in_text(a.quote))
        out.update(numbers_in_text(a.label))
        out.update(numbers_in_text(a.call))
    out.add(report.assumptions.get("min_probability", 0.0) * 100)
    return out


def number_ok(x: float, allowed: set[float]) -> bool:
    return any(abs(x - a) <= max(0.051, abs(a) * 0.006) for a in allowed)


def strike_unverified_numbers(text: str, report: DealReport) -> tuple[str, list[str]]:
    """Keep the sentences whose every number is one the engine stated; return (kept text, struck sentences)."""
    allowed = fact_numbers(report)
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    kept, struck = [], []
    for sentence in parts:
        if not sentence.strip():
            continue
        if all(number_ok(n, allowed) for n in numbers_in_text(sentence)):
            kept.append(sentence.strip())
        else:
            struck.append(sentence.strip())
    return " ".join(kept), struck


def talk_facts(report: DealReport) -> list[dict[str, Any]]:
    """What the talk-track writer is given: the engine's figures, nothing else."""
    out = []
    for a in report.assessments:
        out.append(
            {
                "offer": a.label,
                "decision": a.decision,
                "probability": None if a.probability is None else fmt_prob(a.probability),
                "counted_points": a.counted_pts,
                "face_points": a.face_pts,
                "required_points": a.required_pts,
                "expected_points": a.expected_pts,
                "distribution": None if a.distribution is None else {"p10": a.distribution.p10, "p50": a.distribution.p50, "p90": a.distribution.p90, "window_days": a.distribution.window_days, "metric": a.distribution.metric},
                "counters": [c.text for c in a.counters],
                "call": a.call,
            }
        )
    return out
