"""Promotions and event planner: the deterministic engine. Never imports llm.

For one sale event of the playbook's calendar it decides, from today's ops data and the playbook only:

* which SKUs go on promo, and at what depth. Baseline demand is the SKU's recent daily rate (ops sales) lifted by the event's traffic
  lift; a discount multiplies it by the category's uplift curve ``(1 - depth) ^ elasticity`` (capped), and part of the extra units is
  pulled forward from after the event. For every allowed depth the engine works out the extra margin (promo margin plus the vendor
  funding we ask for, minus the margin the same days would have earned, minus the pulled-forward units, minus what a promoted SKU takes
  from a near-duplicate sibling that is not on promo) and keeps the depth with the best extra margin that still holds the promo margin
  floor with a funding ask the playbook allows;
* stock: baseline demand until the event, then the event's promo demand (plus a safety buffer) against on-hand stock and the open POs
  (arrival dates from the PO tracker). A depth that would stock out before the event ends is capped, or the engine suggests a stock-up PO
  when one can still land in time. The deeper "deep option" that would have stocked out is kept in the output;
* the vendor funding ask (share of the markdown) and, when a vendor offered funding on a condition ("50% if the range sells N units"),
  its value through the deal evaluator's Monte Carlo (``deals.assess_one``): a condition that is unlikely counts as 0 and the offer is countered.

Percent values in the output are fractions. Money is rupees. A SKU key is ``<event>:<vendor>:<sku>``, a vendor key ``<event>:<vendor>``."""

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from typing import Any

from app import deals, policy
from app.config import settings
from app.errors import UnknownPromoEvent
from app.ops import data as od
from app.ops import metrics as om
from app.ops import pos
from app.ops.promotions import data as pdata
from app.policy import PromoEvent, Promotions
from app.pricereq import SkuInfo, vendor_facts
from app.schemas import DealCondition, DealTerm

EPS = 1e-9
_WORDS = re.compile(r"[a-z0-9]+")


# ---------- small maths ----------


def events() -> list[PromoEvent]:
    return list(policy.get().promotions.events)


def event(event_id: str) -> PromoEvent:
    found = next((e for e in events() if e.id == event_id), None)
    if found is None:
        raise UnknownPromoEvent(event_id)
    return found


def event_days(ev: PromoEvent) -> list[date]:
    a, b = date.fromisoformat(ev.start), date.fromisoformat(ev.end)
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def uplift(category: str, depth: float) -> float:
    """Demand multiplier at a discount ``depth`` (a fraction): (1 - depth) ^ elasticity, capped. 1.0 at no discount."""
    u = policy.get().promotions.uplift
    e = u.by_category.get(category, u.default_elasticity)
    return min(u.max_multiplier, max(1.0, (1 - depth) ** e)) if depth > 0 else 1.0


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of the words (letters and digits) of two SKU names."""
    wa, wb = set(_WORDS.findall(a.lower())), set(_WORDS.findall(b.lower()))
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def round_up(x: float, step: int) -> int:
    return int(math.ceil(x / step - EPS) * step)


# ---------- facts about a SKU ----------


@dataclass(frozen=True)
class Fact:
    code: str
    vendor_id: str
    brand: str
    name: str
    category: str
    price: float
    cost: float
    mrp: float
    floor: float  # regular margin floor (fraction)
    rate: float  # baseline units per day
    on_hand: int
    lead_days: int
    arrivals: tuple[tuple[date, int, str], ...]  # (arrival date, open qty, po id)


def facts() -> dict[str, Fact]:
    return _facts(str(settings.data_dir), policy.policy_hash())


@cache
def _facts(data_dir: str, policy_hash: str) -> dict[str, Fact]:  # the keys only identify the inputs
    d = od.load()
    ops = policy.get().operations
    out: dict[str, Fact] = {}
    open_lines: dict[str, list[tuple[date, int, str]]] = {}
    for po_id in pos.open_po_ids(d):
        for line in pos.po_lines(d, po_id):
            if line.status != "open":
                continue
            risk = pos.line_risk(d, ops, line)
            if risk["open_qty"] > 0:
                open_lines.setdefault(line.sku_code, []).append((date.fromisoformat(risk["arrival"]), int(risk["open_qty"]), po_id))
    for vid, v in d.vendors.items():
        vf = vendor_facts(vid)
        for code in d.skus_by_vendor.get(vid, []):
            info: SkuInfo | None = vf.skus.get(code)
            if info is None or not info.price or info.cost is None:
                continue
            out[code] = Fact(
                code, vid, v.brand, d.skus[code].name, info.category, float(info.price), float(info.cost), float(d.skus[code].mrp), float(info.floor),
                om.daily_rate(d, ops, code), om.on_hand(d, code), v.lead_time_days, tuple(sorted(open_lines.get(code, []))),
            )
    return out


# ---------- stock ----------


def can_replenish(f: Fact, ev_days: list[date], pr: Promotions) -> bool:
    """True when a fresh order placed today can still land before the event (lead time plus the receiving buffer)."""
    return (ev_days[0] - od.load().as_of).days >= f.lead_days + pr.stock.receiving_buffer_days


def _arrivals(f: Fact) -> dict[date, float]:
    out: dict[date, float] = {}
    for dt, qty, _ in f.arrivals:
        out[dt] = out.get(dt, 0.0) + qty
    return out


def stock_trajectory(f: Fact, ev_days: list[date]) -> float:
    """Stock on the first event day if nothing more is ordered: today's stock, open POs on their arrival dates, baseline demand until then."""
    d = od.load()
    arr = _arrivals(f)
    stock, day = float(f.on_hand), d.as_of
    while day < ev_days[0]:
        stock += arr.get(day, 0.0)
        stock = max(stock - f.rate, 0.0)
        day += timedelta(days=1)
    return stock


