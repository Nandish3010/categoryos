from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import ledger
from app.auth import require_demo_key
from app.config import settings
from app.constants import ALLOWED_VENDORS, STAGE_META
from app.data_loader import check_vendor, load_application
from app.errors import CategoryOSError
from app.llm import resolve_mode
from app.metrics import apply_levers, build_base
from app.schemas import LeverResponse
from app.verify import VerifySummary, engine_claims, inject_fault, verify_all


@asynccontextmanager
async def lifespan(_: FastAPI):
    for vendor_id in ALLOWED_VENDORS:
        apply_levers(build_base(vendor_id))
    yield


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
    return {
        "mode": settings.effective_mode,
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
