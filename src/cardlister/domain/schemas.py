"""Pydantic schemas for structured model output (card identification)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Aspect(BaseModel):
    """An additional eBay item specific extracted from the card."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: str


class Identification(BaseModel):
    """What a vision model reads off a Pokémon card.

    This is the structured-output schema for identification. ``suggested_title`` should
    be an eBay-ready title of at most 80 characters; the pipeline truncates as a guard.
    """

    model_config = ConfigDict(extra="forbid")

    card_name: str = Field(description="The Pokémon / card name, e.g. 'Charizard'.")
    set_name: str | None = Field(default=None, description="The set, e.g. 'Base Set'.")
    card_number: str | None = Field(
        default=None, description="The collector number, e.g. '4/102'."
    )
    rarity: str | None = Field(
        default=None, description="Rarity, e.g. 'Holo Rare', 'Common'."
    )
    is_holo: bool | None = Field(default=None, description="Whether the card is holofoil.")
    condition_hint: str | None = Field(
        default=None, description="A brief visible-condition note, e.g. 'light edge wear'."
    )
    suggested_title: str = Field(description="An eBay listing title, <= 80 characters.")
    extra_aspects: list[Aspect] = Field(
        default_factory=list,
        description="Other item specifics (e.g. Character, Card Type, Language, Features).",
    )
    confidence: float = Field(
        description="Confidence in this identification, from 0.0 to 1.0."
    )
