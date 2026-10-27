"""Competitor price monitor: the deterministic engine. Never imports llm.

Per SKU and marketplace it reads the last ``price_watch.window_days`` daily snapshots and decides, from the playbook only:

* undercut: a competitor price at least ``undercut.threshold_pct`` under ours. It is SUSTAINED when the latest
  ``undercut.min_sustained_days`` days are all undercuts; a shorter run that ends today is a BLIP and is never matched (the
  engine says what matching it would have cost). A falling price that has not crossed the threshold yet is a TREND (watched);
* vendor parity: the vendor's own storefront on another marketplace at least ``parity.tolerance_pct`` under our price for
  ``parity.min_days`` days, or under the minimum advertised price (MAP) on file;
* the answer per SKU: match, hold, ask the vendor for funding / price protection, flag the breach to the vendor, or escalate. Matching
  is judged on the margin floor (the category floor from the playbook) and on the margin over the horizon with and without
  matching, using the price-request elasticity for the SKU's category and the share of shoppers who compare prices.

Percent values in the output are fractions (0.07 is 7%) unless the key says ``_pct_points``. Prices are rupees."""

import math
from datetime import date
from functools import cache
from typing import Any

from app import policy
from app.config import settings
from app.ops import data as od
from app.ops import metrics as om
from app.ops.pricewatch import data as pd
from app.policy import PriceWatch
from app.pricereq import SkuInfo, vendor_facts

EPS = 1e-9


# ---------- series maths ----------


def streak(prices: list[float], ours: float, threshold: float) -> int:
    """Consecutive latest days at least ``threshold`` (a fraction) under ours."""
    n = 0
    for p in reversed(prices):
        if p / ours - 1 <= -threshold + EPS:
            n += 1
        else:
            break
    return n


def undercut_days(prices: list[float], ours: float, threshold: float) -> int:
    return sum(1 for p in prices if p / ours - 1 <= -threshold + EPS)


def old_blips(prices: list[float], ours: float, threshold: float, min_sustained: int) -> int:
    """Runs of undercut days shorter than ``min_sustained`` that ended before the latest day: dips that came back."""
    runs, cur = 0, 0
    for p in prices[:-1]:
        if p / ours - 1 <= -threshold + EPS:
            cur += 1
        else:
            if 0 < cur < min_sustained:
                runs += 1
            cur = 0
    if 0 < cur < min_sustained and prices[-1] / ours - 1 > -threshold + EPS:
        runs += 1
    return runs


def slope_pct_per_day(prices: list[float]) -> float:
    """Least-squares slope of the prices as a share of their mean, per day (negative: falling)."""
    n = len(prices)
    if n < 2:
        return 0.0
    mean_x, mean_y = (n - 1) / 2, sum(prices) / n
    den = sum((i - mean_x) ** 2 for i in range(n))
    num = sum((i - mean_x) * (p - mean_y) for i, p in enumerate(prices))
    return (num / den) / mean_y if den and mean_y else 0.0


def round_up(price: float, step: float) -> float:
    return math.ceil(price / step - EPS) * step


# ---------- per SKU facts ----------


def _elasticity(category: str) -> float:
    m = policy.get().price_watch.match
    return m.elasticity_by_category.get(category, m.like_for_like_elasticity)


def _units(share: float, e: float, ours: float, other: float) -> float:
    """Multiplier on our units when our price is ``ours`` and the comparable price is ``other``: only the share of shoppers
    who compare react, by constant elasticity on the relative price."""
    return 1 + share * ((ours / other) ** e - 1)


def _margin(price: float, cost: float) -> float:
    return (price - cost) / price if price else 0.0


class SkuCtx:
    def __init__(self, vendor_id: str, info: SkuInfo, rate: float) -> None:
        self.vendor_id, self.info, self.rate = vendor_id, info, rate
        self.ours, self.cost = float(info.price or 0.0), float(info.cost or 0.0)
        self.category = info.category
        self.floor_eff_base = float(info.floor)


