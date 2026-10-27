"""Existing-vendor price-increase requests: the deterministic engine. Never imports llm.

The model (see ``agents/pricereq.py``) only READS a vendor's email and revised price list into ``PriceRequestExtraction``
(every number carries a verbatim quote that is checked). Everything below is plain Python, per SKU:

* the new margin at today's selling price, and the retail price that defends the margin (the category target, or the
  current margin when the SKU is already under target: an old shortfall is not the vendor's doing);
* the competitor price gap if we pass the increase on, demand elasticity risk (playbook elasticity per category), and the
  GMV and margin impact over the playbook's horizon (default 90 days);
* the commodity justification check (optional input index in the playbook);
* conditional sweeteners: "absorb half if you commit N units a month" is valued by the deal evaluator's probability
  engine (``deals.assess_one``); "extra support if you take the full revision" is acceptance-linked and valued directly;
* a decision per SKU (accept, accept_partial with a counter %, pass_through, delay, delist) and overall, the approval tier,
  and the counter-offer.

Percent values in this module's output are percent numbers (4.0 means 4%), not fractions.
"""

import csv
import math
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, Field

from app import deals, policy
from app.config import settings
from app.errors import MissingInput, UnknownOpsVendor
from app.ops import data as ops_data
from app.schemas import DealCondition, DealTerm
from app.taxonomy import classify, segment_hints
from app.util import fmt_inr

Decision = Literal["accept", "accept_partial", "pass_through", "delay", "delist", "needs_review"]
PRIORITY: dict[str, int] = {"delist": 6, "delay": 5, "accept_partial": 4, "needs_review": 3, "pass_through": 2, "accept": 1}
EPS = 1e-9


# ---------- what the model reads ----------


class ExtractedLine(BaseModel):
    sku_code: str
    old_cost: float
    new_cost: float
    effective_date: str | None = None  # ISO, only when the line carries its own date
    source: Literal["email", "price_list"] = "price_list"
    quote: str  # verbatim: the row of the list, or the sentence of the email, stating both costs


class ExtractedSweetener(BaseModel):
    id: str
    kind: Literal["absorb_if_volume", "support_if_full_acceptance"]
    share_pct: float | None = None  # absorb_if_volume: the share of the revision the vendor absorbs ("half" -> 50)
    support_pct: float | None = None  # support_if_full_acceptance: extra marketing support, % of sales
    threshold_units: float | None = None  # absorb_if_volume: units we must commit to / sell
    window_days: int | None = None  # ... per this many days (a month -> 30)
    scope: list[str] = Field(default_factory=list)  # SKU codes; empty means the whole request
    source: Literal["email", "price_list"] = "email"
    quote: str


class PriceRequestExtraction(BaseModel):
    effective_date: str | None = None  # ISO date the new costs apply from
    effective_quote: str = ""
    reason: str = ""  # the vendor's stated reason, short
    reason_quote: str = ""
    lines: list[ExtractedLine] = Field(default_factory=list)
    sweeteners: list[ExtractedSweetener] = Field(default_factory=list)


class PriceReplyDraft(BaseModel):
    subject: str = ""
    body: str = ""


# ---------- outputs ----------


class Scenario(BaseModel):
    label: str
    cost_pct: float
    price: float
    units: float
    gmv: float
    margin_inr: float
    margin_pct: float | None
    gmv_delta: float
    margin_delta: float


class LineResult(BaseModel):
    sku_code: str
    name: str = ""
    category: str = ""
    status: Literal["ok", "unmatched", "no_cost_or_price"] = "ok"
    source: str = "price_list"
    quote: str = ""
    old_cost: float | None = None  # as the vendor states it
    new_cost: float | None = None
    cost_on_file: float | None = None
    old_cost_mismatch: bool = False
    pct_change: float | None = None  # asked, from the stated old and new cost
    effective_pct: float | None = None  # after the part of the sweetener that counts
    selling_price: float | None = None
    competitor_median: float | None = None
    competitor_count: int = 0
    current_margin_pct: float | None = None
    new_margin_pct: float | None = None  # at today's price, asked cost
    margin_drop_pts: float | None = None
    target_margin_pct: float | None = None
    floor_margin_pct: float | None = None
    needed_retail: float | None = None  # defends the margin (target, or current if already under target)
    needed_retail_for_target: float | None = None
    retail_rise_pct: float | None = None
    gap_if_passed_pct: float | None = None  # vs the competitor median
    elasticity: float | None = None
    volume_change_pct: float | None = None  # if passed on
    elasticity_risk: Literal["low", "medium", "high"] | None = None
    absorb_limit_pct: float | None = None  # most the cost can rise with the margin still at the floor
    pass_through_limit_pct: float | None = None  # most we can pass on within the gap and volume rules
    pass_through_ok: bool = False
    justified_ceiling_pct: float | None = None
    justified: bool | None = None  # None: no index configured
    effective_date: str | None = None
    notice_days: int | None = None
    short_notice: bool = False
    ask_effective_date: str | None = None
    decision: Decision = "needs_review"
    then_decision: str | None = None  # delay: what we do once the date is moved
    counter_pct: float | None = None
    counter_cost: float | None = None
    counter_basis: Literal["absorb", "pass_through"] | None = None
    reasons: list[str] = Field(default_factory=list)
    why: str = ""  # one line for the table: the decisive figures behind the decision
    scenarios: list[Scenario] = Field(default_factory=list)  # status quo is the baseline each delta is against
    recommended: str = ""  # label of the scenario the decision leads to


class SweetenerResult(BaseModel):
    id: str
    kind: str
    label: str
    quote: str
    engine: Literal["deals", "acceptance"]
    decision: str
    call: str
    value_pts: float  # face value in margin points
    counted_pts: float  # what the evaluator counts
    probability: float | None = None
    counted_share_pct: float | None = None  # absorb: the share of the revision that counts as absorbed
    net_pts: float | None = None  # acceptance-linked: support minus the margin lost by taking the full revision
    assessment: dict[str, Any] | None = None  # a deals.DealAssessment, so the DealEvaluator card can render it


