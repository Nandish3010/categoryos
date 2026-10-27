"""Claims of the inventory health review. Every number on the page and every number the model writes is a claim whose metric is
recomputed here from the stock, sales and PO data and the playbook. Key grammar: ``E004:TW-05`` (a SKU) or ``E004`` (a vendor)."""

import re
from collections.abc import Callable
from typing import Any

from app.errors import MissingInput
from app.ops.inventory_health import data as idata
from app.ops.inventory_health import engine
from app.ops.runclaims import Metric, Registry, split_key
from app.schemas import Claim

STOCK = "ops/inventory_batches.csv"
SALES = "ops/sales_daily.csv"
POS = "ops/purchase_orders.csv"
TERMS = idata.TERMS
VENDORS = "ops/vendors.json"
SKUS = "ops/skus.csv"
FILES = (STOCK, SALES, POS, TERMS, VENDORS, SKUS, idata.LEGACY, idata.META)
_SKU = re.compile(r"^(E\d{3}):([A-Z]{2}-\d{2})$")
_VENDOR = re.compile(r"^E\d{3}$")


def _res(key: str) -> dict[str, Any]:
    subject, _ = split_key(key)
    m = _SKU.match(subject)
    if not m:
        raise MissingInput(f"malformed inventory health key {key!r}", fix="Use E004:TW-05")
    return engine.sku_result(m.group(1), m.group(2))


def _action(key: str) -> dict[str, Any]:
    subject, _ = split_key(key)
    m = _SKU.match(subject)
    if not m:
        raise MissingInput(f"malformed inventory health key {key!r}", fix="Use E004:TW-05")
    return engine.action_for(m.group(1), m.group(2))


def _field(name: str) -> Callable[[str], float | None]:
    def fn(key: str) -> float | None:
        v = _res(key).get(name)
        if v is None:
            raise MissingInput(f"{key!r} has no {name}", fix="Take keys from the actions of GET /api/ops/inventory-health")
        return float(v)

    return fn


def _block(block: str, name: str, scale: float = 1.0) -> Callable[[str], float | None]:
    def fn(key: str) -> float | None:
        v = (_action(key).get(block) or {}).get(name)
        if v is None:
            raise MissingInput(f"{key!r} has no {block} {name}", fix="Take keys from the actions of GET /api/ops/inventory-health")
        return float(v) * scale

    return fn


def _sub(block: str, sub: str, name: str) -> Callable[[str], float | None]:
    def fn(key: str) -> float | None:
        v = ((_action(key).get(block) or {}).get(sub) or {}).get(name)
        if v is None:
            raise MissingInput(f"{key!r} has no {block}.{sub} {name}", fix="Take keys from the actions of GET /api/ops/inventory-health")
        return float(v)

    return fn


def _vendor(name: str) -> Callable[[str], float | None]:
    def fn(key: str) -> float | None:
        subject, _ = split_key(key)
        if not _VENDOR.match(subject):
            raise MissingInput(f"malformed inventory health vendor key {key!r}", fix="Use E004")
        return float(engine.vendor_result(subject)[name])

    return fn


