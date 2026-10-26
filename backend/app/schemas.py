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


StageId = Literal["intake", "research", "shortlist", "negotiate", "catalog", "marketing", "jbp", "po"]
Unit = Literal["pct", "inr", "units", "score", "ratio", "qty"]
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


class StageResult(BaseModel):
    stage: str
    status: StageStatus
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    needs_approval: bool = False
    locked_reason: str | None = None
    claims: list[Claim] = Field(default_factory=list)
    metrics_hash: str | None = None
    narrative_hash: str | None = None


TraceType = Literal[
    "stage_started", "tool_call", "model_call", "claim_checked", "stage_result", "degraded", "error", "done"
]


class TraceEvent(BaseModel):
    seq: int
    run_id: str
    t_rel_ms: float
    type: TraceType
    stage: str | None = None
    model: str | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------- agent outputs (the "final" of a tool-calling run) ----------


class RiskFlag(BaseModel):
    type: str
    quote: str
    severity: Literal["low", "medium", "high"]


class ScreenFinal(BaseModel):
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    injection_detected: bool
    followup_questions: list[str] = Field(default_factory=list)
    decision: Literal["pass", "fail"]
    reasons: list[str] = Field(default_factory=list)


class SkuRationale(BaseModel):
    code: str
    verdict: Verdict
    why: str


class CounterTerm(BaseModel):
    model_config = {"extra": "allow"}

    term: str
    ask: str | float | int | None = None
    rationale: str = ""


class CounterOffer(BaseModel):
    terms: list[CounterTerm] = Field(default_factory=list)
    email_draft: str = ""


class Extraction(BaseModel):
    sku_code: str
    field: Literal["cost", "mrp"]
    value: float
    row: int
    header: str


class DecideFinal(BaseModel):
    headline: str
    rationale_per_sku: list[SkuRationale]
    counter_offer: CounterOffer
    extractions: list[Extraction] = Field(default_factory=list)


# ---------- request bodies ----------


class ApproveBody(BaseModel):
    metrics_hash: str


class OverrideBody(BaseModel):
    sku_code: str
    verdict: Verdict
    note: str | None = None


class ReplanBody(BaseModel):
    run_id: str
    target_margin_pct_offset: float = Field(ge=-20, le=20)
    moq: int = Field(ge=0, le=20000)


class RejectBody(BaseModel):
    run_id: str
    reason: str


# ---------- Negotiate / Catalog / Launch model outputs ----------

CommitTerm = Literal["margin_pct", "payment_days", "moq", "marketing_inr", "launch_discount_pct", "returns"]


class Commitment(BaseModel):
    term: CommitTerm
    offered: float
    transcript_quote: str
    turn: int


class Refusal(BaseModel):
    term: str
    transcript_quote: str = ""
    turn: int | None = None
    note: str = ""


class NegotiateCounter(BaseModel):
    asks: list[str] = Field(default_factory=list)
    email_draft: str = ""


class NegotiateFinal(BaseModel):
    commitments: list[Commitment] = Field(default_factory=list)
    refusals: list[Refusal] = Field(default_factory=list)
    counter_offer: NegotiateCounter = Field(default_factory=NegotiateCounter)


class ClassifyItem(BaseModel):
    code: str
    category: str
    subcategory: str


class ClassifyFinal(BaseModel):
    classifications: list[ClassifyItem]


class ComplianceFlag(BaseModel):
    rule: str
    text: str
    severity: Literal["low", "medium", "high"] = "medium"


class CatalogCopy(BaseModel):
    sku_code: str
    title: str
    bullets: list[str] = Field(default_factory=list)
    description: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    compliance_flags: list[ComplianceFlag] = Field(default_factory=list)


class CatalogCopyFinal(BaseModel):
    items: list[CatalogCopy]


class JbpFinal(BaseModel):
    markdown: str


class DiscountAsk(BaseModel):
    brand_funded_pct: float
    our_pct: float
    rationale: str = ""


class MarketingFinal(BaseModel):
    model_config = {"populate_by_name": True}

    campaign_name: str
    copy_text: str = Field(alias="copy")
    discount_ask: DiscountAsk
