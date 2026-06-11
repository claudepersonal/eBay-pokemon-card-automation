"""Active comparable listings via the eBay Browse API (uses the application token)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from cardlister.domain.pricing import CompData
from cardlister.domain.states import CompKind
from cardlister.ebay.client import EbayClient

_BROWSE_PATH = "/buy/browse/v1/item_summary/search"


def _price(node: dict[str, Any] | None) -> tuple[Decimal, str] | None:
    if not node:
        return None
    try:
        return Decimal(str(node["value"])), node.get("currency", "USD")
    except (KeyError, InvalidOperation):
        return None


def search_active(
    client: EbayClient, query: str, marketplace_id: str, *, limit: int = 20
) -> list[CompData]:
    body = client.get(
        f"{client.api_base}{_BROWSE_PATH}",
        params={"q": query, "limit": str(limit)},
        headers={"X-EBAY-C-MARKETPLACE-ID": marketplace_id},
    ).json()

    comps: list[CompData] = []
    for summary in body.get("itemSummaries", []):
        priced = _price(summary.get("price"))
        if priced is None:
            continue
        value, currency = priced
        comps.append(
            CompData(
                kind=CompKind.ACTIVE,
                title=summary.get("title"),
                price=value,
                currency=currency,
                condition=summary.get("condition"),
                url=summary.get("itemWebUrl"),
            )
        )
    return comps
