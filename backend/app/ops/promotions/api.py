"""HTTP routes of the promotions planner (``/api/ops/promotions``). The plan of an event is generated on the first request for a given
playbook and data set and cached; approving only writes to the simulated outbox (stock-up POs). Funding emails are approved in the shared
outbox (``/api/ops/outbox``)."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query

from app import policy
from app.auth import require_demo_key
from app.config import settings
from app.ops import outbox as ops_outbox
from app.ops.api import require_key_if_live
from app.ops.data import load as load_ops
from app.ops.promotions import agent, engine, outbox
from app.ops.promotions.schemas import PlanDecideBody

router = APIRouter(prefix="/api/ops/promotions", tags=["run"])
_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
_lock = asyncio.Lock()


def reset() -> None:
    _cache.clear()
    outbox.reset()


async def _result(event_id: str, inject: bool) -> dict[str, Any]:
    engine.event(event_id)  # a typed 404 before any model call
    key = (policy.policy_hash(), str(settings.data_dir), event_id)
    async with _lock:
        if inject:  # a deliberately wrong number is never cached
            return await agent.generate(event_id, True)
        if key not in _cache:
            _cache[key] = await agent.generate(event_id, False)
        return _cache[key]


def _with_state(result: dict[str, Any]) -> dict[str, Any]:
    event_id = result["event"]["id"]
    return {**result, "drafts": [d for d in ops_outbox.listing("promo_funding") if d.get("event_id") == event_id], "decision": outbox.status(event_id)}


@router.get("")
async def list_events() -> dict[str, Any]:
    """The calendar with each event's headline plan numbers. Deterministic: no model call."""
    out = []
    for ev in engine.events():
        p = engine.plan(ev.id)
        out.append({**p["event"], "planned_skus": p["totals"]["planned_skus"], "gmv_inr": p["totals"]["gmv_inr"], "funding_ask_inr": p["totals"]["funding_ask_inr"],
                    "stock_up_inr": p["totals"]["stock_up_inr"], "incremental_margin_inr": p["totals"]["incremental_margin_inr"], "decision": outbox.status(ev.id)})
    return {"as_of": load_ops().as_of.isoformat(), "events": out}


@router.get("/outbox")
async def get_outbox() -> dict[str, Any]:
    return {"simulated": True, "decisions": outbox.listing(), "drafts": ops_outbox.listing("promo_funding")}


@router.get("/{event_id}", dependencies=[Depends(require_key_if_live)])
async def get_event(event_id: str, inject: int = Query(0, ge=0, le=1)) -> dict[str, Any]:
    return _with_state(await _result(event_id, bool(inject)))


@router.post("/{event_id}/approve")
async def approve_plan(event_id: str, body: PlanDecideBody | None = None) -> dict[str, Any]:
    result = await _result(event_id, False)
    return outbox.approve(result, body.sku_codes if body else None, body.note if body else None)


@router.post("/{event_id}/reject")
async def reject_plan(event_id: str, body: PlanDecideBody | None = None) -> dict[str, Any]:
    result = await _result(event_id, False)
    return outbox.reject(result, body.note if body else None)


@router.post("/reset", dependencies=[Depends(require_demo_key)])
async def reset_promotions() -> dict[str, bool]:
    reset()
    return {"ok": True}
