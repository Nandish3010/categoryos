"""Inventory health review: the deterministic engine. Never imports llm.

Per SKU, from the ops stock, sales and PO data and the playbook's ``inventory_health`` section only:

* demand: units sold over the latest ``forecast.window_days`` / that many days. Cover = units on hand / daily demand;
* stock-out risk: the on-hand stock runs down at the forecast rate and every open PO line lands on its promised day (a line past its
  promised date is assumed to land ``stock_out.overdue_assumed_days`` from today). A gap between running out and the next landing is
  a stock-out (days short, units and margin lost). A reorder is due when cover including inbound is under lead time + review cycle +
  safety days; its quantity brings cover at landing to ``cover.target_days`` and rounds UP to the vendor's MOQ;
* ageing and dead stock: batches older than ``ageing.aged_days``; a SKU with stock and no sale for ``ageing.dead_no_sale_days``;
* excess: on-hand cover over ``cover.max_days``; and MOQ-driven overbuy: an open PO line (nothing received yet) that takes cover above
  the band when the cover without it is healthy, and is at least ``moq.overbuy_ratio`` times what was needed;
* the answer per SKU (one action, the most urgent): reorder, expedite the late PO, pause the PO, return the stock to the vendor under
  sell-or-return terms (window still open, credit worth the freight and at least the promo recovery) or liquidate it on a promo.

Fractions (0.25 is 25%) for percentages, days as numbers, rupees. Nothing vertical-specific lives here."""

import math
from dataclasses import dataclass
from datetime import date
from functools import cache
from typing import Any

from app import policy
from app.config import settings
from app.ops import data as od
from app.ops import metrics as om
from app.ops.inventory_health import data as idata
from app.policy import InventoryHealth
from app.pricereq import vendor_facts

EPS = 1e-9
KIND_ORDER = {"stock_out": 0, "overbuy": 1, "dead": 2, "aged": 3, "excess": 4}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def r1(x: float) -> float:
    return round(x, 1)


def r2(x: float) -> float:
    return round(x, 2)


def ceil_to(qty: float, step: int) -> int:
    return math.ceil(qty / step - EPS) * step if step > 0 else math.ceil(qty - EPS)


# ---------- supply timeline ----------


@dataclass(frozen=True)
class Landing:
    po_id: str
    qty: int
    promised: date
    day: float  # days from today
    overdue: bool
    received: int
    ordered: int


def timeline(on_hand: float, rate: float, landings: list[Landing]) -> dict[str, float | None]:
    """Run the stock down at ``rate`` a day and add each landing on its day. Returns the day the stock first ends, days short in total,
    the units not sold because of it and the cover (days from today) after every landing."""
    if rate <= 0:
        return {"run_out_day": None, "short_days": 0.0, "lost_units": 0.0, "cover_end": None, "first_gap_day": None}
    cover_end = on_hand / rate
    first_gap: float | None = None
    short = 0.0
    for ln in sorted(landings, key=lambda x: (x.day, x.po_id)):
        if ln.day <= cover_end + EPS:
            cover_end += ln.qty / rate
        else:
            if first_gap is None:
                first_gap = cover_end
            short += ln.day - cover_end
            cover_end = ln.day + ln.qty / rate
    return {"run_out_day": first_gap if first_gap is not None else cover_end, "short_days": short, "lost_units": short * rate, "cover_end": cover_end, "first_gap_day": first_gap}


def _landings(d: od.OpsData, code: str, w: InventoryHealth, as_of: date) -> list[Landing]:
    out = []
    for ln in d.po_lines:
        if ln.sku_code != code or ln.status != "open" or ln.ordered <= ln.received:
            continue
        overdue = ln.promised < as_of
        day = float(w.stock_out.overdue_assumed_days) if overdue else float((ln.promised - as_of).days)
        out.append(Landing(ln.po_id, ln.ordered - ln.received, ln.promised, day, overdue, ln.received, ln.ordered))
    return out


# ---------- per SKU facts ----------


