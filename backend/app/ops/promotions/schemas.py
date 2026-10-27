"""Structured model outputs and API bodies of the promotions planner."""

from typing import Literal

from pydantic import BaseModel, Field

from app.ops.schemas import Figure


class FundingTerm(BaseModel):
    """One funding promise in a vendor's reply: a share of the markdown, perhaps conditional on a sales target and/or a banner."""

    share_pct: float | None = None  # "fund 50% of the markdown" -> 50
    scope: list[str] = Field(default_factory=list)  # SKU codes the promise covers; empty means the vendor's range
    threshold_units: float | None = None  # a sales target for the range over the event
    window_days: int | None = None
    banner_top_n: int | None = None  # "if you guarantee a top-3 banner" -> 3
    quote: str  # verbatim sentence or clause of the reply stating the promise


class FundingReading(BaseModel):
    reply_id: str
    stance: Literal["offer", "conditional_offer", "decline"]
    summary: str
    lead_time_days: int | None = None  # when the vendor states its lead time
    lead_time_quote: str = ""
    terms: list[FundingTerm] = Field(default_factory=list)


class FundingRepliesFinal(BaseModel):
    readings: list[FundingReading] = Field(default_factory=list)


class PromoBriefFinal(BaseModel):
    headline: str
    brief: str
    figures: list[Figure] = Field(default_factory=list)


class PlanDecideBody(BaseModel):
    sku_codes: list[str] | None = None  # approve only these SKUs (default: every planned SKU)
    note: str | None = None
