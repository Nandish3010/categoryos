from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.constants import ALLOWED_VENDORS, STAGE_META
from app.data_loader import check_vendor, load_application
from app.errors import MissingInput, UnknownMetric, UnknownVendor
from app.metrics import apply_levers, build_base
from app.schemas import LeverResponse


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


@app.exception_handler(UnknownVendor)
async def unknown_vendor_handler(_: Request, exc: UnknownVendor) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(UnknownMetric)
@app.exception_handler(MissingInput)
async def bad_input_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


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