def _band(w: InventoryHealth, category: str) -> dict[str, float]:
    b = w.cover.by_category.get(category) or w.cover
    return {"min_days": float(b.min_days), "target_days": float(b.target_days), "max_days": float(b.max_days)}


def _demand(d: od.OpsData, code: str, w: InventoryHealth) -> tuple[float, int | None]:
    """(daily demand, days since the latest sale in the data; None when nothing sold in the whole window)."""
    n = w.forecast.window_days
    series = d.sales.get(code, {})
    units = sum(u for day, (u, _) in series.items() if (d.data_end - day).days < n and day <= d.data_end)
    last = max((day for day, (u, _) in series.items() if u > 0), default=None)
    return units / n, (None if last is None else (d.as_of - last).days)


def _aged(batches: list[tuple[date, int]], cost: float, w: InventoryHealth, as_of: date) -> dict[str, Any]:
    old = [(as_of - recv).days for recv, u in batches if u > 0]
    aged_units = sum(u for recv, u in batches if (as_of - recv).days > w.ageing.aged_days)
    return {"oldest_age_days": max(old, default=0), "aged_units": aged_units, "aged_value_inr": r2(aged_units * cost)}


def analyse_sku(vendor_id: str, brand: str, lead: int, code: str, w: InventoryHealth, d: od.OpsData, inv: idata.InventoryData) -> dict[str, Any] | None:
    as_of = d.as_of
    legacy = inv.legacy.get(code)
    terms = inv.terms.get(code)
    if legacy is not None:
        name, cost, price, category = legacy.name, legacy.cost, legacy.selling_price, ""
        on_hand = legacy.units
        batches = [(legacy.received, legacy.units)]
        rate = 0.0
        since = (as_of - legacy.last_sale).days
        landings: list[Landing] = []
    else:
        sku = d.skus[code]
        name, cost, price = sku.name, sku.cost, sku.selling_price
        category = vendor_facts(vendor_id).skus[code].category
        on_hand = om.on_hand(d, code)
        batches = [(b.received, b.units) for b in d.batches if b.sku_code == code]
        rate, since = _demand(d, code, w)
        landings = _landings(d, code, w, as_of)
    moving = rate >= w.forecast.min_daily_units - EPS
    rate = rate if moving else 0.0
    band = _band(w, category)
    inbound = sum(x.qty for x in landings)
    tl = timeline(on_hand, rate, landings)
    cover = on_hand / rate if moving else None
    rp = lead + w.stock_out.review_days + w.stock_out.safety_days
    needed = max(0.0, rate * (lead + band["target_days"]) - on_hand - inbound) if moving else 0.0
    state = "not_moving" if not moving else "below" if cover < band["min_days"] - EPS else "above" if cover > band["max_days"] + EPS else "in"
    return {
        "sku_code": code, "vendor_id": vendor_id, "brand": brand, "name": name, "category": category, "legacy": legacy is not None,
        "cost": cost, "price": price, "lead_time_days": lead, "moq_units": terms.moq_units if terms else 0,
        "on_hand": on_hand, "stock_value_inr": r2(on_hand * cost), "daily_demand": r2(rate), "moving": moving,
        "cover_days": None if cover is None else r2(cover), "band_state": state, "band": band,
        "days_since_sale": since, "last_sale_known": since is not None,
        "inbound_units": inbound,
        "landings": [{"po_id": x.po_id, "qty": x.qty, "promised": x.promised.isoformat(), "arrives_in_days": r1(x.day), "overdue": x.overdue, "received": x.received, "ordered": x.ordered} for x in landings],
        "cover_inbound_days": None if tl["cover_end"] is None else r2(tl["cover_end"]),
        "run_out_day": None if tl["run_out_day"] is None else r2(tl["run_out_day"]),
        "short_days": r2(tl["short_days"] or 0.0), "lost_units": round(tl["lost_units"] or 0.0),
        "lost_margin_inr": r2((tl["lost_units"] or 0.0) * (price - cost)),
        "reorder_point_days": r2(rp), "needed_units": round(needed),
        "terms": ({"return_terms": terms.return_terms, "return_window_ends": terms.return_window_ends.isoformat() if terms.return_window_ends else None, "restocking_fee_pct": terms.restocking_fee_pct} if terms else None),
        **_aged(batches, cost, w, as_of),
    }


