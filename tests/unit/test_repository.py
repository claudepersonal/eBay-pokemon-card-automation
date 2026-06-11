"""Repository: persistence round-trips and guarded state transitions."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cardlister.db.base import Database
from cardlister.db.models import Card
from cardlister.db.repository import CardRepository
from cardlister.domain.states import CardState, IllegalTransitionError


def test_add_and_fetch_card(database: Database) -> None:
    with database.session() as session:
        repo = CardRepository(session)
        repo.add(Card(sku="PKM-test-abc123", source_folder="/cards/test"))

    with database.session() as session:
        repo = CardRepository(session)
        card = repo.get_by_sku("PKM-test-abc123")
        assert card is not None
        assert card.state is CardState.INGESTED
        assert card.currency == "USD"
        assert card.item_specifics_json == {}


def test_set_state_enforces_transitions(database: Database) -> None:
    with database.session() as session:
        repo = CardRepository(session)
        card = repo.add(Card(sku="PKM-x-abc123", source_folder="/cards/x"))

        with pytest.raises(IllegalTransitionError):
            repo.set_state(card, CardState.LISTED)

        repo.set_state(card, CardState.IDENTIFIED)
        assert card.state is CardState.IDENTIFIED


def test_decimal_prices_round_trip(database: Database) -> None:
    with database.session() as session:
        repo = CardRepository(session)
        card = repo.add(Card(sku="PKM-p-abc123", source_folder="/cards/p"))
        card.suggested_price = Decimal("12.50")

    with database.session() as session:
        fetched = CardRepository(session).get_by_sku("PKM-p-abc123")
        assert fetched is not None
        assert fetched.suggested_price == Decimal("12.50")