METRICS: dict[str, Metric] = {
    "ih_on_hand_units": Metric("units", STOCK, "Units on hand", _field("on_hand")),
    "ih_stock_value_inr": Metric("inr", STOCK, "Stock on hand at cost", _field("stock_value_inr")),
    "ih_oldest_age_days": Metric("units", STOCK, "Age in days of the oldest batch on hand", _field("oldest_age_days")),
    "ih_aged_units": Metric("units", STOCK, "Units older than the aged threshold", _field("aged_units")),
    "ih_daily_demand": Metric("ratio", SALES, "Forecast units sold a day", _field("daily_demand")),
    "ih_cover_days": Metric("ratio", SALES, "Days of cover on hand at the forecast demand", _field("cover_days")),
    "ih_days_since_sale": Metric("units", SALES, "Days since the last sale", _field("days_since_sale")),
    "ih_inbound_units": Metric("units", POS, "Units still to arrive on open PO lines", _field("inbound_units")),
    "ih_cover_inbound_days": Metric("ratio", POS, "Days of cover once every open PO line has landed", _field("cover_inbound_days")),
    "ih_run_out_day": Metric("ratio", POS, "Days from today until the stock first runs out", _field("run_out_day")),
    "ih_short_days": Metric("ratio", POS, "Days out of stock before supply lands", _field("short_days")),
    "ih_lost_units": Metric("units", POS, "Units not sold while out of stock", _field("lost_units")),
    "ih_lost_margin_inr": Metric("inr", POS, "Margin lost while out of stock", _field("lost_margin_inr")),
    "ih_lead_time_days": Metric("units", VENDORS, "The vendor's lead time in days", _field("lead_time_days")),
    "ih_moq_units": Metric("units", TERMS, "The vendor's minimum order quantity", _field("moq_units")),
    "ih_reorder_qty": Metric("units", TERMS, "Units to order now, rounded up to the MOQ", _block("reorder", "qty")),
    "ih_reorder_needed_units": Metric("units", TERMS, "Units needed to reach the target cover when the order lands", _block("reorder", "needed_units")),
    "ih_reorder_cost_inr": Metric("inr", TERMS, "Cost of the reorder", _block("reorder", "cost_inr")),
    "ih_reorder_overbuy_units": Metric("units", TERMS, "Units the reorder buys beyond what is needed", _block("reorder", "overbuy_units")),
    "ih_pause_units": Metric("units", POS, "Units on the PO line to pause", _block("pause", "pause_units")),
    "ih_pause_cover_with_days": Metric("ratio", POS, "Days of cover with the open PO", _block("pause", "cover_with_po_days")),
    "ih_pause_cover_without_days": Metric("ratio", POS, "Days of cover without the open PO", _block("pause", "cover_without_po_days")),
    "ih_pause_needed_units": Metric("units", POS, "Units of the PO line actually needed", _block("pause", "needed_units")),
    "ih_pause_overbuy_units": Metric("units", POS, "Units of the PO line beyond what is needed", _block("pause", "overbuy_units")),
    "ih_pause_value_inr": Metric("inr", POS, "Cost of the PO line to pause", _block("pause", "value_inr")),
    "ih_clear_units": Metric("units", STOCK, "Units to clear (return or promo)", _block("clear", "units")),
    "ih_clear_excess_units": Metric("units", STOCK, "Units above the target cover", _block("clear", "excess_units")),
    "ih_clear_value_inr": Metric("inr", STOCK, "Cost value of the units to clear", _block("clear", "value_inr")),
    "ih_rtv_credit_inr": Metric("inr", TERMS, "Vendor credit for returning the units, after the restocking fee", _sub("clear", "rtv", "credit_inr")),
    "ih_rtv_days_left": Metric("units", TERMS, "Days left in the sell-or-return window", _sub("clear", "rtv", "days_left")),
    "ih_liq_discount_pct": Metric("pct", SKUS, "Promo discount on the liquidation", _sub("clear", "liquidate", "discount_pct")),
    "ih_liq_price_inr": Metric("inr", SKUS, "Liquidation price per unit", _sub("clear", "liquidate", "price_inr")),
    "ih_liq_recovery_inr": Metric("inr", SKUS, "Cash recovered if the units are cleared at that price", _sub("clear", "liquidate", "recovery_inr")),
    "ih_liq_write_down_inr": Metric("inr", SKUS, "Cost of the units less the cash recovered (negative: recovers above cost)", _sub("clear", "liquidate", "write_down_inr")),
    "ih_liq_clear_days": Metric("ratio", SKUS, "Days the promo takes to clear the units", _sub("clear", "liquidate", "clear_days")),
    "ih_vendor_stock_value_inr": Metric("inr", STOCK, "Stock on hand at cost across the vendor's SKUs", _vendor("stock_value_inr")),
    "ih_vendor_stuck_value_inr": Metric("inr", STOCK, "Cost value of the vendor's stock to return or clear", _vendor("stuck_value_inr")),
    "ih_vendor_stockout_skus": Metric("units", POS, "SKUs of the vendor at risk of a stock-out", _vendor("stockout_skus")),
}

