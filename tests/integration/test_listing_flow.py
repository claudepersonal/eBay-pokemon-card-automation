"""End-to-end list_card flow against a mocked eBay: media -> inventory -> offer -> publish."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from cardlister.config import EbayEnv, Settings
from cardlister.db.base import Database
from cardlister.db.models import Card
from cardlister.db.repository import CardRepository
from cardlister.domain.states import CardState
from cardlister.ebay.account import AccountStatus
from cardlister.ebay.client import EbayClient
from cardlister.ebay.errors import EbayError
from cardlister.pipeline.ingest import ingest_root
from cardlister.pipeline.list_card import list_card

MEDIA = "https://apim.sandbox.ebay.com/commerce/media/v1_beta/image"
INVENTORY = "https://api.sandbox.ebay.com/sell/inventory/v1"
IMAGE_URL = "https://i.ebayimg.com/IMG1.jpg"


def _client() -> EbayClient:
    return EbayClient(EbayEnv.SANDBOX, lambda: "TOKEN", sleep=lambda _: None)


def _ready_account() -> AccountStatus:
    return AccountStatus(
        fulfillment_policy_id="F1",
        payment_policy_id="P1",
        return_policy_id="R1",
        merchant_location_key="LOC1",
        opted_in_business_policies=True,
    )


def _make_reviewed(repo: CardRepository, cards_root: Path) -> Card:
    card = ingest_root(repo, cards_root)[0]
    card.title = "Charizard 4/102 Base Set Holo"
    card.confirmed_price = Decimal("99.99")
    card.item_specifics_json = {"Brand": "Pokémon"}
    for state in (CardState.IDENTIFIED, CardState.PRICED, CardState.REVIEWED):
        repo.set_state(card, state)
    return card


def _mock_happy_path() -> dict[str, respx.Route]:
    create = respx.post(f"{MEDIA}/create_from_file").mock(
        return_value=httpx.Response(201, headers={"Location": f"{MEDIA}/IMG1"})
    )
    respx.get(f"{MEDIA}/IMG1").mock(
        return_value=httpx.Response(200, json={"imageUrl": IMAGE_URL})
    )
    inventory = respx.put(url__regex=rf"{re.escape(INVENTORY)}/inventory_item/.+").mock(
        return_value=httpx.Response(204)
    )
    offer = respx.post(f"{INVENTORY}/offer").mock(
        return_value=httpx.Response(200, json={"offerId": "OFFER-1"})
    )
    publish = respx.post(f"{INVENTORY}/offer/OFFER-1/publish").mock(
        return_value=httpx.Response(200, json={"listingId": "LST-1"})
    )
    return {"create": create, "inventory": inventory, "offer": offer, "publish": publish}


def test_list_card_publishes_and_records(
    settings: Settings, database: Database, cards_root: Path
) -> None:
    with database.session() as session:
        repo = CardRepository(session)
        card = _make_reviewed(repo, cards_root)

        with respx.mock:
            routes = _mock_happy_path()
            listing_id = list_card(repo, card, _client(), _ready_account(), settings)

        assert listing_id == "LST-1"
        assert card.state is CardState.LISTED
        assert card.ebay_listing_id == "LST-1"
        assert card.ebay_offer_id == "OFFER-1"
        assert card.listing_url == "https://www.sandbox.ebay.com/itm/LST-1"
        assert all(p.eps_image_url == IMAGE_URL for p in card.photos)

        # SKU is the inventory item id.
        assert routes["inventory"].calls.last.request.url.path.endswith(card.sku)
        # Price is formatted to 2dp.
        offer_body = json.loads(routes["offer"].calls.last.request.content)
        assert offer_body["pricingSummary"]["price"]["value"] == "99.99"

        attempt = card.listing_attempts[-1]
        assert attempt.success is True and attempt.error is None


def test_failed_publish_marks_card_failed(
    settings: Settings, database: Database, cards_root: Path
) -> None:
    with database.session() as session:
        repo = CardRepository(session)
        card = _make_reviewed(repo, cards_root)

        with respx.mock:
            respx.post(f"{MEDIA}/create_from_file").mock(
                return_value=httpx.Response(201, headers={"Location": f"{MEDIA}/IMG1"})
            )
            respx.get(f"{MEDIA}/IMG1").mock(
                return_value=httpx.Response(200, json={"imageUrl": IMAGE_URL})
            )
            respx.put(url__regex=rf"{re.escape(INVENTORY)}/inventory_item/.+").mock(
                return_value=httpx.Response(204)
            )
            respx.post(f"{INVENTORY}/offer").mock(
                return_value=httpx.Response(200, json={"offerId": "OFFER-1"})
            )
            respx.post(f"{INVENTORY}/offer/OFFER-1/publish").mock(
                return_value=httpx.Response(400, json={"errors": [{"message": "category invalid"}]})
            )
            with pytest.raises(EbayError, match="category invalid"):
                list_card(repo, card, _client(), _ready_account(), settings)

        assert card.state is CardState.FAILED
        assert card.last_error and "category invalid" in card.last_error
        assert card.listing_attempts[-1].success is False


def test_list_card_refuses_when_account_not_ready(
    settings: Settings, database: Database, cards_root: Path
) -> None:
    with database.session() as session:
        repo = CardRepository(session)
        card = _make_reviewed(repo, cards_root)
        not_ready = AccountStatus(problems=["No return policy found."])

        with pytest.raises(EbayError, match="not ready"):
            list_card(repo, card, _client(), not_ready, settings)

        assert card.state is CardState.REVIEWED  # never transitioned to LISTING
