"""The playbook: every tunable business rule, loaded from config/policy.yaml (defaults) plus
config/policy.local.yaml (overrides written by the UI). Nothing vertical-specific lives in Python.

* ``get()`` returns the effective, validated ``Policy`` (cached on file mtimes; replay mode ignores local overrides so
  recorded runs stay consistent).
* ``save_overrides`` validates the merged result BEFORE writing; ``reset`` deletes a section, a path or the whole file.
* ``schema_hints`` is generated from the model's Field metadata so the UI renders forms without hardcoding fields.
"""

import hashlib
import json
import math
import os
import re
import string
import types
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app import scope
from app.config import settings
from app.errors import PolicyInvalid

Scope = Literal["all"] | list[str]
TERM_NAMES = ("margin_offered_pct", "payment_terms_days", "moq_units", "marketing_support_inr", "launch_discount_pct", "returns_policy")
TERM_KEY = {
    "margin_offered_pct": "margin_pct",
    "payment_terms_days": "payment_days",
    "moq_units": "moq",
    "marketing_support_inr": "marketing_inr",
    "launch_discount_pct": "launch_discount_pct",
    "returns_policy": "returns",
}
BUILTIN_FAIL = ("blocking_document", "prompt_injection")
STAGES_ALL = ["intake", "research", "shortlist", "negotiate", "catalog", "marketing", "jbp", "po"]


def F(default: Any = ..., label: str | None = None, help: str = "", *, unit: str | None = None, min: float | None = None,
      max: float | None = None, step: float | None = None, used_in: list[str] | None = None, options: list[str] | None = None) -> Any:
    """Field with UI metadata. min/max also become validation bounds."""
    extra = {k: v for k, v in {"label": label, "help": help, "unit": unit, "min": min, "max": max, "step": step, "used_in": used_in, "options": options}.items() if v is not None}
    kwargs: dict[str, Any] = {}
    if min is not None:
        kwargs["ge"] = min
    if max is not None:
        kwargs["le"] = max
    return Field(default, json_schema_extra=extra, **kwargs)