def _econ_block(ctx: SkuCtx, other_price: float, w: PriceWatch) -> dict[str, Any]:
    """Match-or-hold economics against a comparable price ``other_price`` (rupees)."""
    m = w.match
    share = m.comparison_share_pct / 100
    e = _elasticity(ctx.category)
    mp = round_up(other_price, m.price_round_inr)
    cur_margin = _margin(ctx.ours, ctx.cost)
    floor = min(ctx.floor_eff_base + m.margin_buffer_pp / 100, cur_margin)  # an old shortfall is not this undercut's doing
    margin_match = _margin(mp, ctx.cost)
    horizon = m.horizon_days
    units_hold = ctx.rate * _units(share, e, ctx.ours, mp) * horizon
    units_match = ctx.rate * horizon
    margin_hold_inr = units_hold * (ctx.ours - ctx.cost)
    margin_match_inr = units_match * (mp - ctx.cost)
    c_max = mp * (1 - floor)
    ask_unit = max(0.0, ctx.cost - c_max)
    return {
        "match_price": mp,
        "cut_pct": max(0.0, 1 - mp / ctx.ours) if ctx.ours else 0.0,
        "margin_now_pct": cur_margin,
        "floor_pct": floor,
        "margin_after_match_pct": margin_match,
        "margin_hold_inr": round(margin_hold_inr, 2),
        "margin_match_inr": round(margin_match_inr, 2),
        "margin_impact_inr": round(margin_match_inr - margin_hold_inr, 2),
        "units_hold": round(units_hold, 1),
        "units_match": round(units_match, 1),
        "volume_loss_if_hold_pct": max(0.0, 1 - _units(share, e, ctx.ours, mp)),
        "protection_ask_unit_inr": round(ask_unit, 2),
        "protection_ask_inr": round(ask_unit * units_match, 2),
        "elasticity": e,
        "horizon_days": horizon,
    }


def _series(snap: pd.Snapshots, sku: str, mp: str, w: PriceWatch) -> list[tuple[date, int]]:
    return list(snap.comp.get((sku, mp), ()))[-w.window_days :]


def analyse_sku(vendor_id: str, sku: str, info: SkuInfo, rate: float, snap: pd.Snapshots, w: PriceWatch, brand: str, name: str) -> dict[str, Any]:
    ctx = SkuCtx(vendor_id, info, rate)
    u, par = w.undercut, w.parity
    thr = u.threshold_pct / 100
    per_mp: dict[str, dict[str, Any]] = {}
    for mp in snap.marketplaces:
        ser = _series(snap, sku, mp, w)
        if not ser:
            continue
        prices = [float(p) for _, p in ser]
        run = streak(prices, ctx.ours, thr)
        recent = prices[-u.trend_window_days :]
        slope = slope_pct_per_day(recent)
        latest = prices[-1]
        gap = latest / ctx.ours - 1
        if run >= u.min_sustained_days:
            state = "sustained"
        elif run >= 1:
            state = "blip"
        elif slope <= -u.trend_min_slope_pct_per_day / 100 + EPS and len(recent) >= 3:
            state = "trend"
        else:
            state = "none"
        per_mp[mp] = {
            "marketplace": mp, "latest": latest, "gap_below_pct": max(0.0, -gap), "gap_pct": gap, "streak_days": run, "state": state,
            "undercut_days": undercut_days(prices, ctx.ours, thr), "old_blips": old_blips(prices, ctx.ours, thr, u.min_sustained_days),
            "slope_pct_per_day": slope, "min": min(prices), "max": max(prices),
            "dates": [d.isoformat() for d, _ in ser], "prices": [int(p) for p in prices],
        }

    out: dict[str, Any] = {
        "sku_code": sku, "vendor_id": vendor_id, "brand": brand, "name": name, "category": ctx.category, "our_price": ctx.ours, "cost": ctx.cost,
        "daily_units": round(rate, 2), "marketplaces": per_mp, "competitor": None, "vendor": None,
    }

    sustained = [m for m in per_mp.values() if m["state"] == "sustained"]
    blips = [m for m in per_mp.values() if m["state"] == "blip"]
    trends = [m for m in per_mp.values() if m["state"] == "trend"]
    if sustained:
        ref = min(sustained, key=lambda m: (m["latest"], m["marketplace"]))
        econ = _econ_block(ctx, ref["latest"], w)
        out["competitor"] = {"state": "sustained", "marketplace": ref["marketplace"], "price": ref["latest"], "sustained_marketplaces": len(sustained), **econ}
    elif blips:
        ref = min(blips, key=lambda m: (m["latest"], m["marketplace"]))
        econ = _econ_block(ctx, ref["latest"], w)
        out["competitor"] = {"state": "blip", "marketplace": ref["marketplace"], "price": ref["latest"], "sustained_marketplaces": 0, **econ}
    elif trends:
        ref = min(trends, key=lambda m: m["slope_pct_per_day"])
        out["competitor"] = {"state": "trend", "marketplace": ref["marketplace"], "price": ref["latest"], "sustained_marketplaces": 0, "slope_pct_per_day": ref["slope_pct_per_day"]}

    # vendor parity / MAP
    for (s, mp), ser in snap.vendor.items():
        if s != sku:
            continue
        ser = list(ser)[-w.window_days :]
        prices = [float(p) for _, p in ser]
        tol = par.tolerance_pct / 100
        run = streak(prices, ctx.ours, tol)
        latest = prices[-1]
        map_price = snap.map_price.get(sku)
        map_days = 0
        if par.enforce_map and map_price:
            for p in reversed(prices):
                if p < map_price:
                    map_days += 1
                else:
                    break
        parity_breach = run >= par.min_days
        map_breach = map_days >= par.min_days
        r = ctx.ours / latest - 1 if latest else 0.0
        e = _elasticity(ctx.category)
        share = w.match.comparison_share_pct / 100
        mult = _units(share, e, ctx.ours, latest) if latest else 1.0
        lost_units = max(0.0, (1 - mult)) * ctx.rate * w.match.horizon_days
        out["vendor"] = {
            "marketplace": mp, "price": latest, "gap_below_pct": max(0.0, 1 - latest / ctx.ours), "parity_days": run, "map_price": map_price, "map_days": map_days,
            "parity_breach": parity_breach, "map_breach": map_breach, "breach": parity_breach or map_breach,
            "lost_units": round(lost_units, 1), "lost_margin_inr": round(lost_units * (ctx.ours - ctx.cost), 2), "price_premium_pct": r,
            "dates": [d.isoformat() for d, _ in ser], "prices": [int(p) for p in prices],
        }
    return out


