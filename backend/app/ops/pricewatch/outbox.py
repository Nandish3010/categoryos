"""Decisions on price-watch actions. Everything here is SIMULATED: approving a match records the price change that WOULD be made, approving a
vendor action approves the vendor message in the shared outbox (which only marks it sent_simulated). In memory, like the other outboxes."""

from datetime import UTC, datetime
from typing import Any

from app.errors import PriceWatchActionDecided
from app.ops import outbox as ops_outbox

_decisions: dict[str, dict[str, Any]] = {}


def reset() -> None:
    _decisions.clear()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def status(action_id: str) -> dict[str, Any]:
    return _decisions.get(action_id, {"status": "pending"})


def listing() -> list[dict[str, Any]]:
    return [{"action_id": k, **v} for k, v in sorted(_decisions.items())]


def _effect(action: dict[str, Any]) -> dict[str, Any]:
    rec = action["recommendation"]
    if rec == "match":
        c = action["competitor"]
        return {"type": "price_change", "sku_code": action["sku_code"], "from_price": action["our_price"], "to_price": c["match_price"], "reason": f"match {c['marketplace']}"}
    if rec in ("ask_vendor_funding", "flag_breach"):
        return {"type": "vendor_message", "draft_id": f"DR-PW-{action['vendor_id']}", "vendor_id": action["vendor_id"]}
    if rec == "escalate":
        return {"type": "escalation", "sku_code": action["sku_code"], "to": "category_manager"}
    return {"type": "watch", "sku_code": action["sku_code"], "recheck": "tomorrow's sweep"}


def approve(action: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    if status(action["id"])["status"] != "pending":
        raise PriceWatchActionDecided()
    effect = _effect(action)
    if effect["type"] == "vendor_message":
        draft = next((d for d in ops_outbox.listing("price_watch") if d["id"] == effect["draft_id"]), None)
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
        raise PriceWatchActionDecided()
    rec = {"status": "rejected", "decided_at": _now(), "note": note, "simulated": True, "effect": None, "recommendation": action["recommendation"]}
    _decisions[action["id"]] = rec
    return {"action_id": action["id"], **rec}
