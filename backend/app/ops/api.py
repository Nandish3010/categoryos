"""HTTP routes for the Run area (existing vendors). Mounted by app.main. Model calls (mock, replay or live) happen on the
first request for a given playbook and are cached; sending is simulated: approving a draft never contacts anyone."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request

from app import policy
from app.auth import require_demo_key
from app.config import settings
from app.errors import UnknownOpsVendor
from app.llm import resolve_mode
from app.ops import base as ob
from app.ops import chaser, outbox, review
from app.ops.schemas import DecideBody

router = APIRouter(prefix="/api/ops", tags=["run"])
_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
_lock = asyncio.Lock()


async def require_key_if_live(request: Request, x_demo_key: str | None = Header(default=None)) -> None:
    """Generating a review can spend model credits only when the ops stage runs live."""
    if resolve_mode("ops") == "live":
        await require_demo_key(request, x_demo_key)


def reset() -> None:
    _cache.clear()
    outbox.reset()
    from app.ops.catalog_qc import (
        api as catalog_api,  # lazy: that module imports this one
    )

    catalog_api.reset()


async def _get(kind: str, inject: bool) -> dict[str, Any]:
    key = (kind, policy.policy_hash(), str(settings.data_dir))
    async with _lock:
        if inject:  # a deliberately wrong number is never cached
            return await (review.generate if kind == "review" else chaser.generate)(True)
        if key not in _cache:
            _cache[key] = await (review.generate if kind == "review" else chaser.generate)(False)
        return _cache[key]


def _with_drafts(result: dict[str, Any], kind: str) -> dict[str, Any]:
    return {**result, "drafts": outbox.listing(kind)}


@router.get("/review", dependencies=[Depends(require_key_if_live)])
async def get_review(inject: int = Query(0, ge=0, le=1)) -> dict[str, Any]:
    return _with_drafts(await _get("review", bool(inject)), "vendor_review")


@router.get("/pos", dependencies=[Depends(require_key_if_live)])
async def get_pos(inject: int = Query(0, ge=0, le=1)) -> dict[str, Any]:
    return _with_drafts(await _get("pos", bool(inject)), "po_followup")


@router.get("/vendors/{vendor_id}", dependencies=[Depends(require_key_if_live)])
async def get_vendor(vendor_id: str) -> dict[str, Any]:
    b = ob.base()
    if vendor_id not in b.cards:
        raise UnknownOpsVendor(vendor_id)
    rev = await _get("review", False)
    pos = await _get("pos", False)
    vendor = b.data.vendors[vendor_id]
    reply_ids = {r["reply_id"] for r in pos["readings"] if r["vendor_id"] == vendor_id}
    mine = [c for c in rev["claims"] + pos["claims"] if vendor_id in c["source_ref"]["key"] or c["source_ref"]["key"] in reply_ids]
    return {
        "vendor": {"id": vendor_id, "brand": vendor.brand, "company_name": vendor.company_name, "contact_name": vendor.contact_name, "contact_email": vendor.contact_email, "lead_time_days": vendor.lead_time_days, "category": vendor.category},
        "scorecard": b.cards[vendor_id],
        "anomalies": [a for a in rev["anomalies"] if a["vendor_id"] == vendor_id],
        "actions": [a for a in rev["actions"] if a["vendor_id"] == vendor_id],
        "email": next((d for d in outbox.listing("vendor_review") if d["vendor_id"] == vendor_id), None),
        "pos": [p for p in pos["pos"] if p["vendor_id"] == vendor_id],
        "readings": [r for r in pos["readings"] if r["vendor_id"] == vendor_id],
        "drafts": [d for d in outbox.listing("po_followup") if d["vendor_id"] == vendor_id],
        "claims": mine,
        "week_start": rev["week_start"],
        "week_end": rev["week_end"],
    }


@router.get("/outbox")
async def get_outbox(kind: str | None = None) -> dict[str, Any]:
    drafts = outbox.listing(kind)
    return {"simulated": True, "drafts": drafts, "pending": sum(1 for d in drafts if d["status"] == "pending")}


@router.post("/outbox/{draft_id}/approve")
async def approve_draft(draft_id: str, body: DecideBody | None = None) -> dict[str, Any]:
    body = body or DecideBody()
    return outbox.approve(draft_id, body.body, body.note)


@router.post("/outbox/{draft_id}/reject")
async def reject_draft(draft_id: str, body: DecideBody | None = None) -> dict[str, Any]:
    return outbox.reject(draft_id, (body or DecideBody()).note)


@router.get("/impact")
async def get_impact() -> dict[str, Any]:
    rev = await _get("review", False)
    pos = await _get("pos", False)
    return {"modules": [rev["impact_coverage"], pos["impact_coverage"]]}


@router.post("/reset", dependencies=[Depends(require_demo_key)])
async def reset_ops() -> dict[str, bool]:
    reset()
    return {"ok": True}