# ---------- recommendations ----------


def _stock_out(res: dict[str, Any], w: InventoryHealth, as_of: date) -> dict[str, Any] | None:
    if not res["moving"]:
        return None
    short, final = res["short_days"], res["cover_inbound_days"]
    due = final < res["reorder_point_days"] - EPS
    if short <= EPS and not due:
        return None
    run_out = res["run_out_day"]
    critical = run_out <= w.stock_out.critical_days + EPS
    severity = "critical" if critical else "high" if short > EPS or run_out < res["lead_time_days"] else "medium"
    reasons: list[str] = []
    reorder: dict[str, Any] | None = None
    if short > EPS:
        late = [x for x in res["landings"] if x["overdue"]]
        why = " Its PO is past its promised date." if late else ""
        reasons.append(f"Stock ends in {r1(run_out)} days but the next PO lands in {res['landings'][0]['arrives_in_days']} days: about {res['short_days']:.1f} days out of stock, {res['lost_units']} units not sold.{why}")
    if due:
        qty = ceil_to(res["needed_units"], res["moq_units"] or w.moq.pack_round_units)
        if res["moq_units"]:
            qty = max(qty, res["moq_units"])
        overbuy = qty - res["needed_units"]
        reorder = {
            "qty": qty, "needed_units": res["needed_units"], "moq_units": res["moq_units"], "lead_time_days": res["lead_time_days"],
            "order_by": as_of.isoformat(), "cost_inr": r2(qty * res["cost"]), "overbuy_units": overbuy,
            "moq_driven": bool(res["moq_units"]) and res["needed_units"] > 0 and qty >= w.moq.overbuy_ratio * res["needed_units"] - EPS,
        }
        reasons.append(
            f"Cover including inbound is {res['cover_inbound_days']:.1f} days, under the {res['reorder_point_days']:.1f} days that lead time ({res['lead_time_days']}), the review cycle and safety stock need. "
            f"Order {qty} units now to reach {res['band']['target_days']:g} days of cover when it lands."
        )
        if reorder["moq_driven"]:
            reasons.append(f"The vendor's minimum order quantity of {res['moq_units']} makes this {overbuy} units more than needed.")
    else:
        reasons.append("Cover after the PO lands is healthy, so the fix is to get the PO in sooner, not to order more.")
    return {"kind": "stock_out", "recommendation": "reorder" if due else "expedite_po", "severity": severity, "reasons": reasons, "reorder": reorder}


def _overbuy(res: dict[str, Any], w: InventoryHealth) -> dict[str, Any] | None:
    if not res["moving"] or not res["landings"]:
        return None
    band = res["band"]
    final = res["cover_inbound_days"]
    if final <= band["max_days"] + EPS:
        return None
    rate = res["daily_demand"]
    landings = [Landing(x["po_id"], x["qty"], date.fromisoformat(x["promised"]), x["arrives_in_days"], x["overdue"], x["received"], x["ordered"]) for x in res["landings"]]
    best: dict[str, Any] | None = None
    for ln in landings:
        if ln.received > 0 or ln.overdue or ln.day < 1:  # started or about to be late: not a line to pause
            continue
        rest = [x for x in landings if x is not ln]
        tl = timeline(res["on_hand"], rate, rest)
        cover_wo = tl["cover_end"]
        if (tl["short_days"] or 0) > EPS or cover_wo < band["min_days"] - EPS:
            continue  # pausing it would run us out
        other = sum(x.qty for x in rest)
        needed = max(0.0, rate * (res["lead_time_days"] + band["target_days"]) - res["on_hand"] - other)
        moq = res["moq_units"]
        over = ln.qty - needed
        moq_driven = bool(moq) and ln.qty >= w.moq.overbuy_ratio * max(needed, 1.0) - EPS and ln.qty <= ceil_to(max(needed, 1.0), moq) + EPS
        cand = {"po_id": ln.po_id, "pause_units": ln.qty, "promised": ln.promised.isoformat(), "arrives_in_days": ln.day, "cover_without_po_days": r2(cover_wo), "cover_with_po_days": res["cover_inbound_days"], "needed_units": round(needed), "overbuy_units": round(over), "moq_units": moq, "moq_driven": moq_driven, "value_inr": r2(ln.qty * res["cost"])}
        if best is None or cand["pause_units"] > best["pause_units"]:
            best = cand
    if best is None:
        return None
    why = [f"Cover with the open PO would be {best['cover_with_po_days']:.1f} days, over the {band['max_days']:g}-day ceiling; without it, {best['cover_without_po_days']:.1f} days, which is healthy."]
    if best["moq_driven"]:
        why.append(f"The PO is {best['pause_units']} units against {best['needed_units']} needed: the vendor's minimum order quantity of {best['moq_units']} forces an overbuy of {best['overbuy_units']} units.")
    else:
        why.append(f"Only {best['needed_units']} of the {best['pause_units']} units on the PO are needed.")
    return {"kind": "overbuy", "recommendation": "pause_po", "severity": "medium", "reasons": why, "pause": best}


