"""Command-line entry point for cardlister."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs, urlparse

import typer

from cardlister import __version__
from cardlister.config import ConfigError, EbayEnv, Settings, get_settings
from cardlister.db.base import Database
from cardlister.db.models import Card
from cardlister.db.repository import CardRepository
from cardlister.domain.states import CardState
from cardlister.ebay.account import verify_account
from cardlister.ebay.errors import EbayError
from cardlister.ebay.oauth import OAuthManager
from cardlister.factory import (
    build_app_client,
    build_card_identifier,
    build_oauth_manager,
    build_user_client,
)
from cardlister.listing_text import default_description
from cardlister.logging import configure_logging
from cardlister.pipeline.crop import crop_card_photos
from cardlister.pipeline.identify import identify_card
from cardlister.pipeline.ingest import ingest_root
from cardlister.pipeline.list_card import list_card
from cardlister.pipeline.price import PricingError, price_card
from cardlister.vision.claude_client import VisionError

app = typer.Typer(
    help="Turn photos of Pokémon cards into priced eBay listings, with a human review gate.",
    no_args_is_help=True,
    add_completion=False,
)
auth_app = typer.Typer(help="Authenticate with eBay (OAuth2).", no_args_is_help=True)
app.add_typer(auth_app, name="auth")

# State order used to advance a card forward through legal transitions.
_FORWARD_CHAIN = [
    CardState.INGESTED,
    CardState.IDENTIFIED,
    CardState.PRICED,
    CardState.REVIEWED,
]


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging.")] = False,
) -> None:
    configure_logging("DEBUG" if verbose else "INFO")


def _open_database(settings: Settings) -> Database:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_url)
    database.create_all()
    return database


def _require_card(repo: CardRepository, sku: str) -> Card:
    card = repo.get_by_sku(sku)
    if card is None:
        raise typer.BadParameter(f"No card with SKU {sku!r}.")
    return card


def _manager(settings: Settings, database: Database, env: EbayEnv | None) -> OAuthManager:
    try:
        return build_oauth_manager(settings, database, env=env)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}")
        raise typer.Exit(code=2) from exc


def _advance_to_reviewed(repo: CardRepository, card: Card) -> None:
    if card.state not in _FORWARD_CHAIN:
        raise typer.BadParameter(f"Card is {card.state.value}; cannot move it back to reviewed.")
    start = _FORWARD_CHAIN.index(card.state)
    for next_state in _FORWARD_CHAIN[start + 1 :]:
        repo.set_state(card, next_state)


@app.command()
def version() -> None:
    """Print the cardlister version."""
    typer.echo(__version__)


@app.command()
def ingest(
    root: Annotated[
        Path | None,
        typer.Argument(help="Directory of per-card folders. Defaults to CARDLISTER_CARDS_ROOT."),
    ] = None,
) -> None:
    """Scan a directory of per-card folders into the database."""
    settings = get_settings()
    root = root or settings.cards_root
    if root is None:
        raise typer.BadParameter("Provide a root directory or set CARDLISTER_CARDS_ROOT.")

    database = _open_database(settings)
    with database.session() as session:
        cards = ingest_root(CardRepository(session), root)
        rows = [(card.sku, card.state.value, len(card.photos)) for card in cards]

    if not rows:
        typer.echo("No card folders found.")
        return
    typer.echo(f"Ingested {len(rows)} card(s):")
    for sku, state, photo_count in rows:
        typer.echo(f"  {sku:<40} {state:<10} {photo_count} photo(s)")


@app.command()
def crop(
    sku: Annotated[
        str | None, typer.Argument(help="Crop one card by SKU. Omit to crop all cards.")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-crop even if a derived image exists.")
    ] = False,
    margin: Annotated[
        int, typer.Option(help="Pixels of margin to keep around the detected card.")
    ] = 40,
    sensitivity: Annotated[
        float, typer.Option(help="Edge sensitivity (lower = more permissive).")
    ] = 0.12,
) -> None:
    """Crop card photos to the card, non-destructively (originals are never modified)."""
    settings = get_settings()
    database = _open_database(settings)
    total = 0
    with database.session() as session:
        repo = CardRepository(session)
        cards = [_require_card(repo, sku)] if sku else list(repo.list_cards())
        for card in cards:
            total += crop_card_photos(
                card, settings.derived_dir, force=force, margin=margin, sensitivity=sensitivity
            )
    typer.echo(f"Cropped {total} photo(s).")


@app.command()
def review(
    sku: Annotated[str, typer.Argument(help="SKU of the card to prepare for listing.")],
    title: Annotated[str, typer.Option(help="eBay listing title (<=80 characters).")],
    price: Annotated[str, typer.Option(help="Listing price, e.g. 12.50.")],
    description: Annotated[
        str | None, typer.Option(help="Optional HTML description; a default is generated.")
    ] = None,
) -> None:
    """Set a card's title/price and mark it reviewed (manual stand-in for vision+pricing)."""
    if len(title) > 80:
        raise typer.BadParameter("Title must be at most 80 characters.")
    try:
        amount = Decimal(price)
    except InvalidOperation as exc:
        raise typer.BadParameter(f"Invalid price: {price!r}") from exc

    settings = get_settings()
    database = _open_database(settings)
    with database.session() as session:
        repo = CardRepository(session)
        card = _require_card(repo, sku)
        card.title = title
        card.description = description or default_description(title)
        card.suggested_price = amount
        card.confirmed_price = amount
        card.item_specifics_json = {
            "Brand": "Pokémon",
            "Game": "Pokémon TCG",
            **card.item_specifics_json,
        }
        _advance_to_reviewed(repo, card)
    typer.echo(f"{sku} is reviewed: {title} @ {amount} {settings.ebay_marketplace_id}")