class Tier(BaseModel):
    role: str
    label: str
    above_pct: float


class Approval(BaseModel):
    pct: float  # largest cost increase we would agree to
    asked_pct: float
    tier: Tier
    asked_tier: Tier
    reasons: list[str]
    matrix: list[Tier]


class Evaluation(BaseModel):
    vendor_id: str
    received_date: str
    effective_date: str | None
    today: str
    lines: list[LineResult]
    sweeteners: list[SweetenerResult]
    decision: str
    headline: str
    counts: dict[str, int]
    approval: Approval
    counter_offer: dict[str, Any]
    impact: dict[str, Any]
    justification: dict[str, Any]
    assumptions: dict[str, Any]
    notes: list[str] = Field(default_factory=list)


# ---------- dates and small helpers ----------

_MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_MONTHS = {**{n[:3]: i for i, n in enumerate(_MONTH_NAMES, 1)}, **{n: i for i, n in enumerate(_MONTH_NAMES, 1)}, "sept": 9}
_D_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_D_NUM = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
_D_TXT = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+(?:of\s+)?([A-Za-z]{3,9})\.?(?:[\s,-]+(\d{4}))?", re.IGNORECASE)


def parse_dates(text: str, ref: date) -> list[date]:
    """Dates written in messy ways in ``text``: 2026-12-01, 01.12.2026, 01-Dec-2026, 1st Dec 2026, 10th Nov. A date without a
    year is the next one on or after ``ref``."""
    out: list[date] = []
    for m in _D_ISO.finditer(text):
        try:
            out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            continue
    for m in _D_NUM.finditer(text):
        try:
            out.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
        except ValueError:
            continue
    for m in _D_TXT.finditer(text):
        month = _MONTHS.get(m.group(2).lower())
        if month is None:
            continue
        day = int(m.group(1))
        try:
            if m.group(3):
                out.append(date(int(m.group(3)), month, day))
            else:
                d = date(ref.year, month, day)
                out.append(d if d >= ref else date(ref.year + 1, month, day))
        except ValueError:
            continue
    return out


def date_value(d: date) -> float:
    """A date as the number a claim carries: 2026-12-01 -> 20261201."""
    return float(d.year * 10000 + d.month * 100 + d.day)


def floor1(x: float) -> float:
    return math.floor(x * 10 + EPS) / 10


def r2(x: float | None) -> float | None:
    return None if x is None else round(x, 2)


