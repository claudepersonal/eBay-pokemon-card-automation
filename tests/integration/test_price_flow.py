"""Pricing pipeline against mocked Browse / Marketplace Insights."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from cardlister.config import EbayEnv, Settings
from cardlister.db.base import Database
from cardlister.db.models import Card
from cardlister.db.repository import CardRepository
from cardlister.domain.states import CardState, CompKind
from cardlister.ebay.client import EbayClient
from cardlister.pipeline.ingest import ingest_root
from cardlister.pipeline.price import PricingError, build_query, price_card

BROWSE = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
INSIGHTS = "https://api.sandbox.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search"


def _client() -> EbayClient:
    return EbayClient(EbayEnv.SANDBOX, lambda: "TOKEN", sleep=lambda _: None)


def _identified_card(repo: CardRepository, cards_root: Path) -> Card:
    card = ingest_root(repo, cards_root)[0]
    card.card_name = "Charizard"
    card.set_name = "Base Set"
    card.card_number = "4/102"
    repo.set_state(card, CardState.IDENTIFIED)
    return card


def _active_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "itemSummaries": [
                {"title": "Charizard", "price": {"value": "100.00", "currency": "USD"},
                 "condition": "Used", "itemWebUrl": "http://x"},
                {"title": "Charizard", "price": {"value": "120.00", "currency": "USD"},
                 "condition": "Used", "itemWebUrl": "http://y"},
                {"title": "no price listed"},
            ]
        },
    )


def test_build_query_combines_identification() -> None:
    card = Card(sku="s", source_folder="/f", card_name="Charizard", card_number="4/102",
               set_name="Base Set")
    assert build_query(card) == "Charizard 4/102 Base Set pokemon card"


def test_prices_from_active_comps(
    settings: Settings, database: Database, cards_root: Path
) -> None:
    with database.session() as session:
        repo = CardRepository(session)
        card = _identified_card(repo, cards_root)
        with respx.mock:
            respx.get(BROWSE).mock(return_value=_active_response())
            summary = price_card(repo, card, _client(), settings)

        assert summary is not None
        assert summary.suggested == Decimal("110.00")  # median of 100, 120
        assert card.suggested_price == Decimal("110.00")
        assert card.state is CardState.PRICED
        assert len(card.comps) == 2
        assert all(c.kind is CompKind.ACTIVE for c in card.comps)
        assert card.pricing_basis_json is not None
        assert card.pricing_basis_json["source"] == "active"


def test_prefers_sold_comps_when_insights_enabled(
    settings: Settings, database: Database, cards_root: Path
) -> None:
    insights_settings = settings.model_copy(update={"ebay_use_insights": True})
    with database.session() as session:
        repo = CardRepository(session)
        card = _identified_card(repo, cards_root)
        with respx.mock:
            respx.get(INSIGHTS).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "itemSales": [
                            {"title": "Charizard", "lastSoldPrice": {"value": "90.00",
                             "currency": "USD"}, "condition": "Used", "itemWebUrl": "http://s"}
                        ]
                    },
                )
            )
            summary = price_card(repo, card, _client(), insights_settings)

        assert summary is not None
        assert summary.suggested == Decimal("90.00")
        assert card.comps[0].kind is CompKind.SOLD
        assert card.pricing_basis_json is not None
        assert card.pricing_basis_json["source"] == "sold"


def test_falls_back_to_active_when_insights_errors(
    settings: Settings, database: Database, cards_root: Path
) -> None:
    insights_settings = settings.model_copy(update={"ebay_use_insights": True})
    with database.session() as session:
        repo = CardRepository(session)
        card = _identified_card(repo, cards_root)
        with respx.mock:
            respx.get(INSIGHTS).mock(return_value=httpx.Response(403, json={"errors": []}))
            respx.get(BROWSE).mock(return_value=_active_response())
            summary = price_card(repo, card, _client(), insights_settings)

        assert summary is not None
        assert card.pricing_basis_json is not None
        assert card.pricing_basis_json["source"] == "active"


def test_pricing_requires_identification(
    settings: Settings, database: Database, cards_root: Path
) -> None:
    with database.session() as session:
        repo = CardRepository(session)
        card = ingest_root(repo, cards_root)[0]  # still INGESTED
        with pytest.raises(PricingError, match="identify"):
            price_card(repo, card, _client(), settings)
