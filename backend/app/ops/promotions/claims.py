"""Claims of the promotions planner. Every number in the plan table and every number the model writes is a claim whose metric is
recomputed here from the engine (ops sales, stock and POs, the playbook, and the vendors' funding replies).

Key grammar: ``festive`` (an event), ``festive:E004`` (a vendor in it), ``festive:E004:TW-01`` (a SKU). ``?view=deep`` selects the deep option
that would have stocked out. A vendor's funding offer is valued from the offer itself, so its terms travel in the key:
``festive:E001?share=50&thr=3400&banner=3&scope=BK-01+BK-02`` (thr, banner and scope are optional)."""

import hashlib
import re
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app import policy
from app.errors import MissingInput
from app.ops import claims as oc
from app.ops.promotions import data as pdata
from app.ops.promotions import engine
from app.ops.runclaims import Metric, Registry, build_key, fmt_shown, split_key
from app.schemas import Claim

SALES = oc.SALES
REPLIES = pdata.REPLIES
EXTRACTION_METRICS = {"promo_ext_share_pct": "pct", "promo_ext_threshold_units": "units", "promo_ext_banner_top_n": "units", "promo_ext_lead_days": "units"}
_SKU = re.compile(r"^[A-Z]{2}-\d{2}$")


def data_sha() -> str:
    """One hash over the ops data the engine reads and the funding replies."""
    return hashlib.sha256((oc.data_sha() + pdata.file_sha256()).encode()).hexdigest()


def _split(key: str) -> tuple[str, str | None, str | None, dict[str, str]]:
    subject, params = split_key(key)
    parts = subject.split(":")
    event = parts[0]
    vendor = parts[1] if len(parts) > 1 else None
    sku = parts[2] if len(parts) > 2 else None
    if not event or (sku is not None and not _SKU.match(sku)):
        raise MissingInput(f"malformed promotions key {key!r}", fix="Use festive, festive:E004 or festive:E004:TW-01")
    return event, vendor, sku, params


def _plan(key: str) -> dict[str, Any]:
    return engine.plan(_split(key)[0])


def _row(key: str) -> dict[str, Any]:
    event, vendor, sku, _ = _split(key)
    row = next((r for r in engine.plan(event)["rows"] if r["sku_code"] == sku and r["vendor_id"] == vendor), None)
    if row is None:
        raise MissingInput(f"{key!r} is not a SKU of the {event} plan", fix="Take SKU keys from GET /api/ops/promotions/<event>")
    return row


def _planned_row(key: str) -> dict[str, Any]:
    row = _row(key)
    if row["status"] != "planned":
        raise MissingInput(f"{key!r} is not on promo in this plan", fix="Only planned SKUs carry promo numbers")
    return row


def _field(name: str, scale: float = 1.0) -> Callable[[str], float | None]:
    return lambda key: float(_planned_row(key)[name]) * scale


def _stock_up(name: str) -> Callable[[str], float | None]:
    def fn(key: str) -> float | None:
        su = _planned_row(key)["stock_up"]
        return float(su[name]) if su else 0.0

    return fn


def _deep(name: str) -> Callable[[str], float | None]:
    def fn(key: str) -> float | None:
        deep = _row(key).get("deep_option")
        if not deep:
            raise MissingInput(f"{key!r} has no deep option", fix="Only SKUs whose deepest discount would stock out have one")
        v = deep.get(name)
        if v is None:
            raise MissingInput(f"the deep option of {key!r} has no {name}", fix="The deep option did not stock out")
        return float(v)

    return fn


def _vendor_block(key: str) -> dict[str, Any]:
    event, vendor, _, _ = _split(key)
    block = next((v for v in engine.plan(event)["vendors"] if v["vendor_id"] == vendor), None)
    if block is None:
        raise MissingInput(f"{key!r} has no SKU on promo in this event", fix="Take vendor keys from GET /api/ops/promotions/<event>")
    return block


def offer_params(key: str) -> dict[str, Any]:
    _, _, _, p = _split(key)
    if "share" not in p:
        raise MissingInput(f"{key!r} carries no funding offer", fix="Add ?share=<pct>&thr=<units>&banner=<n>")
    return {
        "share_pct": float(p["share"]),
        "threshold_units": float(p["thr"]) if p.get("thr") else None,
        "banner_top_n": int(p["banner"]) if p.get("banner") else None,
        "scope": [s for s in p.get("scope", "").split("+") if s],
    }


