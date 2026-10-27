"""HTTP routes for the catalog fix queue (``/api/ops/catalog``). The queue is generated on the first request for a given playbook
and cached; deciding on fixes only writes to the simulated catalog-update outbox."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app import policy
from app.auth import require_demo_key
from app.config import settings
from app.errors import UnknownCatalogFix, UnknownCatalogLabel
from app.ops.api import require_key_if_live
from app.ops.catalog_qc import data as cdata
from app.ops.catalog_qc import fixes as fx
from app.ops.catalog_qc import outbox, queue
from app.ops.catalog_qc.schemas import SelectBody
from app.ops.catalog_qc.view import build_view

router = APIRouter(prefix="/api/ops/catalog", tags=["run"])
_cache: dict[tuple[str, str], dict[str, Any]] = {}
_lock = asyncio.Lock()


def reset() -> None:
    _cache.clear()
    _cache_inject.clear()
    outbox.reset()


async def _result(inject: bool) -> dict[str, Any]:
    key = (policy.policy_hash(), str(settings.data_dir))
    async with _lock:
        if inject:  # a deliberately wrong value is never cached
            return await queue.generate(True)
        if key not in _cache:
            _cache[key] = await queue.generate(False)
        return _cache[key]


def _fix(result: dict[str, Any], fix_id: str) -> dict[str, Any]:
    if fix_id not in result["fixes"]:
        raise UnknownCatalogFix(fix_id)
    return result["fixes"][fix_id]


@router.get("", dependencies=[Depends(require_key_if_live)])
async def get_queue(inject: int = Query(0, ge=0, le=1)) -> dict[str, Any]:
    result = await _result(bool(inject))
    _cache_inject.clear()
    if inject:  # fixes of an injected run are not the cached ones: decide against this run's own
        _cache_inject.update(result["fixes"])
    return build_view(result)


_cache_inject: dict[str, dict[str, Any]] = {}


async def _fixes() -> dict[str, dict[str, Any]]:
    return {**(await _result(False))["fixes"], **_cache_inject}


@router.get("/outbox")
async def get_outbox() -> dict[str, Any]:
    ups = outbox.updates()
    return {"simulated": True, "updates": ups, "count": len(ups)}


@router.post("/fixes/{fix_id}/approve")
async def approve_fix(fix_id: str, body: SelectBody | None = None) -> dict[str, Any]:
    fixes = await _fixes()
    if fix_id not in fixes:
        raise UnknownCatalogFix(fix_id)
    update = outbox.approve(fixes[fix_id], fixes, body.note if body else None)
    return {"simulated": True, "fix_id": fix_id, "status": "approved", "update": update}


@router.post("/fixes/{fix_id}/reject")
async def reject_fix(fix_id: str, body: SelectBody | None = None) -> dict[str, Any]:
    fixes = await _fixes()
    if fix_id not in fixes:
        raise UnknownCatalogFix(fix_id)
    outbox.reject(fixes[fix_id], body.note if body else None)
    return {"fix_id": fix_id, "status": "rejected"}


@router.post("/bulk-approve")
async def bulk_approve(body: SelectBody) -> dict[str, Any]:
    return outbox.bulk_approve(await _fixes(), body.fix_ids, body.note)


@router.post("/bulk-reject")
async def bulk_reject(body: SelectBody) -> dict[str, Any]:
    return outbox.bulk_reject(await _fixes(), body.fix_ids, body.note)


@router.get("/labels/{name}")
async def get_label(name: str) -> FileResponse:
    path = cdata.label_path(name)
    if path is None:
        raise UnknownCatalogLabel(name)
    return FileResponse(path, media_type="image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png")


@router.post("/reset", dependencies=[Depends(require_demo_key)])
async def reset_catalog() -> dict[str, bool]:
    reset()
    return {"ok": True}


__all__ = ["fx", "reset", "router"]