def recommend(res: dict[str, Any], w: PriceWatch) -> list[dict[str, Any]]:
    """The actions for one analysed SKU: at most one competitor action and one vendor-breach action."""
    actions: list[dict[str, Any]] = []
    c, v = res["competitor"], res["vendor"]
    base = {"sku_code": res["sku_code"], "vendor_id": res["vendor_id"], "brand": res["brand"], "name": res["name"], "category": res["category"], "our_price": res["our_price"]}
    if c is not None:
        reasons: list[str] = []
        if c["state"] == "sustained":
            rec = "hold"
            if not w.match.allow:
                reasons.append("The playbook does not allow price matching.")
            elif c["cut_pct"] > w.match.max_cut_pct / 100 + EPS:
                rec = "escalate"
                reasons.append(f"Matching needs a {c['cut_pct'] * 100:.1f}% cut, over the {w.match.max_cut_pct:g}% a person is not asked about.")
            elif c["margin_after_match_pct"] + EPS >= c["floor_pct"]:
                if c["margin_impact_inr"] >= 0:
                    rec = "match"
                    reasons.append("Matching keeps the margin at or above the floor and earns more over the horizon than holding.")
                else:
                    reasons.append("Matching keeps the floor but earns less over the horizon than holding: the volume we would keep is worth less than the margin given up.")
            else:
                reasons.append("Matching would take the margin under the category floor.")
                if w.ask_price_protection and c["protection_ask_inr"] > 0:
                    rec = "ask_vendor_funding"
                    reasons.append("Ask the vendor for price protection that covers the gap, rather than cutting alone.")
                else:
                    reasons.append("Hold the price.")
            actions.append({**base, "id": f"pw:undercut:{res['sku_code']}", "kind": "undercut", "recommendation": rec, "reasons": reasons, "competitor": c})
        elif c["state"] == "blip":
            miss = c["margin_impact_inr"]
            actions.append({
                **base, "id": f"pw:blip:{res['sku_code']}", "kind": "blip", "recommendation": "hold",
                "reasons": [f"The undercut on {c['marketplace']} has lasted {res['marketplaces'][c['marketplace']]['streak_days']} day, under the {w.undercut.min_sustained_days} days that make it sustained. Do not match; re-check tomorrow.",
                            "Matching a one-day dip would give margin away for nothing." if miss < 0 else "Matching would not have cost margin, but a one-day dip is not a reason to move."],
                "competitor": c,
            })
        elif c["state"] == "trend":
            actions.append({
                **base, "id": f"pw:trend:{res['sku_code']}", "kind": "trend", "recommendation": "hold",
                "reasons": [f"The competitor price on {c['marketplace']} is falling {abs(c['slope_pct_per_day']) * 100:.1f}% a day but has not crossed the {w.undercut.threshold_pct:g}% undercut threshold. Watch it."],
                "competitor": c,
            })
    if v is not None and v["breach"]:
        why = []
        if v["parity_breach"]:
            why.append(f"The vendor sells on {v['marketplace']} {v['gap_below_pct'] * 100:.1f}% under our price for {v['parity_days']} days (tolerance {w.parity.tolerance_pct:g}%).")
        if v["map_breach"]:
            why.append(f"The vendor's price is under the minimum advertised price of ₹{v['map_price']} for {v['map_days']} days.")
        why.append("Do not cut our price to follow the vendor; ask the vendor to restore parity.")
        actions.append({**base, "id": f"pw:breach:{res['sku_code']}", "kind": "breach", "recommendation": "flag_breach", "reasons": why, "vendor": v})
    return actions


