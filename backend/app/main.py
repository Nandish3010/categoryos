import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Header, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from app import (
    copilot,
    ledger,
    media,
    persist,
    policy,
    registry,
    replay,
    runner,
    sandbox,
    store,
    uploads,
)
from app.agents import pricereq as price_requests
from app.auth import require_demo_key
from app.config import settings
from app.constants import ALLOWED_VENDORS, STAGE_META
from app.data_loader import check_vendor, doc_path, load_application
from app.errors import AssetNotFound, CategoryOSError, LeverOutOfRange, PolicyReadOnly
from app.llm import any_live, resolve_mode
from app.metrics import apply_levers, build_base
from app.ops.api import router as ops_router
from app.ops.catalog_qc.api import router as catalog_qc_router
from app.ops.inventory_health.api import router as inventory_health_router
from app.ops.pricewatch.api import router as price_watch_router
from app.ops.promotions.api import router as promotions_router
from app.schemas import (
    ApproveBody,
    EndCallBody,
    LeverResponse,
    OverrideBody,
    PolicyResetBody,
    RejectBody,
    ReplanBody,
    StageResult,
    StartCallBody,
    TraceEvent,
    TurnBody,
)
from app.verify import VerifySummary, engine_claims, inject_fault, verify_all


def warm_caches() -> None:
    """Pay the one-time costs (market data, playbook, per-vendor metrics and claim verification) before the first request,
    so the first page load of the demo is as fast as the hundredth. Deterministic and free: no model calls."""
    for vendor_id in ALLOWED_VENDORS:
        lever = apply_levers(build_base(vendor_id))
        verify_all(engine_claims(vendor_id, lever))
    policy.policy_hash()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.model_mode == "replay":
        replay.load_all()  # problems are logged; affected vendors fall back to the mock fixtures, degraded
    if not replay.pure_replay():
        await store.init()
    warm_caches()
    sandbox.cleanup()  # expired sandbox vendors from a previous run of the server
    sweeper = asyncio.create_task(sandbox.cleanup_loop())
    yield
    sweeper.cancel()
    persist.flush()


app = FastAPI(title="CategoryOS", lifespan=lifespan)
app.include_router(ops_router)  # Run: weekly review and PO follow-up for existing vendors
app.include_router(catalog_qc_router)  # Run: catalog QC / fix queue for existing listings
app.include_router(promotions_router)  # Run: promotions and event planner
app.include_router(price_watch_router)  # Run: competitor price monitor
app.include_router(inventory_health_router)  # Run: weekly inventory health review

origins = ["http://localhost:3000"]
if settings.frontend_origin:
    origins.append(settings.frontend_origin)

app.add_middleware(sandbox.SandboxScopeMiddleware)
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
    extra = {"sandbox": sandbox.public(vendor_id) | {"skus_without_market_data": sum(1 for s in base.skus if not s.market_data)}} if registry.is_sandbox_id(vendor_id) else {}
    return {**load_application(vendor_id), "id": vendor_id, "sku_count": len(base.skus), **extra}


def check_levers(vendor_id: str, offset: float | None, moq: int | None) -> None:
    """Enforce the playbook's lever bounds (the Query limits stay as the outer safety)."""
    bounds = policy.get().levers
    if offset is not None and not bounds.margin_offset.min <= offset <= bounds.margin_offset.max:
        raise LeverOutOfRange(
            f"target_margin_pct_offset {offset:g} is outside {bounds.margin_offset.min:g} to {bounds.margin_offset.max:g} percentage points",
            fix="Pick a value inside the range, or widen levers.margin_offset in the playbook",
        )
    if moq is not None:
        proposed = int(build_base(vendor_id).proposed_terms.get("moq_units") or 0)
        ceiling = max(proposed, int(bounds.moq.max_factor * proposed))
        if moq > ceiling:
            raise LeverOutOfRange(
                f"moq {moq} is above {ceiling} ({bounds.moq.max_factor:g}x the vendor's proposed {proposed})",
                fix="Pick a lower MOQ, or raise levers.moq.max_factor in the playbook",
            )


@app.get("/api/vendors/{vendor_id}/decide/metrics", response_model=LeverResponse)
async def decide_metrics(
    vendor_id: str,
    target_margin_pct_offset: float = Query(0, ge=-20, le=20),
    moq: int | None = Query(None, ge=0, le=20000),
) -> LeverResponse:
    check_vendor(vendor_id)
    check_levers(vendor_id, target_margin_pct_offset, moq)
    return apply_levers(build_base(vendor_id), target_margin_pct_offset, moq)


