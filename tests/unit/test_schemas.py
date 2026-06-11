"""The Identification structured-output schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cardlister.domain.schemas import Aspect, Identification


def test_minimal_identification_validates() -> None:
    ident = Identification(
        card_name="Charizard", suggested_title="Charizard 4/102", confidence=0.9
    )
    assert ident.set_name is None
    assert ident.extra_aspects == []


def test_card_name_and_title_are_required() -> None:
    with pytest.raises(ValidationError):
        Identification(suggested_title="x", confidence=0.5)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        Identification(card_name="Charizard", confidence=0.5)  # type: ignore[call-arg]


def test_extra_aspects_round_trip() -> None:
    ident = Identification(
        card_name="Charizard",
        suggested_title="Charizard 4/102 Base Set Holo",
        confidence=0.8,
        extra_aspects=[Aspect(name="Character", value="Charizard")],
    )
    dumped = ident.model_dump()
    assert dumped["extra_aspects"] == [{"name": "Character", "value": "Charizard"}]
