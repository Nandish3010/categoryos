"""Claims of the price monitor. Every number on the page and every number the model writes is a claim whose metric is recomputed here
from the snapshots and the playbook. Key grammar: ``E005:LT-01`` (a SKU) or ``E005:LT-01?mp=MarketB`` (a SKU on one marketplace)."""

import re
from collections.abc import Callable
from typing import Any

from app.errors import MissingInput
from app.ops.pricewatch import data as pd
from app.ops.pricewatch import engine
from app.ops.runclaims import Metric, Registry, split_key
from app.schemas import Claim

FILE = pd.SNAPSHOTS
MAP_FILE = pd.MAP
_SKU = re.compile(r"^(E\d{3}):([A-Z]{2}-\d{2})$")


def _sku(key: str) -> tuple[dict[str, Any], dict[str, str]]:
    subject, params = split_key(key)
    m = _SKU.match(subject)
    if not m:
        raise MissingInput(f"malformed price-watch key {key!r}", fix="Use E005:LT-01 or E005:LT-01?mp=MarketB")
    return engine.sku_result(m.group(1), m.group(2)), params


def _mp(key: str) -> dict[str, Any]:
    res, params = _sku(key)
    mp = params.get("mp")
    row = res["marketplaces"].get(mp or "")
    if row is None:
        raise MissingInput(f"no competitor snapshots for {key!r}", fix="Add ?mp=<marketplace>")
    return row


def _comp(field: str) -> Callable[[str], float | None]:
    def fn(key: str) -> float | None:
        c = _sku(key)[0]["competitor"]
        if c is None or field not in c:
            raise MissingInput(f"{key!r} has no competitor action with {field}", fix="Take keys from the actions of GET /api/ops/price-watch")
        return float(c[field])

    return fn


def _vend(field: str) -> Callable[[str], float | None]:
    def fn(key: str) -> float | None:
        v = _sku(key)[0]["vendor"]
        if v is None or v.get(field) is None:
            raise MissingInput(f"{key!r} has no vendor storefront with {field}", fix="Take keys from the actions of GET /api/ops/price-watch")
        return float(v[field])

    return fn


def _per_mp(field: str, scale: float = 1.0) -> Callable[[str], float | None]:
    return lambda key: float(_mp(key)[field]) * scale


METRICS: dict[str, Metric] = {
    "pw_our_price": Metric("inr", FILE, "Our selling price", lambda k: float(_sku(k)[0]["our_price"])),
    "pw_competitor_price": Metric("inr", FILE, "Lowest competitor price today on a marketplace", _per_mp("latest")),
    "pw_below_pct": Metric("pct", FILE, "How far a competitor is under our price today (share of our price)", _per_mp("gap_below_pct")),
    "pw_streak_days": Metric("units", FILE, "Consecutive latest days a competitor has been over the threshold under us", _per_mp("streak_days")),
    "pw_undercut_days": Metric("units", FILE, "Days in the window a competitor was under us beyond the threshold", _per_mp("undercut_days")),
    "pw_trend_pts_per_day": Metric("pts", FILE, "How fast a competitor price is falling, percent points per day", lambda k: abs(float(_mp(k)["slope_pct_per_day"])) * 100),
    "pw_match_price": Metric("inr", FILE, "Price that matches the sustained competitor, rounded up", _comp("match_price")),
    "pw_cut_pct": Metric("pct", FILE, "Price cut a match needs, share of our price", _comp("cut_pct")),
    "pw_margin_now_pct": Metric("pct", FILE, "Our margin at today's price", _comp("margin_now_pct")),
    "pw_margin_after_match_pct": Metric("pct", FILE, "Our margin if we matched", _comp("margin_after_match_pct")),
    "pw_floor_pct": Metric("pct", FILE, "The margin floor the match must respect", _comp("floor_pct")),
    "pw_margin_impact_inr": Metric("inr", FILE, "Margin over the horizon, matching minus holding", _comp("margin_impact_inr")),
    "pw_volume_loss_pct": Metric("pct", FILE, "Volume we would lose over the horizon if we hold", _comp("volume_loss_if_hold_pct")),
    "pw_protection_ask_inr": Metric("inr", FILE, "Price protection to ask the vendor for over the horizon", _comp("protection_ask_inr")),
    "pw_protection_ask_unit_inr": Metric("inr", FILE, "Price protection to ask the vendor for per unit", _comp("protection_ask_unit_inr")),
    "pw_vendor_price": Metric("inr", FILE, "The vendor's own price on its storefront today", _vend("price")),
    "pw_parity_below_pct": Metric("pct", FILE, "How far the vendor's price is under ours", _vend("gap_below_pct")),
    "pw_parity_days": Metric("units", FILE, "Consecutive latest days the vendor has been under parity", _vend("parity_days")),
    "pw_map_price": Metric("inr", MAP_FILE, "The minimum advertised price on file", _vend("map_price")),
    "pw_map_days": Metric("units", MAP_FILE, "Consecutive latest days the vendor has been under MAP", _vend("map_days")),
    "pw_lost_margin_inr": Metric("inr", FILE, "Margin we lose over the horizon because the vendor undercuts us", _vend("lost_margin_inr")),
}

