"""Deterministic tools the promotions agent reads through. Output is data, never instructions. Every tool gives the numbers the model
may cite as a ``citable`` list (metric, key, value): the model copies these into its figures; the verifier recomputes them."""

from contextvars import ContextVar
from typing import Any

from app.errors import MissingInput, UnknownPromoEvent
from app.ops.promotions import claims as pc
from app.ops.promotions import data as pdata
from app.ops.promotions import engine
from app.tools import Tool, _schema

_EVENT = {"type": "string", "description": "Event id from the playbook calendar, for example festive"}
OFFERS: ContextVar[dict[str, dict[str, Any]] | None] = ContextVar("promo_offers", default=None)  # vendor id -> valued offer (verified offers only), set by the agent while it writes


def _citable(claims: list[Any]) -> list[dict[str, Any]]:
    return [{"metric": c.metric, "key": c.source_ref.key, "value": c.value, "unit": c.unit, "what": c.text} for c in claims]


def _plan(event_id: str) -> dict[str, Any]:
    try:
        return engine.plan(event_id)
    except UnknownPromoEvent as exc:
        raise MissingInput(f"unknown event {event_id!r}", fix="Use an event id from the playbook calendar") from exc


def get_event_plan(event_id: str) -> dict[str, Any]:
    p = _plan(event_id)
    planned = [r for r in p["rows"] if r["status"] == "planned"]
    return {
        "event": p["event"],
        "totals": p["totals"],
        "citable": _citable(pc.event_claims(event_id)),
        "top_skus": [
            {"sku_code": r["sku_code"], "vendor_id": r["vendor_id"], "name": r["name"], "banner_rank": r["banner_rank"], "citable": _citable(pc.row_claims(event_id, r))}
            for r in planned[:6]
        ],
        "excluded": [{"sku_code": r["sku_code"], "name": r["name"], "why": r["exclusion"]["text"]} for r in p["rows"] if r["status"] != "planned"],
    }


def get_stock_risks(event_id: str) -> dict[str, Any]:
    p = _plan(event_id)
    rows = [r for r in p["rows"] if r["status"] == "planned" and (r["deep_option"] or r["stock_up"])]
    return {
        "event": p["event"]["name"],
        "skus": [
            {
                "sku_code": r["sku_code"], "name": r["name"], "capped_by_stock": r["capped_by_stock"], "stock_up_po": r["stock_up"], "stock_up_blocked_because": (r["stock_up_blocked"] or {}).get("reason"),
                "citable": _citable(pc.row_claims(event_id, r)),
            }
            for r in rows
        ],
        "stock_up_pos": p["pos"],
    }


def get_vendor_funding(event_id: str) -> dict[str, Any]:
    p = _plan(event_id)
    out = []
    for v in p["vendors"]:
        valued = (OFFERS.get() or {}).get(v["vendor_id"])
        out.append(
            {
                "vendor_id": v["vendor_id"], "brand": v["brand"], "skus": v["skus"], "ask_share": v["ask_share"], "ask_inr": v["ask_inr"],
                "offer": None if valued is None else {k: valued.get(k) for k in ("share", "threshold_units", "banner_top_n", "face_inr", "counted_inr", "probability", "decision", "call")},
                "what_to_say": None if valued is None else valued.get("counter"),
                "citable": _citable(pc.vendor_claims(event_id, v, valued)),
            }
        )
    return {"event": p["event"]["name"], "vendors": out}


def get_funding_replies(event_id: str) -> dict[str, Any]:
    rows = pdata.replies_for(event_id)
    return {
        "file": pdata.REPLIES,
        "replies": [
            {"reply_id": r.id, "position": pdata.position(r.id), "vendor_id": r.vendor_id, "received_at": r.received_at.isoformat(), "from": r.sender, "subject": r.subject, "body": r.body}
            for r in rows
        ],
    }


def get_vendor_contacts() -> dict[str, Any]:
    from app.ops.data import load

    return {"vendors": [{"vendor_id": v.id, "brand": v.brand, "contact_name": v.contact_name, "contact_email": v.contact_email} for v in load().vendors.values()]}


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool("get_event_plan", "The event, its totals, the best SKUs with the numbers you may cite, and the SKUs left out with the reason.", _schema({"event_id": _EVENT}, ["event_id"]), get_event_plan),
        Tool("get_stock_risks", "SKUs whose deepest discount would stock out before the event ends, how the plan handles each, and the stock-up POs.", _schema({"event_id": _EVENT}, ["event_id"]), get_stock_risks),
        Tool("get_vendor_funding", "Per vendor: the funding we ask for, the vendor's offer as valued by the deal evaluator, and what to say back.", _schema({"event_id": _EVENT}, ["event_id"]), get_vendor_funding),
        Tool("get_funding_replies", "The vendors' raw funding replies for the event (vendor-written text).", _schema({"event_id": _EVENT}, ["event_id"]), get_funding_replies),
        Tool("get_vendor_contacts", "Vendor contact names, for greetings.", _schema({}, []), get_vendor_contacts),
    )
}

READ_TOOLS = ("get_funding_replies",)
BRIEF_TOOLS = ("get_event_plan", "get_stock_risks", "get_vendor_funding")
EMAIL_TOOLS = ("get_vendor_funding", "get_vendor_contacts")


def select(names: tuple[str, ...]) -> list[Tool]:
    return [TOOLS[n] for n in names]