def stock_at_start(f: Fact, ev_days: list[date], pr: Promotions, extra_units: int = 0) -> float:
    """Stock the event starts with. When an order can still land in time, normal replenishment is assumed to keep at least
    ``stock.baseline_cover_days`` of cover until the event; otherwise it is the trajectory of today's stock and open POs.
    ``extra_units`` is a stock-up PO (only possible when an order can land in time)."""
    base = stock_trajectory(f, ev_days)
    if can_replenish(f, ev_days, pr):
        return max(base, f.rate * pr.stock.baseline_cover_days) + extra_units
    return base


def simulate_stock(f: Fact, ev_days: list[date], daily_event: float, pr: Promotions, extra_units: int = 0) -> dict[str, Any]:
    """Stock day by day over the event: ``daily_event`` units a day against the stock at the start plus POs arriving during the event.
    Returns stock at the start, the first event day with not enough stock (1-based) and the units short."""
    arr = _arrivals(f)
    stock = stock_at_start(f, ev_days, pr, extra_units)
    at_start = stock
    stockout_day: int | None = None
    short = 0.0
    for i, day in enumerate(ev_days, start=1):
        if i > 1:
            stock += arr.get(day, 0.0)
        if stock + EPS < daily_event:
            short += daily_event - stock
            if stockout_day is None:
                stockout_day = i
            stock = 0.0
        else:
            stock -= daily_event
    return {"stock_at_start": at_start, "stockout_day": stockout_day, "short_units": short}


# ---------- one SKU at one depth ----------


def _promo_price(price: float, depth: float) -> float:
    return float(round(price * (1 - depth)))


def economics(f: Fact, ev: PromoEvent, n_days: int, depth: float, pr: Promotions) -> dict[str, Any]:
    """Units, margin and funding need of the SKU at ``depth`` (a fraction), before the stock check."""
    lift = 1 + ev.traffic_lift_pct / 100
    base_units = f.rate * n_days * lift
    mult = uplift(f.category, depth)
    units = base_units * mult
    pp = _promo_price(f.price, depth)
    eff_depth = 1 - pp / f.price
    markdown = f.price - pp
    unit_margin_reg = f.price - f.cost
    floor_p = f.floor - pr.discount.floor_below_regular_pp / 100
    margin_unfunded = (pp - f.cost) / pp if pp else 0.0
    s_req = max(0.0, (floor_p * pp - (pp - f.cost)) / markdown) if markdown > EPS else 0.0
    target = pr.funding.target_share_by_category.get(f.category, pr.funding.target_share_pct) / 100
    ask_share = max(target, s_req)
    ask_ok = s_req <= pr.funding.max_ask_share_pct / 100 + EPS
    counted_share = min(ask_share, target)  # funding beyond the target share holds the floor but is not counted in the ranking
    funding_ask = ask_share * markdown * units
    funding_counted = counted_share * markdown * units
    promo_margin = units * (pp - f.cost) + funding_counted
    base_margin = base_units * unit_margin_reg
    pull = pr.uplift.pull_forward_pct / 100 * (units - base_units) * unit_margin_reg
    return {
        "depth": depth, "eff_depth": eff_depth, "promo_price": pp, "markdown": markdown, "uplift": mult, "base_units": base_units, "units": units,
        "incremental_units": units - base_units, "gmv": units * pp, "margin_unfunded_pct": margin_unfunded, "floor_promo_pct": floor_p,
        "s_req": s_req, "ask_share": ask_share, "ask_ok": ask_ok, "funding_ask_inr": funding_ask, "funding_counted_inr": funding_counted,
        "margin_at_ask_pct": (pp - f.cost + ask_share * markdown) / pp if pp else 0.0, "promo_margin_inr": promo_margin, "base_margin_inr": base_margin,
        "pull_forward_inr": pull, "net_before_cannibalisation_inr": promo_margin - base_margin - pull,
    }


