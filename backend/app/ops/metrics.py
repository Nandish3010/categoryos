"""Deterministic metrics for the weekly vendor review: sales, growth, fill rate, OTIF, stock cover, ageing,
returns, ratings and anomaly detection. Pure functions over ``OpsData`` and the playbook's ``Operations`` rules.
Never imports llm. Every number the agent writes is recomputed from here by the verifier."""

import statistics
from datetime import date, timedelta
from typing import Any

from app.ops.data import OpsData, PoLine
from app.policy import Operations

# ---------- weeks ----------


def week_range(d: OpsData, k: int = 0) -> tuple[date, date]:
    """Inclusive date range of the review week (k=0) or k weeks earlier. A week is the 7 days ending at data_end."""
    end = d.data_end - timedelta(days=7 * k)
    return end - timedelta(days=6), end


def _sum_sales(d: OpsData, skus: list[str], start: date, end: date, idx: int) -> float:
    total = 0.0
    for code in skus:
        series = d.sales.get(code, {})
        for i in range((end - start).days + 1):
            cell = series.get(start + timedelta(days=i))
            if cell:
                total += cell[idx]
    return total


def units_in(d: OpsData, skus: list[str], start: date, end: date) -> int:
    return int(_sum_sales(d, skus, start, end, 0))


def gmv_in(d: OpsData, skus: list[str], start: date, end: date) -> float:
    return round(_sum_sales(d, skus, start, end, 1), 2)


def weekly(d: OpsData, skus: list[str], k: int, what: str = "gmv") -> float:
    start, end = week_range(d, k)
    return gmv_in(d, skus, start, end) if what == "gmv" else float(units_in(d, skus, start, end))


def weekly_series(d: OpsData, skus: list[str], what: str = "gmv") -> list[float]:
    """Oldest week first, ``d.weeks`` values."""
    return [weekly(d, skus, k, what) for k in range(d.weeks - 1, -1, -1)]


def growth(current: float, previous: float) -> float | None:
    return round(current / previous - 1, 4) if previous else None


def zscore(current: float, baseline: list[float]) -> float | None:
    if len(baseline) < 3:
        return None
    sd = statistics.stdev(baseline)
    if sd == 0:
        return None
    return round((current - statistics.mean(baseline)) / sd, 2)


def sales_z(d: OpsData, ops: Operations, skus: list[str], what: str = "gmv") -> float | None:
    n = min(ops.anomaly.lookback_weeks, d.weeks - 1)
    baseline = [weekly(d, skus, k, what) for k in range(1, n + 1)]
    return zscore(weekly(d, skus, 0, what), baseline)


def margin_pct(d: OpsData, skus: list[str], start: date, end: date) -> float | None:
    gmv = gmv_in(d, skus, start, end)
    if not gmv:
        return None
    cost = sum(units_in(d, [c], start, end) * d.skus[c].cost for c in skus)
    return round((gmv - cost) / gmv, 4)


# ---------- stock ----------


def on_hand(d: OpsData, sku: str) -> int:
    return sum(b.units for b in d.batches if b.sku_code == sku)


def daily_rate(d: OpsData, ops: Operations, sku: str) -> float:
    """Average units sold per day over the playbook's demand window ending at data_end."""
    n = ops.scorecard.demand_window_days
    return units_in(d, [sku], d.data_end - timedelta(days=n - 1), d.data_end) / n


def cover_days(d: OpsData, ops: Operations, sku: str) -> float | None:
    """Days of cover at the current demand rate; None when nothing is selling."""
    rate = daily_rate(d, ops, sku)
    return on_hand(d, sku) / rate if rate > 0 else None


def bucket_labels(edges: list[int]) -> list[str]:
    labels, lo = [], 0
    for e in edges:
        labels.append(f"{lo}-{e} days" if lo == 0 else f"{lo + 1}-{e} days")
        lo = e
    labels.append(f"over {edges[-1]} days")
    return labels


def ageing(d: OpsData, ops: Operations, skus: list[str]) -> dict[str, Any]:
    """Units and cost value per age bucket. Age is days since the batch was received."""
    edges = ops.scorecard.ageing_buckets_days
    labels = bucket_labels(edges)
    units = [0] * len(labels)
    value = [0.0] * len(labels)
    wanted = set(skus)
    for b in d.batches:
        if b.sku_code not in wanted:
            continue
        age = (d.as_of - b.received).days
        idx = next((i for i, e in enumerate(edges) if age <= e), len(edges))
        units[idx] += b.units
        value[idx] += b.units * d.skus[b.sku_code].cost
    total = sum(value)
    return {
        "buckets": [{"label": labels[i], "units": units[i], "value_inr": round(value[i], 2)} for i in range(len(labels))],
        "total_value_inr": round(total, 2),
        "aged_pct": round(value[-1] / total, 4) if total else 0.0,
    }