def _round_price(x: float, step: float) -> float:
    return math.floor(x / step + 0.5) * step


def _clearance(res: dict[str, Any], w: InventoryHealth, as_of: date) -> dict[str, Any] | None:
    band = res["band"]
    dead = res["days_since_sale"] is not None and res["days_since_sale"] >= w.ageing.dead_no_sale_days and res["on_hand"] > 0
    if not res["moving"] and not dead and res["aged_units"] == 0:
        return None
    excess = max(0, round(res["on_hand"] - band["target_days"] * res["daily_demand"])) if res["moving"] and res["cover_days"] > band["max_days"] + EPS else 0
    aged = res["aged_units"]
    if not (dead or aged or excess):
        return None
    kind = "dead" if dead else "aged" if aged else "excess"
    units = res["on_hand"] if dead else min(res["on_hand"], max(excess, aged))
    pct = {"dead": w.liquidate.discount_dead_pct, "aged": w.liquidate.discount_aged_pct, "excess": w.liquidate.discount_excess_pct}[kind] / 100
    price = max(res["price"] * (1 - pct), res["cost"] * w.liquidate.floor_pct_of_cost / 100)
    price = _round_price(price, w.liquidate.price_round_inr)
    recovery = units * price
    liq = {
        "units": units, "discount_pct": pct, "price_inr": r2(price), "recovery_inr": r2(recovery), "write_down_inr": r2(units * res["cost"] - recovery),
        "clear_days": r1(units / (res["daily_demand"] * w.liquidate.uplift_multiplier)) if res["moving"] else None, "floor_applied": res["cost"] * w.liquidate.floor_pct_of_cost / 100 > res["price"] * (1 - pct) + EPS,
    }
    slow = liq["clear_days"] is not None and liq["clear_days"] > w.liquidate.max_clear_days + EPS
    t = res["terms"] or {}
    rtv: dict[str, Any] | None = None
    why: list[str] = []
    if t.get("return_terms") == "sell_or_return" and t.get("return_window_ends"):
        left = (date.fromisoformat(t["return_window_ends"]) - as_of).days
        credit = units * res["cost"] * (1 - (t["restocking_fee_pct"] or 0) / 100)
        rtv = {"units": units, "credit_inr": r2(credit), "days_left": left, "window_ends": t["return_window_ends"], "open": left >= 0, "urgent": 0 <= left <= w.rtv.urgent_window_days, "restocking_fee_pct": t["restocking_fee_pct"]}
    recommendation = "liquidate"
    if rtv is None:
        why.append("No sell-or-return terms on file for this SKU: clear it with a promo.")
    elif not w.rtv.allow:
        why.append("The playbook does not allow return to vendor: clear it with a promo.")
    elif not rtv["open"]:
        why.append(f"The sell-or-return window closed on {rtv['window_ends']}: clear it with a promo.")
    elif rtv["credit_inr"] < w.rtv.min_credit_inr - EPS:
        why.append(f"A return would earn only ₹{rtv['credit_inr']:,.0f} of credit, under the ₹{w.rtv.min_credit_inr:,.0f} that makes the freight worthwhile: clear it with a promo.")
    elif not slow and rtv["credit_inr"] + EPS < recovery * w.rtv.prefer_pct_of_liquidation / 100:
        why.append("The vendor credit is below what a promo would recover: clear it with a promo.")
    else:
        recommendation = "return_to_vendor"
        if slow:
            why.append(f"Sell-or-return terms are open until {rtv['window_ends']} ({rtv['days_left']} days). A promo would take {liq['clear_days']:g} days to clear it, over the {w.liquidate.max_clear_days:g} days the playbook allows: return the stock for ₹{rtv['credit_inr']:,.0f} of credit.")
        else:
            why.append(f"Sell-or-return terms are open until {rtv['window_ends']} ({rtv['days_left']} days): return the stock for ₹{rtv['credit_inr']:,.0f} of credit, more than a promo would recover (₹{recovery:,.0f}).")
        if rtv["urgent"]:
            why.append("The window closes soon: raise the return now.")
    if kind == "dead":
        head = f"No sale for {res['days_since_sale']} days with {res['on_hand']} units on hand (₹{res['stock_value_inr']:,.0f} at cost)."
    elif kind == "aged":
        head = f"{aged} units are older than {w.ageing.aged_days} days (oldest {res['oldest_age_days']} days)."
    else:
        head = f"On-hand cover is {res['cover_days']:.0f} days, over the {band['max_days']:g}-day ceiling: {excess} units above the {band['target_days']:g}-day target."
    if recommendation == "liquidate" and slow:
        why.append(f"At {w.liquidate.uplift_multiplier:g}x the normal rate the promo takes {liq['clear_days']:g} days, over the {w.liquidate.max_clear_days:g} days the playbook allows: consider a deeper cut or a bundle.")
    if kind == "aged" and excess:
        head += f" Cover is {res['cover_days']:.0f} days, {excess} units above the {band['target_days']:g}-day target."
    severity = "high" if kind == "dead" or (rtv and rtv["urgent"] and recommendation == "return_to_vendor") else "medium"
    return {"kind": kind, "recommendation": recommendation, "severity": severity, "reasons": [head, *why], "clear": {"kind": kind, "units": units, "excess_units": excess, "aged_units": aged, "value_inr": r2(units * res["cost"]), "liquidate": liq, "rtv": rtv}}