@app.get("/api/vendors/{vendor_id}/claims", response_model=VerifySummary)
async def vendor_claims(
    vendor_id: str,
    target_margin_pct_offset: float = Query(0, ge=-20, le=20),
    moq: int | None = Query(None, ge=0, le=20000),
    inject: int = Query(0, ge=0, le=1),
) -> VerifySummary:
    check_vendor(vendor_id)
    check_levers(vendor_id, target_margin_pct_offset, moq)
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
        "policy_hash": policy.policy_hash(),
        "degraded": bool(problems),
        **({"replay": replay.status()} if settings.model_mode == "replay" else {}),
        "configured_mode": settings.model_mode,
        "live_stages": [s.strip() for s in settings.live_stages.split(",") if s.strip()],
        "stage_modes": {stage["id"]: resolve_mode(stage["id"]) for stage in STAGE_META},
        "spend_usd": round(ledger.total_usd(), 4),
        "max_spend_usd": settings.max_spend_usd,
        "warn_spend_usd": settings.warn_spend_usd,
    }


# ---------- playbook ----------


async def require_policy_write(request: Request, x_demo_key: str | None = Header(default=None)) -> None:
    """Writes are refused in replay; a demo key is required only when one is configured."""
    if settings.effective_mode == "replay":
        raise PolicyReadOnly()
    if settings.demo_key:
        await require_demo_key(request, x_demo_key)


@app.get("/api/policy")
async def get_policy() -> dict[str, Any]:
    return policy.snapshot()


@app.put("/api/policy", dependencies=[Depends(require_policy_write)])
async def put_policy(body: dict[str, Any]) -> dict[str, Any]:
    policy.save_overrides(body)
    return policy.snapshot()


@app.post("/api/policy/reset", dependencies=[Depends(require_policy_write)])
async def reset_policy(body: PolicyResetBody | None = None) -> dict[str, Any]:
    policy.reset(body.section if body else None)
    return policy.snapshot()


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


@app.get("/api/docs/{vendor_id}/{file}")
async def get_doc(vendor_id: str, file: str) -> FileResponse:
    """A vendor's uploaded scan, label photo or PDF. Path-safe: a known vendor and a file name its manifest lists."""
    path = doc_path(vendor_id, file)
    if path is None:
        raise AssetNotFound(cause=f"{file!r} is not a document of {vendor_id}")
    media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".pdf": "application/pdf"}.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "public, max-age=300"})


# ---------- runs ----------


async def require_demo_key_if_live(
    request: Request, vendor_id: str | None = None, x_demo_key: str | None = Header(default=None)
) -> None:
    """Routes that can spend model credits need the demo key only when some stage would run live. A sandbox vendor never
    needs it: without a key (or once its IP budget is spent) it is run rules-only instead."""
    if registry.is_sandbox_id(vendor_id):
        sandbox.authorize_run(request, vendor_id or "", x_demo_key)
        return
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


@app.get("/api/impact")
async def team_impact() -> dict[str, Any]:
    return await runner.team_impact()


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
    check_levers(vendor_id, body.target_margin_pct_offset, body.moq)
    with registry.scoped(vendor_id):
        return await runner.replan(body.run_id, vendor_id, body.target_margin_pct_offset, body.moq)


@app.post("/api/vendors/{vendor_id}/reject")
async def reject_vendor(vendor_id: str, body: RejectBody) -> dict[str, Any]:
    return await runner.reject(body.run_id, vendor_id, body.reason)


# ---------- live negotiation copilot ----------


@app.post("/api/vendors/{vendor_id}/call", status_code=202, dependencies=[Depends(require_demo_key_if_live)])
async def start_call(vendor_id: str, body: StartCallBody, request: Request, x_demo_key: str | None = Header(default=None)) -> dict[str, Any]:
    """Start a call. `simulate` plays the recorded call through the pipeline (free in mock/replay); `live` listens to the
    microphone chunks and always needs the demo key (and live mode)."""
    check_vendor(vendor_id)
    if body.mode == "live":
        await require_demo_key(request, x_demo_key)
    session = copilot.start(vendor_id, body.mode, body.speed)
    return {"call_id": session.call_id, "mode": session.mode}


@app.post("/api/vendors/{vendor_id}/call/chunks", dependencies=[Depends(require_demo_key_if_live)])
async def call_chunk(
    vendor_id: str,
    call_id: Annotated[str, Form()],
    audio: Annotated[UploadFile, File()],
    speaker: Annotated[str, Form()] = "auto",
) -> dict[str, Any]:
    """One push-to-talk clip (16 kHz mono WAV, about six seconds) -> transcription -> a new turn -> incremental extraction."""
    check_vendor(vendor_id)
    session = copilot.get(call_id, vendor_id)
    data = await audio.read(settings.call_chunk_max_bytes + 1)
    turn = await copilot.ingest_chunk(session, data, speaker)
    return {"turn": turn, "state": session.state}


