"""The Sell Inventory API listing flow: inventory item -> offer -> publish.

The card's SKU is the idempotency key: ``createOrReplaceInventoryItem`` is a PUT that
replaces rather than duplicates, so retrying a failed list never creates a second item.
"""

from __future__ import annotations

from typing import Any

from cardlister.ebay.client import EbayClient
from cardlister.ebay.errors import EbayApiError

_INVENTORY_BASE = "/sell/inventory/v1"
# Inventory item and offer writes require a content language header.
_CONTENT_LANGUAGE = {"Content-Language": "en-US"}


def create_or_replace_inventory_item(client: EbayClient, sku: str, item: dict[str, Any]) -> None:
    client.put(
        f"{client.api_base}{_INVENTORY_BASE}/inventory_item/{sku}",
        json=item,
        headers=_CONTENT_LANGUAGE,
        expected=(200, 201, 204),
    )


def create_offer(client: EbayClient, offer: dict[str, Any]) -> str:
    body = client.post(
        f"{client.api_base}{_INVENTORY_BASE}/offer",
        json=offer,
        headers=_CONTENT_LANGUAGE,
        expected=(200, 201),
    ).json()
    offer_id = body.get("offerId")
    if not offer_id:
        raise EbayApiError(200, message="createOffer returned no offerId")
    return str(offer_id)


def publish_offer(client: EbayClient, offer_id: str) -> str:
    body = client.post(
        f"{client.api_base}{_INVENTORY_BASE}/offer/{offer_id}/publish",
        expected=(200,),
    ).json()
    listing_id = body.get("listingId")
    if not listing_id:
        raise EbayApiError(200, message="publishOffer returned no listingId")
    return str(listing_id)