@app.command()
def identify(
    sku: Annotated[
        str | None, typer.Argument(help="Identify one card by SKU. Omit to identify all.")
    ] = None,
) -> None:
    """Identify cards from their photos with Claude vision and draft listing fields."""
    settings = get_settings()
    database = _open_database(settings)
    identifier = build_card_identifier(settings)

    with database.session() as session:
        repo = CardRepository(session)
        cards = [_require_card(repo, sku)] if sku else list(repo.list_cards())
        results: list[tuple[str, str, float]] = []
        for card in cards:
            try:
                identification = identify_card(repo, card, identifier)
            except VisionError as exc:
                typer.echo(f"  {card.sku}: skipped ({exc})")
                continue
            results.append(
                (card.sku, identification.suggested_title, identification.confidence)
            )

    for card_sku, title, confidence in results:
        typer.echo(f"  {card_sku}: {title}  (confidence {confidence:.2f})")
    typer.echo(f"Identified {len(results)} card(s).")


@app.command()
def price(
    sku: Annotated[str, typer.Argument(help="SKU of an identified card to price.")],
    env: Annotated[EbayEnv | None, typer.Option(help="Override CARDLISTER_EBAY_ENV.")] = None,
    limit: Annotated[int, typer.Option(help="Number of comps to fetch.")] = 20,
) -> None:
    """Suggest a price for a card from recent eBay comps."""
    settings = get_settings()
    database = _open_database(settings)
    manager = _manager(settings, database, env)
    client = build_app_client(manager)

    with database.session() as session:
        repo = CardRepository(session)
        card = _require_card(repo, sku)
        try:
            summary = price_card(repo, card, client, settings, limit=limit)
        except PricingError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if summary is None:
        typer.echo(f"No comps found for {sku}.")
        return
    typer.echo(
        f"{sku}: suggested {summary.suggested} "
        f"({summary.method} of {summary.sample_size} comps; "
        f"range {summary.low}-{summary.high})"
    )


@auth_app.command("login")
def auth_login(
    env: Annotated[EbayEnv | None, typer.Option(help="Override CARDLISTER_EBAY_ENV.")] = None,
) -> None:
    """Authorize cardlister to sell on your eBay account (auth-code grant)."""
    settings = get_settings()
    database = _open_database(settings)
    manager = _manager(settings, database, env)

    typer.echo("Open this URL, sign in, and grant access:\n")
    typer.echo(manager.authorization_url())
    pasted = typer.prompt("\nPaste the full redirect URL (or just the code)")
    code = _extract_auth_code(pasted)
    try:
        manager.exchange_code(code)
    except EbayError as exc:
        raise typer.Exit(code=1) from exc
    typer.echo(f"Saved eBay user token for {manager.env.value}.")


@auth_app.command("status")
def auth_status(
    env: Annotated[EbayEnv | None, typer.Option(help="Override CARDLISTER_EBAY_ENV.")] = None,
) -> None:
    """Show whether a usable eBay user token is stored."""
    settings = get_settings()
    database = _open_database(settings)
    manager = _manager(settings, database, env)
    token = manager.stored_user_token()
    if token is None:
        typer.echo(f"No user token for {manager.env.value}. Run `cardlister auth login`.")
        return
    typer.echo(f"User token for {manager.env.value}: access expires {token.access_expires_at}")
    if token.refresh_expires_at:
        typer.echo(f"  refresh token expires {token.refresh_expires_at}")


@app.command()
def account(
    env: Annotated[EbayEnv | None, typer.Option(help="Override CARDLISTER_EBAY_ENV.")] = None,
) -> None:
    """Check that the eBay account is ready to list (policies + inventory location)."""
    settings = get_settings()
    database = _open_database(settings)
    manager = _manager(settings, database, env)
    client = build_user_client(manager)
    status = verify_account(client, settings.ebay_marketplace_id)
    if status.ok:
        typer.echo("eBay account is ready to list.")
    else:
        typer.echo("eBay account is NOT ready:")
        for problem in status.problems:
            typer.echo(f"  - {problem}")
        raise typer.Exit(code=1)


@app.command(name="list")
def list_cmd(
    sku: Annotated[str, typer.Argument(help="SKU of a reviewed card to list.")],
    env: Annotated[EbayEnv | None, typer.Option(help="Override CARDLISTER_EBAY_ENV.")] = None,
) -> None:
    """Publish a reviewed card to eBay."""
    settings = get_settings()
    database = _open_database(settings)
    manager = _manager(settings, database, env)
    client = build_user_client(manager)
    status = verify_account(client, settings.ebay_marketplace_id)

    with database.session() as session:
        repo = CardRepository(session)
        card = _require_card(repo, sku)
        try:
            list_card(repo, card, client, status, settings)
        except EbayError as exc:
            typer.echo(f"Listing failed: {exc}")
            raise typer.Exit(code=1) from exc
        url = card.listing_url
    typer.echo(f"Listed {sku}: {url}")


def _extract_auth_code(pasted: str) -> str:
    pasted = pasted.strip()
    if "code=" in pasted:
        query = urlparse(pasted).query or pasted
        codes = parse_qs(query).get("code")
        if codes:
            return codes[0]
    return pasted


if __name__ == "__main__":
    app()