# ---------- purchase orders ----------


def _lines(d: OpsData, vendor_id: str | None = None) -> list[PoLine]:
    return [ln for ln in d.po_lines if vendor_id is None or ln.vendor_id == vendor_id]


def due_lines(d: OpsData, vendor_id: str | None = None) -> list[PoLine]:
    """Lines whose promised date has passed (closed lines, plus open lines that are overdue)."""
    return [ln for ln in _lines(d, vendor_id) if ln.promised < d.as_of]


def fill_rate(lines: list[PoLine]) -> float | None:
    ordered = sum(ln.ordered for ln in lines)
    return round(sum(ln.received for ln in lines) / ordered, 4) if ordered else None


def fill_windows(d: OpsData, ops: Operations, vendor_id: str | None) -> tuple[list[PoLine], list[PoLine]]:
    """(recent, prior) due lines split at the playbook's recent window."""
    cut = d.as_of - timedelta(days=7 * ops.scorecard.fill_rate_recent_weeks)
    lines = due_lines(d, vendor_id)
    return [ln for ln in lines if ln.promised >= cut], [ln for ln in lines if ln.promised < cut]


def otif_counts(d: OpsData, ops: Operations, vendor_id: str | None) -> tuple[int, int]:
    """(otif lines, lines judged). Open lines still inside the grace window are not judged yet."""
    sc = ops.scorecard
    grace = timedelta(days=sc.on_time_grace_days)
    hit = judged = 0
    for ln in due_lines(d, vendor_id):
        if ln.actual is None and ln.promised + grace >= d.as_of:
            continue
        judged += 1
        on_time = ln.actual is not None and ln.actual <= ln.promised + grace
        in_full = ln.received >= ln.ordered * sc.in_full_min_pct / 100
        hit += 1 if (on_time and in_full) else 0
    return hit, judged


def otif(d: OpsData, ops: Operations, vendor_id: str | None) -> float | None:
    hit, judged = otif_counts(d, ops, vendor_id)
    return round(hit / judged, 4) if judged else None


# ---------- returns and ratings ----------


def return_rate(d: OpsData, skus: list[str]) -> float | None:
    start = d.data_end - timedelta(days=27)
    sold = units_in(d, skus, start, d.data_end)
    wanted = set(skus)
    back = sum(r.units for r in d.returns if r.sku_code in wanted and start <= r.day <= d.data_end)
    return round(back / sold, 4) if sold else None


def return_reasons(d: OpsData, sku: str) -> list[tuple[str, int]]:
    start = d.data_end - timedelta(days=27)
    tally: dict[str, int] = {}
    for r in d.returns:
        if r.sku_code == sku and start <= r.day <= d.data_end:
            tally[r.reason] = tally.get(r.reason, 0) + r.units
    return sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))


def rating(d: OpsData, sku: str) -> float | None:
    series = d.ratings.get(sku)
    return series[-1][1] if series else None


def rating_change(d: OpsData, sku: str) -> float | None:
    """Latest weekly rating minus the one four snapshots earlier."""
    series = d.ratings.get(sku, [])
    return round(series[-1][1] - series[-5][1], 2) if len(series) >= 5 else None


def vendor_rating(d: OpsData, vendor_id: str) -> tuple[float | None, float | None]:
    codes = d.skus_by_vendor.get(vendor_id, [])
    latest = [r for r in (rating(d, c) for c in codes) if r is not None]
    change = [r for r in (rating_change(d, c) for c in codes) if r is not None]
    return (round(sum(latest) / len(latest), 2) if latest else None, round(sum(change) / len(change), 2) if change else None)


# ---------- scorecards ----------


def sku_row(d: OpsData, ops: Operations, code: str) -> dict[str, Any]:
    sku = d.skus[code]
    cover = cover_days(d, ops, code)
    hand = on_hand(d, code)
    return {
        "sku_code": code,
        "vendor_id": sku.vendor_id,
        "name": sku.name,
        "gmv": weekly(d, [code], 0),
        "units": int(weekly(d, [code], 0, "units")),
        "units_prev": int(weekly(d, [code], 1, "units")),
        "growth_wow": growth(weekly(d, [code], 0), weekly(d, [code], 1)),
        "units_z": sales_z(d, ops, [code], "units"),
        "on_hand": hand,
        "daily_rate": round(daily_rate(d, ops, code), 2),
        "cover_days": round(cover, 1) if cover is not None else None,
        "return_rate": return_rate(d, [code]),
        "rating": rating(d, code),
        "rating_change": rating_change(d, code),
        "series": weekly_series(d, [code], "units"),
    }