def _stock_check(f: Fact, ev_days: list[date], e: dict[str, Any], pr: Promotions) -> dict[str, Any]:
    buf = 1 + pr.stock.safety_buffer_pct / 100
    daily = e["units"] / len(ev_days) * buf
    sim = simulate_stock(f, ev_days, daily, pr)
    price = e["promo_price"]
    return {**sim, "daily_event_demand": daily, "need_units": daily * len(ev_days), "lost_gmv_inr": sim["short_units"] * price, "ok": sim["stockout_day"] is None}


def _stock_up(f: Fact, ev_days: list[date], e: dict[str, Any], pr: Promotions, as_of: date) -> dict[str, Any] | None:
    """A PO that fixes the stock-out, if it can still land before the event (lead time plus receiving buffer) and stays under the cap."""
    start = ev_days[0]
    arrive = as_of + timedelta(days=f.lead_days)
    latest = start - timedelta(days=pr.stock.receiving_buffer_days)
    order_by = latest - timedelta(days=f.lead_days)
    if not can_replenish(f, ev_days, pr):
        return {"feasible": False, "reason": f"the vendor's lead time ({f.lead_days} days) cannot land stock before {latest.isoformat()}", "order_by": order_by.isoformat(), "arrives": arrive.isoformat()}
    buf = 1 + pr.stock.safety_buffer_pct / 100
    daily = e["units"] / len(ev_days) * buf
    step = pr.stock.pack_round_units
    qty = 0
    for _ in range(5000):
        if simulate_stock(f, ev_days, daily, pr, qty)["stockout_day"] is None:
            break
        qty += step
    cap = f.rate * pr.stock.max_stock_up_cover_days
    if qty > cap + EPS:
        return {"feasible": False, "reason": f"the stock-up ({qty} units) would take cover beyond {pr.stock.max_stock_up_cover_days:g} days", "order_by": order_by.isoformat(), "arrives": arrive.isoformat()}
    return {"feasible": True, "qty": qty, "cost_inr": round(qty * f.cost, 2), "order_by": order_by.isoformat(), "arrives": arrive.isoformat(), "lead_days": f.lead_days}


# ---------- the plan ----------


def _best_depth(f: Fact, ev: PromoEvent, n_days: int, pr: Promotions, allowed: list[float], cannibal: dict[str, float]) -> tuple[float, dict[str, Any]] | None:
    best: tuple[float, dict[str, Any]] | None = None
    for depth in allowed:
        e = economics(f, ev, n_days, depth, pr)
        if not e["ask_ok"]:
            continue
        e["cannibalisation_inr"] = cannibal.get(f.code, 0.0) * e["incremental_units"]
        e["net_inr"] = e["net_before_cannibalisation_inr"] - e["cannibalisation_inr"]
        if best is None or e["net_inr"] > best[1]["net_inr"] + EPS:
            best = (depth, e)
    return best


def _siblings(fs: dict[str, Fact], pr: Promotions) -> dict[str, list[tuple[str, float]]]:
    c = pr.cannibalisation
    out: dict[str, list[tuple[str, float]]] = {}
    for a in fs.values():
        for b in fs.values():
            if a.code >= b.code or a.vendor_id != b.vendor_id:
                continue
            sim = similarity(a.name, b.name)
            gap = abs(a.price - b.price) / min(a.price, b.price) * 100
            if sim + EPS >= c.similarity_threshold and gap <= c.max_price_gap_pct + EPS:
                out.setdefault(a.code, []).append((b.code, sim))
                out.setdefault(b.code, []).append((a.code, sim))
    return out


