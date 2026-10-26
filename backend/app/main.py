import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app import ledger, media, persist, replay, runner, store
from app.auth import require_demo_key
from app.config import settings
from app.constants import ALLOWED_VENDORS, STAGE_META
from app.data_loader import check_vendor, load_application
from app.errors import AssetNotFound, CategoryOSError
from app.llm import any_live, resolve_mode
from app.metrics import apply_levers, build_base
from app.schemas import (
    ApproveBody,
    LeverResponse,
    OverrideBody,
    RejectBody,
    ReplanBody,
    StageResult,
    TraceEvent,
)
from app.verify import VerifySummary, engine_claims, inject_fault, verify_all


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.model_mode == "replay":
        replay.load_all()  # problems are logged; affected vendors fall back to the mock fixtures, degraded
    if not replay.pure_replay():
        await store.init()
    for vendor_id in ALLOWED_VENDORS:
        apply_levers(build_base(vendor_id))
    yield
    persist.flush()


app = FastAPI(title="CategoryOS", lifespan=lifespan)

origins = ["http://localhost:3000"]
if settings.frontend_origin:
    origins.append(settings.frontend_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["X-Demo-Key", "Last-Event-ID", "Content-Type"],
)


@app.exception_handler(CategoryOSError)
async def categoryos_error_handler(request: Request, exc: CategoryOSError) -> JSONResponse:
    run_id = request.headers.get("X-Run-Id")
    return JSONResponse(status_code=exc.status, content=exc.to_dict(run_id))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/stages")
async def stages() -> list[dict[str, str]]:
    return [{**stage, "status": "planned"} for stage in STAGE_META]


@app.get("/api/vendors")
async def vendors() -> list[dict[str, Any]]:
    out = []
    for vendor_id in ALLOWED_VENDORS:
        base = build_base(vendor_id)
        lever = apply_levers(base)
        out.append(
            {
                "id": vendor_id,
                "brand": base.brand,
                "company_name": base.company_name,
                "categories": base.categories,
                "proposed_terms": base.proposed_terms,
                "sku_count": len(base.skus),
                "summary": lever.summary.model_dump(),
                "metrics_hash": lever.metrics_hash,
            }
        )
    return out


@app.get("/api/vendors/{vendor_id}")
async def vendor_detail(vendor_id: str) -> dict[str, Any]:
    check_vendor(vendor_id)
    base = build_base(vendor_id)
    return {**load_application(vendor_id), "id": vendor_id, "sku_count": len(base.skus)}


@app.get("/api/vendors/{vendor_id}/decide/metrics", response_model=LeverResponse)
async def decide_metrics(
    vendor_id: str,
    target_margin_pct_offset: float = Query(0, ge=-20, le=20),
    moq: int | None = Query(None, ge=0, le=20000),
) -> LeverResponse:
    check_vendor(vendor_id)
    return apply_levers(build_base(vendor_id), target_margin_pct_offset, moq)


@app.get("/api/vendors/{vendor_id}/claims", response_model=VerifySummary)
async def vendor_claims(
    vendor_id: str,
    target_margin_pct_offset: float = Query(0, ge=-20, le=20),
    moq: int | None = Query(None, ge=0, le=20000),
    inject: int = Query(0, ge=0, le=1),
) -> VerifySummary:
    check_vendor(vendor_id)
    lever = apply_levers(build_base(vendor_id), target_margin_pct_offset, moq)
    claims = engine_claims(vendor_id, lever)
    if inject:
        claims = inject_fault(claims)
    return verify_all(claims)


@app.get("/api/mode")
async def mode() -> dict[str, Any]:
    problems = replay.problems()
    return {
        "mode": settings.effective_mode,
        "degraded": bool(problems),
        **({"replay": replay.status()} if settings.model_mode == "replay" else {}),
        "configured_mode": settings.model_mode,
        "live_stages": [s.strip() for s in settings.live_stages.split(",") if s.strip()],
        "stage_modes": {stage["id"]: resolve_mode(stage["id"]) for stage in STAGE_META},
        "spend_usd": round(ledger.total_usd(), 4),
        "max_spend_usd": settings.max_spend_usd,
        "warn_spend_usd": settings.warn_spend_usd,
    }


@app.get("/api/ledger", dependencies=[Depends(require_demo_key)])
async def get_ledger() -> dict[str, Any]:
    return {**ledger.read(), "max_spend_usd": settings.max_spend_usd, "warn_spend_usd": settings.warn_spend_usd}


# ---------- assets ----------