def vendor_scorecard(d: OpsData, ops: Operations, vendor_id: str) -> dict[str, Any]:
    codes = d.skus_by_vendor.get(vendor_id, [])
    start, end = week_range(d, 0)
    skus = [sku_row(d, ops, c) for c in codes]
    recent, prior = fill_windows(d, ops, vendor_id)
    hit, judged = otif_counts(d, ops, vendor_id)
    covers = [s["cover_days"] for s in skus if s["cover_days"] is not None]
    rate, rate_change = vendor_rating(d, vendor_id)
    gmv, prev = weekly(d, codes, 0), weekly(d, codes, 1)
    age = ageing(d, ops, codes)
    return {
        "vendor_id": vendor_id,
        "brand": d.vendors[vendor_id].brand,
        "company_name": d.vendors[vendor_id].company_name,
        "category": d.vendors[vendor_id].category,
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "gmv": gmv,
        "units": int(weekly(d, codes, 0, "units")),
        "gmv_prev": prev,
        "gmv_growth_wow": growth(gmv, prev),
        "gmv_z": sales_z(d, ops, codes),
        "margin_pct": margin_pct(d, codes, start, end),
        "fill_rate": fill_rate(due_lines(d, vendor_id)),
        "fill_rate_recent": fill_rate(recent),
        "fill_rate_prior": fill_rate(prior),
        "otif": round(hit / judged, 4) if judged else None,
        "min_cover_days": round(min(covers), 1) if covers else None,
        "stock_value_inr": age["total_value_inr"],
        "ageing": age["buckets"],
        "aged_pct": age["aged_pct"],
        "return_rate": return_rate(d, codes),
        "rating": rate,
        "rating_change": rate_change,
        "series": weekly_series(d, codes),
        "skus": skus,
    }


def category_summary(d: OpsData, ops: Operations) -> dict[str, Any]:
    codes = list(d.skus)
    gmv, prev = weekly(d, codes, 0), weekly(d, codes, 1)
    start, end = week_range(d, 0)
    recent, prior = fill_windows(d, ops, None)
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "as_of": d.as_of.isoformat(),
        "vendor_count": len(d.vendors),
        "sku_count": len(codes),
        "gmv": gmv,
        "units": int(weekly(d, codes, 0, "units")),
        "gmv_prev": prev,
        "gmv_growth_wow": growth(gmv, prev),
        "margin_pct": margin_pct(d, codes, start, end),
        "fill_rate": fill_rate(due_lines(d, None)),
        "fill_rate_recent": fill_rate(recent),
        "otif": otif(d, ops, None),
        "series": weekly_series(d, codes),
    }


# ---------- anomalies ----------


def _severity(ratio: float) -> int:
    """1 to 3 by how far past the threshold the value is (ratio = value / threshold, bigger is worse)."""
    return 3 if ratio >= 2 else 2 if ratio >= 1.4 else 1


