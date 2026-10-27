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
Unit = Literal["pct", "inr", "units", "score", "ratio", "qty", "pts"]
Verdict = Literal["list", "negotiate", "reject", "needs_data"]
CostSource = Literal["sheet", "inferred", "missing"]
ClaimOrigin = Literal["engine", "model_extraction", "vision_extraction", "injected_test"]
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
    # vision_extraction only: where on which scan the value was read, and the second, independent read of that region
    doc: str | None = None
    page: int | None = None
    bbox: list[float] | None = None  # [x0, y0, x1, y1], fractions of the page (0 to 1)
    crop_sha256: str | None = None
    reread_value: str | None = None
    as_of: str | None = None  # ISO date the expiry arithmetic of a date claim was done against


class ClaimAttempt(BaseModel):
    """One try at a model-extraction claim. attempt 0 is the agent's first answer; later ones follow verifier feedback."""

    attempt: int
    value: float
    status: ClaimStatus
    reason: str | None = None
    recomputed: float | None = None


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
    # Set only when the verifier rejected the agent's first answer: the timeline of attempts, oldest first.
    attempts: list[ClaimAttempt] = Field(default_factory=list)


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
    vendor_type_pp: float = 0.0
    brand_pp: float = 0.0
    flags: list[str] = Field(default_factory=list)


class TargetBreakdown(BaseModel):
    """Where a SKU's target margin comes from, all in percent / percentage points."""

    category_pct: float
    vendor_type_pp: float = 0.0
    brand_pp: float = 0.0
    lever_pp: float = 0.0


class SkuMetrics(BaseSku):
    target_pct: float
    target_breakdown: TargetBreakdown | None = None
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
    "stage_started",
    "tool_call",
    "model_call",
    "claim_checked",
    "claim_rejected",
    "self_correction",
    "claim_verified",
    "claim_unresolved",
    "stage_result",
    "degraded",
    "error",
    "done",
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


class ClaimFix(BaseModel):
    """The agent's corrected answer to one rejected claim. Which fields it fills depends on the claim:
    a sheet extraction gives value (+ row, header); a negotiation commitment gives value (+ turn, transcript_quote)."""

    claim_id: str
    value: float
    row: int | None = None
    header: str | None = None
    turn: int | None = None
    transcript_quote: str | None = None


class FixFinal(BaseModel):
    fixes: list[ClaimFix] = Field(default_factory=list)


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


class PolicyResetBody(BaseModel):
    section: str | None = None


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


# ---------- Deal evaluator: contingent offers (extracted by the model, valued by app.deals) ----------

DealKind = Literal[
    "base", "conditional", "tiered", "rebate", "free_goods", "exclusivity",
    "payment_for_discount", "moq_for_discount", "sell_or_return", "price_protection",
]
DealTermName = Literal[
    "margin_pct", "back_margin_pct", "discount_pct", "marketing_pct", "marketing_inr",
    "free_goods_pct", "returnable_pct", "exclusivity_months", "price_protection_days",
]
DealMetric = Literal["units", "gmv_inr", "sell_through_pct"]


class DealCondition(BaseModel):
    """What the vendor wants in return: sell ``threshold`` (units | gmv_inr | sell_through_pct) within ``window_days``."""

    metric: DealMetric
    threshold: float
    window_days: int
    scope: list[str] = Field(default_factory=list)  # SKU codes; empty means every SKU we list


class DealTier(BaseModel):
    threshold: float
    value: float


class DealTerm(BaseModel):
    id: str
    kind: DealKind
    term: DealTermName
    value: float
    unit: Literal["pct", "inr", "units", "days", "months"] = "pct"
    condition: DealCondition | None = None
    tiers: list[DealTier] = Field(default_factory=list)  # slabs: the bonus at each threshold (not cumulative)
    scope: list[str] = Field(default_factory=list)  # SKU codes the term applies to; empty means all
    base_of: str | None = None  # id of the base term this bonus sits on top of
    days: float | None = None  # payment_for_discount: pay within this many days; sell_or_return: the window
    units: float | None = None  # moq_for_discount: the first-order quantity the vendor requires
    quote: str
    turn: int  # transcript turn, or 1-based index into application.proposed_terms.additional_terms
    source: Literal["transcript", "application"] = "transcript"


class DealExtraction(BaseModel):
    terms: list[DealTerm] = Field(default_factory=list)


class DealTalk(BaseModel):
    talk_track: str = ""
    email_paragraph: str = ""


class TurnExtraction(BaseModel):
    """Live copilot: what ONE new call turn changed (commitments, refusals, conditional terms)."""

    commitments: list[Commitment] = Field(default_factory=list)
    refusals: list[Refusal] = Field(default_factory=list)
    deal_terms: list[DealTerm] = Field(default_factory=list)

# ---------- Document vision (muse-spark-1.3 with images) ----------


class VisionField(BaseModel):
    """One value the vision model read off a page. ``value`` is the text exactly as printed."""

    name: str
    value: str
    bbox: list[float] = Field(min_length=4, max_length=4)  # [x0, y0, x1, y1] as fractions of the page
    confidence: float = 1.0
    sku_code: str | None = None


class VisionExtraction(BaseModel):
    kind: str
    legible: bool = True
    fields: list[VisionField] = Field(default_factory=list)
    notes: str = ""


class RereadItem(BaseModel):
    name: str
    value: str
    sku_code: str | None = None


class VisionReread(BaseModel):
    reads: list[RereadItem] = Field(default_factory=list)