def r4(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def pct_text(x: float) -> str:
    return f"{x:.1f}%"


# ---------- per-SKU facts ----------


class SkuInfo(BaseModel):
    code: str
    name: str
    category: str
    sku_key: str
    price: float | None
    cost: float | None  # vendor cost on file (before freight)
    landed: float | None
    target: float  # fraction
    floor: float  # fraction
    units_month: float
    comp_median: float | None
    comp_count: int


class VendorFacts(BaseModel):
    skus: dict[str, SkuInfo]
    freight_pct: float


COMPETITORS_FILE = "price_requests/competitors.csv"
WINDOW_DAYS = 28  # recent run-rate: units sold over the last four weeks of the ops data


@lru_cache(maxsize=4)
def _competitors(data_dir: str) -> dict[str, tuple[float, ...]]:
    out: dict[str, list[float]] = {}
    path = Path(data_dir) / COMPETITORS_FILE
    if path.exists():
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                out.setdefault(row["sku_code"], []).append(float(row["price"]))
    return {k: tuple(v) for k, v in out.items()}


def known_vendor(vendor_id: str) -> bool:
    return vendor_id in ops_data.load().vendors


def vendor_info(vendor_id: str) -> dict[str, str]:
    """Brand and contact of an existing vendor (data/synthetic/ops/vendors.json)."""
    ops = ops_data.load()
    v = ops.vendors.get(vendor_id)
    if v is None:
        raise UnknownOpsVendor(vendor_id)
    return {"brand": v.brand, "company_name": v.company_name, "contact_name": v.contact_name, "contact_email": v.contact_email, "category": v.category}


def sku_category(vendor_category: str, name: str, hint: dict[str, str]) -> str:
    """The playbook margin category of an existing vendor's SKU: the vendor's own category when it is one of the playbook's,
    else the taxonomy's reading of the SKU name."""
    cats = policy.get().margins.categories
    if vendor_category in cats:
        return vendor_category
    c = classify(name, "", hint).category
    if vendor_category in ("dog food", "cat food") and not c.endswith("food"):
        return f"{hint.get('species', 'dog')} dry food"
    return c


def vendor_facts(vendor_id: str) -> VendorFacts:
    """Every SKU of an existing vendor: price, cost and recent units from the ops data, the playbook's margin target and floor
    for its category, and competitor prices. The ops ``cost`` is what we pay (landed), so freight is 0."""
    ops = ops_data.load()
    vendor = ops.vendors.get(vendor_id)
    if vendor is None:
        raise UnknownOpsVendor(vendor_id)
    comps = _competitors(str(settings.data_dir))
    hint = segment_hints(f"{vendor.company_name} {vendor.category}")
    start = ops.data_end - timedelta(days=WINDOW_DAYS - 1)
    out: dict[str, SkuInfo] = {}
    for code in ops.skus_by_vendor.get(vendor_id, []):
        s = ops.skus[code]
        cat = sku_category(vendor.category, s.name, hint)
        tgt = policy.target_breakdown(cat, None, vendor.brand)
        units = sum(u for day, (u, _) in ops.sales.get(code, {}).items() if start <= day <= ops.data_end)
        prices = list(comps.get(code, ()))
        out[code] = SkuInfo(
            code=code, name=s.name, category=cat, sku_key=f"{vendor_id}:{code}", price=s.selling_price, cost=s.cost, landed=s.cost,
            target=(tgt["category_pct"] + tgt["brand_pp"]) / 100, floor=policy.min_pct(cat, None, vendor.brand) / 100,
            units_month=units / WINDOW_DAYS * 30, comp_median=float(median(prices)) if prices else None, comp_count=len(prices),
        )
    return VendorFacts(skus=out, freight_pct=0.0)


def deal_facts(facts: VendorFacts) -> tuple[deals.SkuFact, ...]:
    """Every SKU as deal-evaluator facts: steady-state monthly units, cost, selling price, target in percent."""
    return tuple(
        deals.SkuFact(s.code, s.category, s.units_month, float(s.price), float(s.landed or 0.0), 0, s.target * 100)
        for s in sorted(facts.skus.values(), key=lambda x: x.code)
        if s.price and s.landed is not None
    )


# ---------- the economics of one SKU at a given cost rise ----------


class Econ:
    """One SKU's numbers at a cost rise of ``p`` percent on the cost on file."""

    def __init__(self, sku: SkuInfo, freight: float, elasticity: float, pt: Any) -> None:
        assert sku.price and sku.cost is not None
        self.sku, self.f, self.e, self.pt = sku, freight, elasticity, pt
        self.price = sku.price
        self.old_landed = sku.cost * (1 + freight)
        self.cur_margin = (self.price - self.old_landed) / self.price
        self.defend = min(self.cur_margin, sku.target)
        self.floor_eff = min(sku.floor, self.cur_margin)

    def landed(self, p: float) -> float:
        return self.sku.cost * (1 + p / 100) * (1 + self.f)  # type: ignore[operator]

    def margin(self, p: float) -> float:
        return (self.price - self.landed(p)) / self.price

    def needed(self, p: float, target: float | None = None) -> float:
        return self.landed(p) / (1 - (self.defend if target is None else target))

    def rise(self, p: float) -> float:
        return max(self.needed(p) / self.price - 1, 0.0)

    def eff_price(self, p: float) -> float:
        return max(self.price, self.needed(p))

    def gap(self, p: float) -> float | None:
        m = self.sku.comp_median
        return None if not m else self.eff_price(p) / m - 1

    def volume(self, p: float) -> float:
        return (1 + self.rise(p)) ** self.e - 1

    def pass_ok(self, p: float) -> bool:
        if not self.pt.allow:
            return False
        gap = self.gap(p)
        if gap is not None and gap * 100 > self.pt.max_competitor_gap_pct + EPS:
            return False
        return -self.volume(p) * 100 <= self.pt.max_volume_loss_pct + EPS

    def absorb_limit(self, credit: float = 0.0) -> float:
        """Most the cost can rise while the margin stays at the floor (never below the margin we have today); credit is extra margin."""
        landed_max = self.price * (1 - self.floor_eff + credit)
        cost_max = landed_max / (1 + self.f)
        return max((cost_max / self.sku.cost - 1) * 100, 0.0)  # type: ignore[operator]

    def pass_limit(self) -> float:
        if not self.pass_ok(0.0):
            return 0.0
        lo, hi = 0.0, 100.0
        for _ in range(48):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if self.pass_ok(mid) else (lo, mid)
        return lo

    def risk(self, p: float) -> str:
        loss = -self.volume(p) * 100
        el = policy.get().price_requests.elasticity
        return "high" if loss >= el.risk_high_loss_pct - EPS else "medium" if loss >= el.risk_medium_loss_pct - EPS else "low"


def scenario(econ: Econ, label: str, p: float, price: float, units_base: float, baseline: tuple[float, float], months: float, credit_pts: float = 0.0) -> Scenario:
    """Units follow the price with the constant-elasticity curve. Margin is on retail, plus ``credit_pts`` of vendor support."""
    units = units_base * (price / econ.price) ** econ.e
    gmv = units * price
    margin = units * (price - econ.landed(p)) + credit_pts / 100 * gmv
    return Scenario(
        label=label, cost_pct=round(p, 2), price=round(price, 2), units=round(units, 2), gmv=round(gmv, 2), margin_inr=round(margin, 2),
        margin_pct=round(margin / gmv * 100, 2) if gmv else None, gmv_delta=round(gmv - baseline[0], 2), margin_delta=round(margin - baseline[1], 2),
    )


# ---------- the engine ----------


def justified_ceiling(category: str) -> float | None:
    j = policy.get().price_requests.justification
    idx = j.index_change_by_category.get(category, j.index_change_pct)
    return None if idx is None else idx + j.tolerance_pp


def tiers() -> list[Tier]:
    return [Tier(role=r.approver, label=r.label or r.approver.replace("_", " ").capitalize(), above_pct=r.above_pct) for r in policy.get().price_requests.approval.matrix]


def tier_for(pct: float) -> Tier:
    chosen = tiers()[0]
    for t in tiers():
        if pct > t.above_pct + EPS:
            chosen = t
    return chosen


def tier_rank(role: str) -> int:
    for i, t in enumerate(tiers()):
        if t.role == role:
            return i
    raise MissingInput(f"{role!r} is not an approver in the playbook's approval matrix", cause="price_requests.approval.matrix")


def _weighted(lines: list[tuple[float, float]]) -> float:
    """Mean of (value, weight) pairs."""
    total = sum(w for _, w in lines)
    return sum(v * w for v, w in lines) / total if total > 0 else 0.0


def evaluate(
    vendor_id: str, ex: PriceRequestExtraction, received: date, today: date, facts: VendorFacts | None = None, dfacts: tuple[deals.SkuFact, ...] | None = None
) -> Evaluation:
    pr = policy.get().price_requests
    facts = facts or vendor_facts(vendor_id)
    months = pr.horizon_days / 30
    req_eff = _iso(ex.effective_date)
    notes: list[str] = []
    codes = [ln.sku_code for ln in ex.lines]

    # --- asked economics per line (needed by the sweetener valuation) ---
    pre: dict[str, tuple[ExtractedLine, SkuInfo, Econ, float]] = {}
    for ln in ex.lines:
        sku = facts.skus.get(ln.sku_code)
        if sku is None or not sku.price or sku.cost is None or ln.old_cost <= 0:
            continue
        el = pr.elasticity.by_category.get(sku.category, pr.elasticity.default)
        econ = Econ(sku, facts.freight_pct, el, pr.pass_through)
        pre[ln.sku_code] = (ln, sku, econ, (ln.new_cost / ln.old_cost - 1) * 100)

    # --- sweeteners ---
    sweeteners: list[SweetenerResult] = []
    absorbed_share = 0.0  # share of the revision that counts as absorbed (0..1), summed over absorb sweeteners
    support_pts = 0.0
    weights = [(e.price * sku.units_month, e) for _, sku, e, _ in pre.values()]
    wsum = sum(w for w, _ in weights) or 1.0
    drop_pts = sum(w * (e.cur_margin - e.margin(p)) * 100 for (w, e), (_, _, _, p) in zip(weights, pre.values())) / wsum if pre else 0.0
    new_margin_w = sum(w * e.margin(p) * 100 for (w, e), (_, _, _, p) in zip(weights, pre.values())) / wsum if pre else 0.0
    for i, sw in enumerate(ex.sweeteners, start=1):
        res = _value_sweetener(vendor_id, sw, i, ex, codes, drop_pts, new_margin_w, dfacts, notes, facts)
        sweeteners.append(res)
        if sw.kind == "absorb_if_volume" and res.counted_share_pct is not None:
            absorbed_share += res.counted_share_pct / 100
        if sw.kind == "support_if_full_acceptance":
            support_pts += res.counted_pts
    absorbed_share = min(absorbed_share, 1.0)

    # --- per line ---
    results: list[LineResult] = []
    for ln in ex.lines:
        results.append(_line(ln, facts, pre.get(ln.sku_code), req_eff, received, absorbed_share, support_pts, months, pr))

    ok = [r for r in results if r.status == "ok"]
    counts: dict[str, int] = {}
    for r in results:
        counts[r.decision] = counts.get(r.decision, 0) + 1
    overall = max((r.decision for r in results), key=lambda d: PRIORITY[d]) if results else "needs_review"

    # --- approval ---
    outcome = max((_outcome_pct(r) for r in ok), default=0.0)
    asked = max((r.pct_change or 0.0 for r in ok), default=0.0)
    tier = tier_for(outcome)
    reasons = [f"largest cost increase we would agree to is {pct_text(outcome)}: {tier.label}"]
    floors = pr.approval.decision_floor
    kinds = {r.decision if r.decision != "delay" else (r.then_decision or "delay") for r in results}
    if any(r.counter_basis == "pass_through" for r in results):
        kinds.add("pass_through")  # a counter that relies on raising our retail price is a pricing change
    for d in sorted(kinds):
        role = floors.get(d)
        if role and tier_rank(role) > tier_rank(tier.role):
            tier = next(t for t in tiers() if t.role == role)
            reasons.append(f"a '{d.replace('_', ' ')}' decision needs at least {tier.label}")
    approval = Approval(pct=round(outcome, 2), asked_pct=round(asked, 2), tier=tier, asked_tier=tier_for(asked), reasons=reasons, matrix=tiers())

    # --- impact, justification, counter ---
    impact = _impact(ok, pr.horizon_days)
    unjustified = [r.sku_code for r in ok if r.justified is False]
    j = pr.justification
    justification = {
        "index_name": j.index_name,
        "index_change_pct": j.index_change_pct,
        "tolerance_pp": j.tolerance_pp,
        "assessed": any(r.justified is not None for r in ok),
        "unjustified_skus": unjustified,
        "asked_max_pct": round(asked, 2),
        "ceiling_pct": None if j.index_change_pct is None else round(j.index_change_pct + j.tolerance_pp, 2),
    }
    headline = _headline(overall, counts, results)
    ev = Evaluation(
        vendor_id=vendor_id, received_date=received.isoformat(), effective_date=ex.effective_date, today=today.isoformat(), lines=results,
        sweeteners=sweeteners, decision=overall, headline=headline, counts=counts, approval=approval, counter_offer={}, impact=impact,
        justification=justification, assumptions=assumptions(), notes=notes,
    )
    ev.counter_offer = counter_offer(ev)
    return ev


def _iso(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _outcome_pct(r: LineResult) -> float:
    if r.decision in ("accept", "pass_through"):
        return r.effective_pct or 0.0
    if r.decision == "accept_partial":
        return r.counter_pct or 0.0
    if r.decision == "delay":
        return (r.counter_pct if r.then_decision == "accept_partial" else r.effective_pct) or 0.0
    return 0.0


def _value_sweetener(
    vendor_id: str, sw: ExtractedSweetener, n: int, ex: PriceRequestExtraction, codes: list[str], drop_pts: float, new_margin: float,
    dfacts: tuple[deals.SkuFact, ...] | None, notes: list[str], facts: VendorFacts,
) -> SweetenerResult:
    if sw.kind == "support_if_full_acceptance":
        pts = deals.to_pts("marketing_pct", sw.support_pct or 0.0, ())
        net = pts - drop_pts
        return SweetenerResult(
            id=sw.id, kind=sw.kind, label=f"{sw.support_pct or 0:g}% extra marketing support if we take the full revision", quote=sw.quote, engine="acceptance",
            decision="accept", value_pts=round(pts, 4), counted_pts=round(pts, 4), probability=1.0, net_pts=round(net, 4),
            call=(
                f"Accept as upside: the support is certain once we take the full revision and is worth {pts:.1f} margin points; the revision itself costs {drop_pts:.1f} points "
                f"at today's prices, so the package nets {net:+.1f} points."
            ),
        )
    # absorb_if_volume -> a conditional discount valued by the deal evaluator's probability engine
    share = (sw.share_pct or 0.0) / 100
    bonus_pts = share * drop_pts
    scope = [c for c in (sw.scope or codes)]
    term = DealTerm(
        id=sw.id, kind="conditional", term="margin_pct", value=round(bonus_pts, 4), unit="pct",
        condition=DealCondition(metric="units", threshold=float(sw.threshold_units or 0), window_days=int(sw.window_days or 30), scope=[]),
        scope=scope, quote=sw.quote, turn=n, source="application",
    )
    sku_facts = dfacts if dfacts is not None else deal_facts(facts)
    ctx = deals.Context(sku_facts, base_margin_pct=new_margin, ramp=(1.0,))
    a = deals.assess_one(term, None, ctx)
    face = max(a.face_pts - a.base_pts, 0.0)
    counted_share = (a.counted_bonus_pts / face) * (sw.share_pct or 0.0) if face > 0 else 0.0
    label = f"absorb {sw.share_pct or 0:g}% of the revision if we commit {sw.threshold_units or 0:,.0f} units in {sw.window_days or 30} days"
    a = a.model_copy(update={"label": label, "source": "application", "turn": n})
    if a.decision == "not_assessable":
        notes.append(f"Sweetener {sw.id} could not be valued: {a.call}")
    return SweetenerResult(
        id=sw.id, kind=sw.kind, label=label, quote=sw.quote, engine="deals", decision=a.decision, call=a.call, value_pts=round(face, 4),
        counted_pts=a.counted_bonus_pts, probability=a.probability, counted_share_pct=round(counted_share, 4), assessment=a.model_dump(mode="json"),
    )


def _line(
    ln: ExtractedLine, facts: VendorFacts, pre: tuple[ExtractedLine, SkuInfo, Econ, float] | None, req_eff: date | None, received: date,
    absorbed_share: float, support_pts: float, months: float, pr: Any,
) -> LineResult:
    sku = facts.skus.get(ln.sku_code)
    base = LineResult(sku_code=ln.sku_code, source=ln.source, quote=ln.quote, old_cost=ln.old_cost, new_cost=ln.new_cost, name=sku.name if sku else "", category=sku.category if sku else "")
    if sku is None:
        return base.model_copy(update={"status": "unmatched", "decision": "needs_review", "reasons": [f"{ln.sku_code} is not a SKU of this vendor in our system: a person must match it."]})
    if pre is None:
        return base.model_copy(update={"status": "no_cost_or_price", "decision": "needs_review", "reasons": [f"{ln.sku_code} has no cost or selling price on file, so the margin cannot be computed."]})
    _, sku, e, p = pre
    stated_gap = abs(ln.old_cost - (sku.cost or 0.0))
    mismatch = stated_gap > policy.tol("inr")
    reasons: list[str] = []
    if mismatch:
        reasons.append(f"The vendor's old cost {fmt_inr(ln.old_cost)} differs from the {fmt_inr(sku.cost or 0.0)} on file; the margin maths use the cost on file with the same % rise.")
    p_eff = p * (1 - absorbed_share)
    if absorbed_share > 0:
        reasons.append(f"A sweetener counts as absorbing {absorbed_share * 100:.1f}% of the revision, so the effective rise is {pct_text(p_eff)}.")
    # justification
    ceiling = justified_ceiling(sku.category)
    justified = None if ceiling is None else p_eff <= ceiling + EPS
    K = ceiling if ceiling is not None else float(pr.max_acceptable_increase_pct)
    if ceiling is not None:
        reasons.append(
            f"The {pr.justification.index_name.lower()} is {pr.justification.index_change_by_category.get(sku.category, pr.justification.index_change_pct):g}%: "
            f"a rise up to {ceiling:.1f}% is justified, {pct_text(p_eff)} is {'within that' if justified else 'above it'}."
        )
    else:
        reasons.append(f"No input index is configured, so up to {K:g}% is accepted without escalation.")
    lim_plain = e.absorb_limit()
    lim_full = e.absorb_limit(support_pts / 100) if support_pts else lim_plain
    pt_lim = e.pass_limit()
    eff_date = _iso(ln.effective_date) or req_eff
    notice = None if eff_date is None else (eff_date - received).days
    short = notice is not None and notice < pr.notice_period_days
    ask_date = (received + timedelta(days=pr.notice_period_days)).isoformat() if short else None

    margin_asked = e.margin(p)
    out = base.model_copy(
        update={
            "cost_on_file": sku.cost, "old_cost_mismatch": mismatch, "pct_change": round(p, 4), "effective_pct": round(p_eff, 4), "selling_price": sku.price,
            "competitor_median": sku.comp_median, "competitor_count": sku.comp_count, "current_margin_pct": round(e.cur_margin * 100, 4),
            "new_margin_pct": round(margin_asked * 100, 4), "margin_drop_pts": round((e.cur_margin - margin_asked) * 100, 4),
            "target_margin_pct": round(sku.target * 100, 4), "floor_margin_pct": round(sku.floor * 100, 4), "needed_retail": round(e.needed(p), 2),
            "needed_retail_for_target": round(e.needed(p, sku.target), 2), "retail_rise_pct": round(e.rise(p) * 100, 4),
            "gap_if_passed_pct": None if e.gap(p) is None else round(e.gap(p) * 100, 4),  # type: ignore[operator]
            "elasticity": e.e, "volume_change_pct": round(e.volume(p) * 100, 4), "elasticity_risk": e.risk(p),
            "absorb_limit_pct": round(lim_plain, 4), "pass_through_limit_pct": round(pt_lim, 4), "pass_through_ok": e.pass_ok(p_eff),
            "justified_ceiling_pct": None if ceiling is None else round(ceiling, 4), "justified": justified,
            "effective_date": eff_date.isoformat() if eff_date else None, "notice_days": notice, "short_notice": short, "ask_effective_date": ask_date,
        }
    )
    d, then, counter, basis, why = _decide(p_eff, K, justified, e, sku, lim_plain, lim_full, pt_lim, pr)
    reasons.extend(why)
    if short and d in ("accept", "pass_through", "accept_partial"):
        reasons.append(f"Notice is {notice} days against the {pr.notice_period_days} the playbook asks for: ask for {ask_date} (a later effective date).")
        then, d = d, "delay"
    elif notice is None:
        reasons.append("The effective date could not be verified, so notice was not checked.")
    counter_cost = None
    if d == "delay" and then in ("accept", "pass_through"):
        counter_cost = round(sku.cost * (1 + p_eff / 100), 2)
    elif counter is not None:
        counter_cost = round(sku.cost * (1 + counter / 100), 2)
    elif d in ("accept", "pass_through"):
        counter_cost = round(sku.cost * (1 + p_eff / 100), 2)
    out = out.model_copy(update={"decision": d, "then_decision": then if d == "delay" else None, "counter_pct": counter, "counter_basis": basis, "counter_cost": counter_cost, "reasons": reasons})
    out = out.model_copy(update={"why": _why_line(out, ceiling, justified)})
    return _with_scenarios(out, e, sku, p, p_eff, months, support_pts)


def _why_line(out: LineResult, ceiling: float | None, justified: bool | None) -> str:
    """One line of decisive engine figures for the lines table, e.g. 'margin stays 38.4% vs 38% target; index justifies up to 5.0%'."""
    nm, tgt, flr = out.new_margin_pct, out.target_margin_pct, out.floor_margin_pct
    d = out.then_decision if out.decision == "delay" else out.decision
    index = "" if ceiling is None else (f"; index justifies up to {pct_text(ceiling)}" if justified else f"; index justifies only {pct_text(ceiling)}")
    if nm is None or tgt is None:
        return out.reasons[0] if out.reasons else ""
    if d == "accept":
        head = f"margin stays {pct_text(nm)} vs {tgt:g}% target" if nm >= tgt else f"margin falls to {pct_text(nm)}, above the {flr:g}% floor (target {tgt:g}%)"
    elif d == "pass_through":
        gap = "" if out.gap_if_passed_pct is None else f", {pct_text(out.gap_if_passed_pct)} vs competitors"
        head = f"absorbing leaves margin at {pct_text(nm)} vs {tgt:g}% target; pass on {pct_text(out.retail_rise_pct or 0.0)}{gap}"
    elif d == "accept_partial" and out.counter_pct is not None:
        how = "absorbing it holds the floor" if out.counter_basis == "absorb" else "passing it on fits the gap and volume rules"
        head = f"asked {pct_text(out.effective_pct or 0.0)} takes margin to {pct_text(nm)}; counter {pct_text(out.counter_pct)} ({how})"
    elif d == "delist":
        head = f"margin would fall to {pct_text(nm)} and passing it on breaks the gap or volume rules"
    else:
        return out.reasons[0] if out.reasons else ""
    if out.decision == "delay":
        head += f"; ask for {out.ask_effective_date}"
    return head + index


def _decide(
    p: float, K: float, justified: bool | None, e: Econ, sku: SkuInfo, lim_plain: float, lim_full: float, pt_lim: float, pr: Any
) -> tuple[str, str | None, float | None, str | None, list[str]]:
    """(decision, then, counter %, counter basis, reasons). The matrix, first match wins:
    no rise -> accept; within the justified ceiling and absorbable -> accept (or pass on when that keeps the target and is
    allowed); within the ceiling but not absorbable -> pass on when the gap and volume rules allow; otherwise counter at the
    largest rise we can take (ceiling, absorb limit or pass-through limit); nothing useful to counter -> delist."""
    why: list[str] = []
    if p <= EPS:
        return "accept", None, None, None, ["No cost increase after what counts of the sweetener: accept."]
    gap = e.gap(p)
    if p <= K + EPS:
        if p <= lim_full + EPS:
            if e.margin(p) < e.defend - EPS and pr.pass_through.prefer_when_below_target and e.pass_ok(p) and e.rise(p) > EPS:
                why.append(f"Absorbing leaves the margin at {e.margin(p) * 100:.1f}%, under the {e.defend * 100:.1f}% we defend; passing on {pct_text(e.rise(p) * 100)} is within the playbook's gap and volume rules.")
                return "pass_through", None, None, None, why
            why.append(f"The new margin {e.margin(p) * 100:.1f}% stays at or above the {e.floor_eff * 100:.1f}% floor: accept.")
            return "accept", None, None, None, why
        if e.pass_ok(p):
            why.append(f"We cannot absorb {pct_text(p)} (the margin would fall below {e.floor_eff * 100:.1f}%), but passing it on puts us {pct_text(gap * 100) if gap is not None else 'level'} above competitors and loses {pct_text(-e.volume(p) * 100)} of units: pass it on.")
            return "pass_through", None, None, None, why
    else:
        why.append(f"{pct_text(p)} is above the {pct_text(K)} we accept (justified ceiling or the largest increase without escalation): counter.")
    if not e.pass_ok(p) and gap is not None:
        why.append(
            f"Passing {pct_text(p)} on would price us {pct_text(gap * 100)} above the competitor median and lose {pct_text(-e.volume(p) * 100)} of units"
            + (f" (limits {pr.pass_through.max_competitor_gap_pct:g}% and {pr.pass_through.max_volume_loss_pct:g}%)." if pr.pass_through.allow else " (pass-through is switched off).")
        )
    best_pass = pt_lim
    c = floor1(min(p, K, max(lim_plain, best_pass)))
    if c + EPS >= pr.min_counter_pct:
        basis = "absorb" if c <= lim_plain + 0.05 else "pass_through"
        why.append(
            f"Counter at {pct_text(c)}: the most we can take ({'absorbing it keeps the margin at the floor' if basis == 'absorb' else 'passing it on stays within the gap and volume rules'})."
        )
        return "accept_partial", None, c, basis, why
    why.append(f"We cannot absorb or pass on even {pct_text(pr.min_counter_pct)}: delist or find an alternate.")
    return "delist", None, None, None, why


def _with_scenarios(out: LineResult, e: Econ, sku: SkuInfo, p: float, p_eff: float, months: float, support_pts: float) -> LineResult:
    units_base = sku.units_month * months
    base_gmv = units_base * e.price
    base_margin = units_base * (e.price - e.old_landed)
    baseline = (base_gmv, base_margin)
    status_quo = Scenario(
        label="status quo", cost_pct=0.0, price=round(e.price, 2), units=round(units_base, 2), gmv=round(base_gmv, 2), margin_inr=round(base_margin, 2),
        margin_pct=round(base_margin / base_gmv * 100, 2) if base_gmv else None, gmv_delta=0.0, margin_delta=0.0,
    )
    sc = [status_quo]
    sc.append(scenario(e, "absorb the asked rise", p_eff, e.price, units_base, baseline, months, support_pts))
    sc.append(scenario(e, "pass the asked rise on", p_eff, e.eff_price(p_eff), units_base, baseline, months, support_pts))
    d = out.then_decision if out.decision == "delay" else out.decision
    label = "status quo"
    if d == "accept":
        label = "absorb the asked rise"
    elif d == "pass_through":
        label = "pass the asked rise on"
    elif d == "accept_partial" and out.counter_pct is not None:
        c = out.counter_pct
        price = e.eff_price(c) if out.counter_basis == "pass_through" else e.price
        sc.append(scenario(e, "counter", c, price, units_base, baseline, months))
        label = "counter"
    elif d == "delist":
        sc.append(Scenario(label="delist", cost_pct=0.0, price=round(e.price, 2), units=0.0, gmv=0.0, margin_inr=0.0, margin_pct=None, gmv_delta=round(-base_gmv, 2), margin_delta=round(-base_margin, 2)))
        label = "delist"
    return out.model_copy(update={"scenarios": sc, "recommended": label})


def _impact(ok: list[LineResult], horizon: int) -> dict[str, Any]:
    def total(label: str, key: str) -> float:
        return round(sum(s.__getattribute__(key) for r in ok for s in r.scenarios if s.label == (r.recommended if label == "recommended" else label)), 2)

    return {
        "horizon_days": horizon,
        "baseline_gmv": total("status quo", "gmv"),
        "baseline_margin_inr": total("status quo", "margin_inr"),
        "absorb": {"gmv_delta": total("absorb the asked rise", "gmv_delta"), "margin_delta": total("absorb the asked rise", "margin_delta")},
        "pass_through": {"gmv_delta": total("pass the asked rise on", "gmv_delta"), "margin_delta": total("pass the asked rise on", "margin_delta")},
        "recommended": {"gmv_delta": total("recommended", "gmv_delta"), "margin_delta": total("recommended", "margin_delta")},
    }


def _headline(overall: str, counts: dict[str, int], lines: list[LineResult]) -> str:
    n = len(lines)
    parts = ", ".join(f"{c} {d.replace('_', ' ')}" for d, c in sorted(counts.items(), key=lambda kv: -PRIORITY[kv[0]]))
    thens = {r.then_decision for r in lines if r.decision == "delay"}
    lead = {
        "accept": "Accept the revision",
        "accept_partial": "Counter: accept part of the revision",
        "pass_through": "Accept and pass the increase on to retail prices",
        "delay": "Ask for a later effective date" + (" and counter at the largest rise we can take" if "accept_partial" in thens else ""),
        "delist": "Delist or find an alternate for at least one SKU",
        "needs_review": "A person must review unmatched lines",
    }[overall]
    return f"{lead} ({n} line{'s' if n != 1 else ''}: {parts})." if n else "No price lines could be read and verified."


def counter_offer(ev: Evaluation) -> dict[str, Any]:
    ask_dates = sorted({r.ask_effective_date for r in ev.lines if r.ask_effective_date})
    lines = []
    for r in ev.lines:
        lines.append(
            {
                "sku_code": r.sku_code, "name": r.name, "decision": r.decision, "then_decision": r.then_decision, "asked_cost": r.new_cost, "old_cost": r.old_cost,
                "asked_pct": r.pct_change, "counter_cost": r.counter_cost, "counter_pct": r.counter_pct if r.decision in ("accept_partial",) or r.then_decision == "accept_partial" else r.effective_pct,
                "basis": r.counter_basis,
            }
        )
    asks: list[str] = []
    for sw in ev.sweeteners:
        window = int(((sw.assessment or {}).get("distribution") or {}).get("window_days", 30))
        for c in (sw.assessment or {}).get("counters", []):
            if c["kind"] == "threshold" and c.get("threshold") is not None:
                asks.append(f"the volume commitment were lowered to {c['threshold']:,.0f} units in {window} days")
            elif c["kind"] == "window" and c.get("window_days") is not None:
                asks.append(f"the {c['threshold']:,.0f} units were measured over {c['window_days']:g} days")
    return {"lines": lines, "effective_date_ask": ask_dates[0] if ask_dates else None, "sweetener_asks": asks}


def assumptions() -> dict[str, Any]:
    pr = policy.get().price_requests
    return {
        "notice_period_days": pr.notice_period_days, "max_acceptable_increase_pct": pr.max_acceptable_increase_pct, "min_counter_pct": pr.min_counter_pct,
        "horizon_days": pr.horizon_days, "max_competitor_gap_pct": pr.pass_through.max_competitor_gap_pct, "max_volume_loss_pct": pr.pass_through.max_volume_loss_pct,
        "pass_through_allowed": pr.pass_through.allow, "index_name": pr.justification.index_name, "index_change_pct": pr.justification.index_change_pct,
        "tolerance_pp": pr.justification.tolerance_pp, "elasticity_default": pr.elasticity.default, "min_probability": policy.get().negotiation.contingent.min_probability,
        "freight_pct": policy.get().research.freight_pct,
    }


# ---------- the reply: every number must be one the engine stated ----------


def _collect(x: Any, out: set[float]) -> None:
    if isinstance(x, bool) or x is None:
        return
    if isinstance(x, int | float):
        for v in (x, abs(x), x * 100):
            out.add(round(float(v), 4))
            out.add(round(float(v), 2))
            out.add(round(float(v), 1))
            out.add(float(round(v)))
    elif isinstance(x, str):
        for n in deals.numbers_in_text(x):
            out.add(n)
        for d in parse_dates(x, date(2026, 1, 1)) + [dd for dd in [_iso(x)] if dd]:
            out.update({float(d.day), float(d.year), float(d.month)})
    elif isinstance(x, dict):
        for v in x.values():
            _collect(v, out)
    elif isinstance(x, list | tuple):
        for v in x:
            _collect(v, out)


def email_facts(ev: Evaluation) -> dict[str, Any]:
    """What the reply writer is given: the engine's figures and the counter-offer, nothing else."""
    return {
        "vendor_id": ev.vendor_id,
        "decision": ev.decision,
        "headline": ev.headline,
        "received_date": ev.received_date,
        "requested_effective_date": ev.effective_date,
        "ask_effective_date": ev.counter_offer.get("effective_date_ask"),
        "notice_period_days": ev.assumptions["notice_period_days"],
        "justification": ev.justification,
        "lines": [
            {
                "sku": r.sku_code, "name": r.name, "decision": r.decision, "then": r.then_decision, "old_cost": r.old_cost, "asked_cost": r.new_cost,
                "asked_pct": None if r.pct_change is None else round(r.pct_change, 1), "counter_cost": r.counter_cost,
                "counter_pct": None if r.counter_pct is None else round(r.counter_pct, 1), "new_margin_pct": None if r.new_margin_pct is None else round(r.new_margin_pct, 1),
                "gap_if_passed_pct": None if r.gap_if_passed_pct is None else round(r.gap_if_passed_pct, 1), "reasons": r.reasons,
            }
            for r in ev.lines
        ],
        "sweeteners": [
            {"label": s.label, "decision": s.decision, "call": s.call, "probability": s.probability, "counted_pts": s.counted_pts, "value_pts": s.value_pts, "net_pts": s.net_pts}
            for s in ev.sweeteners
        ],
        "sweetener_asks": ev.counter_offer.get("sweetener_asks", []),
    }


def allowed_numbers(ev: Evaluation) -> set[float]:
    out: set[float] = set()
    _collect(email_facts(ev), out)
    _collect(ev.counter_offer, out)
    _collect([r.model_dump(mode="json", exclude={"scenarios", "quote"}) for r in ev.lines], out)
    for s in ev.sweeteners:
        _collect({k: v for k, v in s.model_dump(mode="json").items() if k != "assessment"}, out)
        if s.assessment:
            out.update(deals.fact_numbers(deals.DealReport(assessments=[deals.DealAssessment.model_validate(s.assessment)], assumptions=deals.assumptions())))
    _collect([ev.received_date, ev.effective_date, ev.today], out)
    return out


def strike_unsupported(text: str, ev: Evaluation) -> tuple[str, list[str]]:
    """Keep the sentences whose every number the engine stated; return (kept text, struck sentences). Line breaks are kept."""
    allowed = allowed_numbers(ev)
    codes = re.compile("|".join(re.escape(r.sku_code) for r in ev.lines) or "(?!)")  # "GW-01" is a code, not the number 1
    kept_lines: list[str] = []
    struck: list[str] = []
    for raw in text.strip().split("\n"):
        if not raw.strip():
            kept_lines.append("")
            continue
        parts = re.split(r"(?<=[.!?])\s+", raw)
        kept = []
        for sentence in parts:
            if all(deals.number_ok(n, allowed) for n in deals.numbers_in_text(codes.sub(" ", sentence))):
                kept.append(sentence)
            else:
                struck.append(sentence.strip())
        if kept:
            kept_lines.append(" ".join(kept))
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()
    return body, struck


def _d(iso: str | None) -> str:
    d = _iso(iso)
    return d.strftime("%-d %B %Y") if d else "the requested date"


def rs(x: float) -> str:
    return f"₹{x:,.2f}"


def template_reply(ev: Evaluation, vendor_brand: str, contact: str) -> PriceReplyDraft:
    """The deterministic reply when no model text is available: built only from the engine's figures."""
    lines = []
    for r in ev.lines:
        label = f"{r.sku_code} ({r.name})" if r.name else r.sku_code
        then = r.then_decision if r.decision == "delay" else r.decision
        if r.status != "ok":
            lines.append(f"- {label}: we need to confirm this line with you.")
        elif then in ("accept", "pass_through"):
            lines.append(f"- {label}: accepted at {rs(r.counter_cost or r.new_cost or 0)} ({(r.effective_pct or 0):.1f}%).")
        elif then == "accept_partial":
            lines.append(f"- {label}: we can accept {(r.counter_pct or 0):.1f}% (cost {rs(r.counter_cost or 0)}) against the {(r.pct_change or 0):.1f}% asked.")
        else:
            lines.append(f"- {label}: we are unable to take this increase and are reviewing alternatives.")
    paras = [f"Dear {contact},", f"Thank you for your note of {_d(ev.received_date)} on the revised prices. Our position, line by line:", "\n".join(lines)]
    if ev.counter_offer.get("effective_date_ask"):
        paras.append(f"On timing, our agreement asks for {ev.assumptions['notice_period_days']} days notice, so the earliest effective date we can agree is {_d(ev.counter_offer['effective_date_ask'])}.")
    for sw in ev.sweeteners:
        if sw.kind == "support_if_full_acceptance":
            paras.append(f"We note your offer of {sw.label} and will plan activity against it.")
        else:
            paras.append(f"On your offer to {sw.label}: on our forecast the chance of reaching it is {(sw.probability or 0) * 100:.1f}%, so we cannot count on it.")
    if ev.counter_offer.get("sweetener_asks"):
        paras.append("We would reconsider if " + ", or if ".join(ev.counter_offer["sweetener_asks"]) + ".")
    paras.append("Please let us know if this works.\n\nRegards,\nCategory team")
    return PriceReplyDraft(subject=f"Re: price revision - {vendor_brand}", body="\n\n".join(paras))
