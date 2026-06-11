"""Command-line entry point for cardlister."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cardlister import __version__
from cardlister.config import Settings, get_settings
from cardlister.db.base import Database
from cardlister.db.repository import CardRepository
from cardlister.logging import configure_logging
from cardlister.pipeline.crop import crop_card_photos
from cardlister.pipeline.ingest import ingest_root

app = typer.Typer(
    help="Turn photos of Pokémon cards into priced eBay listings, with a human review gate.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    configure_logging("DEBUG" if verbose else "INFO")


def _open_database(settings: Settings) -> Database:
    """Open the local database, creating the data dir and tables on first run."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_url)
    database.create_all()
    return database


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
        cards = [repo.get_by_sku(sku)] if sku else list(repo.list_cards())
        if sku and cards[0] is None:
            raise typer.BadParameter(f"No card with SKU {sku!r}.")
        for card in cards:
            if card is None:
                continue
            total += crop_card_photos(
                card,
                settings.derived_dir,
                force=force,
                margin=margin,
                sensitivity=sensitivity,
            )
    typer.echo(f"Cropped {total} photo(s).")


if __name__ == "__main__":
    app()
