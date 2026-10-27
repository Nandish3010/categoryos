"""The playbook: every tunable business rule, loaded from config/policy.yaml (defaults) plus
config/policy.local.yaml (overrides written by the UI). Nothing vertical-specific lives in Python.

* ``get()`` returns the effective, validated ``Policy`` (cached on file mtimes; replay mode ignores local overrides so
  recorded runs stay consistent).
* ``save_overrides`` validates the merged result BEFORE writing; ``reset`` deletes a section, a path or the whole file.
* ``schema_hints`` is generated from the model's Field metadata so the UI renders forms without hardcoding fields.
"""

import hashlib
import json
import os
import re
import string
import types
from collections.abc import Callable, Iterable
from dataclasses import dataclass
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
    model_config = ConfigDict(extra="forbid")


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


class Negotiation(M):
    margin_ask: Literal["target", "min"] = F("target", "Margin we ask for", "target or the floor.", used_in=["negotiate"], options=["target", "min"])
    payment_terms_days: Literal["category"] | int = F("category", "Payment terms", "'category' or a fixed number of days.", used_in=["negotiate"])
    payment_longer_is_better: bool = F(True, "Longer payment terms favour us", used_in=["negotiate"])
    moq_max_factor: float = F(2.0, "MOQ ceiling", "Largest acceptable first-order MOQ as a multiple of monthly units.", unit="x", min=0, max=100, step=0.5, used_in=["negotiate"])
    marketing_min_pct_of_order: float = F(0.10, "Marketing support", "Share of first-order retail value.", unit="ratio", min=0, max=1, step=0.01, used_in=["negotiate"])
    launch_discount_min_pct: float = F(5, "Launch discount", unit="%", min=0, max=100, step=0.5, used_in=["negotiate"])
    defect_return_min_days: int = F(7, "Defect return window", unit="days", min=0, max=365, step=1, used_in=["negotiate"])


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


class Verifier(M):
    tolerances: Tolerances = F(label="Tolerances", help="How closely a claim must match the recomputed value.", used_in=["research", "negotiate", "catalog", "po"])


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


def get() -> Policy:
    return load().policy


def policy_hash() -> str:
    return load().hash


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


def save_overrides(partial: dict[str, Any]) -> Loaded:
    """Apply a nested partial to the effective playbook, validate the result BEFORE writing, store only the diff vs defaults."""
    if not isinstance(partial, dict):
        raise PolicyInvalid("The request body must be an object", cause="Expected a partial playbook", fix='Send e.g. {"research": {"demand_min": 0.5}}')
    defaults_raw = _read_yaml(defaults_path())
    eff = _apply_partial(merge(defaults_raw, load().overrides), partial)
    _validate(eff)
    over = _diff(eff, defaults_raw)
    _write({} if over is _SAME else over)
    _invalidate()
    return load()


def reset(section: str | None = None) -> Loaded:
    """Reset everything, or one section / dotted path, to the committed defaults."""
    cur = load()
    if section is None:
        _write({})
    else:
        over = json.loads(json.dumps(cur.overrides))
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
        _validate(merge(_read_yaml(defaults_path()), over))
        _write(over)
    _invalidate()
    return load()


def overridden_paths() -> list[str]:
    cur = load()
    out: list[str] = []

    def walk(o: Any, path: str) -> None:
        if isinstance(o, dict) and path not in table_paths():
            for k, v in o.items():
                walk(v, f"{path}.{k}" if path else k)
        else:
            out.append(path)

    walk(cur.overrides, "")
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


def snapshot() -> dict[str, Any]:
    """Everything GET /api/policy returns."""
    cur = load()
    return {
        "policy": cur.policy.model_dump(mode="json"),
        "defaults": cur.defaults.model_dump(mode="json"),
        "overridden_paths": overridden_paths(),
        "hash": cur.hash,
        "editable": settings.effective_mode != "replay",
        "schema_hints": schema_hints(),
    }