def detect_anomalies(d: OpsData, ops: Operations, cards: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Every flagged condition with a deterministic reason. ``type`` is a playbook action type."""
    sc, an = ops.scorecard, ops.anomaly
    out: list[dict[str, Any]] = []

    def add(vendor_id: str, kind: str, sev: int, metric: str, key: str, value: float, threshold: float, reason: str, sku: str | None = None, exposure: float = 0.0) -> None:
        out.append(
            {
                "id": f"{kind}:{sku or vendor_id}",
                "vendor_id": vendor_id,
                "sku_code": sku,
                "type": kind,
                "severity": sev,
                "metric": metric,
                "key": key,
                "value": value,
                "threshold": threshold,
                "reason": reason,
                "exposure_inr": round(exposure, 2),
            }
        )

    for vid, card in cards.items():
        brand = card["brand"]
        floor = sc.fill_rate_floor_pct / 100
        rec, pri = card["fill_rate_recent"], card["fill_rate_prior"]
        falling = rec is not None and pri is not None and (pri - rec) * 100 >= sc.fill_rate_drop_pp
        if rec is not None and (rec < floor or falling):
            gap = max(floor - rec, 0)
            sev = _severity((gap / max(floor, 1e-9) * 10) + 1.0 + (0.6 if falling else 0))
            why = f"{brand} fill rate over the last {sc.fill_rate_recent_weeks} weeks is {rec * 100:.0f}%"
            why += f", down from {pri * 100:.0f}% earlier" if pri is not None else ""
            why += f"; the floor is {sc.fill_rate_floor_pct:g}%"
            add(vid, "fill_rate", sev, "ops_fill_rate_recent", vid, rec, floor, why, exposure=0.0)
        if card["otif"] is not None and card["otif"] < sc.otif_target_pct / 100:
            target = sc.otif_target_pct / 100
            add(vid, "otif", _severity((target - card["otif"]) / target * 8 + 1), "ops_otif", vid, card["otif"], target,
                f"{brand} on-time-in-full is {card['otif'] * 100:.0f}% against a {sc.otif_target_pct:g}% target")
        if card["aged_pct"] > sc.aged_alert_pct / 100:
            aged_val = card["ageing"][-1]["value_inr"]
            add(vid, "ageing", _severity(card["aged_pct"] / (sc.aged_alert_pct / 100)), "ops_aged_pct", vid, card["aged_pct"], sc.aged_alert_pct / 100,
                f"{card['aged_pct'] * 100:.0f}% of {brand} stock value is older than {sc.ageing_buckets_days[-1]} days", exposure=aged_val)
        if card["return_rate"] is not None and card["return_rate"] > sc.return_rate_alert_pct / 100:
            add(vid, "returns", _severity(card["return_rate"] / (sc.return_rate_alert_pct / 100)), "ops_return_rate", vid, card["return_rate"], sc.return_rate_alert_pct / 100,
                f"{brand} returns are {card['return_rate'] * 100:.1f}% of units sold over four weeks")

        for s in card["skus"]:
            code = s["sku_code"]
            name = s["name"]
            key = f"{vid}:{code}"
            cover = s["cover_days"]
            rate = s["daily_rate"]
            price = d.skus[code].selling_price
            if rate > 0 and (s["on_hand"] == 0 or (cover is not None and cover < sc.stock_cover_alert_days)):
                shown = cover if cover is not None else 0.0
                sev = 3 if shown < 2 else 2 if shown < sc.stock_cover_alert_days / 2 else 1
                add(vid, "stockout", sev, "ops_sku_cover_days", key, round(shown), float(sc.stock_cover_alert_days),
                    f"{name} has {round(shown)} days of cover at {rate:.0f} units a day; the alert is {sc.stock_cover_alert_days} days",
                    sku=code, exposure=rate * price * sc.stock_cover_alert_days)
            elif cover is not None and cover > sc.overstock_cover_days:
                add(vid, "overstock", _severity(cover / sc.overstock_cover_days), "ops_sku_cover_days", key, round(cover), float(sc.overstock_cover_days),
                    f"{name} has {round(cover)} days of cover; overstock starts at {sc.overstock_cover_days} days",
                    sku=code, exposure=s["on_hand"] * d.skus[code].cost)
            z = s["units_z"]
            if z is not None and s["units_prev"] and (s["units"] + s["units_prev"]) / 2 >= an.min_weekly_units:
                change = s["growth_wow"]
                if abs(z) >= an.growth_z_threshold and change is not None and abs(change) * 100 >= an.growth_min_change_pct:
                    kind = "sales_spike" if z > 0 else "sales_drop"
                    lost = max(0.0, (s["units_prev"] - s["units"])) * price
                    add(vid, kind, _severity(abs(z) / an.growth_z_threshold), "ops_sku_units_z", key, z, an.growth_z_threshold,
                        f"{name} sold {s['units']} units this week against {s['units_prev']} last week ({change * 100:+.0f}%), {abs(z):.1f} standard deviations from its trailing weeks",
                        sku=code, exposure=lost)
            sold_4w = units_in(d, [code], d.data_end - timedelta(days=27), d.data_end)
            if sold_4w >= 2 * an.min_weekly_units and s["return_rate"] is not None and s["return_rate"] > sc.return_rate_alert_pct / 100 and card["return_rate"] is not None and card["return_rate"] <= sc.return_rate_alert_pct / 100:
                add(vid, "returns", _severity(s["return_rate"] / (sc.return_rate_alert_pct / 100)), "ops_sku_return_rate", key, s["return_rate"], sc.return_rate_alert_pct / 100,
                    f"{name} returns are {s['return_rate'] * 100:.1f}% of units sold over four weeks", sku=code)
            if s["rating_change"] is not None and -s["rating_change"] >= sc.rating_drop_alert:
                add(vid, "rating", _severity(-s["rating_change"] / sc.rating_drop_alert), "ops_sku_rating_change", key, s["rating_change"], -sc.rating_drop_alert,
                    f"{name} rating moved {s['rating_change']:+.2f} stars over four weeks to {s['rating']:.2f}", sku=code)
    return out