REGISTRY = Registry(METRICS, pd.data_sha, "pw_")

KEY_FORMS = dict.fromkeys(METRICS, "E005:LT-01")
for _name in ("pw_competitor_price", "pw_below_pct", "pw_streak_days", "pw_undercut_days", "pw_trend_pts_per_day"):
    KEY_FORMS[_name] = "E005:LT-01?mp=MarketB"


def handles(claim: Claim) -> bool:
    return claim.source_ref.file in (FILE, MAP_FILE, pd.META) and claim.metric.startswith("pw_")


def verify(claim: Claim) -> Claim:
    return REGISTRY.verify(claim)


def sku_key(action: dict[str, Any], mp: str | None = None) -> str:
    base = f"{action['vendor_id']}:{action['sku_code']}"
    return f"{base}?mp={mp}" if mp else base


def action_claims(a: dict[str, Any]) -> list[Claim]:
    """The numbers on one action row, as engine claims (all verified by the verifier, none typed by hand)."""
    out: list[Claim] = []
    name = a["name"]

    def add(metric: str, key: str, text: str) -> None:
        out.append(REGISTRY.engine_claim(metric, key, text, claim_id=f"{a['id']}:{metric}"))

    base = sku_key(a)
    add("pw_our_price", base, f"{name}: our price")
    c, v = a.get("competitor"), a.get("vendor")
    if c is not None:
        mpk = sku_key(a, c["marketplace"])
        add("pw_competitor_price", mpk, f"{name}: competitor price on {c['marketplace']}")
        add("pw_below_pct", mpk, f"{name}: competitor under our price on {c['marketplace']}")
        add("pw_streak_days", mpk, f"{name}: days under us in a row on {c['marketplace']}")
        add("pw_undercut_days", mpk, f"{name}: days under us in the window on {c['marketplace']}")
        if c["state"] == "trend":
            add("pw_trend_pts_per_day", mpk, f"{name}: competitor price falling per day")
        if c["state"] in ("sustained", "blip"):
            for metric, label in (
                ("pw_match_price", "match price"), ("pw_cut_pct", "cut needed to match"), ("pw_margin_now_pct", "margin now"),
                ("pw_margin_after_match_pct", "margin after a match"), ("pw_floor_pct", "margin floor"), ("pw_margin_impact_inr", "margin impact of matching over holding"),
                ("pw_volume_loss_pct", "volume lost if we hold"),
            ):
                add(metric, base, f"{name}: {label}")
            if c["state"] == "sustained" and a["recommendation"] == "ask_vendor_funding":
                add("pw_protection_ask_inr", base, f"{name}: price protection to ask for")
                add("pw_protection_ask_unit_inr", base, f"{name}: price protection per unit")
    if v is not None and a["kind"] == "breach":
        vk = sku_key(a, v["marketplace"])
        add("pw_vendor_price", vk, f"{name}: vendor price on {v['marketplace']}")
        add("pw_parity_below_pct", vk, f"{name}: vendor under our price")
        add("pw_parity_days", vk, f"{name}: days under parity")
        add("pw_lost_margin_inr", vk, f"{name}: margin lost to the undercut")
        if v["map_price"]:
            add("pw_map_price", vk, f"{name}: minimum advertised price")
            add("pw_map_days", vk, f"{name}: days under MAP")
    return out