class M(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def _compile_all(patterns: list[str]) -> list[str]:
    for p in patterns:
        try:
            re.compile(p)
        except re.error as exc:
            raise ValueError(f"invalid regex {p!r}: {exc}") from exc
    return patterns


# ---------- sections ----------


class Business(M):
    retailer: str = F("an Indian online pet retailer", "Retailer", "Who the agents work for, as it reads in a sentence.", used_in=STAGES_ALL)
    vertical: str = F("pet", "Vertical", "One word for the product world, used in prompts.", used_in=STAGES_ALL)


class VendorType(M):
    label: str = F(label="Label")
    target_offset_pp: float = F(0, "Target offset", "Percentage points added to every category target for this kind of vendor.", unit="pp", min=-50, max=50, step=0.5)


class Onboarding(M):
    required_application_fields: list[str] = F(label="Required application fields", help="Application fields that must be present; Intake flags the rest.", used_in=["intake"])
    required_terms: list[str] = F(label="Terms compared in negotiation", help="Commercial terms in the gap table (application field names).", used_in=["negotiate"], options=list(TERM_NAMES))
    vendor_types: dict[str, VendorType] = F(label="Vendor types", help="Kinds of vendor; the application's vendor_type picks one and shifts the margin target.", used_in=["research", "negotiate"])

    @field_validator("required_terms")
    @classmethod
    def _terms(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in TERM_NAMES]
        if bad:
            raise ValueError(f"unknown term(s) {bad}; use {list(TERM_NAMES)}")
        return v


class DocumentRule(M):
    type: str = F(label="Document")
    blocking: bool = F(True, "Blocking", "Expired or missing fails screening.")
    categories: Scope = F("all", "Applies to", "'all' or the categories this document applies to.")


class ClaimRule(M):
    type: str = F(label="Rule")
    severity: Literal["low", "medium", "high"] = F("medium", "Severity", options=["low", "medium", "high"])
    categories: Scope = F("all", "Applies to", "'all' or the categories this rule applies to.")
    patterns: list[str] = F(label="Patterns", help="Regex alternatives, case-insensitive, matched on word boundaries.")
    examples: list[str] = F([], label="Examples", help="Shown to the model in prompts.")

    @field_validator("patterns")
    @classmethod
    def _patterns(cls, v: list[str]) -> list[str]:
        return _compile_all(v)


class Screening(M):
    documents: list[DocumentRule] = F(label="Documents", help="One row per compliance document type.", used_in=["intake"])
    absent_document_counts_as_missing: bool = F(True, "Absent counts as missing", "A blocking document that applies but is not listed counts as missing.", used_in=["intake"])
    expiry_warning_days: int = F(60, "Expiry warning", "Flag valid documents expiring within this many days.", unit="days", min=0, max=3650, step=5, used_in=["intake"])
    fail_on: list[str] = F(label="Fail screening on", help="blocking_document, prompt_injection or a claim rule type.", used_in=["intake"], options=["blocking_document", "prompt_injection"])
    claim_rules: list[ClaimRule] = F(label="Claim rules", help="Shared by Intake (vendor text) and Catalog (listing compliance).", used_in=["intake", "catalog"])
    injection_patterns: list[str] = F(label="Injection patterns", help="Regexes spotting vendor text addressed to an AI reviewer.", used_in=["intake"])
    data_quality_flags: list[str] = F(label="Data-quality flags", help="SKU data gaps the agent reports as missing_data.", used_in=["intake"])

    @field_validator("injection_patterns")
    @classmethod
    def _inj(cls, v: list[str]) -> list[str]:
        return _compile_all(v)


class Segment(M):
    name: str = F(label="Segment", help="Placeholder name usable as {name} in category names.")
    values: dict[str, list[str]] = F(label="Values", help="value -> regexes; the first value is the default.")

    @field_validator("values")
    @classmethod
    def _vals(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if not v:
            raise ValueError("a segment needs at least one value")
        for pats in v.values():
            _compile_all(pats)
        return v


class TaxCategory(M):
    name: str = F(label="Category", help="May contain {segment} placeholders.")
    patterns: list[str] = F(label="Patterns", help="Regexes matched against the SKU name, then the description.")
    subcategories: dict[str, list[str]] = F({}, label="Subcategories", help="Ordered; first match wins; an empty list is the default.")
    approximate_as: str | None = F(None, "Approximate as", "Classify matches as this category and flag approx_category.")

    @field_validator("patterns")
    @classmethod
    def _patterns(cls, v: list[str]) -> list[str]:
        return _compile_all(v)

    @field_validator("subcategories")
    @classmethod
    def _subs(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for pats in v.values():
            _compile_all(pats)
        return v


class Taxonomy(M):
    fallback_category: str = F(label="Fallback category", help="Used when nothing matches.", used_in=["research", "catalog"])
    segments: list[Segment] = F([], label="Segments", help="Optional extra dimension read from text (species, gender, skin type).", used_in=["research", "catalog"])
    categories: list[TaxCategory] = F(label="Classification rules", help="Ordered; the first category whose patterns match wins.", used_in=["research", "catalog"])


class KeywordMatching(M):
    generic_tokens: list[str] = F(label="Generic tokens", help="Words that carry less weight when matching a keyword.")
    generic_weight: float = F(0.5, "Generic weight", "Weight of a generic token relative to a specific one.", min=0, max=1, step=0.05)
    stop_tokens: list[str] = F(label="Stop tokens", help="Words ignored when comparing names.")
    min_coverage: float = F(0.7, "Minimum coverage", "Share of the keyword's weight that must be present.", min=0, max=1, step=0.05)


class FitWeights(M):
    margin: float = F(0.4, "Margin", min=0, max=1, step=0.05)
    demand: float = F(0.3, "Demand", min=0, max=1, step=0.05)
    overlap: float = F(0.2, "Low overlap", min=0, max=1, step=0.05)
    review: float = F(0.1, "Reviews", min=0, max=1, step=0.05)


class Research(M):
    demand_min: float = F(0.40, "Minimum demand", "A SKU below this demand percentile is rejected.", min=0, max=1, step=0.05, used_in=["research", "shortlist"])
    overlap_max: float = F(0.60, "Maximum overlap", "A SKU at or above this catalog similarity is rejected.", min=0, max=1, step=0.05, used_in=["research", "shortlist"])
    freight_pct: float = F(0.04, "Freight", "Landed cost = cost x (1 + freight).", unit="ratio", min=0, max=1, step=0.01, used_in=["research"])
    neutral_review_score: float = F(0.6, "Neutral review score", "Used when the brand has no reviews.", min=0, max=1, step=0.05, used_in=["research"])
    keyword_matching: KeywordMatching = F(label="Keyword matching", used_in=["research"])
    fit_weights: FitWeights = F(label="Fit score weights", help="Must sum to 1.", used_in=["research"])
    below_min_margin_action: Literal["negotiate", "reject"] = F("negotiate", "Below-floor action", "reject makes the minimum margin bite.", used_in=["research", "shortlist"], options=["negotiate", "reject"])
    moq_flag_factor: float = F(2.0, "MOQ flag factor", "Flag a vendor MOQ above this multiple of monthly units.", unit="x", min=0, max=100, step=0.5, used_in=["research"])

    @model_validator(mode="after")
    def _weights(self) -> "Research":
        w = self.fit_weights
        total = w.margin + w.demand + w.overlap + w.review
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"fit_weights must sum to 1 (got {total:g})")
        return self


class CategoryMargin(M):
    target_pct: float = F(label="Target margin", unit="%", min=0, max=95, step=0.5)
    min_pct: float = F(label="Minimum margin", unit="%", min=0, max=95, step=0.5)
    payment_terms_days: int = F(30, "Payment terms", unit="days", min=0, max=365, step=1)

    @model_validator(mode="after")
    def _order(self) -> "CategoryMargin":
        if self.min_pct > self.target_pct:
            raise ValueError("min_pct cannot exceed target_pct")
        return self


class BrandOffset(M):
    target_offset_pp: float = F(0, "Target offset", unit="pp", min=-50, max=50, step=0.5)
    note: str = F("", "Note")


class Margins(M):
    categories: dict[str, CategoryMargin] = F(label="Category margins", help="Base targets per category; add or remove rows for your vertical.", used_in=["research", "shortlist", "negotiate"])
    brands: dict[str, BrandOffset] = F({}, label="Brand offsets", help="Optional per-brand offsets.", used_in=["research", "negotiate"])

    @field_validator("categories")
    @classmethod
    def _nonempty(cls, v: dict[str, CategoryMargin]) -> dict[str, CategoryMargin]:
        if not v:
            raise ValueError("at least one category is required")
        return v


class Forecast(M):
    ramp_by_month: list[float] = F([0.5, 0.75, 0.9, 1.0], "Ramp by month", "Share of steady-state monthly units a new listing sells in month 1, 2, 3...; the last value repeats.", used_in=["negotiate"])
    cv: float = F(0.45, "Forecast uncertainty", "Coefficient of variation of a SKU's demand over the window (lognormal).", unit="ratio", min=0.01, max=3, step=0.05, used_in=["negotiate"])
    cv_by_category: dict[str, float] = F({}, label="Uncertainty by category", help="Per-category override of the coefficient of variation.", used_in=["negotiate"])
    sku_correlation: float = F(0.5, "SKU correlation", "Share of demand noise common to all SKUs (0 independent, 1 move together).", min=0, max=1, step=0.05, used_in=["negotiate"])
    mc_draws: int = F(20000, "Monte Carlo draws", "Simulation size; more draws, smoother probabilities.", min=1000, max=200000, step=1000, used_in=["negotiate"])
    seed: int = F(42, "Random seed", "Fixed so the same inputs always give the same probability.", min=0, max=2147483647, step=1, used_in=["negotiate"])

    @field_validator("ramp_by_month")
    @classmethod
    def _ramp(cls, v: list[float]) -> list[float]:
        if not v or any(not 0 < x <= 3 for x in v):
            raise ValueError("ramp_by_month needs at least one value, each above 0 and at most 3")
        return v

    @field_validator("cv_by_category")
    @classmethod
    def _cv(cls, v: dict[str, float]) -> dict[str, float]:
        for k, x in v.items():
            if not 0.01 <= x <= 3:
                raise ValueError(f"cv for {k!r} must be between 0.01 and 3")
        return v


class Contingent(M):
    min_probability: float = F(0.6, "Minimum probability", "A conditional bonus counts only when the chance of earning it is at least this.", unit="ratio", min=0, max=1, step=0.05, used_in=["negotiate"])
    value_basis: Literal["risk_adjusted", "guaranteed_only"] = F("risk_adjusted", "Value basis", "risk_adjusted counts probability x bonus; guaranteed_only counts no conditional bonus at all.", used_in=["negotiate"], options=["risk_adjusted", "guaranteed_only"])
    dead_stock_horizon_days: int = F(180, "Dead-stock horizon", "Days after which unsold stock is treated as dead.", unit="days", min=30, max=730, step=30, used_in=["negotiate"])
    dead_stock_writeoff_pct: float = F(100, "Dead-stock write-off", "Share of the cost of unsold stock that is lost.", unit="%", min=0, max=100, step=5, used_in=["negotiate"])
    counter_window_days: list[float] = F([30, 45, 60, 90, 120, 180, 270, 365], "Counter windows", "Windows (days) tried when proposing a longer or shorter condition window.", used_in=["negotiate"])
    threshold_round_units: float = F(10, "Round unit thresholds to", unit="units", min=1, max=10000, step=1, used_in=["negotiate"])
    threshold_round_inr: float = F(5000, "Round rupee thresholds to", unit="inr", min=1, max=10000000, step=500, used_in=["negotiate"])
    threshold_round_pct: float = F(1, "Round sell-through thresholds to", unit="pp", min=0.1, max=50, step=0.5, used_in=["negotiate"])

    @field_validator("counter_window_days")
    @classmethod
    def _windows(cls, v: list[float]) -> list[float]:
        if any(x < 1 for x in v):
            raise ValueError("each counter window must be at least 1 day")
        return v


class Negotiation(M):
    margin_ask: Literal["target", "min"] = F("target", "Margin we ask for", "target or the floor.", used_in=["negotiate"], options=["target", "min"])
    payment_terms_days: Literal["category"] | int = F("category", "Payment terms", "'category' or a fixed number of days.", used_in=["negotiate"])
    payment_longer_is_better: bool = F(True, "Longer payment terms favour us", used_in=["negotiate"])
    moq_max_factor: float = F(2.0, "MOQ ceiling", "Largest acceptable first-order MOQ as a multiple of monthly units.", unit="x", min=0, max=100, step=0.5, used_in=["negotiate"])
    marketing_min_pct_of_order: float = F(0.10, "Marketing support", "Share of first-order retail value.", unit="ratio", min=0, max=1, step=0.01, used_in=["negotiate"])
    launch_discount_min_pct: float = F(5, "Launch discount", unit="%", min=0, max=100, step=0.5, used_in=["negotiate"])
    defect_return_min_days: int = F(7, "Defect return window", unit="days", min=0, max=365, step=1, used_in=["negotiate"])
    cost_of_capital_pct_annual: float = F(14, "Cost of capital", "Annual rate used to price paying earlier for a discount.", unit="%", min=0, max=100, step=0.5, used_in=["negotiate"])
    inventory_carrying_pct_monthly: float = F(2, "Inventory carrying cost", "Monthly cost of holding extra stock, as a share of its cost.", unit="%", min=0, max=20, step=0.25, used_in=["negotiate"])
    forecast: Forecast = F(Forecast(), "Demand forecast", "How the agent estimates the chance of hitting a vendor's sales target.", used_in=["negotiate"])
    contingent: Contingent = F(Contingent(), "Conditional offers", "How offers such as '20% marketing support if you sell 2,000 units' are valued and decided.", used_in=["negotiate"])


class Bullets(M):
    min: int = F(3, "Min bullets", min=0, max=20, step=1)
    max: int = F(5, "Max bullets", min=1, max=20, step=1)

    @model_validator(mode="after")
    def _o(self) -> "Bullets":
        if self.min > self.max:
            raise ValueError("min cannot exceed max")
        return self


class Sentences(M):
    min: int = F(2, "Min sentences", min=0, max=20, step=1)
    max: int = F(3, "Max sentences", min=1, max=20, step=1)

    @model_validator(mode="after")
    def _o(self) -> "Sentences":
        if self.min > self.max:
            raise ValueError("min cannot exceed max")
        return self


class LabelLicence(M):
    document: str = F(label="Document")
    attribute: str = F(label="Listing attribute")
    categories: Scope = F("all", "Applies to")


class LabelCheck(M):
    categories: Scope = F("all", "Applies to")
    require: list[str] = F(label="Require", options=["shelf_life", "net_quantity", "ingredients"])

    @field_validator("require")
    @classmethod
    def _req(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if r not in ("shelf_life", "net_quantity", "ingredients")]
        if bad:
            raise ValueError(f"unknown label check(s) {bad}")
        return v


_SIZE = re.compile(r"^\d{2,5}x\d{2,5}$")


class ImageSizes(M):
    packshot: str = F("1024x1024", "Packshot")
    lifestyle: str = F("1792x1024", "Lifestyle")
    campaign: str = F("1792x1024", "Campaign")

    @field_validator("packshot", "lifestyle", "campaign")
    @classmethod
    def _size(cls, v: str) -> str:
        if not _SIZE.match(v):
            raise ValueError("use WIDTHxHEIGHT, for example 1024x1024")
        return v


class ImagePrompts(M):
    packshot: str = F(label="Packshot prompt", help="Placeholders: {brand} {name} {pack} {category} {subcategory}.")
    lifestyle: str = F(label="Lifestyle prompt", help="Placeholders as above plus segment names.")
    campaign: str = F(label="Campaign prompt", help="Placeholders: {brand} {campaign}.")
    segmentation: dict[str, str] = F(label="Cut-out phrases", help="Phrase per category for segmentation; 'default' covers the rest.")

    @field_validator("packshot", "lifestyle", "campaign")
    @classmethod
    def _tpl(cls, v: str) -> str:
        try:
            list(string.Formatter().parse(v))
        except ValueError as exc:
            raise ValueError(f"bad template: {exc}") from exc
        return v

    @field_validator("segmentation")
    @classmethod
    def _seg(cls, v: dict[str, str]) -> dict[str, str]:
        if "default" not in v:
            raise ValueError("segmentation needs a 'default' phrase")
        return v


class Catalog(M):
    title_max_chars: int = F(80, "Title length", unit="chars", min=10, max=500, step=5, used_in=["catalog"])
    bullets: Bullets = F(label="Bullets", used_in=["catalog"])
    description_sentences: Sentences = F(label="Description sentences", used_in=["catalog"])
    required_attributes: dict[str, list[str]] = F(label="Required attributes", help="Per category; 'default' covers the rest.", used_in=["catalog"])
    label_licences: list[LabelLicence] = F([], label="Label licences", help="Licence numbers that must appear on listings.", used_in=["catalog"])
    label_checks: list[LabelCheck] = F([], label="Label information checks", used_in=["catalog"])
    hero_sku_count: int = F(3, "Hero SKUs", "SKUs that get a lifestyle image.", min=0, max=50, step=1, used_in=["catalog"])
    label_panel_prompt: str = F(
        "the nutrition or ingredients table and claims panel on the back of the pack",
        "Label panel prompt",
        "Noun phrase SAM uses to find the panel of a product label that Catalog reads closely.",
        used_in=["catalog"],
    )
    image_sizes: ImageSizes = F(label="Image sizes", used_in=["catalog", "marketing"])
    image_prompts: ImagePrompts = F(label="Image prompts", used_in=["catalog", "marketing"])

    @field_validator("required_attributes")
    @classmethod
    def _ra(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if "default" not in v:
            raise ValueError("required_attributes needs a 'default' row")
        return v


class Launch(M):
    launch_discount_days: int = F(30, "Discount window", unit="days", min=0, max=365, step=1, used_in=["marketing", "jbp"])
    launch_week_days: int = F(7, "Launch week", unit="days", min=1, max=60, step=1, used_in=["jbp"])
    sell_through_review_day: int = F(30, "Sell-through review", "Days after listings go live.", unit="days", min=0, max=365, step=1, used_in=["jbp"])
    listing_lag_days: int = F(2, "Listing lag", "Days between PO receipt and listings going live.", unit="days", min=0, max=60, step=1, used_in=["jbp"])
    platform_funded_discount_max_pct: float = F(0, "Platform-funded discount cap", unit="%", min=0, max=100, step=0.5, used_in=["marketing"])
    jbp_top_skus: int = F(5, "JBP SKUs", min=1, max=50, step=1, used_in=["jbp"])
    jbp_sections: list[str] = F(label="JBP sections", used_in=["jbp"])


class LeadDays(M):
    confirmed: int = F(2, "Confirmed", unit="days", min=0, max=365, step=1)
    shipped: int = F(5, "Shipped", unit="days", min=0, max=365, step=1)
    received: int = F(12, "Received", unit="days", min=0, max=365, step=1)


class Po(M):
    gst_rate_default: float = F(0.18, "Tax rate", unit="ratio", min=0, max=1, step=0.01, used_in=["po"])
    gst_rate_by_category: dict[str, float] = F({}, label="Tax rate by category", used_in=["po"])
    lead_days: LeadDays = F(label="Lead days", used_in=["po"])
    simulated_delay_days: int = F(3, "Simulated delay", "Demo only.", unit="days", min=0, max=60, step=1, used_in=["po"])
    number_format: str = F("PO-{vendor}-{date}", "PO number format", "{vendor} and {date} (YYYYMMDD).", used_in=["po"])

    @field_validator("number_format")
    @classmethod
    def _fmt(cls, v: str) -> str:
        try:
            v.format(vendor="V001", date="20260101")
        except (KeyError, IndexError, ValueError) as exc:
            raise ValueError("use only {vendor} and {date}") from exc
        return v

    @field_validator("gst_rate_by_category")
    @classmethod
    def _rates(cls, v: dict[str, float]) -> dict[str, float]:
        for k, rate in v.items():
            if not 0 <= rate <= 1:
                raise ValueError(f"rate for {k!r} must be between 0 and 1")
        return v


class MarginOffsetBounds(M):
    min: float = F(-10, "Minimum", unit="pp", min=-20, max=0, step=1)
    max: float = F(10, "Maximum", unit="pp", min=0, max=20, step=1)
    step: float = F(1, "Step", unit="pp", min=0.1, max=20, step=0.1)


class MoqBounds(M):
    step: int = F(50, "Step", unit="units", min=1, max=20000, step=10)
    max_factor: float = F(2, "Maximum factor", "Largest MOQ as a multiple of the vendor's proposal.", unit="x", min=1, max=100, step=0.5)


class Levers(M):
    margin_offset: MarginOffsetBounds = F(label="Margin offset", used_in=["research"])
    moq: MoqBounds = F(label="MOQ", used_in=["research"])


class Tolerances(M):
    pct: float = F(0.01, "Percent", min=0, max=5, step=0.005)
    inr: float = F(1.0, "Money", min=0, max=1000, step=0.5)
    units: float = F(0, "Units", min=0, max=1000, step=1)
    score: float = F(0.5, "Score", min=0, max=100, step=0.1)
    ratio: float = F(0.005, "Ratio", min=0, max=1, step=0.001)
    qty: float = F(0, "Quantity", min=0, max=1000, step=1)
    pts: float = F(0.05, "Margin points", "Tolerance for deal values expressed in margin points.", unit="pp", min=0, max=5, step=0.01)


class Verifier(M):
    tolerances: Tolerances = F(label="Tolerances", help="How closely a claim must match the recomputed value.", used_in=["research", "negotiate", "catalog", "po"])
    max_self_corrections: int = F(2, "Self-corrections", "When the verifier rejects something the agent read from a document, the agent is told what the source says and may retry this many times before the claim is left unresolved. 0 turns self-correction off.", unit="retries", min=0, max=5, step=1, used_in=["research", "negotiate", "catalog"])


IMPACT_SOURCE = "Research estimate (not measured): docs/research/category-manager-workload.md. Replace with your own time diary."


def _minutes(label: str, default: float, help: str = "") -> Any:
    return F(default, label, f"{help} {IMPACT_SOURCE}".strip(), unit="min", min=0, max=6000, step=5, used_in=["impact"])


class BaselineMinutes(M):
    """Human minutes each step of onboarding one new vendor takes by hand today (the report's table A, about 12 SKUs)."""

    screening: float = _minutes("Document screening", 45, "GST, licences, brand authorisation, FSSAI for one vendor.")
    market_research_per_sku: float = _minutes("Market research go/no-go, per SKU", 20)
    shortlist: float = _minutes("Shortlist and rationale", 30)
    negotiation_prep: float = _minutes("Negotiation prep and gap analysis", 60)
    negotiation_calls: float = _minutes("Negotiation calls and notes", 110, "Two 45 minute calls plus notes.")
    conditional_offer_eval: float = _minutes("Conditional-offer evaluation", 30)
    catalog_listing_per_sku: float = _minutes("Catalog listing from a messy sheet, per SKU", 25)
    image_content_per_sku: float = _minutes("Images and content sourcing and QC, per SKU", 10)
    compliance_per_sku: float = _minutes("Compliance checks, per SKU", 5)
    marketing_jbp_draft: float = _minutes("Marketing and JBP draft", 60)
    first_po_draft: float = _minutes("First PO draft", 30)


class RecurringMinutes(M):
    """By-hand minutes for recurring tasks that future modules would take over (the report's table B). Reference only."""

    price_increase_request: float = _minutes("Price-increase request evaluation", 90, "Per request (CM 60 + CE 30).")
    weekly_review_pack: float = _minutes("Weekly business review / MIS pack", 240, "Per category per week.")
    vendor_scorecard: float = _minutes("Vendor scorecard", 75, "Per vendor per month.")
    po_chase: float = _minutes("PO chase", 15, "Per late PO.")
    fill_rate_reconciliation: float = _minutes("Fill-rate reconciliation", 45, "Per vendor per week.")
    catalog_fix_per_sku: float = _minutes("Existing catalog fix, per SKU", 12)
    promotion_event_plan: float = _minutes("Promotion / event plan", 480, "Per event.")
    qbr_jbp_deck: float = _minutes("QBR / JBP deck", 600, "Per top vendor per quarter.")
    competitor_price_sweep: float = _minutes("Competitor price sweep", 30, "Per day per category.")
    inventory_ageing_review: float = _minutes("Inventory ageing review and liquidation plan", 180, "Per category per week.")


class Team(M):
    category_managers: int = F(1, "Category managers", "Headcount. " + IMPACT_SOURCE, min=0, max=1000, step=1, used_in=["impact"])
    category_executives: int = F(2, "Category executives", "Headcount. " + IMPACT_SOURCE, min=0, max=1000, step=1, used_in=["impact"])
    work_hours_per_week: float = F(45, "Working hours per week", "Per person. " + IMPACT_SOURCE, unit="h", min=1, max=100, step=1, used_in=["impact"])
    weeks_per_month: float = F(4.33, "Weeks per month", unit="weeks", min=1, max=5, step=0.01, used_in=["impact"])
    vendors_onboarded_per_month: float = F(3.2, "Vendors onboarded per month", "New vendors taken from application to PO each month (the report: 0.5 to 1 a week). " + IMPACT_SOURCE, min=0, max=10000, step=0.5, used_in=["impact"])
    typical_skus_per_vendor: int = F(12, "SKUs per new vendor", "Used to price a typical onboarding for the team projection. " + IMPACT_SOURCE, min=1, max=1000, step=1, used_in=["impact"])


class WorkTask(M):
    label: str = F(label="Task")
    category_manager_pct: float = F(0, "Category manager: share of week", unit="%", min=0, max=100, step=0.5)
    category_executive_pct: float = F(0, "Category executive: share of week", unit="%", min=0, max=100, step=0.5)
    saved_pct: float = F(0, "Time saved if automated", "Share of this task's time saved by a module that covers it, with human review.", unit="%", min=0, max=100, step=1)


class Module(M):
    label: str = F(label="Module")
    status: Literal["shipped", "not_built"] = F("not_built", "Status", "Only shipped modules count towards the saving; the rest are shown as a projection.", options=["shipped", "not_built"])
    measured_from_runs: bool = F(False, "Measured by runs", "Once runs are fully reviewed, this module's saved share is the measured review reduction instead of the table's estimate.")


class Coverage(M):
    module: str = F(label="Module", help="A key of impact.modules.")
    task: str = F(label="Task", help="A key of impact.workload.")
    in_scope_pct: float = F(100, "Share of the task covered", unit="%", min=0, max=100, step=5)


class Impact(M):
    baseline_status: Literal["research_estimate", "measured"] = F("research_estimate", "Baseline status", "research_estimate: the times, shares and team size here come from docs/research/category-manager-workload.md and are NOT measured; the UI says so. Set to measured once you have replaced them with a time diary of your own team.", used_in=["impact"], options=["research_estimate", "measured"])
    baseline_minutes: BaselineMinutes = F(label="Onboarding baseline, minutes by hand", help="One new vendor. " + IMPACT_SOURCE, used_in=["impact"])
    recurring_minutes: RecurringMinutes = F(label="Recurring tasks, minutes by hand", help="For future modules. " + IMPACT_SOURCE, used_in=["impact"])
    team: Team = F(label="Team", help=IMPACT_SOURCE, used_in=["impact"])
    workload: dict[str, WorkTask] = F(label="Where the week goes", help="Each task's share of a category manager's and a category executive's week, and how much of it automation saves. Each column sums to 100. " + IMPACT_SOURCE, used_in=["impact"])
    modules: dict[str, Module] = F(label="Modules", help="What exists or is planned. Register a new module here and list the tasks it covers below.", used_in=["impact"])
    coverage: list[Coverage] = F(label="Module coverage", help="Which share of which task each module takes over. Register new modules' coverage here.", used_in=["impact"])
    max_review_minutes: float = F(120, "Longest review counted", "A review gap longer than this is capped (the reviewer walked away); the cap is shown.", unit="min", min=1, max=1440, step=5, used_in=["impact"])
    target_reduction_pct: float = F(33.3, "Workload target", "The goal the team view is compared with: cut category-team workload by this much.", unit="%", min=0, max=100, step=0.1, used_in=["impact"])

    @model_validator(mode="after")
    def _refs(self) -> "Impact":
        for row in self.coverage:
            if row.module not in self.modules:
                raise ValueError(f"coverage row names unknown module {row.module!r}; use one of {sorted(self.modules)}")
            if row.task not in self.workload:
                raise ValueError(f"coverage row names unknown task {row.task!r}; use one of {sorted(self.workload)}")
        return self


# ---------- existing-vendor price-increase requests ----------


class Elasticity(M):
    default: float = F(-1.3, "Default elasticity", "Price elasticity of demand for a category without its own value: % change in units for a 1% price rise (negative).", min=-6, max=0, step=0.1)
    by_category: dict[str, float] = F({}, label="Elasticity by category", help="Category -> elasticity (negative). Units sold change by (1 + price rise) ^ elasticity.")
    risk_medium_loss_pct: float = F(5, "Medium risk from", "Volume loss at or above this is flagged as medium elasticity risk.", unit="%", min=0, max=100, step=0.5)
    risk_high_loss_pct: float = F(10, "High risk from", "Volume loss at or above this is flagged as high elasticity risk.", unit="%", min=0, max=100, step=0.5)

    @field_validator("by_category")
    @classmethod
    def _neg(cls, v: dict[str, float]) -> dict[str, float]:
        bad = [k for k, e in v.items() if e > 0]
        if bad:
            raise ValueError(f"elasticity must be zero or negative for {bad}")
        return v

    @model_validator(mode="after")
    def _order(self) -> "Elasticity":
        if self.risk_medium_loss_pct > self.risk_high_loss_pct:
            raise ValueError("the medium risk threshold cannot exceed the high one")
        return self


class PassThrough(M):
    allow: bool = F(True, "Allow pass-through to price", "When off, a cost increase is never answered by raising our retail price.", used_in=["negotiate"])
    max_competitor_gap_pct: float = F(5, "Largest gap to competitors", "Passing on is only allowed while the new price stays within this % above the competitor median.", unit="%", min=0, max=100, step=0.5, used_in=["negotiate"])
    max_volume_loss_pct: float = F(8, "Largest volume loss", "Passing on is only allowed while the elasticity model expects to lose no more than this share of units.", unit="%", min=0, max=100, step=0.5, used_in=["negotiate"])
    prefer_when_below_target: bool = F(True, "Prefer pass-through below target", "When absorbing would leave the margin under the category target but passing on is allowed, pass it on.", used_in=["negotiate"])


class Justification(M):
    index_name: str = F("Raw material index", "Index name", "The commodity or input index the justification check compares with.", used_in=["negotiate"])
    index_change_pct: float | None = F(3.0, "Index change", "Change in the input index since the vendor's last revision. Leave empty to skip the justification check.", unit="%", min=-100, max=1000, step=0.1, used_in=["negotiate"])
    index_change_by_category: dict[str, float] = F({}, label="Index change by category", help="Category -> index change (%), overriding the overall figure.")
    tolerance_pp: float = F(2.0, "Tolerance", "A request is justified up to the index change plus this many percentage points.", unit="pp", min=0, max=100, step=0.5, used_in=["negotiate"])


class ApprovalTier(M):
    above_pct: float = F(0, "Above", "The request (or counter) raises cost by more than this %.", unit="%", min=0, max=1000, step=0.5)
    approver: str = F(label="Approver", help="Role id, e.g. category_executive, category_manager, head_of_category.")
    label: str = F("", "Label")


class Approval(M):
    matrix: list[ApprovalTier] = F(label="Approval matrix", help="Who must approve, by the size of the cost increase being agreed. Ascending, the first row starts at 0.", used_in=["negotiate"])
    decision_floor: dict[str, str] = F({}, label="Minimum approver by decision", help="Decision (pass_through, delist, ...) -> role id: that decision needs at least this approver whatever the size.")

    @model_validator(mode="after")
    def _matrix(self) -> "Approval":
        if not self.matrix:
            raise ValueError("the approval matrix needs at least one row")
        steps = [r.above_pct for r in self.matrix]
        if steps != sorted(set(steps)) or steps[0] != 0:
            raise ValueError("approval matrix rows must start at 0 and have ascending, distinct 'above' values")
        roles = {r.approver for r in self.matrix}
        bad = [d for d, role in self.decision_floor.items() if role not in roles]
        if bad:
            raise ValueError(f"decision_floor names an approver that is not in the matrix for {bad}")
        return self


def _default_matrix() -> list[ApprovalTier]:
    return [
        ApprovalTier(above_pct=0, approver="category_executive", label="Category executive"),
        ApprovalTier(above_pct=5, approver="category_manager", label="Category manager"),
        ApprovalTier(above_pct=10, approver="head_of_category", label="Head of category"),
    ]


class PriceRequests(M):
    notice_period_days: int = F(30, "Notice period", "A cost change needs this many days between the request and its effective date; shorter notice is answered with a later date.", unit="days", min=0, max=365, step=1, used_in=["negotiate"])
    max_acceptable_increase_pct: float = F(5, "Largest increase without escalation", "Accepted outright up to this % when no input index justifies more; anything above is countered down to it (or passed on).", unit="%", min=0, max=100, step=0.5, used_in=["negotiate"])
    min_counter_pct: float = F(0.5, "Smallest useful counter", "A counter below this % is not offered: the line is delisted or an alternate is sought.", unit="%", min=0, max=100, step=0.1, used_in=["negotiate"])
    horizon_days: int = F(90, "Impact horizon", "Window for the GMV and margin impact.", unit="days", min=7, max=365, step=1, used_in=["negotiate"])
    elasticity: Elasticity = F(label="Demand elasticity", used_in=["negotiate"])
    pass_through: PassThrough = F(label="Pass-through to price", used_in=["negotiate"])
    justification: Justification = F(label="Commodity justification", used_in=["negotiate"])
    approval: Approval = F(label="Approvals", used_in=["negotiate"])


class DocKind(M):
    kind: str = F(label="Kind", help="Document kind id; a vendor's manifest assigns each file one.")
    label: str = F(label="Label")
    stage: Literal["intake", "catalog"] = F("intake", "Read in", "intake reads it during Screen; catalog reads it for shortlisted SKUs.", options=["intake", "catalog"])
    panel: bool = F(False, "Segment a panel", "Find the panel with SAM (catalog.label_panel_prompt) and re-read that crop.")
    per_sku: bool = F(False, "One row per SKU", "The document is a table: each field is read once per row, tagged with the row's SKU code.")


class DocField(M):
    kind: str = F(label="Kind")
    name: str = F(label="Field")
    label: str = F(label="Label")
    type: Literal["text", "date", "pct", "inr", "qty", "number"] = F("text", "Type", options=["text", "date", "pct", "inr", "qty", "number"])
    critical: bool = F(False, "Re-read", "Crop the field and read it a second time; the verifier needs both reads to agree.")


class CrossCheck(M):
    id: str = F(label="Id")
    label: str = F(label="Label")
    kind: str = F(label="Document kind")
    field: str = F(label="Field")
    against: Literal["application_document", "sku_sheet", "listing_copy"] = F(
        "application_document", "Compared with", options=["application_document", "sku_sheet", "listing_copy"]
    )
    target: str = F("", "Target", "application_document: number | valid_until | company_name; sku_sheet: mrp | cost | pack (a sheet column).")
    pattern: str = F("", "Pattern", "sku_sheet or listing_copy: a regex with one capture group, matched against the SKU row or listing text.")
    tolerance: float | None = F(None, "Tolerance", "In the field's unit (a fraction for pct). Empty uses the verifier tolerance for that unit.", min=0)
    severity: Literal["low", "medium", "high"] = F("medium", "Severity", options=["low", "medium", "high"])

    @field_validator("pattern")
    @classmethod
    def _pat(cls, v: str) -> str:
        if v:
            _compile_all([v])
        return v


class Documents(M):
    enabled: bool = F(False, "Read scanned documents", "Turn the vision pipeline on: certificates, labels and price lists are read, cross-checked and verified.", used_in=["intake", "catalog"])
    min_confidence: float = F(0.6, "Minimum confidence", "A field the model reads below this confidence is not trusted.", min=0, max=1, step=0.05, used_in=["intake", "catalog"])
    crop_padding: float = F(0.01, "Crop padding", "Margin added around a box when it is cropped for the re-read (share of the page).", min=0, max=0.2, step=0.005, used_in=["intake", "catalog"])
    max_pages: int = F(3, "Pages per document", "Pages read per document; the rest are ignored.", min=1, max=20, step=1, used_in=["intake", "catalog"])
    kinds: list[DocKind] = F([], label="Document kinds", help="Which kinds of document are read, and in which stage.", used_in=["intake", "catalog"])
    fields: list[DocField] = F([], label="Fields", help="What is read from each kind.", used_in=["intake", "catalog"])
    cross_checks: list[CrossCheck] = F([], label="Cross-checks", help="Which pairs of sources are compared, and how closely they must agree.", used_in=["intake", "catalog"])

    @model_validator(mode="after")
    def _refs(self) -> "Documents":
        kinds = {k.kind for k in self.kinds}
        if len(kinds) != len(self.kinds):
            raise ValueError("document kinds must be unique")
        names = {(f.kind, f.name) for f in self.fields}
        for f in self.fields:
            if f.kind not in kinds:
                raise ValueError(f"field {f.name!r} refers to unknown document kind {f.kind!r}")
        for c in self.cross_checks:
            if (c.kind, c.field) not in names:
                raise ValueError(f"cross-check {c.id!r} refers to unknown field {c.kind}.{c.field}")
            if c.against == "application_document" and c.target not in ("number", "valid_until", "company_name"):
                raise ValueError(f"cross-check {c.id!r}: target must be number, valid_until or company_name")
            if c.against == "sku_sheet" and not (c.pattern or c.target in ("mrp", "cost", "pack")):
                raise ValueError(f"cross-check {c.id!r}: give a pattern, or a target of mrp, cost or pack")
            if c.against == "listing_copy" and not c.pattern:
                raise ValueError(f"cross-check {c.id!r}: listing_copy needs a pattern")
        return self


# ---------- operations (Run: existing vendors) ----------


class Scorecard(M):
    fill_rate_floor_pct: float = F(90, "Fill-rate floor", "A vendor whose recent fill rate is below this is flagged.", unit="%", min=0, max=100, step=1, used_in=["ops_review", "ops_chaser"])
    fill_rate_drop_pp: float = F(8, "Fill-rate drop", "Flag a vendor whose recent fill rate fell this many points below its earlier fill rate.", unit="pp", min=0, max=100, step=1, used_in=["ops_review"])
    fill_rate_recent_weeks: int = F(4, "Recent window", "PO lines promised in the last N weeks count as recent; earlier lines are the comparison.", unit="weeks", min=1, max=12, step=1, used_in=["ops_review"])
    otif_target_pct: float = F(85, "OTIF target", "On time and in full: a vendor below this is flagged.", unit="%", min=0, max=100, step=1, used_in=["ops_review"])
    on_time_grace_days: int = F(1, "On-time grace", "A delivery up to this many days after the promised date still counts as on time.", unit="days", min=0, max=30, step=1, used_in=["ops_review"])
    in_full_min_pct: float = F(98, "In-full threshold", "A line counts as in full when at least this share of the ordered quantity arrived.", unit="%", min=1, max=100, step=1, used_in=["ops_review"])
    demand_window_days: int = F(28, "Demand window", "Daily demand for stock cover is the average over this many days.", unit="days", min=7, max=91, step=7, used_in=["ops_review", "ops_chaser"])
    stock_cover_alert_days: int = F(14, "Stock-cover alert", "A SKU with fewer days of cover than this is flagged.", unit="days", min=0, max=365, step=1, used_in=["ops_review"])
    overstock_cover_days: int = F(90, "Overstock cover", "A SKU with more days of cover than this counts as overstocked.", unit="days", min=1, max=1000, step=5, used_in=["ops_review"])
    ageing_buckets_days: list[int] = F(label="Ageing buckets", help="Upper edges in days since receipt, for example 30, 60, 90. The last bucket is everything older than the largest edge.", used_in=["ops_review"])
    aged_alert_pct: float = F(20, "Aged-stock alert", "Flag a vendor when this share of its stock value is older than the last bucket edge.", unit="%", min=0, max=100, step=1, used_in=["ops_review"])
    return_rate_alert_pct: float = F(4, "Return-rate alert", "Flag a SKU or vendor whose returns over the last four weeks exceed this share of units sold.", unit="%", min=0, max=100, step=0.5, used_in=["ops_review"])
    rating_drop_alert: float = F(0.3, "Rating-drop alert", "Flag a SKU whose rating fell by at least this much over four weeks.", unit="stars", min=0, max=5, step=0.1, used_in=["ops_review"])

    @field_validator("ageing_buckets_days")
    @classmethod
    def _buckets(cls, v: list[int]) -> list[int]:
        if not v or any(b <= 0 for b in v) or v != sorted(set(v)):
            raise ValueError("use positive, strictly increasing day edges, for example 30, 60, 90")
        return v


class AnomalyRules(M):
    growth_z_threshold: float = F(2.5, "Growth anomaly z-score", "A week is an anomaly when it sits this many standard deviations from the trailing weeks.", unit="z", min=0.5, max=10, step=0.1, used_in=["ops_review"])
    growth_min_change_pct: float = F(15, "Minimum week-on-week change", "...and moved at least this much against the previous week.", unit="%", min=0, max=500, step=1, used_in=["ops_review"])
    lookback_weeks: int = F(12, "Lookback", "Trailing weeks that form the baseline.", unit="weeks", min=4, max=12, step=1, used_in=["ops_review"])
    min_weekly_units: int = F(30, "Minimum weekly units", "SKUs selling less than this per week are too noisy to test.", unit="units", min=0, max=10000, step=5, used_in=["ops_review"])


class WeeklyActions(M):
    max_actions: int = F(8, "Actions listed", "Length of the what-to-do-this-week list.", unit="actions", min=1, max=30, step=1, used_in=["ops_review"])
    priority_weights: dict[str, float] = F(label="Priority weights", help="Base score per action type; severity multiplies it. Types: stockout, fill_rate, otif, ageing, returns, rating, sales_drop, sales_spike, overstock.", used_in=["ops_review"])


class EscalationRung(M):
    name: str = F(label="Rung")
    days_overdue: int = F(0, "From days overdue", "Reached when the PO is this many days past its promised date (negative: before it is due).", unit="days", min=-30, max=365, step=1)
    channel: str = F("email", "Channel", options=["email", "whatsapp", "email+whatsapp"])
    owner: str = F("category executive", "Owner")
    tone: str = F("friendly", "Tone", "How the drafted message should read.")


class PoFollowup(M):
    ladder: list[EscalationRung] = F(label="Escalation ladder", help="Ordered by days overdue. The PO sits on the highest rung it has reached.", used_in=["ops_chaser"])
    vague_reply_bumps_rung: bool = F(True, "Vague reply escalates", "A reply with no dated commitment moves a late PO up one rung.", used_in=["ops_chaser"])
    stockout_buffer_days: int = F(2, "Stock-out buffer", "Cover must exceed the remaining lead time by this many days to be safe.", unit="days", min=0, max=60, step=1, used_in=["ops_chaser"])
    default_lead_days: int = F(7, "Default lead time", "Assumed wait for an overdue PO with no dated commitment.", unit="days", min=1, max=90, step=1, used_in=["ops_chaser"])

    @field_validator("ladder")
    @classmethod
    def _ladder(cls, v: list[EscalationRung]) -> list[EscalationRung]:
        if not v:
            raise ValueError("the ladder needs at least one rung")
        days = [r.days_overdue for r in v]
        if days != sorted(days):
            raise ValueError("order the rungs by days overdue, smallest first")
        return v


def _default_ladder() -> list[EscalationRung]:
    return [
        EscalationRung(name="Nudge", days_overdue=-2, channel="email", owner="category executive", tone="friendly"),
        EscalationRung(name="Chase", days_overdue=1, channel="email+whatsapp", owner="category executive", tone="firm but polite"),
        EscalationRung(name="Escalate", days_overdue=4, channel="email", owner="category manager", tone="firm; copy the vendor's head of sales"),
        EscalationRung(name="Formal notice", days_overdue=8, channel="email", owner="category manager", tone="formal; refer to the PO terms and name the alternative-sourcing option"),
    ]


def _default_weights() -> dict[str, float]:
    return {"stockout": 100, "fill_rate": 70, "otif": 50, "ageing": 45, "overstock": 30, "returns": 55, "rating": 40, "sales_drop": 60, "sales_spike": 25}


class Operations(M):
    scorecard: Scorecard = Field(
        default_factory=lambda: Scorecard(ageing_buckets_days=[30, 60, 90]),
        json_schema_extra={"label": "Scorecard thresholds", "help": "Fill rate, OTIF, stock cover, ageing, returns and rating limits.", "used_in": ["ops_review"]},
    )
    anomaly: AnomalyRules = Field(default_factory=AnomalyRules, json_schema_extra={"label": "Anomaly detection", "help": "When a weekly movement counts as unusual.", "used_in": ["ops_review"]})
    actions: WeeklyActions = Field(
        default_factory=lambda: WeeklyActions(max_actions=8, priority_weights=_default_weights()),
        json_schema_extra={"label": "Weekly actions", "help": "How the what-to-do-this-week list is ranked.", "used_in": ["ops_review"]},
    )
    po_followup: PoFollowup = Field(
        default_factory=lambda: PoFollowup(ladder=_default_ladder()),
        json_schema_extra={"label": "PO follow-up", "help": "Escalation ladder and stock-out risk for open purchase orders.", "used_in": ["ops_chaser"]},
    )


# ---------- catalog QC (Run: fix queue for existing listings) ----------

QC_ISSUE_TYPES = (
    "title_too_long", "title_missing_attributes", "missing_attribute", "banned_claim", "mrp_mismatch", "pack_mismatch",
    "duplicate_listing", "wrong_category", "missing_image", "low_res_image", "high_returns_not_as_described", "expired_licence",
    "label_mismatch",
)
_Sev = Literal["low", "medium", "high"]


def _sev(label: str, default: _Sev, help: str = "") -> Any:
    return F(default, label, help, options=["low", "medium", "high"], used_in=["ops_catalog"])


class QcSeverities(M):
    title_too_long: _Sev = _sev("Title over the limit", "low", "Longer than catalog.title_max_chars.")
    title_missing_attributes: _Sev = _sev("Title missing key attributes", "medium", "Lacks something listed in 'Title must contain'.")
    missing_attribute: _Sev = _sev("Missing required attribute", "medium", "A catalog.required_attributes entry for the listing's category is empty.")
    banned_claim: _Sev = _sev("Banned or unproven claim", "high", "A screening.claim_rules pattern matches the listing copy. The rule's own severity is used when it is higher.")
    mrp_mismatch: _Sev = _sev("MRP differs from price list or label", "high")
    pack_mismatch: _Sev = _sev("Pack size differs from the price list", "high")
    duplicate_listing: _Sev = _sev("Near-duplicate listing", "medium")
    wrong_category: _Sev = _sev("Wrong category or subcategory", "medium")
    missing_image: _Sev = _sev("No image", "high")
    low_res_image: _Sev = _sev("Low-resolution image", "medium")
    high_returns_not_as_described: _Sev = _sev("High returns citing 'not as described'", "medium")
    expired_licence: _Sev = _sev("Expired licence number", "high")
    label_mismatch: _Sev = _sev("Label differs from the listing", "high", "A value read off the pack label (protein, licence number) differs from the listing copy.")


class QcSeverityPoints(M):
    low: float = F(1, "Low", min=0, max=100, step=0.5, used_in=["ops_catalog"])
    medium: float = F(2, "Medium", min=0, max=100, step=0.5, used_in=["ops_catalog"])
    high: float = F(3, "High", min=0, max=100, step=0.5, used_in=["ops_catalog"])


class QcWeights(M):
    gmv_at_risk: float = F(0.5, "GMV at risk", "Weight of the listing's recent GMV, scaled to the biggest listing.", min=0, max=10, step=0.05, used_in=["ops_catalog"])
    severity: float = F(0.35, "Severity", "Weight of the issue's severity points, scaled to the highest severity.", min=0, max=10, step=0.05, used_in=["ops_catalog"])
    return_rate: float = F(0.15, "Return-rate signal", "Weight of the 'not as described' return rate, scaled to twice the threshold.", min=0, max=10, step=0.05, used_in=["ops_catalog"])


class QcReturns(M):
    threshold_pct: float = F(0.6, "Return-rate threshold", "Flag a listing when returns citing the reasons below are at least this share of units sold.", unit="%", min=0, max=100, step=0.1, used_in=["ops_catalog"])
    min_returned_units: int = F(5, "Minimum returned units", "...and at least this many units came back (too few is noise).", unit="units", min=0, max=10000, step=1, used_in=["ops_catalog"])
    window_days: int = F(91, "Window", "Sales and returns of the last N days of data.", unit="days", min=7, max=365, step=7, used_in=["ops_catalog"])
    reasons: list[str] = Field(
        default_factory=lambda: ["quality not as expected", "wrong item sent", "not as described"],
        json_schema_extra={"label": "Return reasons that mean 'not as described'", "help": "Matched against the reason column of the ops returns data, case-insensitive.", "used_in": ["ops_catalog"]},
    )


class QcImages(M):
    min_resolution_px: int = F(800, "Minimum resolution", "Shortest side of the main image.", unit="px", min=100, max=10000, step=50, used_in=["ops_catalog"])
    min_count: int = F(1, "Minimum images", unit="images", min=0, max=20, step=1, used_in=["ops_catalog"])


class CatalogQc(M):
    severities: QcSeverities = Field(default_factory=QcSeverities, json_schema_extra={"label": "Issue severities", "help": "", "used_in": ["ops_catalog"]})
    severity_points: QcSeverityPoints = Field(default_factory=QcSeverityPoints, json_schema_extra={"label": "Severity points", "help": "What low, medium and high count as in the priority score.", "used_in": ["ops_catalog"]})
    priority_weights: QcWeights = Field(default_factory=QcWeights, json_schema_extra={"label": "Priority weights", "help": "Score = weighted sum of three 0-100 signals; the weights are normalised, so only their ratio matters.", "used_in": ["ops_catalog"]})
    gmv_window_days: int = F(28, "GMV window", "GMV at risk is the listing's sales of the last N days of data.", unit="days", min=7, max=365, step=7, used_in=["ops_catalog"])
    near_duplicate_threshold: float = F(0.8, "Near-duplicate threshold", "Name similarity (Jaccard overlap of the title words and the pack) at or above which two listings in the same category are duplicates.", min=0.1, max=1, step=0.05, used_in=["ops_catalog"])
    returns: QcReturns = Field(default_factory=QcReturns, json_schema_extra={"label": "Returns signal", "help": "", "used_in": ["ops_catalog"]})
    images: QcImages = Field(default_factory=QcImages, json_schema_extra={"label": "Images", "help": "", "used_in": ["ops_catalog"]})
    title_required: list[str] = Field(
        default_factory=lambda: ["brand", "pack"],
        json_schema_extra={"label": "Title must contain", "help": "brand: the vendor's brand name. pack: the pack size (or size word).", "used_in": ["ops_catalog"], "options": ["brand", "pack"]},
    )
    bulk_approve_limit: int = F(25, "Bulk-approve limit", "Most fixes one bulk approve may apply. A bigger selection is refused, so a person looks at it in batches.", unit="fixes", min=1, max=500, step=1, used_in=["ops_catalog"])
    model_rewrites: bool = F(True, "Model-written fixes", "Let the model (muse-spark) rewrite titles, bullets and fill text attributes. Off: only the deterministic fixes are proposed.", used_in=["ops_catalog"])

    @model_validator(mode="after")
    def _weights(self) -> "CatalogQc":
        w = self.priority_weights
        if w.gmv_at_risk + w.severity + w.return_rate <= 0:
            raise ValueError("priority_weights cannot all be zero")
        return self

    @field_validator("title_required")
    @classmethod
    def _tr(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in ("brand", "pack")]
        if bad:
            raise ValueError(f"unknown title requirement(s) {bad}; use brand and/or pack")
        return v


# ---------- promotions and event planner (Run) ----------

_PROMO = ["ops_promotions"]
_WATCH = ["ops_price_watch"]


class PromoEvent(M):
    id: str = F(label="Id", help="Short key used in URLs and claim keys, for example festive.")
    name: str = F(label="Event")
    start: str = F(label="Starts", help="ISO date, for example 2026-11-06.")
    end: str = F(label="Ends", help="ISO date, inclusive.")
    traffic_lift_pct: float = F(0, "Traffic lift", "Extra demand the event brings to every SKU even without a discount.", unit="%", min=0, max=500, step=1, used_in=_PROMO)
    banner_slots: int = F(3, "Banner slots", "Top banner slots a vendor can be promised.", min=0, max=50, step=1, used_in=_PROMO)

    @model_validator(mode="after")
    def _dates(self) -> "PromoEvent":
        try:
            a, b = date.fromisoformat(self.start), date.fromisoformat(self.end)
        except ValueError as exc:
            raise ValueError(f"event {self.id!r}: start and end must be ISO dates ({exc})") from exc
        if b < a:
            raise ValueError(f"event {self.id!r} ends before it starts")
        if not re.fullmatch(r"[a-z0-9_-]{1,32}", self.id):
            raise ValueError(f"event id {self.id!r} must be lower-case letters, digits, - or _")
        return self


class PromoUplift(M):
    default_elasticity: float = F(-3.0, "Default promo elasticity", "Units sold change by (1 - discount) ^ elasticity. Promo elasticity is steeper than everyday price elasticity.", min=-12, max=0, step=0.1, used_in=_PROMO)
    by_category: dict[str, float] = F({}, label="Promo elasticity by category", help="Category -> elasticity (negative): the uplift curve for that category.", used_in=_PROMO)
    max_multiplier: float = F(4.0, "Largest uplift", "Demand cannot grow without limit: the uplift curve is capped at this multiple of baseline demand.", min=1, max=50, step=0.1, used_in=_PROMO)
    pull_forward_pct: float = F(15, "Pulled forward", "Share of the extra units that would have sold anyway in the weeks after the event (it is not new demand).", unit="%", min=0, max=100, step=1, used_in=_PROMO)

    @field_validator("by_category")
    @classmethod
    def _neg(cls, v: dict[str, float]) -> dict[str, float]:
        bad = [k for k, e in v.items() if e > 0]
        if bad:
            raise ValueError(f"promo elasticity must be negative; fix {bad}")
        return v


class PromoDiscount(M):
    steps_pct: list[float] = F([5, 10, 15, 20, 25, 30], "Discount steps", "Depths tried for each SKU (percent off today's selling price).", used_in=_PROMO)
    max_pct: float = F(25, "Deepest discount", "No SKU is planned deeper than this.", unit="%", min=0, max=90, step=1, used_in=_PROMO)
    floor_below_regular_pp: float = F(5, "Promo margin floor", "The margin after vendor funding may sit this many points under the category's regular floor during the event.", unit="pp", min=0, max=50, step=0.5, used_in=_PROMO)

    @field_validator("steps_pct")
    @classmethod
    def _steps(cls, v: list[float]) -> list[float]:
        if not v or any(x <= 0 or x >= 100 for x in v):
            raise ValueError("discount steps must be numbers between 0 and 100")
        return sorted(set(v))


class PromoStock(M):
    safety_buffer_pct: float = F(10, "Safety buffer", "Event demand is multiplied by (1 + this) when checking stock.", unit="%", min=0, max=200, step=1, used_in=_PROMO)
    baseline_cover_days: float = F(14, "Cover kept by normal replenishment", "When an order placed today can still land before the event, normal replenishment is assumed to keep at least this many days of baseline cover until it starts. A vendor whose lead time is too long is planned on today's stock and open POs alone.", unit="days", min=0, max=120, step=1, used_in=_PROMO)
    min_cover_days: float = F(3, "Thinnest stock at event start", "A SKU with fewer days of baseline cover than this at the event start is left out (fix supply first).", unit="days", min=0, max=60, step=0.5, used_in=_PROMO)
    receiving_buffer_days: int = F(2, "Receiving buffer", "A stock-up PO must land this many days before the event starts.", unit="days", min=0, max=30, step=1, used_in=_PROMO)
    pack_round_units: int = F(10, "Round POs to", "Suggested PO quantities are rounded up to a multiple of this.", unit="units", min=1, max=10000, step=1, used_in=_PROMO)
    max_stock_up_cover_days: float = F(45, "Largest stock-up", "A stock-up never takes the SKU beyond this many days of baseline cover.", unit="days", min=1, max=365, step=1, used_in=_PROMO)


class PromoFunding(M):
    target_share_pct: float = F(30, "Funding ask", "Share of the markdown cost we ask each vendor to fund.", unit="%", min=0, max=100, step=1, used_in=_PROMO)
    target_share_by_category: dict[str, float] = F({}, label="Funding ask by category", help="Category -> share (%) of the markdown we ask for, where the everyday margin is thinner and a promo needs more support.", used_in=_PROMO)
    max_ask_share_pct: float = F(60, "Largest funding ask", "A depth that would need a bigger share than this to hold the margin floor is not planned.", unit="%", min=0, max=100, step=1, used_in=_PROMO)
    banner_slot_cost_inr: float = F(5000, "Cost of a banner slot", "Opportunity cost we charge a vendor's funding offer for each top banner slot it asks us to guarantee.", unit="INR", min=0, max=10000000, step=500, used_in=_PROMO)


class PromoCannibalisation(M):
    similarity_threshold: float = F(0.5, "Near-duplicate similarity", "Name similarity (shared title words) at or above which two SKUs of one vendor are near-duplicates.", min=0.1, max=1, step=0.05, used_in=_PROMO)
    max_price_gap_pct: float = F(25, "Largest price gap", "Near-duplicates must sit within this % of each other's price.", unit="%", min=0, max=500, step=1, used_in=_PROMO)
    cannibalised_share_pct: float = F(30, "Taken from the sibling", "Share of a promoted SKU's extra units that come out of a near-duplicate sibling that is NOT on promo.", unit="%", min=0, max=100, step=1, used_in=_PROMO)


class PromoCandidates(M):
    max_skus_per_event: int = F(24, "SKUs per event", "At most this many SKUs go on promo in one event (best incremental margin first).", min=1, max=500, step=1, used_in=_PROMO)
    min_incremental_margin_inr: float = F(250, "Smallest worthwhile gain", "A SKU whose net extra margin (after pull-forward and cannibalisation) is below this is left out.", unit="INR", min=0, max=10000000, step=100, used_in=_PROMO)


def _default_events() -> list[PromoEvent]:
    return [
        PromoEvent(id="festive", name="Festive Sale", start="2026-11-06", end="2026-11-12", traffic_lift_pct=10, banner_slots=3),
        PromoEvent(id="payday", name="Payday Sale", start="2026-11-28", end="2026-11-30", traffic_lift_pct=6, banner_slots=2),
    ]


class Promotions(M):
    events: list[PromoEvent] = Field(
        default_factory=_default_events,
        json_schema_extra={"label": "Calendar", "help": "Sale events to plan. Add a row for each event; the planner works from today's stock and demand.", "used_in": _PROMO},
    )
    uplift: PromoUplift = Field(default_factory=PromoUplift, json_schema_extra={"label": "Uplift curves", "help": "How much extra demand a discount buys.", "used_in": _PROMO})
    discount: PromoDiscount = Field(default_factory=PromoDiscount, json_schema_extra={"label": "Discount depth", "help": "Depths tried and the margin floor during the event.", "used_in": _PROMO})
    stock: PromoStock = Field(default_factory=PromoStock, json_schema_extra={"label": "Stock", "help": "Stock-out checks and stock-up POs.", "used_in": _PROMO})
    funding: PromoFunding = Field(default_factory=PromoFunding, json_schema_extra={"label": "Vendor funding", "help": "What we ask vendors to fund.", "used_in": _PROMO})
    cannibalisation: PromoCannibalisation = Field(default_factory=PromoCannibalisation, json_schema_extra={"label": "Cannibalisation", "help": "Near-duplicate SKUs.", "used_in": _PROMO})
    candidates: PromoCandidates = Field(default_factory=PromoCandidates, json_schema_extra={"label": "Candidates", "help": "Which SKUs make the plan.", "used_in": _PROMO})

    @model_validator(mode="after")
    def _unique(self) -> "Promotions":
        ids = [e.id for e in self.events]
        if len(set(ids)) != len(ids):
            raise ValueError("event ids must be unique")
        return self


# ---------- competitor price monitor (Run) ----------


class WatchUndercut(M):
    threshold_pct: float = F(3, "Undercut threshold", "A competitor price at least this % below ours is an undercut.", unit="%", min=0, max=100, step=0.5, used_in=_WATCH)
    min_sustained_days: int = F(3, "Sustained after", "Consecutive latest days beyond the threshold before an undercut counts as sustained. Anything shorter is a blip: watched, never matched.", unit="days", min=1, max=30, step=1, used_in=_WATCH)
    trend_window_days: int = F(7, "Trend window", "Days used to fit the price trend.", unit="days", min=3, max=30, step=1, used_in=_WATCH)
    trend_min_slope_pct_per_day: float = F(0.5, "Falling trend from", "A competitor price falling by at least this % a day over the trend window is flagged as a trend (watched, not yet matched).", unit="% per day", min=0, max=50, step=0.1, used_in=_WATCH)


class WatchParity(M):
    tolerance_pct: float = F(3, "Parity tolerance", "A vendor selling on another marketplace this % or more below our price is breaching price parity.", unit="%", min=0, max=100, step=0.5, used_in=_WATCH)
    min_days: int = F(3, "Breach after", "Consecutive latest days below parity before it is flagged.", unit="days", min=1, max=30, step=1, used_in=_WATCH)
    enforce_map: bool = F(True, "Check MAP", "Also flag a vendor price below the minimum advertised price on file.", used_in=_WATCH)


class WatchMatch(M):
    allow: bool = F(True, "Allow price matching", "When off, an undercut is never answered by cutting our price.", used_in=_WATCH)
    max_cut_pct: float = F(12, "Largest cut without a person", "A match that needs a bigger price cut than this is escalated, not recommended.", unit="%", min=0, max=100, step=0.5, used_in=_WATCH)
    price_round_inr: float = F(1, "Round match price up to", "The match price is the competitor's price rounded up to a multiple of this (never below it).", unit="INR", min=0.01, max=1000, step=0.5, used_in=_WATCH)
    margin_buffer_pp: float = F(0, "Margin buffer", "The margin after a match must stay at the category floor plus this.", unit="pp", min=-50, max=50, step=0.5, used_in=_WATCH)
    comparison_share_pct: float = F(70, "Shoppers who compare", "Share of demand that compares prices across marketplaces: only this share reacts to a price gap.", unit="%", min=0, max=100, step=5, used_in=_WATCH)
    like_for_like_elasticity: float = F(-5.0, "Elasticity against an identical pack", "Units change by (our price / competitor price) ^ this for shoppers who compare. Much steeper than everyday price elasticity because the product is the same.", min=-20, max=0, step=0.5, used_in=_WATCH)
    elasticity_by_category: dict[str, float] = F({}, label="Elasticity by category", help="Category -> like-for-like elasticity (negative), overriding the overall figure.", used_in=_WATCH)
    horizon_days: int = F(30, "Impact horizon", "Window of the margin impact of matching or holding.", unit="days", min=7, max=180, step=1, used_in=_WATCH)


class PriceWatch(M):
    window_days: int = F(30, "History analysed", "Days of snapshots read.", unit="days", min=7, max=120, step=1, used_in=_WATCH)
    undercut: WatchUndercut = Field(default_factory=WatchUndercut, json_schema_extra={"label": "Undercuts", "help": "What counts as an undercut, a trend or a blip.", "used_in": _WATCH})
    parity: WatchParity = Field(default_factory=WatchParity, json_schema_extra={"label": "Vendor parity and MAP", "help": "When a vendor selling cheaper elsewhere is flagged.", "used_in": _WATCH})
    match: WatchMatch = Field(default_factory=WatchMatch, json_schema_extra={"label": "Match rules", "help": "When to match, hold or ask the vendor for help.", "used_in": _WATCH})
    ask_price_protection: bool = F(True, "Ask the vendor for price protection", "When matching would break the margin floor, ask the vendor to fund the gap instead.", used_in=_WATCH)


# ---------- inventory health (Run) ----------

_INV = ["ops_inventory_health"]


class InvForecast(M):
    window_days: int = F(28, "Demand window", "Days of recent sales that set the daily demand forecast.", unit="days", min=7, max=120, step=1, used_in=_INV)
    min_daily_units: float = F(0.05, "Smallest rate that counts as selling", "A SKU selling less than this many units a day has no cover figure (it is treated as not moving).", unit="units/day", min=0, max=1000, step=0.01, used_in=_INV)


class InvCoverBand(M):
    min_days: float = F(14, "Lowest healthy cover", "Days of cover on hand under this is below the band.", unit="days", min=0, max=365, step=1)
    target_days: float = F(30, "Target cover", "Days of cover a reorder or a clearance brings the SKU to.", unit="days", min=1, max=365, step=1)
    max_days: float = F(60, "Highest healthy cover", "Days of cover on hand over this is excess stock.", unit="days", min=1, max=730, step=1)

    @model_validator(mode="after")
    def _order(self) -> "InvCoverBand":
        if not self.min_days <= self.target_days <= self.max_days:
            raise ValueError("cover band needs min_days <= target_days <= max_days")
        return self


class InvCover(InvCoverBand):
    by_category: dict[str, InvCoverBand] = F({}, label="Cover band by category", help="Category -> its own band, where one pace does not fit (fast movers, long-shelf-life or bulky goods).", used_in=_INV)


class InvStockOut(M):
    safety_days: float = F(5, "Safety days", "Extra cover on top of lead time and the review cycle before a reorder is due.", unit="days", min=0, max=90, step=0.5, used_in=_INV)
    review_days: float = F(7, "Review cycle", "How often the category is reviewed: an order placed at the next review lands this much later.", unit="days", min=0, max=60, step=1, used_in=_INV)
    overdue_assumed_days: float = F(7, "Overdue PO lands in", "A PO line past its promised date is assumed to land this many days from today, not today.", unit="days", min=0, max=90, step=1, used_in=_INV)
    critical_days: float = F(3, "Critical when stock ends within", "A stock-out forecast to start within this many days is critical.", unit="days", min=0, max=60, step=0.5, used_in=_INV)


class InvAgeing(M):
    aged_days: int = F(90, "Aged after", "A batch received more than this many days ago is aged stock.", unit="days", min=7, max=1000, step=5, used_in=_INV)
    dead_no_sale_days: int = F(45, "Dead after no sale for", "A SKU with stock but no sale for this many days is dead stock.", unit="days", min=7, max=1000, step=5, used_in=_INV)


class InvMoq(M):
    overbuy_ratio: float = F(1.5, "Overbuy ratio", "A PO line or reorder at least this many times the quantity actually needed is an overbuy forced by the vendor's minimum order quantity.", min=1, max=50, step=0.1, used_in=_INV)
    pack_round_units: int = F(10, "Round orders to", "Reorder quantities with no MOQ on file round up to a multiple of this.", unit="units", min=1, max=10000, step=1, used_in=_INV)


class InvRtv(M):
    allow: bool = F(True, "Allow return to vendor", "When off, aged and dead stock is never sent back under sell-or-return terms.", used_in=_INV)
    min_credit_inr: float = F(2000, "Smallest worthwhile return", "A return worth less credit than this is not worth the freight and paperwork: liquidate instead.", unit="INR", min=0, max=10000000, step=500, used_in=_INV)
    prefer_pct_of_liquidation: float = F(100, "Return when credit is at least", "Return to the vendor when its credit is at least this % of what a liquidation promo would recover.", unit="%", min=0, max=500, step=5, used_in=_INV)
    urgent_window_days: int = F(21, "Window closing soon", "A sell-or-return window with this many days or fewer left is flagged urgent.", unit="days", min=0, max=365, step=1, used_in=_INV)


class InvLiquidate(M):
    discount_aged_pct: float = F(25, "Aged stock discount", "Promo discount on stock past the aged threshold.", unit="%", min=0, max=90, step=1, used_in=_INV)
    discount_dead_pct: float = F(40, "Dead stock discount", "Promo discount on stock with no sale for the dead-stock period.", unit="%", min=0, max=90, step=1, used_in=_INV)
    discount_excess_pct: float = F(15, "Excess stock discount", "Promo discount on stock above the healthy cover band.", unit="%", min=0, max=90, step=1, used_in=_INV)
    floor_pct_of_cost: float = F(60, "Never below", "A liquidation price is never set under this % of cost, whatever the discount.", unit="%", min=0, max=200, step=5, used_in=_INV)
    uplift_multiplier: float = F(2.0, "Sales lift on promo", "Daily sales on a liquidation promo are this multiple of the normal rate (sets the days to clear).", min=1, max=20, step=0.1, used_in=_INV)
    max_clear_days: float = F(90, "Longest sensible promo", "A promo that would take longer than this to clear the stock is not counted as a recovery: a return to the vendor is preferred when its window is open.", unit="days", min=1, max=730, step=5, used_in=_INV)
    price_round_inr: float = F(1, "Round price to", "Liquidation prices are rounded to a multiple of this.", unit="INR", min=0.01, max=1000, step=0.5, used_in=_INV)


class InventoryHealth(M):
    forecast: InvForecast = Field(default_factory=InvForecast, json_schema_extra={"label": "Demand forecast", "help": "How daily demand is read from recent sales.", "used_in": _INV})
    cover: InvCover = Field(default_factory=InvCover, json_schema_extra={"label": "Days of cover", "help": "The healthy band and the target a reorder or clearance aims for.", "used_in": _INV})
    stock_out: InvStockOut = Field(default_factory=InvStockOut, json_schema_extra={"label": "Stock-out risk", "help": "Lead time, review cycle and how overdue POs are treated.", "used_in": _INV})
    ageing: InvAgeing = Field(default_factory=InvAgeing, json_schema_extra={"label": "Ageing and dead stock", "help": "When stock counts as aged or dead.", "used_in": _INV})
    moq: InvMoq = Field(default_factory=InvMoq, json_schema_extra={"label": "Minimum order quantity", "help": "Overbuy forced by MOQ and how orders round.", "used_in": _INV})
    rtv: InvRtv = Field(default_factory=InvRtv, json_schema_extra={"label": "Return to vendor", "help": "When sell-or-return terms are used.", "used_in": _INV})
    liquidate: InvLiquidate = Field(default_factory=InvLiquidate, json_schema_extra={"label": "Liquidation promo", "help": "Discount depth, price floor and lift.", "used_in": _INV})


ROLES = ("head", "manager", "analyst")
Role = Literal["head", "manager", "analyst"]
_ID = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")
_GOV = ["governance"]


class Member(M):
    name: str = F(label="Name", help="Synthetic demo names only.")
    role: Role = F("analyst", "Role", "head: change anything and approve. manager: own sections, within limits. analyst: propose only.", options=list(ROLES))


class RoleRule(M):
    label: str = F(label="Role title")
    can_apply: bool = F(False, "Can apply changes", "False means the role can write a rule and see the preview but not apply it.", used_in=_GOV)
    can_approve: bool = F(False, "Can approve", "May approve or reject a change that is waiting for approval (never one of their own).", used_in=_GOV)
    sections: list[str] = F(label="May change", help="Playbook sections (or dotted paths) this role may change; * means all. Changing governance is always head-only.", used_in=_GOV)


class Limit(M):
    role: Role = F("manager", "Applies to", options=list(ROLES))
    path: str = F(label="Section or path", help="The limit covers every numeric setting at or under this path.")
    max_abs_change: float = F(label="Largest change", help="A single change larger than this needs approval.", min=0, max=1000000, step=0.5)
    unit: str = F("", "Unit", help="Only settings in this unit count (pp and % are treated alike); empty means any unit.")


class Governance(M):
    members: dict[str, Member] = F(label="Team", help="Who can act on the playbook. The key is the member id. This is a demo identity picker, not authentication.", used_in=_GOV)
    roles: dict[str, RoleRule] = F(label="Roles", help="What each role may do.", used_in=_GOV)
    limits: dict[str, Limit] = F({}, label="Limits", help="Numeric limits per change; a larger change becomes a request for approval.", used_in=_GOV)

    @model_validator(mode="after")
    def _check(self) -> "Governance":
        if set(self.roles) != set(ROLES):
            raise ValueError(f"roles must be exactly {list(ROLES)}")
        bad = [m for m in self.members if not _ID.match(m)]
        if bad:
            raise ValueError(f"member id(s) {bad} must be lowercase letters, digits, - or _ (2 to 31 characters)")
        known = set(Policy.model_fields)
        for role, rule in self.roles.items():
            for sec in rule.sections:
                if sec != "*" and sec.split(".")[0] not in known:
                    raise ValueError(f"roles.{role}.sections: {sec!r} is not a playbook section")
        for key, lim in self.limits.items():
            if lim.path.split(".")[0] not in known or lim.path.split(".")[0] == "governance":
                raise ValueError(f"limits.{key}.path: {lim.path!r} is not a playbook section a limit can cover")
        if not any(self.roles[m.role].can_apply and self.roles[m.role].can_approve for m in self.members.values()):
            raise ValueError("at least one team member needs a role that can apply and approve changes, or nobody could ever approve")
        return self


def _default_governance() -> Governance:
    """The seed team (synthetic names). config/policy.yaml carries the same data; this keeps starter playbooks without a governance section valid."""
    return Governance(
        members={"meera": Member(name="Meera", role="head"), "arjun": Member(name="Arjun", role="manager"), "priya": Member(name="Priya", role="analyst")},
        roles={
            "head": RoleRule(label="Head of category", can_apply=True, can_approve=True, sections=["*"]),
            "manager": RoleRule(
                label="Category manager", can_apply=True, can_approve=False,
                sections=["margins", "negotiation", "promotions", "price_watch", "inventory_health", "price_requests"],
            ),
            "analyst": RoleRule(label="Category analyst", can_apply=False, can_approve=False, sections=[]),
        },
        limits={"manager_margins": Limit(role="manager", path="margins", max_abs_change=2, unit="pp")},
    )


class Policy(M):
    version: int = F(1, "Version")
    business: Business = F(label="Business", help="Wording injected into every model prompt.", used_in=STAGES_ALL)
    onboarding: Onboarding = F(label="Onboarding", used_in=["intake", "negotiate"])
    screening: Screening = F(label="Screening", used_in=["intake", "catalog"])
    taxonomy: Taxonomy = F(label="Taxonomy", help="How SKUs are classified.", used_in=["research", "catalog"])
    research: Research = F(label="Research", used_in=["research", "shortlist"])
    margins: Margins = F(label="Margins", used_in=["research", "shortlist", "negotiate"])
    negotiation: Negotiation = F(label="Negotiation", used_in=["negotiate"])
    catalog: Catalog = F(label="Catalog", used_in=["catalog"])
    launch: Launch = F(label="Launch", used_in=["marketing", "jbp"])
    po: Po = F(label="Purchase order", used_in=["po"])
    levers: Levers = F(label="Levers", used_in=["research"])
    verifier: Verifier = F(label="Verifier", used_in=["research", "negotiate", "catalog", "po"])
    operations: Operations = Field(
        default_factory=Operations,
        json_schema_extra={"label": "Operations", "help": "Run: weekly vendor review and PO follow-up for existing vendors.", "used_in": ["ops_review", "ops_chaser"]},
    )
    catalog_qc: CatalogQc = Field(
        default_factory=CatalogQc,
        json_schema_extra={"label": "Catalog QC (Run)", "help": "Fix queue for the live listings of existing vendors.", "used_in": ["ops_catalog"]},
    )
    promotions: Promotions = Field(
        default_factory=Promotions,
        json_schema_extra={"label": "Promotions (Run)", "help": "Sale events, uplift curves, discount depth, stock checks and vendor funding asks.", "used_in": ["ops_promotions"]},
    )
    price_watch: PriceWatch = Field(
        default_factory=PriceWatch,
        json_schema_extra={"label": "Price watch (Run)", "help": "Competitor undercuts, blips, vendor parity breaches and match rules.", "used_in": ["ops_price_watch"]},
    )
    inventory_health: InventoryHealth = Field(
        default_factory=InventoryHealth,
        json_schema_extra={"label": "Inventory health (Run)", "help": "Cover band, stock-out risk, ageing, MOQ overbuy, return to vendor and liquidation.", "used_in": ["ops_inventory_health"]},
    )
    impact: Impact = F(label="Impact", help="How the impact meter turns recorded review time into saved hours.", used_in=["impact"])
    governance: Governance = Field(
        default_factory=_default_governance,
        json_schema_extra={"label": "Team and permissions", "help": "Who may change which rules, and how large a change may be before it needs approval. Demo identities, not authentication.", "used_in": _GOV},
    )

    price_requests: PriceRequests = Field(
        default_factory=lambda: PriceRequests(
            elasticity=Elasticity(),
            pass_through=PassThrough(),
            justification=Justification(),
            approval=Approval(matrix=_default_matrix(), decision_floor={"pass_through": "category_manager", "delist": "head_of_category"}),
        ),
        json_schema_extra={"label": "Price requests", "help": "How an existing vendor's price-increase request is evaluated.", "used_in": ["negotiate"]},
    )

    documents: Documents = Field(
        default_factory=Documents,
        json_schema_extra={"label": "Documents", "help": "Scanned certificates, labels and price lists read by the vision models.", "used_in": ["intake", "catalog"]},
    )

    @model_validator(mode="after")
    def _cross(self) -> "Policy":
        cats = set(self.margins.categories)
        allowed_fail = set(BUILTIN_FAIL) | {r.type for r in self.screening.claim_rules}
        bad = [f for f in self.screening.fail_on if f not in allowed_fail]
        if bad:
            raise ValueError(f"fail_on has unknown entries {bad}; use {sorted(allowed_fail)}")
        tax = self.taxonomy
        if tax.fallback_category not in cats:
            raise ValueError(f"taxonomy.fallback_category {tax.fallback_category!r} is not in margins.categories")
        names = {s.name for s in tax.segments}
        for cat in tax.categories:
            if cat.approximate_as is not None:
                if cat.approximate_as not in cats:
                    raise ValueError(f"taxonomy category {cat.name!r}: approximate_as {cat.approximate_as!r} is not in margins.categories")
                continue
            for concrete in expand_name(cat.name, tax.segments):
                if concrete not in cats:
                    raise ValueError(f"taxonomy category {concrete!r} (from {cat.name!r}) is not in margins.categories")
            unknown = set(re.findall(r"\{(\w+)\}", cat.name)) - names
            if unknown:
                raise ValueError(f"taxonomy category {cat.name!r} uses unknown segment(s) {sorted(unknown)}")
        return self


# ---------- name expansion (segments) ----------


def expand_name(name: str, segments: list[Segment]) -> list[str]:
    """All concrete names a category template can take, e.g. '{species} dry food' -> dog dry food, cat dry food."""
    out = [name]
    for seg in segments:
        token = "{" + seg.name + "}"
        if any(token in n for n in out):
            out = [n.replace(token, v) for n in out for v in seg.values]
    return out


# ---------- loading, merging, persistence ----------


def config_dir() -> Path:
    return Path(settings.config_dir)


def defaults_path() -> Path:
    return config_dir() / "policy.yaml"


def local_path() -> Path:
    return Path(settings.policy_local_path) if settings.policy_local_path else config_dir() / "policy.local.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise PolicyInvalid(f"{path.name} must be a YAML mapping", cause="The top level of the file is not a mapping", fix="Fix the file or reset the playbook")
    return data


_TABLE_PATHS: set[str] | None = None
_listeners: list[Callable[[], None]] = []


def on_change(fn: Callable[[], None]) -> None:
    """Register a cache invalidator (metrics registers build_base's)."""
    _listeners.append(fn)


def table_paths() -> set[str]:
    global _TABLE_PATHS
    if _TABLE_PATHS is None:
        _TABLE_PATHS = {p for p, h in schema_hints().items() if h["kind"] in {"table", "string_list"}}
    return _TABLE_PATHS


def merge(base: Any, over: Any, path: str = "") -> Any:
    """Deep-merge dicts; tables and lists replace wholesale."""
    if isinstance(base, dict) and isinstance(over, dict) and path not in table_paths():
        out = dict(base)
        for k, v in over.items():
            out[k] = merge(base[k], v, f"{path}.{k}" if path else k) if k in base else v
        return out
    return over


def _validate(data: dict[str, Any]) -> Policy:
    try:
        return Policy.model_validate(data)
    except ValidationError as exc:
        errors = [{"path": ".".join(str(p) for p in e["loc"]), "message": e["msg"].removeprefix("Value error, ")} for e in exc.errors()]
        first = errors[0]
        raise PolicyInvalid(
            f"{first['path'] or 'playbook'}: {first['message']}" + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""),
            cause="The playbook failed validation, so nothing was saved",
            fix="Correct the value shown and save again, or reset the field to its default",
            errors=errors,
        ) from exc


@dataclass(frozen=True)
class Loaded:
    policy: Policy
    defaults: Policy
    overrides: dict[str, Any]
    hash: str


_cache: tuple[tuple, Loaded] | None = None


def _stamp(p: Path) -> int:
    try:
        return p.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def _ignore_local() -> bool:
    return settings.effective_mode == "replay"


def _digest(policy: Policy) -> str:
    """The playbook hash the engine's caches, metrics hashes and recorded runs key on. Governance (who may change a rule) does not
    change any number, so it is left out: editing the team never invalidates an approval or a golden run."""
    return hashlib.sha256(json.dumps(policy.model_dump(mode="json", exclude={"governance"}), sort_keys=True).encode()).hexdigest()[:16]


def full_digest(policy: Policy) -> str:
    """Every field, governance included: the change log's before/after hash."""
    return hashlib.sha256(json.dumps(policy.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:16]


def load() -> Loaded:
    global _cache
    ignore = _ignore_local()
    key = (str(defaults_path()), str(local_path()), ignore, _stamp(defaults_path()), 0 if ignore else _stamp(local_path()))
    if _cache is not None and _cache[0] == key:
        return _cache[1]
    defaults_raw = _read_yaml(defaults_path())
    if not defaults_raw:
        raise PolicyInvalid("config/policy.yaml is missing or empty", cause=f"Looked for {defaults_path()}", fix="Restore config/policy.yaml from git", code="policy_missing")
    defaults = _validate(defaults_raw)
    overrides = {} if ignore else _read_yaml(local_path())
    effective = _validate(merge(defaults_raw, overrides)) if overrides else defaults
    loaded = Loaded(effective, defaults, overrides, _digest(effective))
    _cache = (key, loaded)
    return loaded


STARTERS = ("pet", "beauty", "electronics")
_starter_cache: dict[str, tuple[int, Loaded]] = {}


def starter_path(name: str) -> Path:
    return config_dir() / "examples" / f"{name}.yaml"


def starter(name: str) -> Loaded:
    """A starter playbook for a sandbox vendor. "pet" is the effective playbook (config/policy.yaml plus the local
    overrides); beauty and electronics are the complete example playbooks in config/examples, used as shipped."""
    if name == "pet" or name not in STARTERS:
        return load()
    path = starter_path(name)
    stamp = _stamp(path)
    hit = _starter_cache.get(f"{path}")
    if hit is not None and hit[0] == stamp:
        return hit[1]
    raw = _read_yaml(path)
    if not raw:
        raise PolicyInvalid(f"starter playbook {name!r} is missing", cause=f"Looked for {path}", fix="Restore config/examples from git", code="policy_missing")
    policy = _validate(raw)
    loaded = Loaded(policy, policy, {}, _digest(policy))
    _starter_cache[f"{path}"] = (stamp, loaded)
    return loaded


def _active() -> Loaded:
    """The playbook in force: a sandbox vendor's starter while its scope is active, else the global one."""
    sc = scope.current()
    return starter(sc.starter) if sc is not None else load()


def get() -> Policy:
    return _active().policy


def policy_hash() -> str:
    return _active().hash


def _invalidate() -> None:
    global _cache
    _cache = None
    for fn in _listeners:
        fn()


def dict_table_paths() -> set[str]:
    return {p for p, h in schema_hints().items() if h["kind"] == "table" and h.get("shape") == "dict"}


def _apply_partial(cur: Any, part: Any, path: str = "") -> Any:
    """Nested partial: dicts merge (null deletes a key of a dict-table), lists and scalars replace."""
    if not isinstance(part, dict) or not isinstance(cur, dict):
        return part
    out = dict(cur)
    in_table = path in dict_table_paths()
    for k, v in part.items():
        sub = f"{path}.{k}" if path else k
        if v is None and in_table:
            out.pop(k, None)
        elif k in cur:
            out[k] = _apply_partial(cur[k], v, sub)
        else:
            out[k] = _drop_nulls(v) if isinstance(v, dict) else v
    return out


def _drop_nulls(v: dict[str, Any]) -> dict[str, Any]:
    return {k: (_drop_nulls(x) if isinstance(x, dict) else x) for k, x in v.items() if x is not None}


def _diff(eff: Any, base: Any, path: str = "") -> Any:
    """Overrides = the parts of the effective playbook that differ from the defaults (tables and lists whole)."""
    if isinstance(eff, dict) and isinstance(base, dict) and path not in table_paths():
        out = {}
        for k, v in eff.items():
            d = _diff(v, base[k], f"{path}.{k}" if path else k) if k in base else v
            if d is not _SAME:
                out[k] = d
        return out if out else _SAME
    return _SAME if _normal(eff) == _normal(base) else eff


_SAME = object()


def _normal(v: Any) -> Any:
    return json.loads(json.dumps(v, sort_keys=True))


def _write(overrides: dict[str, Any]) -> None:
    path = local_path()
    if not overrides:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    header = "# CategoryOS playbook overrides written by the UI. Delete this file to return to config/policy.yaml.\n"
    tmp.write_text(header + yaml.safe_dump(overrides, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    os.replace(tmp, path)


def effective_with(overrides: dict[str, Any]) -> Policy:
    """The playbook that defaults plus these overrides give (validated). Used for a visitor's sandbox playbook."""
    defaults_raw = _read_yaml(defaults_path())
    return _validate(merge(defaults_raw, overrides) if overrides else defaults_raw)


def _non_finite(v: Any, path: str = "") -> str | None:
    """Dotted path of the first NaN or infinity anywhere in a partial, else None."""
    if isinstance(v, float) and not math.isfinite(v):
        return path or "playbook"
    items = v.items() if isinstance(v, dict) else enumerate(v) if isinstance(v, list) else ()
    for k, x in items:
        found = _non_finite(x, f"{path}.{k}" if path else str(k))
        if found:
            return found
    return None


def plan_partial(partial: dict[str, Any], base: dict[str, Any]) -> tuple[Policy, dict[str, Any]]:
    """Dry run of a save: apply a nested partial to the playbook that ``base`` overrides give. Returns (the validated playbook it
    would produce, the overrides to store: only the diff vs defaults). Writes nothing."""
    if not isinstance(partial, dict):
        raise PolicyInvalid("The request body must be an object", cause="Expected a partial playbook", fix='Send e.g. {"research": {"demand_min": 0.5}}')
    bad = _non_finite(partial)
    if bad:
        raise PolicyInvalid(f"{bad}: not a finite number", cause="NaN and infinity are not valid playbook values, so nothing was saved", fix="Enter an ordinary number", errors=[{"path": bad, "message": "not a finite number"}])
    defaults_raw = _read_yaml(defaults_path())
    eff = _apply_partial(merge(defaults_raw, base), partial)
    policy = _validate(eff)
    over = _diff(eff, defaults_raw)
    return policy, ({} if over is _SAME else over)


def save_overrides(partial: dict[str, Any]) -> Loaded:
    """Apply a nested partial to the effective playbook, validate the result BEFORE writing, store only the diff vs defaults."""
    _, over = plan_partial(partial, load().overrides)
    _write(over)
    _invalidate()
    return load()


def plan_reset(section: str | None, base: dict[str, Any]) -> tuple[Policy, dict[str, Any]]:
    """Dry run of a reset of everything, or one section / dotted path: (the playbook it would produce, the overrides to store)."""
    over = json.loads(json.dumps(base))
    if section is None:
        over = {}
    else:
        parts = section.split(".")
        node = over
        chain = []
        for p in parts[:-1]:
            if not isinstance(node, dict) or p not in node:
                node = None
                break
            chain.append((node, p))
            node = node[p]
        if isinstance(node, dict):
            node.pop(parts[-1], None)
            for parent, key in reversed(chain):
                if not parent[key]:
                    del parent[key]
    defaults_raw = _read_yaml(defaults_path())
    return _validate(merge(defaults_raw, over) if over else defaults_raw), over


def reset(section: str | None = None) -> Loaded:
    """Reset everything, or one section / dotted path, to the committed defaults."""
    _, over = plan_reset(section, load().overrides)
    _write(over)
    _invalidate()
    return load()


def commit_overrides(over: dict[str, Any]) -> Loaded:
    """Write already-validated overrides (from plan_partial / plan_reset) and drop the caches."""
    _write(over)
    _invalidate()
    return load()


def overridden_paths(overrides: dict[str, Any] | None = None) -> list[str]:
    overrides = load().overrides if overrides is None else overrides
    out: list[str] = []

    def walk(o: Any, path: str) -> None:
        if isinstance(o, dict) and path not in table_paths():
            for k, v in o.items():
                walk(v, f"{path}.{k}" if path else k)
        else:
            out.append(path)

    walk(overrides, "")
    return sorted(p for p in out if p)


# ---------- accessors used by the engine ----------


def in_scope(scope: Scope, category: str | Iterable[str] | None) -> bool:
    """True when ``scope`` is 'all' or covers the category (or any of several categories)."""
    if scope == "all":
        return True
    cats = [category] if isinstance(category, str) else list(category or [])
    return any(c in scope for c in cats)


def vendor_type_offset(vendor_type: str | None) -> float:
    vt = get().onboarding.vendor_types.get(vendor_type or "")
    return float(vt.target_offset_pp) if vt else 0.0


def brand_offset(brand: str | None) -> float:
    if not brand:
        return 0.0
    for name, row in get().margins.brands.items():
        if name.lower() == brand.lower():
            return float(row.target_offset_pp)
    return 0.0


def target_breakdown(category: str, vendor_type: str | None, brand: str | None, lever_pp: float = 0.0) -> dict[str, float]:
    cat = get().margins.categories[category]
    return {"category_pct": float(cat.target_pct), "vendor_type_pp": vendor_type_offset(vendor_type), "brand_pp": brand_offset(brand), "lever_pp": float(lever_pp)}


def min_pct(category: str, vendor_type: str | None, brand: str | None) -> float:
    cat = get().margins.categories[category]
    return float(cat.min_pct) + vendor_type_offset(vendor_type) + brand_offset(brand)


def tol(unit: str) -> float:
    return float(getattr(get().verifier.tolerances, unit, 0.0))


def gst_rate(category: str | None) -> float:
    po = get().po
    return float(po.gst_rate_by_category.get(category or "", po.gst_rate_default))


def gst_total(items: Iterable[tuple[str | None, float]]) -> float:
    """Tax on PO lines: amounts are grouped by their category's rate, each group taxed once and rounded."""
    groups: dict[float, float] = {}
    for category, amount in items:
        rate = gst_rate(category)
        groups[rate] = groups.get(rate, 0.0) + amount
    return round(sum(round(total * rate, 2) for rate, total in groups.items()), 2)


def po_number(vendor_id: str, day: str) -> str:
    return get().po.number_format.format(vendor=vendor_id, date=day.replace("-", ""))


def category_names() -> tuple[str, ...]:
    return tuple(get().margins.categories)


def required_attributes(category: str) -> list[str]:
    ra = get().catalog.required_attributes
    return ra.get(category, ra["default"])


def claim_regex(rule: ClaimRule) -> re.Pattern[str]:
    return _claim_regex(tuple(rule.patterns))


@lru_cache(maxsize=64)
def _claim_regex(patterns: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(patterns) + r")\b", re.IGNORECASE)


# ---------- schema hints ----------


def _unwrap(ann: Any) -> Any:
    origin = get_origin(ann)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _leaf(ann: Any, extra: dict[str, Any]) -> dict[str, Any]:
    ann = _unwrap(ann)
    origin = get_origin(ann)
    h: dict[str, Any] = {}
    if ann is bool:
        h["kind"] = "bool"
    elif ann in (int, float):
        h["kind"] = "number"
        h["integer"] = ann is int
    elif ann is str:
        h["kind"] = "text"
    elif origin is Literal:
        h["kind"] = "enum"
        h["options"] = list(get_args(ann))
    elif origin in (Union, types.UnionType):
        args = get_args(ann)
        if any(get_origin(a) is list for a in args):  # Scope: "all" | list[str]
            h["kind"] = "string_list"
            h["allows_all"] = True
        else:
            h["kind"] = "text"
    elif origin is list:
        (item,) = get_args(ann)
        if isinstance(item, type) and issubclass(item, BaseModel):
            h["kind"] = "table"
            h["shape"] = "list"
            h["columns"] = _columns(item)
        else:
            h["kind"] = "string_list"
    elif origin is dict:
        _, val = get_args(ann)
        h["kind"] = "table"
        h["shape"] = "dict"
        if isinstance(val, type) and issubclass(val, BaseModel):
            h["columns"] = [{"key": "name", "label": "Name", "kind": "text"}, *_columns(val)]
        else:
            h["columns"] = [{"key": "name", "label": "Name", "kind": "text"}, {"key": "value", **_leaf(val, {})}]
    elif isinstance(ann, type) and issubclass(ann, BaseModel):
        h["kind"] = "section"
    else:
        h["kind"] = "text"
    h.update({k: v for k, v in extra.items() if v is not None})
    return h


def _columns(model: type[BaseModel]) -> list[dict[str, Any]]:
    cols = []
    for name, fi in model.model_fields.items():
        extra = dict(fi.json_schema_extra or {})  # type: ignore[arg-type]
        extra.setdefault("label", name.replace("_", " ").capitalize())
        cols.append({"key": name, **_leaf(fi.annotation, extra)})
    return cols


_HINTS: dict[str, dict[str, Any]] | None = None


def schema_hints() -> dict[str, dict[str, Any]]:
    """Dotted path -> {label, help, unit, min, max, step, kind, options?, used_in, ...}, generated from Field metadata."""
    global _HINTS
    if _HINTS is not None:
        return _HINTS
    hints: dict[str, dict[str, Any]] = {}

    def walk(model: type[BaseModel], prefix: str, inherited: list[str]) -> None:
        for name, fi in model.model_fields.items():
            path = f"{prefix}{name}"
            extra = dict(fi.json_schema_extra or {})  # type: ignore[arg-type]
            extra.setdefault("label", name.replace("_", " ").capitalize())
            extra.setdefault("help", "")
            extra["used_in"] = extra.get("used_in") or inherited
            h = _leaf(fi.annotation, extra)
            hints[path] = h
            sub = _unwrap(fi.annotation)
            if isinstance(sub, type) and issubclass(sub, BaseModel):
                walk(sub, f"{path}.", extra["used_in"])

    walk(Policy, "", STAGES_ALL)
    # options for string lists whose values come from other parts of the playbook
    hints["screening.fail_on"]["options"] = [*BUILTIN_FAIL, "medical_claim", "unverifiable_superlative", "unsubstantiated_claim"]
    _HINTS = hints
    return hints


def snapshot(overrides: dict[str, Any] | None = None, *, editable: bool | None = None) -> dict[str, Any]:
    """Everything GET /api/policy returns. With ``overrides`` it is that (visitor sandbox) playbook instead of the global one."""
    if overrides is None:
        cur = load()
        policy, defaults, over, hash_ = cur.policy, cur.defaults, cur.overrides, cur.hash
    else:
        defaults = load().defaults
        policy, over = effective_with(overrides), overrides
        hash_ = _digest(policy)
    return {
        "policy": policy.model_dump(mode="json"),
        "defaults": defaults.model_dump(mode="json"),
        "overridden_paths": overridden_paths(over),
        "hash": hash_,
        "editable": settings.effective_mode != "replay" if editable is None else editable,
        "schema_hints": schema_hints(),
    }
