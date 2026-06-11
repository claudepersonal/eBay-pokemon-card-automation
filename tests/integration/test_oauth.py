"""OAuth flows: app token caching, auth-code exchange, refresh, encryption at rest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from cardlister.config import Settings
from cardlister.db.base import Database
from cardlister.db.models import OAuthToken
from cardlister.domain.states import TokenType
from cardlister.ebay.errors import EbayAuthError
from cardlister.ebay.oauth import OAuthManager, TokenEncryptor, TokenStore

TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"


def _store(settings: Settings, database: Database) -> TokenStore:
    key = settings.token_encryption_key
    assert key is not None
    return TokenStore(database, TokenEncryptor(key.get_secret_value()))


def test_token_encryptor_round_trips(settings: Settings, database: Database) -> None:
    key = settings.token_encryption_key
    assert key is not None
    enc = TokenEncryptor(key.get_secret_value())
    ciphertext = enc.encrypt("REFRESH-1")
    assert ciphertext != "REFRESH-1"
    assert enc.decrypt(ciphertext) == "REFRESH-1"


def test_app_token_mints_once_and_caches(settings: Settings, database: Database) -> None:
    manager = OAuthManager(settings, _store(settings, database))
    with respx.mock:
        route = respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "APP-TOK", "expires_in": 7200})
        )
        assert manager.app_token() == "APP-TOK"
        assert manager.app_token() == "APP-TOK"
    assert route.call_count == 1  # second call served from the store


def test_authorization_url_includes_client_and_scopes(
    settings: Settings, database: Database
) -> None:
    manager = OAuthManager(settings, _store(settings, database))
    url = manager.authorization_url()
    assert "auth.sandbox.ebay.com" in url
    assert "client_id=APP-ID" in url
    assert "redirect_uri=cardlister-RuName" in url
    assert "sell.inventory" in url


def test_exchange_stores_encrypted_refresh_token(
    settings: Settings, database: Database
) -> None:
    manager = OAuthManager(settings, _store(settings, database))
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "USER-1",
                    "expires_in": 7200,
                    "refresh_token": "REFRESH-1",
                    "refresh_token_expires_in": 47_304_000,
                },
            )
        )
        manager.exchange_code("AUTH-CODE")

    with database.session() as session:
        row = session.scalar(
            select(OAuthToken).where(OAuthToken.token_type == TokenType.USER)
        )
    assert row is not None
    assert row.refresh_token_encrypted not in (None, "REFRESH-1")  # not stored in plaintext


def test_user_token_refreshes_when_access_expires(
    settings: Settings, database: Database
) -> None:
    clock = {"t": datetime(2026, 1, 1, tzinfo=UTC)}
    manager = OAuthManager(settings, _store(settings, database), now=lambda: clock["t"])
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "access_token": "USER-1",
                        "expires_in": 7200,
                        "refresh_token": "REFRESH-1",
                        "refresh_token_expires_in": 47_304_000,
                    },
                ),
                httpx.Response(200, json={"access_token": "USER-2", "expires_in": 7200}),
            ]
        )
        manager.exchange_code("AUTH-CODE")
        assert manager.user_token() == "USER-1"  # still fresh

        clock["t"] = clock["t"] + timedelta(hours=3)
        assert manager.user_token() == "USER-2"  # access expired -> refreshed


def test_user_token_without_login_raises(settings: Settings, database: Database) -> None:
    manager = OAuthManager(settings, _store(settings, database))
    with pytest.raises(EbayAuthError, match="auth login"):
        manager.user_token()
