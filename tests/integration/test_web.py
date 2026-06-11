"""Web review UI: rendering, editing, the confirm gate, and photo serving."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cardlister.config import Settings
from cardlister.db.base import Database
from cardlister.db.repository import CardRepository
from cardlister.domain.states import CardState, PhotoRole
from cardlister.pipeline.ingest import ingest_root
from cardlister.web.app import create_app


@dataclass
class WebFixture:
    client: TestClient
    database: Database
    card_id: int
    photo_id: int


@pytest.fixture
def web(settings: Settings, cards_root: Path) -> Iterator[WebFixture]:
    database = Database("sqlite://")
    database.create_all()
    with database.session() as session:
        cards = ingest_root(CardRepository(session), cards_root)
        card_id = cards[0].id
        photo_id = cards[0].photos[0].id

    app = create_app(settings, database)
    with TestClient(app) as client:
        yield WebFixture(client, database, card_id, photo_id)


def _state(database: Database, card_id: int) -> CardState:
    with database.session() as session:
        card = CardRepository(session).get(card_id)
        assert card is not None
        return card.state


def test_cards_list_renders(web: WebFixture) -> None:
    response = web.client.get("/cards")
    assert response.status_code == 200
    assert "Cards" in response.text


def test_card_detail_renders(web: WebFixture) -> None:
    response = web.client.get(f"/cards/{web.card_id}")
    assert response.status_code == 200
    assert "Listing draft" in response.text


def test_save_updates_draft(web: WebFixture) -> None:
    response = web.client.post(
        f"/cards/{web.card_id}/save",
        data={"title": "Charizard 4/102 Holo", "price": "120.00", "description": "Nice"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with web.database.session() as session:
        card = CardRepository(session).get(web.card_id)
        assert card is not None
        assert card.title == "Charizard 4/102 Holo"
        assert card.confirmed_price == Decimal("120.00")


def test_confirm_advances_to_reviewed(web: WebFixture) -> None:
    web.client.post(
        f"/cards/{web.card_id}/confirm",
        data={"title": "Charizard 4/102 Holo", "price": "120.00"},
        follow_redirects=False,
    )
    assert _state(web.database, web.card_id) is CardState.REVIEWED


def test_confirm_requires_valid_price(web: WebFixture) -> None:
    response = web.client.post(
        f"/cards/{web.card_id}/confirm",
        data={"title": "x", "price": "not-a-number"},
        follow_redirects=False,
    )
    assert "err=" in response.headers["location"]
    assert _state(web.database, web.card_id) is CardState.INGESTED


def test_set_photo_role(web: WebFixture) -> None:
    web.client.post(
        f"/cards/{web.card_id}/photos/{web.photo_id}/role",
        data={"role": "extra"},
        follow_redirects=False,
    )
    with web.database.session() as session:
        from cardlister.db.models import Photo

        photo = session.get(Photo, web.photo_id)
        assert photo is not None
        assert photo.role is PhotoRole.EXTRA


def test_list_blocked_until_reviewed(web: WebFixture) -> None:
    response = web.client.post(
        f"/cards/{web.card_id}/list", follow_redirects=False
    )
    assert response.status_code == 303
    assert "err=" in response.headers["location"]
    assert _state(web.database, web.card_id) is CardState.INGESTED  # untouched


def test_preview_renders_payloads(web: WebFixture) -> None:
    with web.database.session() as session:
        card = CardRepository(session).get(web.card_id)
        assert card is not None
        card.title = "Charizard 4/102 Holo"
        card.confirmed_price = Decimal("120.00")

    response = web.client.get(f"/cards/{web.card_id}/preview")
    assert response.status_code == 200
    assert "Inventory item" in response.text
    assert "Charizard 4/102 Holo" in response.text


def test_serve_photo_returns_image(web: WebFixture) -> None:
    response = web.client.get(f"/photos/{web.photo_id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")