def valued_offer(key: str) -> dict[str, Any]:
    """The engine's value of the funding offer written in ``key`` (cached: the deal evaluator runs a Monte Carlo)."""
    _event, vendor, _, _ = _split(key)
    if vendor is None:
        raise MissingInput(f"{key!r} needs a vendor", fix="Use festive:E001?share=50")
    return _valued(key, policy.policy_hash(), data_sha())


@lru_cache(maxsize=256)
def _valued(key: str, policy_hash: str, data_hash: str) -> dict[str, Any]:  # the hashes only identify the inputs
    event, vendor, _, _ = _split(key)
    plan = engine.plan(event)
    return engine.value_offer(engine.event(event), plan["rows"], vendor or "", offer_params(key))


def _offer(name: str, scale: float = 1.0) -> Callable[[str], float | None]:
    def fn(key: str) -> float | None:
        v = valued_offer(key)
        value = v.get(name)
        if value is None:
            raise MissingInput(f"the offer at {key!r} has no {name}", fix="The offer has no sales condition")
        return float(value) * scale

    return fn


def _event(name: str) -> Callable[[str], float | None]:
    def fn(key: str) -> float | None:
        p = _plan(key)
        if name in p["totals"]:
            return float(p["totals"][name])
        return float(p["event"][name])

    return fn


def _vendor(name: str) -> Callable[[str], float | None]:
    return lambda key: float(_vendor_block(key)[name])


METRICS: dict[str, Metric] = {
    # sku
    "promo_discount_pct": Metric("pct", SALES, "Discount depth planned for the SKU", _field("discount_pct")),
    "promo_price": Metric("inr", SALES, "Promo selling price", _field("promo_price")),
    "promo_uplift": Metric("ratio", SALES, "Demand multiplier the discount buys", _field("uplift")),
    "promo_baseline_daily_units": Metric("ratio", SALES, "Baseline units a day (recent sales)", _field("daily_units")),
    "promo_baseline_units": Metric("units", SALES, "Units the SKU would sell in the event without a discount", _field("baseline_units")),
    "promo_units": Metric("units", SALES, "Units the SKU sells in the event at the planned depth", _field("promo_units")),
    "promo_incremental_units": Metric("units", SALES, "Extra units the discount brings", _field("incremental_units")),
    "promo_margin_unfunded_pct": Metric("pct", SALES, "Margin at the promo price before vendor funding", _field("margin_unfunded_pct")),
    "promo_margin_at_ask_pct": Metric("pct", SALES, "Margin at the promo price if the vendor funds what we ask", _field("margin_at_ask_pct")),
    "promo_funding_ask_share_pct": Metric("pct", SALES, "Share of the markdown we ask the vendor to fund", _field("funding_ask_share")),
    "promo_funding_ask_inr": Metric("inr", SALES, "Funding we ask for on this SKU", _field("funding_ask_inr")),
    "promo_incremental_margin_inr": Metric("inr", SALES, "Net extra margin of the SKU's promo (after pull-forward and cannibalisation)", _field("incremental_margin_inr")),
    "promo_pull_forward_inr": Metric("inr", SALES, "Margin lost to units pulled forward from after the event", _field("pull_forward_inr")),
    "promo_cannibalisation_inr": Metric("inr", SALES, "Margin taken from a near-duplicate sibling that is not on promo", _field("cannibalisation_inr")),
    "promo_stock_at_start": Metric("units", SALES, "Stock the event starts with", _field("stock_at_start")),
    "promo_need_units": Metric("units", SALES, "Units the event needs, with the safety buffer", _field("need_units")),
    "promo_stock_up_qty": Metric("units", SALES, "Units of the suggested stock-up PO", _stock_up("qty")),
    "promo_stock_up_cost_inr": Metric("inr", SALES, "Cost of the suggested stock-up PO", _stock_up("cost_inr")),
    "promo_banner_rank": Metric("units", SALES, "Rank of the SKU by net extra margin (banner order)", _field("banner_rank")),
    # the deep option that would have stocked out
    "promo_deep_discount_pct": Metric("pct", SALES, "The deepest discount that pays, which would stock out", _deep("depth")),
    "promo_deep_uplift": Metric("ratio", SALES, "Demand multiplier at the deep discount", _deep("uplift")),
    "promo_deep_stockout_day": Metric("units", SALES, "Event day the SKU runs out at the deep discount", _deep("stockout_day")),
    "promo_deep_short_units": Metric("units", SALES, "Units short by the end of the event at the deep discount", _deep("short_units")),
    "promo_deep_lost_gmv_inr": Metric("inr", SALES, "Sales lost to the stock-out at the deep discount", _deep("lost_gmv_inr")),
    # vendor
    "promo_vendor_ask_inr": Metric("inr", SALES, "Funding we ask the vendor for", _vendor("ask_inr")),
    "promo_vendor_markdown_inr": Metric("inr", SALES, "Markdown the vendor's SKUs give away in the event", _vendor("markdown_inr")),
    "promo_vendor_ask_share_pct": Metric("pct", SALES, "Share of the vendor's markdown we ask it to fund", _vendor("ask_share")),
    "promo_offer_face_inr": Metric("inr", REPLIES, "Face value of the vendor's funding offer", _offer("face_inr")),
    "promo_offer_counted_inr": Metric("inr", REPLIES, "Value we count for the vendor's offer after the chance of its condition and the banner cost", _offer("counted_inr")),
    "promo_offer_probability_pct": Metric("pct", REPLIES, "Chance of reaching the offer's sales condition", _offer("probability")),
    "promo_offer_ask_inr": Metric("inr", REPLIES, "Funding we ask on the SKUs the offer covers", _offer("ask_inr")),
    "promo_offer_covers_ask_pct": Metric("pct", REPLIES, "Share of our ask the counted offer covers", _offer("covers_ask_pct")),
    "promo_offer_banner_cost_inr": Metric("inr", REPLIES, "Banner value the offer's top-banner condition costs us", _offer("banner_cost_inr")),
    # event
    "promo_event_days": Metric("units", SALES, "Days in the event", _event("days")),
    "promo_event_banner_slots": Metric("units", SALES, "Top banner slots in the event", _event("banner_slots")),
    "promo_event_planned_skus": Metric("units", SALES, "SKUs on promo", _event("planned_skus")),
    "promo_event_gmv_inr": Metric("inr", SALES, "GMV of the SKUs on promo during the event", _event("gmv_inr")),
    "promo_event_incremental_margin_inr": Metric("inr", SALES, "Net extra margin of the plan", _event("incremental_margin_inr")),
    "promo_event_funding_ask_inr": Metric("inr", SALES, "Funding asked of all vendors", _event("funding_ask_inr")),
    "promo_event_stock_up_inr": Metric("inr", SALES, "Cost of the suggested stock-up POs", _event("stock_up_inr")),
    "promo_event_margin_at_ask_pct": Metric("pct", SALES, "Margin of the plan if the vendors fund what we ask", _event("margin_at_ask_pct")),
}