@app.post("/api/vendors/{vendor_id}/call/turns", dependencies=[Depends(require_demo_key_if_live)])
async def call_turn(vendor_id: str, body: TurnBody) -> dict[str, Any]:
    """A typed line (the fallback when there is no microphone), through the same pipeline."""
    check_vendor(vendor_id)
    session = copilot.get(body.call_id, vendor_id)
    turn = await copilot.ingest_text(session, body.speaker, body.text)
    return {"turn": turn, "state": session.state}


@app.post("/api/vendors/{vendor_id}/call/end")
async def end_call(vendor_id: str, body: EndCallBody) -> dict[str, Any]:
    check_vendor(vendor_id)
    session = copilot.get(body.call_id, vendor_id)
    await copilot.end(session)
    return copilot.snapshot(session)


@app.get("/api/vendors/{vendor_id}/call/{call_id}")
async def get_call(vendor_id: str, call_id: str) -> dict[str, Any]:
    check_vendor(vendor_id)
    return copilot.snapshot(copilot.get(call_id, vendor_id))


def _call_sse(event: dict[str, Any]) -> str:
    return f"id: {event['seq']}\nevent: call\ndata: {json.dumps(event)}\n\n"


async def _call_stream(session: copilot.CallSession, last_id: int) -> AsyncIterator[str]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    session.subscribers.append(queue)  # subscribe first so nothing falls between the replay and the live events
    try:
        seen = last_id
        for event in list(session.events):
            if event["seq"] > seen:
                seen = event["seq"]
                yield _call_sse(event)
                if event["type"] == "ended":
                    return
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=settings.sse_heartbeat_s)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if event["seq"] <= seen:
                continue
            seen = event["seq"]
            yield _call_sse(event)
            if event["type"] == "ended":
                return
    finally:
        session.subscribers.remove(queue)


