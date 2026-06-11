"""Identify pipeline with a stub identifier (no network)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from cardlister.db.repository import CardRepository
from cardlister.domain.schemas import Aspect, Identification
from cardlister.domain.states import CardState
from cardlister.pipeline.identify import identify_card
from cardlister.pipeline.ingest import ingest_root
from cardlister.vision.claude_client import VisionError


class FakeIdentifier:
    def __init__(self, identification: Identification) -> None:
        self._identification = identification
        self.received: list[Path] = []

    def identify(self, image_paths: Sequence[Path]) -> Identification:
        self.received = list(image_paths)
        return self._identification


def _identification(**kwargs: object) -> Identification:
    defaults: dict[str, object] = {
        "card_name": "Charizard",
        "set_name": "Base Set",
        "card_number": "4/102",
        "rarity": "Holo Rare",
        "is_holo": True,
        "suggested_title": "Charizard 4/102 Base Set Holo Rare Pokemon Card",
        "confidence": 0.92,
        "extra_aspects": [Aspect(name="Character", value="Charizard")],
    }
    defaults.update(kwargs)
    return Identification(**defaults)


def test_identify_populates_card_and_specifics(
    repo: CardRepository, cards_root: Path
) -> None:
    card = ingest_root(repo, cards_root)[0]
    fake = FakeIdentifier(_identification())

    identify_card(repo, card, fake)

    assert card.state is CardState.IDENTIFIED
    assert card.card_name == "Charizard"
    assert card.is_holo is True
    assert card.title == "Charizard 4/102 Base Set Holo Rare Pokemon Card"
    assert card.item_specifics_json == {
        "Brand": "Pokémon",
        "Game": "Pokémon TCG",
        "Set": "Base Set",
        "Card Number": "4/102",
        "Rarity": "Holo Rare",
        "Character": "Charizard",
    }
    assert len(fake.received) == 2  # front + back sent


def test_identify_truncates_title_to_80_chars(
    repo: CardRepository, cards_root: Path
) -> None:
    card = ingest_root(repo, cards_root)[0]
    long_title = "Charizard " * 20
    identify_card(repo, card, FakeIdentifier(_identification(suggested_title=long_title)))
    assert card.title is not None
    assert len(card.title) == 80


def test_identify_clamps_confidence(repo: CardRepository, cards_root: Path) -> None:
    card = ingest_root(repo, cards_root)[0]
    identify_card(repo, card, FakeIdentifier(_identification(confidence=1.7)))
    assert card.identification_confidence == 1.0


def test_identify_requires_photos(repo: CardRepository, tmp_path: Path) -> None:
    from cardlister.db.models import Card

    card = repo.add(Card(sku="PKM-empty-abc123", source_folder=str(tmp_path / "empty")))
    with pytest.raises(VisionError, match="no photos"):
        identify_card(repo, card, FakeIdentifier(_identification()))