REGISTRY = Registry(METRICS, data_sha, "promo_")

KEY_FORMS = {
    **dict.fromkeys(METRICS, "festive:E004:TW-01"),
    **dict.fromkeys(("promo_deep_discount_pct", "promo_deep_uplift", "promo_deep_stockout_day", "promo_deep_short_units", "promo_deep_lost_gmv_inr"), "festive:E004:TW-01?view=deep"),
    **dict.fromkeys(("promo_vendor_ask_inr", "promo_vendor_markdown_inr", "promo_vendor_ask_share_pct"), "festive:E004"),
    **dict.fromkeys(("promo_offer_face_inr", "promo_offer_counted_inr", "promo_offer_probability_pct", "promo_offer_covers_ask_pct", "promo_offer_banner_cost_inr", "promo_offer_ask_inr"), "festive:E001?share=50&thr=3400&banner=3"),
    **dict.fromkeys([m for m in METRICS if m.startswith("promo_event_")], "festive"),
}


def handles(claim: Claim) -> bool:
    return claim.metric.startswith("promo_")


def sku_key(event: str, row: dict[str, Any], view: str | None = None) -> str:
    return build_key(f"{event}:{row['vendor_id']}:{row['sku_code']}", view=view)


def offer_key(event: str, vendor_id: str, offer: dict[str, Any]) -> str:
    return build_key(
        f"{event}:{vendor_id}", share=f"{offer['share_pct']:g}", thr=f"{offer['threshold_units']:g}" if offer.get("threshold_units") else None,
        banner=str(int(offer["banner_top_n"])) if offer.get("banner_top_n") else None, scope="+".join(offer.get("scope") or []) or None,
    )