def recommend(res: dict[str, Any], w: InventoryHealth, as_of: date) -> dict[str, Any] | None:
    """The one action for a SKU, the most urgent of: stock-out, overbuy, dead, aged, excess."""
    found = _stock_out(res, w, as_of) or _overbuy(res, w) or _clearance(res, w, as_of)
    if found is None:
        return None
    base = {"id": f"ih:{found['kind']}:{res['sku_code']}", "sku_code": res["sku_code"], "vendor_id": res["vendor_id"], "brand": res["brand"], "name": res["name"], "category": res["category"], "legacy": res["legacy"]}
    return {**base, **found}


# ---------- the review ----------


def _stock_row(res: dict[str, Any], action: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "sku_code": res["sku_code"], "vendor_id": res["vendor_id"], "brand": res["brand"], "name": res["name"], "legacy": res["legacy"],
        "on_hand": res["on_hand"], "daily_demand": res["daily_demand"], "cover_days": res["cover_days"], "inbound_units": res["inbound_units"],
        "cover_inbound_days": res["cover_inbound_days"], "stock_value_inr": res["stock_value_inr"], "days_since_sale": res["days_since_sale"],
        "band_state": res["band_state"], "kind": action["kind"] if action else None, "recommendation": action["recommendation"] if action else None,
    }


def _sort_key(a: dict[str, Any]) -> tuple[Any, ...]:
    value = (a.get("clear") or {}).get("value_inr", 0.0) or (a.get("pause") or {}).get("value_inr", 0.0)
    return (SEVERITY_ORDER[a["severity"]], KIND_ORDER[a["kind"]], -value, a["sku_code"])


