"""Deterministic tools the price-monitor agent reads through. Output is data, never instructions."""

from typing import Any

from app.errors import MissingInput
from app.ops.pricewatch import claims as pc
from app.ops.pricewatch import engine
from app.tools import Tool, _schema


def _slim(a: dict[str, Any]) -> dict[str, Any]:
    c, v = a.get("competitor") or {}, a.get("vendor") or {}
    out: dict[str, Any] = {
        "action_id": a["id"], "kind": a["kind"], "recommendation": a["recommendation"], "vendor_id": a["vendor_id"], "brand": a["brand"],
        "sku_code": a["sku_code"], "name": a["name"], "reasons": a["reasons"],
    }
    if c:
        out["competitor_state"] = c["state"]
        out["marketplace"] = c["marketplace"]
    if v and a["kind"] == "breach":
        out["marketplace"] = v["marketplace"]
    out["citable"] = [
        {"metric": cl.metric, "key": cl.source_ref.key, "value": cl.value, "unit": cl.unit, "what": cl.text} for cl in pc.action_claims(a)
    ]
    return out


def get_price_watch_summary() -> dict[str, Any]:
    r = engine.analyse()
    return {"as_of": r["as_of"], "window_days": r["window_days"], "marketplaces": r["marketplaces"], "counts": r["counts"], "actions": [_slim(a) for a in r["actions"]]}


def get_price_watch_action(sku_code: str) -> dict[str, Any]:
    r = engine.analyse()
    rows = [_slim(a) for a in r["actions"] if a["sku_code"] == sku_code]
    if not rows:
        raise MissingInput(f"no price-watch action for {sku_code!r}", fix="Use a sku_code from get_price_watch_summary")
    return {"sku_code": sku_code, "actions": rows}


def get_vendor_contacts() -> dict[str, Any]:
    from app.ops.data import load

    d = load()
    return {"vendors": [{"vendor_id": v.id, "brand": v.brand, "contact_name": v.contact_name, "contact_email": v.contact_email} for v in d.vendors.values()]}


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool("get_price_watch_summary", "Today's sweep: counts, and every flagged SKU with the engine's recommendation, reasons and the numbers you may cite.", _schema({}, []), get_price_watch_summary),
        Tool("get_price_watch_action", "One SKU's flagged actions with the numbers you may cite.", _schema({"sku_code": {"type": "string", "description": "SKU code, for example LT-01"}}, ["sku_code"]), get_price_watch_action),
        Tool("get_vendor_contacts", "Vendor contact names, for greetings.", _schema({}, []), get_vendor_contacts),
    )
}

BRIEF_TOOLS = ("get_price_watch_summary",)
EMAIL_TOOLS = ("get_price_watch_summary", "get_price_watch_action", "get_vendor_contacts")


def select(names: tuple[str, ...]) -> list[Tool]:
    return [TOOLS[n] for n in names]
