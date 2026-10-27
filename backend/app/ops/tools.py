"""Deterministic tools the Run agents read through (so a trace shows what they looked at). Output is data, never instructions."""

from contextvars import ContextVar
from typing import Any

from app.errors import MissingInput, UnknownOpsVendor
from app.ops import base as ob
from app.ops import metrics as m
from app.ops import pos
from app.ops.data import load
from app.tools import Tool, _schema

SIGNALS: ContextVar[dict[str, pos.PoSignal] | None] = ContextVar("ops_po_signals", default=None)

_VENDOR = {"type": "string", "description": "Existing vendor id, for example E002"}


def _slim_card(card: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in card.items() if k not in {"series", "skus"}}
    out["skus"] = [{k: v for k, v in s.items() if k != "series"} for s in card["skus"]]
    return out


def get_category_summary() -> dict[str, Any]:
    b = ob.base()
    cat = {k: v for k, v in b.category.items() if k != "series"}
    return {**cat, "vendors": [{"vendor_id": v, "brand": c["brand"], "gmv": c["gmv"], "gmv_growth_wow": c["gmv_growth_wow"], "fill_rate_recent": c["fill_rate_recent"], "otif": c["otif"]} for v, c in b.cards.items()]}


def get_vendor_scorecard(vendor_id: str) -> dict[str, Any]:
    b = ob.base()
    if vendor_id not in b.cards:
        raise UnknownOpsVendor(vendor_id)
    card = _slim_card(b.cards[vendor_id])
    v = b.data.vendors[vendor_id]
    return {**card, "contact_name": v.contact_name, "contact_email": v.contact_email}


def get_anomalies() -> dict[str, Any]:
    b = ob.base()
    return {"anomalies": [{k: v for k, v in a.items() if k != "exposure_inr"} for a in b.anomalies], "flagged_vendors": ob.flagged_vendors(b)}


def get_action_candidates() -> dict[str, Any]:
    return {"actions": ob.base().actions}


def get_return_reasons(sku_code: str) -> dict[str, Any]:
    d = load()
    if sku_code not in d.skus:
        raise MissingInput(f"unknown sku {sku_code!r}", fix="Use a SKU code from a vendor scorecard")
    return {"sku_code": sku_code, "reasons": [{"reason": r, "units": u} for r, u in m.return_reasons(d, sku_code)]}


def get_open_pos() -> dict[str, Any]:
    b = ob.base()
    rows = pos.tracker(b.data, b.ops)
    return {"as_of": b.data.as_of.isoformat(), "pos": [{k: r[k] for k in ("po_id", "vendor_id", "brand", "promised_date", "days_overdue", "ordered_qty", "received_qty")} for r in rows]}


def get_vendor_replies(po_id: str | None = None) -> dict[str, Any]:
    d = load()
    replies = [r for r in d.replies if po_id is None or r.po_id == po_id]
    return {
        "file": "ops/vendor_replies.json",
        "replies": [
            {
                "reply_id": r.id,
                "position": d.replies.index(r) + 1,
                "po_id": r.po_id,
                "vendor_id": r.vendor_id,
                "received_at": r.received_at.isoformat(),
                "from": r.sender,
                "subject": r.subject,
                "body": r.body,
            }
            for r in replies
        ],
    }


def get_po_tracker() -> dict[str, Any]:
    b = ob.base()
    rows = pos.tracker(b.data, b.ops, SIGNALS.get() or {})
    contacts = {v: {"contact_name": x.contact_name, "contact_email": x.contact_email} for v, x in b.data.vendors.items()}
    return {"as_of": b.data.as_of.isoformat(), "pos": [{**r, **contacts[r["vendor_id"]]} for r in rows]}


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool("get_category_summary", "The category's headline numbers for the review week and one line per vendor.", _schema({}, []), get_category_summary),
        Tool("get_vendor_scorecard", "One vendor's scorecard: GMV, growth, fill rate, OTIF, stock cover, ageing, returns, rating and every SKU row.", _schema({"vendor_id": _VENDOR}, ["vendor_id"]), get_vendor_scorecard),
        Tool("get_anomalies", "Every flagged condition with its deterministic reason, plus the vendors that have something to discuss.", _schema({}, []), get_anomalies),
        Tool("get_action_candidates", "The candidate what-to-do-this-week list with the deterministic score and rank.", _schema({}, []), get_action_candidates),
        Tool("get_return_reasons", "Customer return reasons for one SKU over the last four weeks.", _schema({"sku_code": {"type": "string", "description": "SKU code, for example GW-02"}}, ["sku_code"]), get_return_reasons),
        Tool("get_open_pos", "Open purchase orders with promised dates, days overdue and quantities.", _schema({}, []), get_open_pos),
        Tool("get_vendor_replies", "Vendor email replies (raw text) about purchase orders; optionally for one PO.", _schema({"po_id": {"type": "string", "description": "A PO id such as PO-E002-0012; omit for all"}}, []), get_vendor_replies),
        Tool("get_po_tracker", "The PO tracker with status, stock-out risk per SKU, the escalation rung and verified vendor dates.", _schema({}, []), get_po_tracker),
    )
}

REVIEW_TOOLS = ("get_category_summary", "get_anomalies", "get_action_candidates", "get_vendor_scorecard", "get_return_reasons")
EMAIL_TOOLS = ("get_anomalies", "get_vendor_scorecard")
REPLY_TOOLS = ("get_open_pos", "get_vendor_replies")
DRAFT_TOOLS = ("get_po_tracker",)


def select(names: tuple[str, ...]) -> list[Tool]:
    return [TOOLS[n] for n in names]