@cache
def _analyse(data_dir: str, policy_hash: str, data_hash: str) -> dict[str, Any]:  # keys only identify the inputs
    w = policy.get().inventory_health
    inv = idata.load()
    d = od.load()
    skus: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []
    for vid, vendor in d.vendors.items():
        codes = [*d.skus_by_vendor.get(vid, []), *[c for c, lot in inv.legacy.items() if lot.vendor_id == vid]]
        for code in codes:
            res = analyse_sku(vid, vendor.brand, vendor.lead_time_days, code, w, d, inv)
            if res is None:
                continue
            skus[code] = res
            act = recommend(res, w, d.as_of)
            if act is not None:
                actions.append(act)
    actions.sort(key=_sort_key)
    by_sku = {a["sku_code"]: a for a in actions}
    rows = [_stock_row(r, by_sku.get(c)) for c, r in skus.items()]
    vendors = []
    for vid, vendor in d.vendors.items():
        mine = [r for r in skus.values() if r["vendor_id"] == vid]
        acts = [a for a in actions if a["vendor_id"] == vid]
        vendors.append({
            "vendor_id": vid, "brand": vendor.brand, "skus": len(mine), "stock_value_inr": r2(sum(r["stock_value_inr"] for r in mine)),
            "stuck_value_inr": r2(sum((a.get("clear") or {}).get("value_inr", 0.0) for a in acts)),
            "stockout_skus": sum(1 for a in acts if a["kind"] == "stock_out"), "actions": len(acts), "lead_time_days": vendor.lead_time_days,
        })
    count = lambda rec: sum(1 for a in actions if a["recommendation"] == rec)
    counts = {
        "skus": len(skus), "live_skus": sum(1 for r in skus.values() if not r["legacy"]), "legacy_lots": sum(1 for r in skus.values() if r["legacy"]),
        "actions": len(actions), "stock_out": sum(1 for a in actions if a["kind"] == "stock_out"), "overbuy": sum(1 for a in actions if a["kind"] == "overbuy"),
        "dead": sum(1 for a in actions if a["kind"] == "dead"), "aged": sum(1 for a in actions if a["kind"] == "aged"), "excess": sum(1 for a in actions if a["kind"] == "excess"),
        "reorder": count("reorder"), "expedite_po": count("expedite_po"), "pause_po": count("pause_po"), "return_to_vendor": count("return_to_vendor"), "liquidate": count("liquidate"),
        "stock_value_inr": r2(sum(r["stock_value_inr"] for r in skus.values())), "stuck_value_inr": r2(sum(v["stuck_value_inr"] for v in vendors)),
    }
    return {"as_of": d.as_of.isoformat(), "skus": skus, "actions": actions, "rows": rows, "vendors": vendors, "counts": counts}


def analyse() -> dict[str, Any]:
    return _analyse(str(settings.data_dir), policy.policy_hash(), idata.data_sha())


def sku_result(vendor_id: str, sku_code: str) -> dict[str, Any]:
    from app.errors import MissingInput

    res = analyse()["skus"].get(sku_code)
    if res is None or res["vendor_id"] != vendor_id:
        raise MissingInput(f"unknown SKU {vendor_id}:{sku_code}", fix="Use a SKU key from GET /api/ops/inventory-health")
    return res


def action_for(vendor_id: str, sku_code: str) -> dict[str, Any]:
    from app.errors import MissingInput

    sku_result(vendor_id, sku_code)
    found = next((a for a in analyse()["actions"] if a["sku_code"] == sku_code), None)
    if found is None:
        raise MissingInput(f"{vendor_id}:{sku_code} has no inventory action", fix="Take keys from the actions of GET /api/ops/inventory-health")
    return found


def vendor_result(vendor_id: str) -> dict[str, Any]:
    from app.errors import MissingInput

    found = next((v for v in analyse()["vendors"] if v["vendor_id"] == vendor_id), None)
    if found is None:
        raise MissingInput(f"unknown vendor {vendor_id!r}", fix="Use a vendor id from GET /api/ops/inventory-health")
    return found