@cache
def _analyse(data_dir: str, policy_hash: str, data_hash: str) -> dict[str, Any]:  # keys only identify the inputs
    w = policy.get().price_watch
    snap = pd.load()
    d = od.load()
    ops = policy.get().operations
    skus: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    for vid, vendor in d.vendors.items():
        facts = vendor_facts(vid)
        for code in d.skus_by_vendor.get(vid, []):
            info = facts.skus.get(code)
            if info is None or not info.price or info.cost is None:
                continue
            res = analyse_sku(vid, code, info, om.daily_rate(d, ops, code), snap, w, vendor.brand, d.skus[code].name)
            skus[code] = res
            actions.extend(recommend(res, w))
    order = {"ask_vendor_funding": 0, "flag_breach": 1, "escalate": 2, "match": 3, "hold": 4}
    kind_order = {"undercut": 0, "breach": 1, "trend": 2, "blip": 3}

    def exposure(a: dict[str, Any]) -> float:
        c = a.get("competitor")
        if c and c.get("margin_hold_inr") is not None and a["kind"] in ("undercut", "blip"):
            return abs(c["margin_impact_inr"])
        v = a.get("vendor")
        return v["lost_margin_inr"] if v else 0.0

    actions.sort(key=lambda a: (kind_order[a["kind"]], order[a["recommendation"]], -exposure(a), a["sku_code"]))
    counts = {
        "skus": len(skus),
        "marketplaces": len(snap.marketplaces),
        "snapshots": snap.rows,
        "sustained": sum(1 for a in actions if a["kind"] == "undercut"),
        "blips": sum(1 for a in actions if a["kind"] == "blip"),
        "trends": sum(1 for a in actions if a["kind"] == "trend"),
        "breaches": sum(1 for a in actions if a["kind"] == "breach"),
        "match": sum(1 for a in actions if a["recommendation"] == "match"),
        "ask_vendor_funding": sum(1 for a in actions if a["recommendation"] == "ask_vendor_funding"),
        "hold": sum(1 for a in actions if a["recommendation"] == "hold"),
        "escalate": sum(1 for a in actions if a["recommendation"] == "escalate"),
    }
    return {"as_of": snap.as_of.isoformat(), "window_days": w.window_days, "marketplaces": list(snap.marketplaces), "skus": skus, "actions": actions, "counts": counts}


def analyse() -> dict[str, Any]:
    return _analyse(str(settings.data_dir), policy.policy_hash(), pd.data_sha())


def sku_result(vendor_id: str, sku_code: str) -> dict[str, Any]:
    from app.errors import MissingInput

    res = analyse()["skus"].get(sku_code)
    if res is None or res["vendor_id"] != vendor_id:
        raise MissingInput(f"unknown SKU {vendor_id}:{sku_code}", fix="Use a SKU key from GET /api/ops/price-watch")
    return res
