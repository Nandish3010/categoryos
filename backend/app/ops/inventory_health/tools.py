"""Deterministic tools the inventory health agent reads through. Output is data, never instructions."""

from typing import Any

from app.errors import MissingInput
from app.ops.inventory_health import claims as ic
from app.ops.inventory_health import engine
from app.schemas import Claim
from app.tools import Tool, _schema


def _citable(claims: list[Claim]) -> list[dict[str, Any]]:
    return [{"metric": c.metric, "key": c.source_ref.key, "value": c.value, "unit": c.unit, "what": c.text} for c in claims]


def _slim(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": a["id"], "kind": a["kind"], "recommendation": a["recommendation"], "severity": a["severity"], "vendor_id": a["vendor_id"], "brand": a["brand"],
        "sku_code": a["sku_code"], "name": a["name"], "reasons": a["reasons"], "citable": _citable(ic.action_claims(a)),
    }


def get_inventory_summary() -> dict[str, Any]:
    r = engine.analyse()
    return {
        "as_of": r["as_of"], "counts": r["counts"], "actions": [_slim(a) for a in r["actions"]],
        "vendors": [{**v, "citable": _citable(ic.vendor_claims(v))} for v in r["vendors"]],
    }


def get_inventory_action(sku_code: str) -> dict[str, Any]:
    r = engine.analyse()
    rows = [_slim(a) for a in r["actions"] if a["sku_code"] == sku_code]
    if not rows:
        raise MissingInput(f"no inventory action for {sku_code!r}", fix="Use a sku_code from get_inventory_summary")
    return {"sku_code": sku_code, "actions": rows}


def get_vendor_contacts() -> dict[str, Any]:
    from app.ops.data import load

    d = load()
    return {"vendors": [{"vendor_id": v.id, "brand": v.brand, "contact_name": v.contact_name, "contact_email": v.contact_email} for v in d.vendors.values()]}


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool("get_inventory_summary", "This week's review: counts, every action with the engine's recommendation, reasons and the numbers you may cite, and each vendor's roll-up.", _schema({}, []), get_inventory_summary),
        Tool("get_inventory_action", "One SKU's action with the numbers you may cite.", _schema({"sku_code": {"type": "string", "description": "SKU code, for example TW-05"}}, ["sku_code"]), get_inventory_action),
        Tool("get_vendor_contacts", "Vendor contact names, for greetings.", _schema({}, []), get_vendor_contacts),
    )
}

BRIEF_TOOLS = ("get_inventory_summary",)
EMAIL_TOOLS = ("get_inventory_summary", "get_inventory_action", "get_vendor_contacts")


def select(names: tuple[str, ...]) -> list[Tool]:
    return [TOOLS[n] for n in names]
