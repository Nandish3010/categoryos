"""Structured model outputs and API bodies of the inventory health review."""

from pydantic import BaseModel, Field

from app.ops.schemas import ActionNote, Figure


class BriefFinal(BaseModel):
    """The weekly review the model writes from the engine's numbers: a headline, a short narrative and one plain-English note per action."""

    headline: str
    narrative: str
    figures: list[Figure] = Field(default_factory=list)
    notes: list[ActionNote] = Field(default_factory=list)


class DecideBody(BaseModel):
    note: str | None = None
