"""Routes for the local review UI."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from cardlister.config import Settings
from cardlister.db.models import Card, Photo
from cardlister.db.repository import CardRepository
from cardlister.domain.states import CardState, PhotoRole
from cardlister.ebay.account import verify_account
from cardlister.ebay.errors import EbayError
from cardlister.ebay.payloads import build_inventory_item, build_offer
from cardlister.factory import (
    build_app_client,
    build_card_identifier,
    build_oauth_manager,
    build_user_client,
)
from cardlister.listing_text import default_description
from cardlister.pipeline.identify import identify_card
from cardlister.pipeline.list_card import list_card
from cardlister.pipeline.price import PricingError, price_card
from cardlister.vision.claude_client import VisionError
from cardlister.web.deps import get_session, get_settings
from cardlister.web.templating import templates

router = APIRouter()

_FORWARD_CHAIN = [
    CardState.INGESTED,
    CardState.IDENTIFIED,
    CardState.PRICED,
    CardState.REVIEWED,
]


def _parse_price(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _load_card(session: Session, card_id: int) -> Card:
    card = session.scalar(
        select(Card)
        .options(selectinload(Card.photos), selectinload(Card.comps))
        .where(Card.id == card_id)
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


def _advance_to_reviewed(repo: CardRepository, card: Card) -> None:
    if card.state not in _FORWARD_CHAIN:
        return
    start = _FORWARD_CHAIN.index(card.state)
    for state in _FORWARD_CHAIN[start + 1 :]:
        repo.set_state(card, state)


def _redirect(card_id: int, *, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    query = ""
    if msg:
        query = f"?msg={msg}"
    elif err:
        query = f"?err={err}"
    return RedirectResponse(url=f"/cards/{card_id}{query}", status_code=303)


@router.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/cards")


@router.get("/cards")
def list_cards(
    request: Request, session: Annotated[Session, Depends(get_session)]
) -> Response:
    cards = session.scalars(
        select(Card).options(selectinload(Card.photos)).order_by(Card.id)
    ).all()
    return templates.TemplateResponse(
        request, "cards.html", {"cards": cards, "CardState": CardState}
    )


@router.get("/cards/{card_id}")
def card_detail(
    card_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    msg: str | None = None,
    err: str | None = None,
) -> Response:
    card = _load_card(session, card_id)
    return templates.TemplateResponse(
        request,
        "card.html",
        {
            "card": card,
            "CardState": CardState,
            "PhotoRole": PhotoRole,
            "msg": msg,
            "err": err,
        },
    )


@router.post("/cards/{card_id}/save")
def save_card(
    card_id: int,
    session: Annotated[Session, Depends(get_session)],
    title: Annotated[str, Form()],
    price: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
) -> RedirectResponse:
    card = _load_card(session, card_id)
    if len(title) > 80:
        return _redirect(card_id, err="Title must be 80 characters or fewer.")
    amount = _parse_price(price) if price else None
    if price and amount is None:
        return _redirect(card_id, err="Invalid price.")
    card.title = title
    card.description = description or None
    if amount is not None:
        card.confirmed_price = amount
    return _redirect(card_id, msg="Saved.")


@router.post("/cards/{card_id}/confirm")
def confirm_card(
    card_id: int,
    session: Annotated[Session, Depends(get_session)],
    title: Annotated[str, Form()],
    price: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
) -> RedirectResponse:
    card = _load_card(session, card_id)
    repo = CardRepository(session)
    if len(title) > 80:
        return _redirect(card_id, err="Title must be 80 characters or fewer.")
    amount = _parse_price(price)
    if amount is None:
        return _redirect(card_id, err="A valid price is required to confirm.")
    card.title = title
    card.description = description or default_description(title)
    card.confirmed_price = amount
    if card.suggested_price is None:
        card.suggested_price = amount
    _advance_to_reviewed(repo, card)
    return _redirect(card_id, msg="Confirmed and ready to list.")


@router.post("/cards/{card_id}/photos/{photo_id}/role")
def set_photo_role(
    card_id: int,
    photo_id: int,
    session: Annotated[Session, Depends(get_session)],
    role: Annotated[str, Form()],
) -> RedirectResponse:
    photo = session.get(Photo, photo_id)
    if photo is None or photo.card_id != card_id:
        raise HTTPException(status_code=404, detail="Photo not found")
    try:
        photo.role = PhotoRole(role)
    except ValueError:
        return _redirect(card_id, err="Invalid photo role.")
    return _redirect(card_id, msg="Photo role updated.")


@router.post("/cards/{card_id}/identify")
def identify_action(
    card_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    card = _load_card(session, card_id)
    repo = CardRepository(session)
    try:
        identify_card(repo, card, build_card_identifier(settings))
    except VisionError as exc:
        return _redirect(card_id, err=str(exc))
    return _redirect(card_id, msg="Identified.")


@router.post("/cards/{card_id}/price")
def price_action(
    card_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    card = _load_card(session, card_id)
    repo = CardRepository(session)
    try:
        manager = build_oauth_manager(settings, request.app.state.database, env=settings.ebay_env)
        client = build_app_client(manager)
        price_card(repo, card, client, settings)
    except (PricingError, EbayError) as exc:
        return _redirect(card_id, err=str(exc))
    return _redirect(card_id, msg="Priced from comps.")


@router.post("/cards/{card_id}/list")
def list_action(
    card_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    card = _load_card(session, card_id)
    if card.state is not CardState.REVIEWED and card.state is not CardState.FAILED:
        return _redirect(card_id, err="Confirm the card before listing.")
    repo = CardRepository(session)
    try:
        manager = build_oauth_manager(settings, request.app.state.database, env=settings.ebay_env)
        client = build_user_client(manager)
        status = verify_account(client, settings.ebay_marketplace_id)
        list_card(repo, card, client, status, settings)
    except EbayError as exc:
        return _redirect(card_id, err=str(exc))
    return _redirect(card_id, msg="Listed on eBay.")


@router.get("/cards/{card_id}/preview")
def preview(
    card_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    card = _load_card(session, card_id)
    image_urls = [
        p.eps_image_url or f"(upload pending: {Path(p.original_path).name})"
        for p in sorted(card.photos, key=lambda p: p.order_index)
    ]
    error: str | None = None
    inventory_item = None
    offer = None
    try:
        inventory_item = build_inventory_item(card, image_urls or ["(no photos)"])
        offer = build_offer(
            card,
            marketplace_id=settings.ebay_marketplace_id,
            category_id=settings.ebay_category_id,
            fulfillment_policy_id="(your fulfillment policy)",
            payment_policy_id="(your payment policy)",
            return_policy_id="(your return policy)",
            merchant_location_key="(your inventory location)",
        )
    except ValueError as exc:
        error = str(exc)
    return templates.TemplateResponse(
        request,
        "preview.html",
        {"card": card, "inventory_item": inventory_item, "offer": offer, "error": error},
    )


@router.get("/photos/{photo_id}")
def serve_photo(
    photo_id: int, session: Annotated[Session, Depends(get_session)]
) -> FileResponse:
    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    path = Path(photo.derived_path or photo.original_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file missing")
    return FileResponse(path)
