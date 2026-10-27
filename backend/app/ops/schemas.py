"""Structured model outputs and API bodies for the Run modules."""

from typing import Literal

from pydantic import BaseModel, Field


class Figure(BaseModel):
    """One number the agent wrote in prose. ``value`` is in the metric's unit (pct metrics as fractions), ``shown`` is the
    exact text of the number as it appears in the prose, and the verifier recomputes ``metric`` at ``key``."""

    metric: str
    key: str
    value: float
    shown: str
    text: str


class AnomalyNote(BaseModel):
    anomaly_id: str
    explanation: str
    figures: list[Figure] = Field(default_factory=list)


class ActionNote(BaseModel):
    action_id: str
    rationale: str
    figures: list[Figure] = Field(default_factory=list)


class ReviewFinal(BaseModel):
    headline: str
    narrative: str
    figures: list[Figure] = Field(default_factory=list)
    anomaly_notes: list[AnomalyNote] = Field(default_factory=list)
    priority: list[ActionNote] = Field(default_factory=list)


class EmailDraft(BaseModel):
    vendor_id: str
    subject: str
    body: str
    figures: list[Figure] = Field(default_factory=list)


class EmailsFinal(BaseModel):
    emails: list[EmailDraft] = Field(default_factory=list)


class Commitment(BaseModel):
    kind: Literal["eta_date", "qty"]
    quote: str
    eta_date: str | None = None  # ISO date, for kind eta_date
    qty: float | None = None  # for kind qty
    note: str | None = None


class ReplyReading(BaseModel):
    reply_id: str
    stance: Literal["committed", "partial", "vague", "excuse_only", "shipped", "declined"]
    summary: str
    excuse: str | None = None
    root_cause: Literal["transport", "raw_material", "production", "packing", "demand", "other", "none"] = "none"
    commitments: list[Commitment] = Field(default_factory=list)


class PoRepliesFinal(BaseModel):
    readings: list[ReplyReading] = Field(default_factory=list)


class PoDraft(BaseModel):
    po_id: str
    channel: Literal["email", "whatsapp"]
    subject: str
    body: str
    figures: list[Figure] = Field(default_factory=list)


class PoDraftsFinal(BaseModel):
    drafts: list[PoDraft] = Field(default_factory=list)


class DecideBody(BaseModel):
    body: str | None = None  # an edited message; checked again for unclaimed numbers
    note: str | None = None
