"""Card -> eBay request body builders."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cardlister.db.models import Card
from cardlister.ebay.payloads import build_inventory_item, build_offer, offer_price


def _card(**kwargs: object) -> Card:
    defaults: dict[str, object] = {
        "sku": "PKM-charizard-abc123",
        "source_folder": "/cards/charizard",
        "title": "Charizard 4/102 Base Set Holo",
        "currency": "USD",
        "item_specifics_json": {"Brand": "Pokémon", "Set": "Base Set"},
    }
    defaults.update(kwargs)
    return Card(**defaults)


def test_build_inventory_item_shapes_aspects_as_lists() -> None:
    card = _card()
    item = build_inventory_item(card, ["https://img/1.jpg", "https://img/2.jpg"])

    assert item["availability"]["shipToLocationAvailability"]["quantity"] == 1
    assert item["product"]["title"] == card.title
    assert item["product"]["imageUrls"] == ["https://img/1.jpg", "https://img/2.jpg"]
    assert item["product"]["aspects"] == {"Brand": ["Pokémon"], "Set": ["Base Set"]}


def test_build_inventory_item_requires_title_and_images() -> None:
    with pytest.raises(ValueError, match="no title"):
        build_inventory_item(_card(title=None), ["https://img/1.jpg"])
    with pytest.raises(ValueError, match="no image"):
        build_inventory_item(_card(), [])


def test_offer_price_prefers_confirmed() -> None:
    card = _card(suggested_price=Decimal("10.00"), confirmed_price=Decimal("12.50"))
    assert offer_price(card) == Decimal("12.50")


def test_offer_price_falls_back_to_suggested() -> None:
    assert offer_price(_card(suggested_price=Decimal("9.99"))) == Decimal("9.99")


def test_offer_price_raises_when_unset() -> None:
    with pytest.raises(ValueError, match="no price"):
        offer_price(_card())


def test_build_offer_formats_price_and_policies() -> None:
    card = _card(confirmed_price=Decimal("12.5"))
    offer = build_offer(
        card,
        marketplace_id="EBAY_US",
        category_id="183454",
        fulfillment_policy_id="F1",
        payment_policy_id="P1",
        return_policy_id="R1",
        merchant_location_key="LOC1",
    )
    assert offer["sku"] == card.sku
    assert offer["format"] == "FIXED_PRICE"
    assert offer["categoryId"] == "183454"
    assert offer["pricingSummary"]["price"] == {"value": "12.50", "currency": "USD"}
    assert offer["listingPolicies"] == {
        "fulfillmentPolicyId": "F1",
        "paymentPolicyId": "P1",
        "returnPolicyId": "R1",
    }
    assert offer["merchantLocationKey"] == "LOC1"