@app.get("/api/vendors/{vendor_id}/call/{call_id}/events")
async def call_events(vendor_id: str, call_id: str, last_event_id: str | None = Header(default=None)) -> StreamingResponse:
    check_vendor(vendor_id)
    session = copilot.get(call_id, vendor_id)
    try:
        last_id = max(int(last_event_id), 0) if last_event_id else 0
    except ValueError:
        last_id = 0
    return StreamingResponse(
        _call_stream(session, last_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/admin/reset", dependencies=[Depends(require_demo_key)])
async def admin_reset() -> dict[str, bool]:
    await runner.reset()
    return {"ok": True}


# ---------- bring your own vendor ----------

MAX_UPLOAD_BODY = 40 * 1024 * 1024  # sheet + application + documents + multipart overhead; refused before parsing


@app.get("/api/uploads/options")
async def upload_options(request: Request, x_demo_key: str | None = Header(default=None)) -> dict[str, Any]:
    return sandbox.options(sandbox.demo_key_ok(x_demo_key), sandbox.client_ip(request))


@app.get("/api/uploads/samples/{name}/sku_sheet.csv")
async def sample_sheet(name: str) -> FileResponse:
    return FileResponse(sandbox.sample_dir(name) / "sku_sheet.csv", media_type="text/csv", filename=f"{name}_sample_sku_sheet.csv")


async def _read_capped(f: UploadFile, limit: int, what: str) -> bytes:
    data = await f.read(limit + 1)
    if len(data) > limit:
        raise uploads.UploadTooLarge(f"The {what} is over {limit // 1024 // 1024 or limit // 1024} {'MB' if limit >= 1024 * 1024 else 'KB'}")
    return data


@app.post("/api/uploads", status_code=201)
async def create_upload(
    request: Request,
    starter: str = Form("pet"),
    sample: str | None = Form(None),
    sheet: UploadFile | None = File(None),  # noqa: B008
    application: UploadFile | None = File(None),  # noqa: B008
    company_name: str | None = Form(None),
    brand_name: str | None = Form(None),
    vendor_type: str | None = Form(None),
    categories: str | None = Form(None),
    margin_offered_pct: float | None = Form(None),
    payment_terms_days: int | None = Form(None),
    moq_units: int | None = Form(None),
    marketing_support_inr: float | None = Form(None),
    launch_discount_pct: float | None = Form(None),
    returns_policy: str | None = Form(None),
    pitch: str | None = Form(None),
    documents: list[UploadFile] = File(default_factory=list),  # noqa: B008
    doc_kinds: list[str] = Form(default_factory=list),  # noqa: B008
    doc_declares: list[str] = Form(default_factory=list),  # noqa: B008
    x_demo_key: str | None = Header(default=None),
) -> dict[str, Any]:
    """Create a sandbox vendor from an uploaded SKU sheet (or a bundled sample). Free: the engine runs without models;
    model stages run only when allowed (see sandbox.decide_llm_mode)."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_UPLOAD_BODY:
        raise uploads.UploadTooLarge("The upload is too large", fix="Send a smaller sheet and fewer or smaller documents")
    if sample and sheet is not None:
        raise uploads.UploadError("Send either a sample or a sheet, not both")
    sheet_bytes = await _read_capped(sheet, settings.upload_max_sheet_bytes, "sheet") if sheet is not None else None
    app_in = None
    if application is not None:
        app_in = uploads.parse_application_json(await _read_capped(application, settings.upload_max_application_bytes, "application"))
    elif company_name or brand_name:
        terms = {
            k: v
            for k, v in {
                "margin_offered_pct": margin_offered_pct,
                "payment_terms_days": payment_terms_days,
                "moq_units": moq_units,
                "marketing_support_inr": marketing_support_inr,
                "launch_discount_pct": launch_discount_pct,
                "returns_policy": returns_policy,
            }.items()
            if v is not None
        }
        app_in = uploads.application_from(
            {
                "company_name": company_name or brand_name,
                "brand_name": brand_name or company_name,
                "vendor_type": vendor_type,
                "categories": categories or "",
                "proposed_terms": terms,
                "pitch": pitch or "",
            }
        )
    docs = []
    for i, f in enumerate(documents[: settings.upload_max_docs + 1]):
        data = await _read_capped(f, settings.upload_max_doc_bytes, "document")
        kind = doc_kinds[i] if i < len(doc_kinds) else ""
        docs.append(sandbox.DocIn(data, kind, "", doc_declares[i] if i < len(doc_declares) else ""))
    keyed = sandbox.demo_key_ok(x_demo_key)
    return sandbox.create(ip=sandbox.client_ip(request), keyed=keyed, starter=starter, sheet=sheet_bytes, sample=sample, application=app_in, docs=docs)


@app.get("/api/vendors/{vendor_id}/export.csv")
async def export_verdicts(vendor_id: str) -> Response:
    """The verdict table as CSV. Every cell is neutralised against spreadsheet formula injection."""
    import csv
    import io

    check_vendor(vendor_id)
    lever = apply_levers(build_base(vendor_id))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["sku_code", "name", "category", "verdict", "mrp", "cost", "margin_pct", "target_pct", "demand_score", "overlap", "reasons"])
    for s in lever.skus:
        row = [s.code, s.name, s.category, s.verdict, s.mrp, s.cost, s.margin_pct, s.target_pct, s.demand_score, s.overlap, "; ".join(s.reasons)]
        w.writerow([uploads.csv_safe(c) if isinstance(c, str) else c for c in row])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{vendor_id}_verdicts.csv"'})


# ---------- existing-vendor price-increase requests ----------


class PriceRequestBody(BaseModel):
    vendor_id: str
    email: str
    price_list: str = ""
    sender: str = ""
    subject: str = ""
    received_at: str | None = None


class PriceDecisionBody(BaseModel):
    role: str
    email_body: str | None = None
    note: str | None = None


@app.get("/api/price-requests")
async def list_price_requests() -> dict[str, Any]:
    """The inbox: requests from existing vendors waiting for a decision (no model call)."""
    return {"requests": [price_requests.request_row(r) for r in price_requests.inbox()]}


@app.post("/api/price-requests", status_code=201, dependencies=[Depends(require_demo_key_if_live)])
async def submit_price_request(body: PriceRequestBody) -> dict[str, Any]:
    req = price_requests.submit(body.vendor_id, body.email, body.price_list, body.sender, body.subject, body.received_at)
    return price_requests.request_row(req)


@app.get("/api/price-requests/{request_id}", dependencies=[Depends(require_demo_key_if_live)])
async def get_price_request(request_id: str) -> dict[str, Any]:
    """Extraction (quote-checked, self-corrected), the engine's per-SKU numbers and decisions, sweetener value, approval tier,
    counter-offer and the reply draft. The numbers follow the live playbook."""
    return await price_requests.view(price_requests.get_request(request_id))


@app.post("/api/price-requests/{request_id}/approve", dependencies=[Depends(require_demo_key_if_live)])
async def approve_price_request(request_id: str, body: PriceDecisionBody) -> dict[str, Any]:
    """A person approves at their role: the reply is recorded as sent. Sending is simulated, nothing leaves the backend."""
    return await price_requests.decide(price_requests.get_request(request_id), "approve", body.role, body.email_body, body.note)


@app.post("/api/price-requests/{request_id}/reject", dependencies=[Depends(require_demo_key_if_live)])
async def reject_price_request(request_id: str, body: PriceDecisionBody) -> dict[str, Any]:
    return await price_requests.decide(price_requests.get_request(request_id), "reject", body.role, None, body.note)