@app.get("/api/assets/{vendor_id}/{file}")
async def get_asset(vendor_id: str, file: str) -> FileResponse:
    """A cached catalog or campaign image. Path-safe: known vendor, plain `<sku>-<kind>.png` / `campaign.png` names only.
    A missing file is rendered as a labelled placeholder (mock and replay) when it names a real SKU."""
    path = media.resolve_asset(vendor_id, file)
    if path is None:
        raise AssetNotFound(cause=f"{file!r} is not a valid asset name for {vendor_id}")
    if not path.exists():
        parsed = media.is_known_asset_name(file)
        base = build_base(vendor_id)
        sku = next((s for s in base.skus if parsed and s.code == parsed[0]), None)
        if parsed is None or resolve_mode("catalog") == "live" or (sku is None and parsed[0] != "campaign"):
            raise AssetNotFound()
        title = sku.name if sku else f"{base.brand} launch campaign"
        subtitle = (sku.pack or "") if sku else base.brand
        media.ensure_placeholder(vendor_id, file, parsed[1], title, subtitle)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})


# ---------- runs ----------


async def require_demo_key_if_live(request: Request, x_demo_key: str | None = Header(default=None)) -> None:
    """Routes that can spend model credits need the demo key only when some stage would run live."""
    if any_live():
        await require_demo_key(request, x_demo_key)


@app.post("/api/vendors/{vendor_id}/runs", status_code=202, dependencies=[Depends(require_demo_key_if_live)])
async def start_run(vendor_id: str) -> dict[str, str]:
    check_vendor(vendor_id)
    return {"run_id": await runner.create_run(vendor_id)}


@app.get("/api/vendors/{vendor_id}/runs/latest")
async def latest_run(vendor_id: str) -> dict[str, str | None]:
    check_vendor(vendor_id)
    return {"run_id": await runner.latest_run(vendor_id)}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    return await runner.get_run_view(run_id)


def _sse(event: TraceEvent) -> str:
    return f"id: {event.seq}\nevent: trace\ndata: {event.model_dump_json()}\n\n"


async def _event_stream(run_id: str, last_id: int) -> AsyncIterator[str]:
    state = await runner.get_state(run_id)
    assert state is not None
    queue: asyncio.Queue[TraceEvent] = asyncio.Queue()
    state.subscribers.append(queue)  # subscribe first so nothing falls between replay and live
    try:
        seen = last_id
        for event in await state.db.events_after(run_id, last_id):
            seen = event.seq
            yield _sse(event)
            if event.type == "done":
                return
        if state.done:  # stored history ended without a done event (interrupted run)
            tail = TraceEvent(seq=seen + 1, run_id=run_id, t_rel_ms=0, type="done", payload={"interrupted": True})
            yield _sse(tail)
            return
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=settings.sse_heartbeat_s)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if event.seq <= seen:
                continue
            seen = event.seq
            yield _sse(event)
            if event.type == "done":
                return
    finally:
        state.subscribers.remove(queue)


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, last_event_id: str | None = Header(default=None)) -> StreamingResponse:
    await runner.require_run(run_id)
    try:
        last_id = max(int(last_event_id), 0) if last_event_id else 0
    except ValueError:
        last_id = 0
    return StreamingResponse(
        _event_stream(run_id, last_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/runs/{run_id}/stages/{stage}/approve")
async def approve_stage(run_id: str, stage: str, body: ApproveBody) -> StageResult:
    return await runner.approve(run_id, runner.check_stage(stage), body.metrics_hash)


@app.post("/api/runs/{run_id}/stages/{stage}/override")
async def override_stage(run_id: str, stage: str, body: OverrideBody) -> StageResult:
    return await runner.override(run_id, runner.check_stage(stage), body.sku_code, body.verdict, body.note)


@app.post("/api/vendors/{vendor_id}/decide/replan", dependencies=[Depends(require_demo_key_if_live)])
async def replan(vendor_id: str, body: ReplanBody) -> StageResult:
    check_vendor(vendor_id)
    return await runner.replan(body.run_id, vendor_id, body.target_margin_pct_offset, body.moq)


@app.post("/api/vendors/{vendor_id}/reject")
async def reject_vendor(vendor_id: str, body: RejectBody) -> dict[str, Any]:
    return await runner.reject(body.run_id, vendor_id, body.reason)


@app.post("/api/admin/reset", dependencies=[Depends(require_demo_key)])
async def admin_reset() -> dict[str, bool]:
    await runner.reset()
    return {"ok": True}