def _plan_rows(ev: PromoEvent, fs: dict[str, Fact], pr: Promotions) -> list[dict[str, Any]]:
    d = od.load()
    ev_days = event_days(ev)
    n = len(ev_days)
    sibs = _siblings(fs, pr)
    allowed = [x / 100 for x in pr.discount.steps_pct if x <= pr.discount.max_pct + EPS]
    chosen: dict[str, tuple[float, dict[str, Any]]] = {}
    reasons: dict[str, str] = {}

    # eligibility on stock before any promo: the SKU must have stock at the start
    eligible: dict[str, Fact] = {}
    for code, f in fs.items():
        cover_units = stock_at_start(f, ev_days, pr)
        cover = cover_units / f.rate if f.rate > 0 else 0.0
        if f.rate <= 0:
            reasons[code] = "not_selling"
        elif cover + EPS < pr.stock.min_cover_days:
            reasons[code] = "thin_stock"
        else:
            eligible[code] = f

    # The promoted set and the cannibalisation cost depend on each other. Start from "every eligible SKU is on promo" (no sibling loses
    # sales to a non-promoted one) and drop SKUs that stop paying, until the set stops changing.
    promoted: set[str] = set(eligible)
    for _ in range(5):
        new_chosen: dict[str, tuple[float, dict[str, Any]]] = {}
        for code, f in eligible.items():
            best = _best_depth(f, ev, n, pr, allowed, cannibal_cost_per_unit(f, fs, sibs, promoted, pr))
            if best is not None and best[1]["net_inr"] + EPS >= pr.candidates.min_incremental_margin_inr:
                new_chosen[code] = best
        ranked = sorted(new_chosen, key=lambda c: (-new_chosen[c][1]["net_inr"], c))[: pr.candidates.max_skus_per_event]
        new_set = set(ranked)
        chosen = {c: new_chosen[c] for c in ranked}
        if new_set == promoted:
            break
        promoted = new_set

    rows: list[dict[str, Any]] = []
    for rank, code in enumerate(sorted(chosen, key=lambda c: (-chosen[c][1]["net_inr"], c)), start=1):
        f = fs[code]
        depth, e = chosen[code]
        row = _row(f, ev, ev_days, pr, depth, e, d.as_of)
        row["banner_rank"] = rank
        row["banner_candidate"] = rank <= ev.banner_slots
        row["cannibalisation"] = _cannibal_view(code, fs, sibs, promoted, pr, e)
        if row["status"] == "planned":
            rows.append(row)
        else:
            reasons[code] = row["exclusion"]["code"]
            rows.append(row)
    seen = {r["sku_code"] for r in rows}
    for code, f in fs.items():
        if code in seen:
            continue
        reason, view = reasons.get(code, "unprofitable"), None
        if code in eligible:  # profitable on its own but not once the sibling it would take sales from is counted
            alone = _best_depth(f, ev, n, pr, allowed, {})
            if alone is not None and alone[1]["net_inr"] + EPS >= pr.candidates.min_incremental_margin_inr and code in sibs:
                reason = "cannibalises"
                e2 = {**alone[1], "cannibalisation_inr": 0.0}
                cost = cannibal_cost_per_unit(f, fs, sibs, promoted, pr).get(code, 0.0) * alone[1]["incremental_units"]
                view = _cannibal_view(code, fs, sibs, promoted, pr, {**e2, "cannibalisation_inr": cost})
            elif alone is not None and alone[1]["net_inr"] + EPS >= pr.candidates.min_incremental_margin_inr:
                reason = "outranked"
        rows.append(_excluded_row(f, ev, ev_days, pr, reason, view))
    rows.sort(key=lambda r: (r["status"] != "planned", -(r.get("incremental_margin_inr") or 0), r["sku_code"]))
    return rows


def cannibal_cost_per_unit(f: Fact, fs: dict[str, Fact], sibs: dict[str, list[tuple[str, float]]], promoted: set[str], pr: Promotions) -> dict[str, float]:
    """Margin lost per extra unit of ``f``: the share of those units taken from the most similar sibling that is not on promo."""
    share = pr.cannibalisation.cannibalised_share_pct / 100
    off = [(sim, code) for code, sim in sibs.get(f.code, []) if code not in promoted]
    if not off or share <= 0:
        return {}
    _sim, code = max(off)
    s = fs[code]
    return {f.code: share * (s.price - s.cost)}


