"""Price stage: suggest a price for a card from recent eBay comps.

Prefers sold comps (Marketplace Insights) when enabled and available, otherwise uses
active-listing stats from the Browse API. Persists the comps it used so the review UI
can show the evidence behind the suggestion.
"""

from __future__ import annotations

from cardlister.config import Settings
from cardlister.db.models import Card, Comp
from cardlister.db.repository import CardRepository
from cardlister.domain.pricing import CompData, PriceSuggestion, summarize_prices
from cardlister.domain.states import CardState
from cardlister.ebay.browse import search_active
from cardlister.ebay.client import EbayClient
from cardlister.ebay.errors import EbayApiError
from cardlister.ebay.insights import search_sold
from cardlister.logging import get_logger

log = get_logger(__name__)

_PRICEABLE = frozenset({CardState.IDENTIFIED, CardState.PRICED, CardState.REVIEWED})


class PricingError(RuntimeError):
    """Raised when a card can't be priced (e.g. it hasn't been identified yet)."""


def build_query(card: Card) -> str:
    parts = [card.card_name or card.display_name, card.card_number, card.set_name]
    query = " ".join(p for p in parts if p).strip()
    return f"{query} pokemon card" if query else "pokemon card"


def _fetch_comps(
    client: EbayClient, query: str, settings: Settings, limit: int
) -> tuple[list[CompData], str]:
    if settings.ebay_use_insights:
        try:
            sold = search_sold(client, query, settings.ebay_marketplace_id, limit=limit)
        except EbayApiError as exc:
            log.warning("Marketplace Insights unavailable (%s); falling back to active comps", exc)
        else:
            if sold:
                return sold, "sold"
    return search_active(client, query, settings.ebay_marketplace_id, limit=limit), "active"


def price_card(
    repo: CardRepository,
    card: Card,
    app_client: EbayClient,
    settings: Settings,
    *,
    limit: int = 20,
) -> PriceSuggestion | None:
    """Fetch comps, store them, and set the card's suggested price. Returns the summary."""
    if card.state not in _PRICEABLE:
        raise PricingError(
            f"Card {card.sku} is {card.state.value}; identify it before pricing."
        )

    query = build_query(card)
    comps, source = _fetch_comps(app_client, query, settings, limit)

    card.comps.clear()
    repo.session.flush()
    for comp in comps:
        card.comps.append(
            Comp(
                kind=comp.kind,
                title=comp.title,
                price=comp.price,
                currency=comp.currency,
                condition=comp.condition,
                url=comp.url,
            )
        )

    summary = summarize_prices([comp.price for comp in comps])
    if summary is not None:
        card.suggested_price = summary.suggested
        card.pricing_basis_json = {
            "method": summary.method,
            "source": source,
            "query": query,
            "sample_size": summary.sample_size,
            "low": str(summary.low),
            "median": str(summary.median),
            "high": str(summary.high),
        }
        log.info(
            "Priced %s at %s (%s of %d %s comps)",
            card.sku,
            summary.suggested,
            summary.method,
            summary.sample_size,
            source,
        )
    else:
        log.info("No comps found for %s (query: %s)", card.sku, query)

    repo.set_state(card, CardState.PRICED)
    return summary
