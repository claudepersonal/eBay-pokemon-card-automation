"""Data-access helpers. State transitions go through here so they're always guarded."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from cardlister.db.models import Card, Photo
from cardlister.domain.states import CardState, assert_transition


class CardRepository:
    """Thin repository over a SQLAlchemy session for cards and their photos."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # --- queries -------------------------------------------------------------

    def get(self, card_id: int) -> Card | None:
        return self.session.get(Card, card_id)

    def get_by_sku(self, sku: str) -> Card | None:
        return self.session.scalar(select(Card).where(Card.sku == sku))

    def get_by_folder(self, source_folder: str) -> Card | None:
        return self.session.scalar(
            select(Card).where(Card.source_folder == source_folder)
        )

    def list_cards(self, *, state: CardState | None = None) -> Sequence[Card]:
        stmt = select(Card).order_by(Card.id)
        if state is not None:
            stmt = stmt.where(Card.state == state)
        return self.session.scalars(stmt).all()

    # --- mutations -----------------------------------------------------------

    def add(self, card: Card) -> Card:
        self.session.add(card)
        self.session.flush()
        return card

    def set_state(self, card: Card, to_state: CardState) -> None:
        """Move a card to ``to_state``, raising on an illegal transition."""
        assert_transition(card.state, to_state)
        card.state = to_state

    def replace_photos(self, card: Card, photos: list[Photo]) -> None:
        """Replace a card's photos wholesale (used when re-scanning a folder)."""
        card.photos.clear()
        self.session.flush()
        for photo in photos:
            card.photos.append(photo)
        self.session.flush()