def _cannibal_view(code: str, fs: dict[str, Fact], sibs: dict[str, list[tuple[str, float]]], promoted: set[str], pr: Promotions, e: dict[str, Any]) -> dict[str, Any] | None:
    mine = sibs.get(code, [])
    if not mine:
        return None
    return {
        "siblings": [{"sku_code": c, "name": fs[c].name, "similarity": round(sim, 3), "on_promo": c in promoted} for c, sim in sorted(mine, key=lambda x: (-x[1], x[0]))],
        "cost_inr": round(e.get("cannibalisation_inr", 0.0), 2),
        "share_pct": pr.cannibalisation.cannibalised_share_pct,
    }


def _row(f: Fact, ev: PromoEvent, ev_days: list[date], pr: Promotions, depth: float, e: dict[str, Any], as_of: date) -> dict[str, Any]:
    """The SKU's plan row with the stock check applied: stock-up PO, or a shallower depth, or out."""
    deep = _stock_check(f, ev_days, e, pr)
    deep_option = None
    stock_up = None
    final_e, final_depth, chk = e, depth, deep
    status, exclusion = "planned", None
    if not deep["ok"]:
        deep_option = {
            "depth": e["eff_depth"], "promo_price": e["promo_price"], "uplift": e["uplift"], "units": e["units"], "stockout_day": deep["stockout_day"],
            "short_units": deep["short_units"], "lost_gmv_inr": deep["lost_gmv_inr"], "net_inr": e["net_inr"],
        }
        su = _stock_up(f, ev_days, e, pr, as_of)
        if su and su["feasible"]:
            stock_up = su
            chk = {**deep, "ok": True, "stockout_day": None, "short_units": 0.0, "lost_gmv_inr": 0.0}
        else:
            deep_option["why"] = su["reason"] if su else "no stock-up possible"
            capped = None
            for d2 in sorted((x for x in [s / 100 for s in pr.discount.steps_pct] if x < depth - EPS), reverse=True):
                e2 = economics(f, ev, len(ev_days), d2, pr)
                if not e2["ask_ok"]:
                    continue
                e2["cannibalisation_inr"] = e["cannibalisation_inr"] / e["incremental_units"] * e2["incremental_units"] if e["incremental_units"] else 0.0
                e2["net_inr"] = e2["net_before_cannibalisation_inr"] - e2["cannibalisation_inr"]
                c2 = _stock_check(f, ev_days, e2, pr)
                if c2["ok"] and e2["net_inr"] + EPS >= pr.candidates.min_incremental_margin_inr:
                    capped = (d2, e2, c2)
                    break
            if capped is None:
                status, exclusion = "excluded", {"code": "stock_out", "text": "A discount deep enough to pay would stock out before the event ends, and a shallower one earns too little."}
            else:
                final_depth, final_e, chk = capped
    row = {
        "sku_code": f.code, "vendor_id": f.vendor_id, "brand": f.brand, "name": f.name, "category": f.category, "status": status, "exclusion": exclusion,
        "selling_price": f.price, "cost": f.cost, "mrp": f.mrp, "daily_units": round(f.rate, 2), "on_hand": f.on_hand, "lead_days": f.lead_days,
        "open_pos": [{"po_id": po, "qty": q, "arrives": dt.isoformat()} for dt, q, po in f.arrivals],
        "discount_pct": final_e["eff_depth"], "promo_price": final_e["promo_price"], "uplift": final_e["uplift"],
        "baseline_units": final_e["base_units"], "promo_units": final_e["units"], "incremental_units": final_e["incremental_units"], "gmv": final_e["gmv"],
        "margin_unfunded_pct": final_e["margin_unfunded_pct"], "margin_at_ask_pct": final_e["margin_at_ask_pct"], "floor_promo_pct": final_e["floor_promo_pct"],
        "funding_needed_share": final_e["s_req"], "funding_ask_share": final_e["ask_share"], "funding_ask_inr": final_e["funding_ask_inr"],
        "incremental_margin_inr": final_e["net_inr"], "pull_forward_inr": final_e["pull_forward_inr"], "cannibalisation_inr": final_e.get("cannibalisation_inr", 0.0),
        "stock_at_start": chk["stock_at_start"], "need_units": chk["need_units"], "stockout_day": chk["stockout_day"], "stock_ok": chk["ok"],
        "stock_up": stock_up if stock_up and stock_up.get("feasible") else None, "stock_up_blocked": stock_up if stock_up and not stock_up.get("feasible") else None,
        "capped_by_stock": final_depth < depth - EPS, "deep_option": deep_option,
    }
    return row


