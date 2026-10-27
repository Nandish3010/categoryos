"""Decisions on inventory health actions. Everything here is SIMULATED: approving a reorder records the PO that WOULD be drafted, approving a
liquidation records the promo nomination, and approving a vendor action (expedite, pause, return) approves the vendor message in the shared
outbox, which only marks it sent_simulated. In memory, like the other outboxes."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.errors import InventoryActionDecided
from app.ops import outbox as ops_outbox

_decisions: dict[str, dict[str, Any]] = {}
VENDOR_KINDS = ("expedite_po", "pause_po", "return_to_vendor")


def reset() -> None:
    _decisions.clear()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def status(action_id: str) -> dict[str, Any]:
    return _decisions.get(action_id, {"status": "pending"})


def listing() -> list[dict[str, Any]]:
    return [{"action_id": k, **v} for k, v in sorted(_decisions.items())]


def draft_id(vendor_id: str) -> str:
    return f"DR-IH-{vendor_id}"


def _effect(action: dict[str, Any], as_of: str) -> dict[str, Any]:
    rec = action["recommendation"]
    if rec == "reorder":
        r = action["reorder"]
        lands = (date.fromisoformat(as_of) + timedelta(days=r["lead_time_days"])).isoformat()
        return {"type": "po_draft", "sku_code": action["sku_code"], "vendor_id": action["vendor_id"], "qty": r["qty"], "lead_time_days": r["lead_time_days"], "lands_on": lands}
    if rec == "liquidate":
        liq = action["clear"]["liquidate"]
        return {"type": "promo_nomination", "sku_code": action["sku_code"], "units": liq["units"], "discount_pct": liq["discount_pct"], "price_inr": liq["price_inr"]}
    base: dict[str, Any] = {"type": "vendor_message", "draft_id": draft_id(action["vendor_id"]), "vendor_id": action["vendor_id"], "action": rec, "sku_code": action["sku_code"]}
    if rec == "pause_po":
        base["po_id"] = action["pause"]["po_id"]
        base["units"] = action["pause"]["pause_units"]
    elif rec == "return_to_vendor":
        base["units"] = action["clear"]["rtv"]["units"]
        base["credit_inr"] = action["clear"]["rtv"]["credit_inr"]
    return base


def approve(action: dict[str, Any], as_of: str, note: str | None = None) -> dict[str, Any]:
    if status(action["id"])["status"] != "pending":
        raise InventoryActionDecided()
    effect = _effect(action, as_of)
    if effect["type"] == "vendor_message":
        draft = next((d for d in ops_outbox.listing("inventory_health") if d["id"] == effect["draft_id"]), None)
        if draft is not None and draft["status"] == "pending":
            ops_outbox.approve(effect["draft_id"], None, note)  # may raise DraftBlocked: nothing is recorded then
            effect["draft_status"] = "sent_simulated"
        elif draft is not None:
            effect["draft_status"] = draft["status"]
    rec = {"status": "approved", "decided_at": _now(), "note": note, "simulated": True, "effect": effect, "recommendation": action["recommendation"]}
    _decisions[action["id"]] = rec
    return {"action_id": action["id"], **rec}


def reject(action: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    if status(action["id"])["status"] != "pending":
        raise InventoryActionDecided()
    rec = {"status": "rejected", "decided_at": _now(), "note": note, "simulated": True, "effect": None, "recommendation": action["recommendation"]}
    _decisions[action["id"]] = rec
    return {"action_id": action["id"], **rec}
