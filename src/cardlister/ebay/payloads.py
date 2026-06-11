"""Pure builders that map a Card to eBay Inventory/Offer request bodies.

Kept free of I/O so the mapping is unit-testable on its own.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from cardlister.db.models import Card

DEFAULT_CONDITION = "USED_VERY_GOOD"


def _aspects(item_specifics: dict[str, Any]) -> dict[str, list[str]]:
    """eBay aspects are name -> list-of-strings."""
    aspects: dict[str, list[str]] = {}
    for name, value in item_specifics.items():
        if value is None or value == "":
            continue
        aspects[name] = [str(v) for v in value] if isinstance(value, list) else [str(value)]
    return aspects


def build_inventory_item(
    card: Card,
    image_urls: list[str],
    *,
    condition: str = DEFAULT_CONDITION,
) -> dict[str, Any]:
    if not card.title:
        raise ValueError(f"Card {card.sku} has no title")
    if not image_urls:
        raise ValueError(f"Card {card.sku} has no image URLs")
    return {
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
        "condition": card.condition_id or condition,
        "product": {
            "title": card.title,
            "description": card.description or card.title,
            "imageUrls": image_urls,
            "aspects": _aspects(card.item_specifics_json),
        },
    }


def offer_price(card: Card) -> Decimal:
    price = card.confirmed_price if card.confirmed_price is not None else card.suggested_price
    if price is None:
        raise ValueError(f"Card {card.sku} has no price set")
    return price


def build_offer(
    card: Card,
    *,
    marketplace_id: str,
    category_id: str,
    fulfillment_policy_id: str,
    payment_policy_id: str,
    return_policy_id: str,
    merchant_location_key: str,
) -> dict[str, Any]:
    price = offer_price(card)
    return {
        "sku": card.sku,
        "marketplaceId": marketplace_id,
        "format": "FIXED_PRICE",
        "availableQuantity": 1,
        "categoryId": card.category_id or category_id,
        "listingDescription": card.description or card.title,
        "listingPolicies": {
            "fulfillmentPolicyId": fulfillment_policy_id,
            "paymentPolicyId": payment_policy_id,
            "returnPolicyId": return_policy_id,
        },
        "pricingSummary": {"price": {"value": f"{price:.2f}", "currency": card.currency}},
        "merchantLocationKey": merchant_location_key,
    }
