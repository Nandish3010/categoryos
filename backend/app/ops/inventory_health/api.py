"""HTTP routes of the weekly inventory health review (``/api/ops/inventory-health``). The review is generated on the first request for a given playbook and
data set and cached; approving an action only writes to the simulated outbox."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query

from app import policy
from app.auth import require_demo_key
from app.config import settings
from app.errors import UnknownInventoryAction
from app.ops import outbox as ops_outbox
from app.ops.api import require_key_if_live
from app.ops.inventory_health import agent, engine, outbox
from app.ops.inventory_health.schemas import DecideBody

router = APIRouter(prefix="/api/ops/inventory-health", tags=["run"])
_cache: dict[tuple[str, str], dict[str, Any]] = {}
_lock = asyncio.Lock()


def reset() -> None:
    _cache.clear()
    outbox.reset()


async def _result(inject: bool) -> dict[str, Any]:
    key = (policy.policy_hash(), str(settings.data_dir))
    async with _lock:
        if inject:  # a deliberately wrong number is never cached
            return await agent.generate(True)
        if key not in _cache:
            _cache[key] = await agent.generate(False)
        return _cache[key]


def _with_state(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "drafts": ops_outbox.listing("inventory_health"),
        "actions": [{**a, "decision": outbox.status(a["id"])} for a in result["actions"]],
        "decisions": outbox.listing(),
    }


@router.get("", dependencies=[Depends(require_key_if_live)])
async def get_inventory_health(inject: int = Query(0, ge=0, le=1)) -> dict[str, Any]:
    return _with_state(await _result(bool(inject)))


def _action(action_id: str) -> dict[str, Any]:
    found = next((a for a in engine.analyse()["actions"] if a["id"] == action_id), None)
    if found is None:
        raise UnknownInventoryAction(action_id)
    return found


@router.post("/actions/{action_id}/approve")
async def approve_action(action_id: str, body: DecideBody | None = None) -> dict[str, Any]:
    await _result(False)  # the vendor drafts exist once the review has run
    return outbox.approve(_action(action_id), engine.analyse()["as_of"], body.note if body else None)


@router.post("/actions/{action_id}/reject")
async def reject_action(action_id: str, body: DecideBody | None = None) -> dict[str, Any]:
    return outbox.reject(_action(action_id), body.note if body else None)


@router.get("/outbox")
async def get_outbox() -> dict[str, Any]:
    return {"simulated": True, "decisions": outbox.listing(), "drafts": ops_outbox.listing("inventory_health")}


@router.post("/reset", dependencies=[Depends(require_demo_key)])
async def reset_inventory_health() -> dict[str, bool]:
    reset()
    return {"ok": True}