def _excluded_row(f: Fact, ev: PromoEvent, ev_days: list[date], pr: Promotions, code: str, view: dict[str, Any] | None = None) -> dict[str, Any]:
    text = {
        "cannibalises": "Worth promoting on its own, but it would take more margin from a near-duplicate sibling that is not on promo than it adds.",
        "outranked": "Worth promoting, but the event's SKU limit left it out: better SKUs took the places.",
        "thin_stock": "Stock at the start of the event covers fewer days than the playbook's minimum: fix supply first, a promo would stock it out.",
        "not_selling": "The SKU is not selling, so there is no baseline to lift.",
        "unprofitable": "No allowed depth earns the SKU a worthwhile extra margin once the funding the vendor can be asked for, the units pulled forward and the sales taken from siblings are counted.",
    }.get(code, code)
    sim = {"stock_at_start": stock_at_start(f, ev_days, pr)}
    return {
        "sku_code": f.code, "vendor_id": f.vendor_id, "brand": f.brand, "name": f.name, "category": f.category, "status": "excluded", "exclusion": {"code": code, "text": text},
        "selling_price": f.price, "cost": f.cost, "mrp": f.mrp, "daily_units": round(f.rate, 2), "on_hand": f.on_hand, "lead_days": f.lead_days,
        "open_pos": [{"po_id": po, "qty": q, "arrives": dt.isoformat()} for dt, q, po in f.arrivals],
        "stock_at_start": sim["stock_at_start"], "incremental_margin_inr": None, "stock_up": None, "stock_up_blocked": None, "capped_by_stock": False, "deep_option": None,
        "banner_rank": None, "banner_candidate": False, "cannibalisation": view,
    }


# ---------- vendors: the funding ask and the value of an offer ----------


def _planned(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["status"] == "planned"]


