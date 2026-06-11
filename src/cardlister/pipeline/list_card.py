"""List stage: take a REVIEWED card all the way to a published eBay listing.

Idempotent and retry-safe: images are uploaded once and their EPS URLs cached on the
photo; the inventory item is keyed by SKU (replace, not duplicate); a stored offer ID
is reused instead of creating a second offer. Every attempt is recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cardlister.config import Settings
from cardlister.db.models import Card, ListingAttempt
from cardlister.db.repository import CardRepository
from cardlister.domain.states import CardState
from cardlister.ebay.account import AccountStatus
from cardlister.ebay.client import EbayClient
from cardlister.ebay.errors import EbayApiError, EbayError
from cardlister.ebay.inventory import (
    create_offer,
    create_or_replace_inventory_item,
    publish_offer,
)
from cardlister.ebay.media import upload_image
from cardlister.ebay.payloads import build_inventory_item, build_offer
from cardlister.logging import get_logger

log = get_logger(__name__)

_LISTABLE_STATES = frozenset({CardState.REVIEWED, CardState.FAILED})


def _ensure_image_urls(client: EbayClient, card: Card) -> list[str]:
    """Upload any photos that don't yet have an EPS URL; return URLs in display order."""
    urls: list[str] = []
    for photo in sorted(card.photos, key=lambda p: p.order_index):
        if not photo.eps_image_url:
            source = Path(photo.derived_path or photo.original_path)
            photo.eps_image_url = upload_image(client, source)
            log.info("Uploaded %s -> %s", source.name, photo.eps_image_url)
        urls.append(photo.eps_image_url)
    return urls


def list_card(
    repo: CardRepository,
    card: Card,
    client: EbayClient,
    account: AccountStatus,
    settings: Settings,
) -> str:
    """Publish ``card`` to eBay and return the listing ID.

    Raises :class:`EbayError` (leaving the card in FAILED with ``last_error`` set) if
    the account isn't ready or any eBay call fails.
    """
    if card.state not in _LISTABLE_STATES:
        raise EbayError(f"Card {card.sku} is {card.state.value}; must be reviewed before listing.")
    if not account.ok or not all(
        (
            account.fulfillment_policy_id,
            account.payment_policy_id,
            account.return_policy_id,
            account.merchant_location_key,
        )
    ):
        raise EbayError(
            "eBay account is not ready to list: "
            + "; ".join(account.problems or ["missing policies"])
        )

    repo.set_state(card, CardState.LISTING)
    attempt = ListingAttempt(stage="publish", success=False, started_at=datetime.now(UTC))
    card.listing_attempts.append(attempt)

    try:
        image_urls = _ensure_image_urls(client, card)
        create_or_replace_inventory_item(
            client, card.sku, build_inventory_item(card, image_urls)
        )
        if not card.ebay_offer_id:
            card.ebay_offer_id = create_offer(
                client,
                build_offer(
                    card,
                    marketplace_id=settings.ebay_marketplace_id,
                    category_id=settings.ebay_category_id,
                    fulfillment_policy_id=account.fulfillment_policy_id,  # type: ignore[arg-type]
                    payment_policy_id=account.payment_policy_id,  # type: ignore[arg-type]
                    return_policy_id=account.return_policy_id,  # type: ignore[arg-type]
                    merchant_location_key=account.merchant_location_key,  # type: ignore[arg-type]
                ),
            )
        listing_id = publish_offer(client, card.ebay_offer_id)
    except (EbayApiError, ValueError) as exc:
        card.last_error = str(exc)
        attempt.error = str(exc)
        attempt.finished_at = datetime.now(UTC)
        repo.set_state(card, CardState.FAILED)
        log.error("Listing %s failed: %s", card.sku, exc)
        raise EbayError(str(exc)) from exc

    card.ebay_listing_id = listing_id
    card.listing_url = f"https://{settings.ebay_env.view_host}/itm/{listing_id}"
    card.last_error = None
    attempt.success = True
    attempt.finished_at = datetime.now(UTC)
    repo.set_state(card, CardState.LISTED)
    log.info("Listed %s -> %s", card.sku, card.listing_url)
    return listing_id
