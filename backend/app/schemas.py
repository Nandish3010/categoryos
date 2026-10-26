from typing import Any, Literal

from pydantic import BaseModel, Field


class Vendor(BaseModel):
    id: str
    name: str
    contact_email: str
    category: str
    documents: list[str] = Field(default_factory=list)


class SKU(BaseModel):
    id: str
    vendor_id: str
    name: str
    brand: str
    category: str
    mrp: float
    cost_price: float
    pack_size: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    image_urls: list[str] = Field(default_factory=list)


class StageResult(BaseModel):
    stage: str
    status: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    needs_approval: bool = False


StageId = Literal["intake", "research", "shortlist", "negotiate", "catalog", "marketing", "jbp", "po"]
Unit = Literal["pct", "inr", "units", "score"]
Verdict = Literal["list", "negotiate", "reject", "needs_data"]
CostSource = Literal["sheet", "inferred", "missing"]
ClaimOrigin = Literal["engine", "model_extraction", "injected_test"]
ClaimStatus = Literal["pending", "verified", "rejected", "unverifiable"]
StageStatus = Literal["pending", "running", "review", "done", "locked", "failed", "degraded"]


class SourceRef(BaseModel):
    file: str
    key: str
    column: str | None = None


class Evidence(BaseModel):
    row: int | None = None
    header: str | None = None
    raw_value: str | None = None
    normalized_value: float | str | None = None
    parser_version: str
    sha256: str


class Claim(BaseModel):
    id: str
    text: str
    value: float
    metric: str
    unit: Unit
    sku_key: str | None = None
    source_ref: SourceRef
    evidence: Evidence | None = None
    origin: ClaimOrigin = "engine"
    status: ClaimStatus = "pending"
    recomputed: float | None = None
    reason: str | None = None


class BaseSku(BaseModel):
    sku_key: str
    code: str
    name: str
    sheet_row: int
    raw: dict[str, str]
    columns: dict[str, str]
    category: str
    subcategory: str
    pack: str | None = None
    pack_normalized: str | None = None
    mrp: float | None = None
    cost: float | None = None
    cost_source: CostSource
    selling_price: float | None = None
    competitor_count: int = 0
    price_gap_pct: float | None = None
    matched_keyword: str | None = None
    demand_score: float = 0.0
    overlap: float = 0.0
    nearest_sku_id: str | None = None
    review_score: float | None = None
    avg_monthly_units: float
    est_monthly_units: float
    category_target_pct: float
    category_min_pct: float
    flags: list[str] = Field(default_factory=list)


class SkuMetrics(BaseSku):
    target_pct: float
    landed_cost: float | None = None
    margin_pct: float | None = None
    est_gmv: float = 0.0
    fit_score: float | None = None
    verdict: Verdict
    reasons: list[str] = Field(default_factory=list)
    required_cost: float | None = None
    alloc_units: int = 0
    capital_at_risk_inr: float = 0.0


class VendorBase(BaseModel):
    vendor_id: str
    brand: str
    company_name: str
    categories: list[str]
    proposed_terms: dict[str, Any]
    parser_version: str
    skus: list[BaseSku]


class DecideSummary(BaseModel):
    counts: dict[str, int]
    moq: int
    shortlisted: int
    capital_at_risk_inr: float
    days_of_cover: float | None
    est_monthly_gmv: float
    moq_flag: bool


class LeverResponse(BaseModel):
    vendor_id: str
    target_margin_pct_offset: float
    skus: list[SkuMetrics]
    summary: DecideSummary
    metrics_hash: str
    computed_ms: float
