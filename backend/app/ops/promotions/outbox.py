"""Decisions on event plans. Everything here is SIMULATED: approving a plan queues the stock-up POs that WOULD be raised and marks the plan
approved; the vendor funding emails are approved one by one in the shared outbox. In memory, like the other outboxes."""

from datetime import UTC, datetime
from typing import Any

from app.errors import PromoPlanDecided, PromoPlanEmpty

_decisions: dict[str, dict[str, Any]] = {}


def reset() -> None:
    _decisions.clear()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def status(event_id: str) -> dict[str, Any]:
    return _decisions.get(event_id, {"status": "pending"})


def listing() -> list[dict[str, Any]]:
    return [{"event_id": k, **v} for k, v in sorted(_decisions.items())]


def approve(plan: dict[str, Any], sku_codes: list[str] | None, note: str | None) -> dict[str, Any]:
    event_id = plan["event"]["id"]
    if status(event_id)["status"] != "pending":
        raise PromoPlanDecided()
    planned = [r for r in plan["rows"] if r["status"] == "planned"]
    chosen = [r for r in planned if sku_codes is None or r["sku_code"] in sku_codes]
    if not chosen:
        raise PromoPlanEmpty()
    codes = {r["sku_code"] for r in chosen}
    pos = []
    for po in plan["pos"]:
        lines = [ln for ln in po["lines"] if ln["sku_code"] in codes]
        if lines:
            pos.append({**po, "lines": lines, "qty": sum(x["qty"] for x in lines), "cost_inr": round(sum(x["cost_inr"] for x in lines), 2), "status": "queued_simulated"})
    rec = {
        "status": "approved", "decided_at": _now(), "note": note, "simulated": True, "skus": sorted(codes), "n_skus": len(codes),
        "prices": [{"sku_code": r["sku_code"], "from_price": r["selling_price"], "to_price": r["promo_price"]} for r in chosen], "pos": pos,
        "stock_up_inr": round(sum(p["cost_inr"] for p in pos), 2),
    }
    _decisions[event_id] = rec
    return {"event_id": event_id, **rec}


def reject(plan: dict[str, Any], note: str | None) -> dict[str, Any]:
    event_id = plan["event"]["id"]
    if status(event_id)["status"] != "pending":
        raise PromoPlanDecided()
    rec = {"status": "rejected", "decided_at": _now(), "note": note, "simulated": True, "skus": [], "n_skus": 0, "prices": [], "pos": [], "stock_up_inr": 0.0}
    _decisions[event_id] = rec
    return {"event_id": event_id, **rec}
