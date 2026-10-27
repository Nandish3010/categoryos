"""Structured model output and API bodies for the catalog fix queue."""

from typing import Literal

from pydantic import BaseModel, Field


class AttrFill(BaseModel):
    """A text attribute the model fills from the listing's own words. ``quote`` must appear verbatim in the listing."""

    name: str
    value: str
    quote: str


class StatedFact(BaseModel):
    """A pack quantity (grams, millilitres or pieces) or an MRP (rupees) the rewritten text states. Checked against the latest
    price list; a wrong one goes back to the model with the price-list value (self-correction)."""

    metric: Literal["pack_qty", "mrp"]
    value: float
    quote: str


class ListingRewrite(BaseModel):
    listing_id: str
    title: str | None = None
    bullets: list[str] | None = None
    description: str | None = None
    attributes: list[AttrFill] = Field(default_factory=list)
    facts: list[StatedFact] = Field(default_factory=list)
    note: str | None = None


class RewriteFinal(BaseModel):
    items: list[ListingRewrite] = Field(default_factory=list)


class SelectBody(BaseModel):
    fix_ids: list[str] = Field(default_factory=list)
    note: str | None = None