def row_claims(event: str, r: dict[str, Any]) -> list[Claim]:
    """The numbers on one planned row, as engine claims."""
    out: list[Claim] = []
    name = r["name"]
    key = sku_key(event, r)

    def add(metric: str, text: str, k: str = key) -> None:
        out.append(REGISTRY.engine_claim(metric, k, f"{name}: {text}", claim_id=f"{k}:{metric}"))

    for metric, text in (
        ("promo_discount_pct", "discount"), ("promo_price", "promo price"), ("promo_uplift", "demand multiplier"), ("promo_baseline_daily_units", "baseline units a day"),
        ("promo_baseline_units", "baseline units in the event"), ("promo_units", "units in the event"), ("promo_incremental_units", "extra units"),
        ("promo_margin_unfunded_pct", "margin before funding"), ("promo_margin_at_ask_pct", "margin if funded as asked"), ("promo_funding_ask_share_pct", "funding share asked"),
        ("promo_funding_ask_inr", "funding asked"), ("promo_incremental_margin_inr", "net extra margin"), ("promo_pull_forward_inr", "margin lost to pull-forward"),
        ("promo_stock_at_start", "stock at the event start"), ("promo_need_units", "units the event needs"), ("promo_banner_rank", "banner rank"),
    ):
        add(metric, text)
    if r.get("cannibalisation"):
        add("promo_cannibalisation_inr", "margin taken from siblings")
    if r.get("stock_up"):
        add("promo_stock_up_qty", "stock-up units")
        add("promo_stock_up_cost_inr", "stock-up cost")
    if r.get("deep_option"):
        dk = sku_key(event, r, "deep")
        for metric, text in (("promo_deep_discount_pct", "deep discount"), ("promo_deep_uplift", "deep demand multiplier"), ("promo_deep_stockout_day", "deep option runs out on day"),
                             ("promo_deep_short_units", "deep option units short"), ("promo_deep_lost_gmv_inr", "deep option lost sales")):
            if metric == "promo_deep_stockout_day" and r["deep_option"].get("stockout_day") is None:
                continue
            add(metric, text, dk)
    return out


def vendor_claims(event: str, v: dict[str, Any], valued: dict[str, Any] | None) -> list[Claim]:
    out = []
    key = f"{event}:{v['vendor_id']}"
    for metric, text in (("promo_vendor_ask_inr", "funding asked"), ("promo_vendor_markdown_inr", "markdown"), ("promo_vendor_ask_share_pct", "share of the markdown asked")):
        out.append(REGISTRY.engine_claim(metric, key, f"{v['brand']}: {text}", claim_id=f"{key}:{metric}"))
    if valued and valued.get("offer_key"):
        ok = valued["offer_key"]
        for metric, text in (("promo_offer_face_inr", "offer face value"), ("promo_offer_counted_inr", "offer value counted"), ("promo_offer_ask_inr", "ask on the SKUs the offer covers"), ("promo_offer_covers_ask_pct", "share of the ask covered")):
            out.append(REGISTRY.engine_claim(metric, ok, f"{v['brand']}: {text}", claim_id=f"{ok}:{metric}"))
        if valued.get("probability") is not None:
            out.append(REGISTRY.engine_claim("promo_offer_probability_pct", ok, f"{v['brand']}: chance of the sales condition", claim_id=f"{ok}:promo_offer_probability_pct"))
        if valued.get("banner_cost_inr"):
            out.append(REGISTRY.engine_claim("promo_offer_banner_cost_inr", ok, f"{v['brand']}: banner cost", claim_id=f"{ok}:promo_offer_banner_cost_inr"))
    return out


def event_claims(event: str) -> list[Claim]:
    out = []
    for metric, text in (
        ("promo_event_days", "days"), ("promo_event_banner_slots", "banner slots"), ("promo_event_planned_skus", "SKUs on promo"), ("promo_event_gmv_inr", "GMV of the SKUs on promo"),
        ("promo_event_incremental_margin_inr", "net extra margin"), ("promo_event_funding_ask_inr", "funding asked"), ("promo_event_stock_up_inr", "stock-up cost"),
        ("promo_event_margin_at_ask_pct", "margin if funded as asked"),
    ):
        out.append(REGISTRY.engine_claim(metric, event, f"{event}: {text}", claim_id=f"{event}:{metric}"))
    return out


def figure_text(unit: str, value: float) -> str:
    return fmt_shown(unit, value)