def vendor_blocks(ev: PromoEvent, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    by_vendor: dict[str, list[dict[str, Any]]] = {}
    for r in _planned(rows):
        by_vendor.setdefault(r["vendor_id"], []).append(r)
    for vid in sorted(by_vendor):
        mine = by_vendor[vid]
        markdown = sum((r["selling_price"] - r["promo_price"]) * r["promo_units"] for r in mine)
        ask = sum(r["funding_ask_inr"] for r in mine)
        out.append(
            {
                "vendor_id": vid, "brand": mine[0]["brand"], "skus": [r["sku_code"] for r in mine], "n_skus": len(mine), "markdown_inr": markdown, "ask_inr": ask,
                "ask_share": ask / markdown if markdown else 0.0, "gmv": sum(r["gmv"] for r in mine), "best_banner_rank": min(r["banner_rank"] for r in mine),
            }
        )
    return out


def _vendor_range_facts(ev: PromoEvent, rows: list[dict[str, Any]], vendor_id: str, fs: dict[str, Fact], n_days: int) -> tuple[deals.SkuFact, ...]:
    """Every SKU of the vendor over the event window: promo demand for the SKUs on promo, baseline demand (with the traffic lift) for the rest."""
    promo = {r["sku_code"]: r for r in _planned(rows) if r["vendor_id"] == vendor_id}
    out = []
    for code in sorted(c for c, f in fs.items() if f.vendor_id == vendor_id):
        f = fs[code]
        r = promo.get(code)
        units = r["promo_units"] if r else f.rate * n_days * (1 + ev.traffic_lift_pct / 100)
        price = r["promo_price"] if r else f.price
        floor_pct = (f.floor - policy.get().promotions.discount.floor_below_regular_pp / 100) * 100
        out.append(deals.SkuFact(code, f.category, units / n_days * 30.0, float(price), f.cost, 0, floor_pct))
    return tuple(out)


def value_offer(ev: PromoEvent, rows: list[dict[str, Any]], vendor_id: str, offer: dict[str, Any]) -> dict[str, Any]:
    """The value of one vendor's funding offer. ``offer``: share_pct, scope (SKU codes, empty = every promoted SKU of the vendor),
    threshold_units (a sales target for the vendor's range over the event, or None), banner_top_n (or None).
    Returns face and counted rupees, the probability of the condition, the deal evaluator's assessment and what we would counter with."""
    pr = policy.get().promotions
    fs = facts()
    n = len(event_days(ev))
    promoted = [r for r in _planned(rows) if r["vendor_id"] == vendor_id and (not offer.get("scope") or r["sku_code"] in offer["scope"])]
    share = float(offer.get("share_pct") or 0.0) / 100
    thr, banner = offer.get("threshold_units"), offer.get("banner_top_n")
    markdown = sum((r["selling_price"] - r["promo_price"]) * r["promo_units"] for r in promoted)
    gmv = sum(r["promo_price"] * r["promo_units"] for r in promoted)
    face = share * markdown
    ask = sum(r["funding_ask_inr"] for r in promoted)
    out: dict[str, Any] = {
        "vendor_id": vendor_id, "share": share, "scope": [r["sku_code"] for r in promoted], "threshold_units": thr, "banner_top_n": banner, "markdown_inr": markdown,
        "face_inr": face, "counted_inr": 0.0, "banner_cost_inr": 0.0, "probability": None, "decision": "no_offer", "call": "", "assessment": None, "ask_inr": ask,
        "covers_ask_pct": 0.0,
    }
    if not promoted or markdown <= 0:
        out["call"] = "None of the offer's SKUs is on promo, so there is nothing for it to fund."
        return out
    notes: list[str] = []
    banner_ok = True
    if banner:
        banner_ok = int(banner) <= ev.banner_slots
        if banner_ok:
            out["banner_cost_inr"] = pr.funding.banner_slot_cost_inr
            notes.append(f"Guaranteeing the top-{int(banner)} banner costs us {pr.funding.banner_slot_cost_inr:,.0f} of banner value, taken off the funding.")
        else:
            notes.append(f"The event has only {ev.banner_slots} top banner slots, so a top-{int(banner)} banner cannot be promised.")
    if thr:
        base_pct = sum((r["promo_price"] - r["cost"]) * r["promo_units"] for r in promoted) / gmv * 100 if gmv else 0.0
        bonus_pts = face / gmv * 100 if gmv else 0.0
        term = DealTerm(
            id=f"promo-{vendor_id}", kind="conditional", term="margin_pct", value=round(bonus_pts, 4), unit="pct",
            condition=DealCondition(metric="units", threshold=float(thr), window_days=n, scope=[]), scope=[r["sku_code"] for r in promoted],
            quote=f"{share * 100:g}% of the markdown if the range sells {thr:,.0f} units", turn=1, source="application",
        )
        ctx = deals.Context(_vendor_range_facts(ev, rows, vendor_id, fs, n), base_margin_pct=base_pct, ramp=(1.0,))
        a = deals.assess_one(term, None, ctx)
        out["assessment"] = a.model_dump(mode="json")
        out["probability"] = a.probability
        out["required_pts"] = a.required_pts
        counted = a.counted_bonus_pts / 100 * gmv
        call = a.call
        rejected = a.decision == "reject_structure"
    else:
        counted = face
        rejected = False
        call = f"A flat {share * 100:g}% of the markdown is worth {face:,.0f}; we asked for {ask:,.0f}."
    counted = max(0.0, counted - out["banner_cost_inr"]) if banner_ok else 0.0
    if not banner_ok:
        rejected = True
    out["counted_inr"] = round(counted, 2)
    out["covers_ask_pct"] = counted / ask if ask else 0.0
    out["decision"] = "reject_structure" if rejected else "accept" if counted + EPS >= ask else "counter"
    out["call"] = " ".join([call, *notes]).strip()
    return out


def counter_for(block: dict[str, Any], offered: dict[str, Any] | None) -> dict[str, Any]:
    """What we say back. ``kind``: ask (no offer yet), counter (the deal evaluator's counter to a structure it rejected), top_up (the share
    offered is below what we need), firm_up (the share is enough but its condition makes it worth less than the ask), accept."""
    if offered is None or offered.get("decision") == "no_offer":
        return {"kind": "ask", "text": f"Ask {block['brand']} to fund {block['ask_share'] * 100:.0f}% of the markdown."}
    if offered.get("decision") == "declined":
        return {"kind": "ask", "text": f"Ask {block['brand']} whether a smaller share is possible."}
    a = offered.get("assessment")
    if offered.get("decision") == "reject_structure" and a and a.get("counters"):
        rec = a.get("recommended_counter")
        c = a["counters"][rec if rec is not None else 0]
        return {"kind": "counter", "text": c["text"], "counter": c}
    if offered["counted_inr"] + EPS >= offered["ask_inr"]:
        return {"kind": "accept", "text": "The offer covers the ask."}
    if offered["share"] + EPS < block["ask_share"]:
        return {"kind": "top_up", "text": f"Ask {block['brand']} to raise the share to {block['ask_share'] * 100:.0f}% of the markdown."}
    return {"kind": "firm_up", "text": f"Ask {block['brand']} to lower the sales target or make the share unconditional, so that it counts in full."}


# ---------- the event ----------


def build(event_id: str) -> dict[str, Any]:
    ev = event(event_id)
    pr = policy.get().promotions
    fs = facts()
    rows = _plan_rows(ev, fs, pr)
    planned = _planned(rows)
    n = len(event_days(ev))
    d = od.load()
    pos_rows = stock_up_pos(ev, rows)
    totals = {
        "planned_skus": len(planned),
        "excluded_skus": len(rows) - len(planned),
        "gmv_inr": sum(r["gmv"] for r in planned),
        "units": sum(r["promo_units"] for r in planned),
        "incremental_margin_inr": sum(r["incremental_margin_inr"] for r in planned),
        "funding_ask_inr": sum(r["funding_ask_inr"] for r in planned),
        "stock_up_inr": sum(p["cost_inr"] for p in pos_rows),
        "stock_up_units": sum(p["qty"] for p in pos_rows),
        "margin_unfunded_pct": (sum((r["promo_price"] - r["cost"]) * r["promo_units"] for r in planned) / sum(r["gmv"] for r in planned)) if planned else 0.0,
        "margin_at_ask_pct": (sum((r["promo_price"] - r["cost"] + r["funding_ask_share"] * (r["selling_price"] - r["promo_price"])) * r["promo_units"] for r in planned) / sum(r["gmv"] for r in planned)) if planned else 0.0,
        "capped_by_stock": sum(1 for r in planned if r["capped_by_stock"]),
        "stock_up_pos": len(pos_rows),
    }
    return {
        "event": {"id": ev.id, "name": ev.name, "start": ev.start, "end": ev.end, "days": n, "traffic_lift_pct": ev.traffic_lift_pct, "banner_slots": ev.banner_slots, "days_away": (date.fromisoformat(ev.start) - d.as_of).days},
        "as_of": d.as_of.isoformat(),
        "rows": rows,
        "vendors": vendor_blocks(ev, rows),
        "pos": pos_rows,
        "totals": totals,
    }


def stock_up_pos(ev: PromoEvent, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Suggested stock-up POs, one per vendor, lines per SKU."""
    by: dict[str, list[dict[str, Any]]] = {}
    for r in _planned(rows):
        if r["stock_up"]:
            by.setdefault(r["vendor_id"], []).append(r)
    out = []
    for vid in sorted(by):
        lines = [{"sku_code": r["sku_code"], "name": r["name"], "qty": r["stock_up"]["qty"], "cost": r["cost"], "cost_inr": r["stock_up"]["cost_inr"]} for r in by[vid]]
        out.append(
            {
                "po_ref": f"PO-PROMO-{ev.id}-{vid}", "vendor_id": vid, "brand": by[vid][0]["brand"], "lines": lines, "qty": sum(x["qty"] for x in lines), "cost_inr": round(sum(x["cost_inr"] for x in lines), 2),
                "order_by": min(r["stock_up"]["order_by"] for r in by[vid]), "arrives": max(r["stock_up"]["arrives"] for r in by[vid]),
            }
        )
    return out


@cache
def _build(data_dir: str, policy_hash: str, event_id: str, data_hash: str) -> dict[str, Any]:  # keys only identify the inputs
    return build(event_id)


def plan(event_id: str) -> dict[str, Any]:
    return _build(str(settings.data_dir), policy.policy_hash(), event_id, pdata.file_sha256() + od.load().data_end.isoformat())
