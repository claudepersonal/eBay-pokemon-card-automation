"""Identify stage: read a card's photos with vision and draft its listing fields."""

from __future__ import annotations

from pathlib import Path

from cardlister.db.models import Card
from cardlister.db.repository import CardRepository
from cardlister.domain.schemas import Identification
from cardlister.domain.states import CardState
from cardlister.logging import get_logger
from cardlister.vision.claude_client import CardIdentifier, VisionError

log = get_logger(__name__)

_TITLE_MAX = 80
_IDENTIFIABLE = frozenset(
    {CardState.INGESTED, CardState.IDENTIFIED, CardState.PRICED, CardState.REVIEWED}
)


def _image_paths(card: Card) -> list[Path]:
    """Photos to send, in display order, preferring cropped versions when present."""
    return [
        Path(photo.derived_path or photo.original_path)
        for photo in sorted(card.photos, key=lambda p: p.order_index)
    ]


def _item_specifics(identification: Identification) -> dict[str, str]:
    specifics = {"Brand": "Pokémon", "Game": "Pokémon TCG"}
    if identification.set_name:
        specifics["Set"] = identification.set_name
    if identification.card_number:
        specifics["Card Number"] = identification.card_number
    if identification.rarity:
        specifics["Rarity"] = identification.rarity
    for aspect in identification.extra_aspects:
        specifics.setdefault(aspect.name, aspect.value)
    return specifics


def identify_card(
    repo: CardRepository, card: Card, identifier: CardIdentifier
) -> Identification:
    """Run vision identification and populate the card's draft listing fields."""
    if card.state not in _IDENTIFIABLE:
        raise VisionError(f"Card {card.sku} is {card.state.value}; cannot identify it now.")

    images = _image_paths(card)
    if not images:
        raise VisionError(f"Card {card.sku} has no photos to identify.")

    identification = identifier.identify(images)

    card.card_name = identification.card_name
    card.set_name = identification.set_name
    card.card_number = identification.card_number
    card.rarity = identification.rarity
    card.is_holo = identification.is_holo
    card.condition_hint = identification.condition_hint
    card.identification_confidence = max(0.0, min(1.0, identification.confidence))
    card.identification_json = identification.model_dump()
    card.title = identification.suggested_title.strip()[:_TITLE_MAX]
    card.item_specifics_json = _item_specifics(identification)

    repo.set_state(card, CardState.IDENTIFIED)
    log.info(
        "Identified %s as %r (confidence %.2f)",
        card.sku,
        card.title,
        card.identification_confidence,
    )
    return identification
