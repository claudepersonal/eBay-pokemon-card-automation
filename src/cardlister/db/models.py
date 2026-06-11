"""SQLAlchemy ORM models — the persistent domain.

``Card`` is the aggregate root. Nothing about a card is coupled to file order: each
photo carries an explicit :class:`~cardlister.domain.states.PhotoRole`, and the eBay
``sku`` (generated once at ingest, never changed) is the idempotency key for every
eBay write.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cardlister.config import EbayEnv
from cardlister.db.base import Base
from cardlister.domain.states import CardState, CompKind, PhotoRole, TokenType


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _enum_column(enum_type: type[enum.Enum]) -> Enum:
    """Store an enum as its string value (portable, human-readable in SQLite)."""
    return Enum(enum_type, native_enum=False, values_callable=lambda e: [m.value for m in e])


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class Card(TimestampMixin, Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    source_folder: Mapped[str] = mapped_column(String, unique=True, index=True)
    state: Mapped[CardState] = mapped_column(
        _enum_column(CardState), default=CardState.INGESTED, index=True
    )
    display_name: Mapped[str | None] = mapped_column(String)

    # Identification (filled at IDENTIFIED).
    card_name: Mapped[str | None] = mapped_column(String)
    set_name: Mapped[str | None] = mapped_column(String)
    card_number: Mapped[str | None] = mapped_column(String)
    rarity: Mapped[str | None] = mapped_column(String)
    is_holo: Mapped[bool | None] = mapped_column()
    condition_hint: Mapped[str | None] = mapped_column(String)
    identification_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    identification_confidence: Mapped[float | None] = mapped_column()

    # Listing draft (editable during review).
    title: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    item_specifics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    category_id: Mapped[str | None] = mapped_column(String)
    condition_id: Mapped[str | None] = mapped_column(String)

    # Pricing (filled at PRICED).
    suggested_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    confirmed_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    pricing_basis_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Listing result.
    ebay_offer_id: Mapped[str | None] = mapped_column(String)
    ebay_listing_id: Mapped[str | None] = mapped_column(String)
    listing_url: Mapped[str | None] = mapped_column(String)
    last_error: Mapped[str | None] = mapped_column(Text)

    photos: Mapped[list[Photo]] = relationship(
        back_populates="card",
        cascade="all, delete-orphan",
        order_by="Photo.order_index",
    )
    comps: Mapped[list[Comp]] = relationship(
        back_populates="card", cascade="all, delete-orphan"
    )
    listing_attempts: Mapped[list[ListingAttempt]] = relationship(
        back_populates="card", cascade="all, delete-orphan", order_by="ListingAttempt.id"
    )

    def __repr__(self) -> str:
        return f"<Card id={self.id} sku={self.sku!r} state={self.state.value}>"


class Photo(TimestampMixin, Base):
    __tablename__ = "photos"
    __table_args__ = (UniqueConstraint("card_id", "original_path", name="uq_photo_card_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    role: Mapped[PhotoRole] = mapped_column(_enum_column(PhotoRole))
    original_path: Mapped[str] = mapped_column(String)
    derived_path: Mapped[str | None] = mapped_column(String)
    order_index: Mapped[int] = mapped_column(default=0)
    eps_image_url: Mapped[str | None] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    card: Mapped[Card] = relationship(back_populates="photos")

    def __repr__(self) -> str:
        return f"<Photo id={self.id} role={self.role.value} path={self.original_path!r}>"


class Comp(TimestampMixin, Base):
    __tablename__ = "comps"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    kind: Mapped[CompKind] = mapped_column(_enum_column(CompKind))
    title: Mapped[str | None] = mapped_column(String)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    condition: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    card: Mapped[Card] = relationship(back_populates="comps")


class ListingAttempt(TimestampMixin, Base):
    __tablename__ = "listing_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String)
    success: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    card: Mapped[Card] = relationship(back_populates="listing_attempts")


class OAuthToken(TimestampMixin, Base):
    """An eBay OAuth token. The refresh token is stored encrypted at rest."""

    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint("environment", "token_type", name="uq_token_env_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    environment: Mapped[EbayEnv] = mapped_column(_enum_column(EbayEnv))
    token_type: Mapped[TokenType] = mapped_column(_enum_column(TokenType))
    access_token: Mapped[str] = mapped_column(Text)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str | None] = mapped_column(Text)


class EbayPolicyCache(TimestampMixin, Base):
    """Cached account prerequisites per environment (policy IDs + location key)."""

    __tablename__ = "ebay_policy_cache"

    environment: Mapped[EbayEnv] = mapped_column(_enum_column(EbayEnv), primary_key=True)
    fulfillment_policy_id: Mapped[str | None] = mapped_column(String)
    payment_policy_id: Mapped[str | None] = mapped_column(String)
    return_policy_id: Mapped[str | None] = mapped_column(String)
    merchant_location_key: Mapped[str | None] = mapped_column(String)