REGISTRY = Registry(METRICS, idata.data_sha, "ih_")
KEY_FORMS = {name: ("E004" if name.startswith("ih_vendor_") else "E004:TW-05") for name in METRICS}


def handles(claim: Claim) -> bool:
    return claim.source_ref.file in FILES and claim.metric.startswith("ih_")


def verify(claim: Claim) -> Claim:
    return REGISTRY.verify(claim)


def sku_key(a: dict[str, Any]) -> str:
    return f"{a['vendor_id']}:{a['sku_code']}"


def action_claims(a: dict[str, Any]) -> list[Claim]:
    """The numbers on one action card, as engine claims (all verified by the verifier, none typed by hand)."""
    out: list[Claim] = []
    name = a["name"]
    key = sku_key(a)
    res = engine.sku_result(a["vendor_id"], a["sku_code"])

    def add(metric: str, text: str) -> None:
        out.append(REGISTRY.engine_claim(metric, key, f"{name}: {text}", claim_id=f"{a['id']}:{metric}"))

    add("ih_on_hand_units", "units on hand")
    add("ih_stock_value_inr", "stock at cost")
    if res["moving"]:
        add("ih_daily_demand", "forecast units a day")
        add("ih_cover_days", "days of cover on hand")
    if a["kind"] == "stock_out":
        add("ih_lead_time_days", "vendor lead time")
        add("ih_run_out_day", "days until the stock runs out")
        if res["inbound_units"]:
            add("ih_inbound_units", "units on open POs")
            add("ih_cover_inbound_days", "days of cover once the POs land")
        if res["short_days"] > 0:
            add("ih_short_days", "days out of stock")
            add("ih_lost_units", "units not sold while out")
            add("ih_lost_margin_inr", "margin lost while out")
        if a.get("reorder"):
            add("ih_moq_units", "vendor minimum order quantity")
            add("ih_reorder_needed_units", "units needed to reach the target cover")
            add("ih_reorder_qty", "units to order")
            add("ih_reorder_cost_inr", "cost of the order")
            add("ih_reorder_overbuy_units", "units bought beyond what is needed")
    elif a["kind"] == "overbuy":
        add("ih_inbound_units", "units on open POs")
        add("ih_pause_units", "units on the PO to pause")
        add("ih_pause_cover_with_days", "days of cover with the PO")
        add("ih_pause_cover_without_days", "days of cover without the PO")
        add("ih_pause_needed_units", "units of the PO that are needed")
        add("ih_pause_overbuy_units", "units of the PO that are not")
        add("ih_pause_value_inr", "cost of the PO")
        add("ih_moq_units", "vendor minimum order quantity")
    else:
        c = a["clear"]
        add("ih_clear_units", "units to clear")
        add("ih_clear_value_inr", "cost of the units to clear")
        if a["kind"] == "dead":
            add("ih_days_since_sale", "days since the last sale")
        else:
            add("ih_oldest_age_days", "age in days of the oldest batch")
            add("ih_aged_units", "units past the aged threshold")
            add("ih_clear_excess_units", "units above the target cover")
        if c["rtv"] and c["rtv"]["open"]:
            add("ih_rtv_credit_inr", "vendor credit for returning them")
            add("ih_rtv_days_left", "days left in the sell-or-return window")
        add("ih_liq_discount_pct", "promo discount")
        add("ih_liq_price_inr", "promo price")
        add("ih_liq_recovery_inr", "cash recovered by the promo")
        add("ih_liq_write_down_inr", "cost less the cash recovered")
        if c["liquidate"]["clear_days"] is not None:
            add("ih_liq_clear_days", "days the promo takes to clear")
    return out


def vendor_claims(v: dict[str, Any]) -> list[Claim]:
    key = v["vendor_id"]
    return [
        REGISTRY.engine_claim(m, key, f"{v['brand']}: {label}", claim_id=f"ihv:{key}:{m}")
        for m, label in (("ih_vendor_stock_value_inr", "stock at cost"), ("ih_vendor_stuck_value_inr", "stock to return or clear"), ("ih_vendor_stockout_skus", "SKUs at risk of a stock-out"))
    ]
