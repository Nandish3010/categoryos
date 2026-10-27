"""Structured model outputs and API bodies of the price monitor."""

from pydantic import BaseModel, Field

from app.ops.schemas import Figure


class BriefFinal(BaseModel):
    """The daily sweep summary the model writes from the engine's numbers."""

    headline: str
    narrative: str
    figures: list[Figure] = Field(default_factory=list)


class DecideBody(BaseModel):
    note: str | None = None
