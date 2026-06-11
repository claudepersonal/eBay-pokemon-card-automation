"""Sold comparables via the Marketplace Insights API (uses the application token).

This API is a Limited Release behind an eBay Application Growth Check approval, so it's
feature-flagged (CARDLISTER_EBAY_USE_INSIGHTS). When it isn't available, pricing falls
back to active-listing stats from the Browse API.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from cardlister.domain.pricing import CompData
from cardlister.domain.states import CompKind
from cardlister.ebay.client import EbayClient

_INSIGHTS_PATH = "/buy/marketplace_insights/v1_beta/item_sales/search"


def _price(node: dict[str, Any] | None) -> tuple[Decimal, str] | None:
    if not node:
        return None
    try:
        return Decimal(str(node["value"])), node.get("currency", "USD")
    except (KeyError, InvalidOperation):
        return None


def search_sold(
    client: EbayClient, query: str, marketplace_id: str, *, limit: int = 20
) -> list[CompData]:
    body = client.get(
        f"{client.api_base}{_INSIGHTS_PATH}",
        params={"q": query, "limit": str(limit)},
        headers={"X-EBAY-C-MARKETPLACE-ID": marketplace_id},
    ).json()

    comps: list[CompData] = []
    for sale in body.get("itemSales", []):
        priced = _price(sale.get("lastSoldPrice"))
        if priced is None:
            continue
        value, currency = priced
        comps.append(
            CompData(
                kind=CompKind.SOLD,
                title=sale.get("title"),
                price=value,
                currency=currency,
                condition=sale.get("condition"),
                url=sale.get("itemWebUrl"),
            )
        )
    return comps
