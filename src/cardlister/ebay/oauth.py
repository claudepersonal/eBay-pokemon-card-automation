"""eBay OAuth2: application (client-credentials) and user (auth-code) token flows.

User access tokens last ~2h; refresh tokens ~18 months. Refresh tokens are stored
encrypted at rest (Fernet) because the SQLite file is plaintext. The app token (used
for the Browse API) has no refresh token and is simply re-minted when it expires.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from cardlister.config import ConfigError, EbayCredentials, EbayEnv, Settings
from cardlister.db.base import Database
from cardlister.db.models import OAuthToken
from cardlister.domain.states import TokenType
from cardlister.ebay.errors import EbayAuthError
from cardlister.logging import get_logger

log = get_logger(__name__)

# Scope identifiers always use the api.ebay.com host, regardless of environment.
USER_SCOPES = (
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
)
APP_SCOPES = ("https://api.ebay.com/oauth/api_scope/buy.browse",)

_EXPIRY_SKEW = timedelta(seconds=60)

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat stored values as UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class StoredToken:
    access_token: str
    access_expires_at: datetime
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None
    scopes: str | None = None


class TokenEncryptor:
    """Encrypts/decrypts refresh tokens with a Fernet key from settings."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise ConfigError(
                "CARDLISTER_TOKEN_ENCRYPTION_KEY is not a valid Fernet key"
            ) from exc

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise EbayAuthError("stored refresh token could not be decrypted") from exc


class TokenStore:
    """Persists eBay tokens, encrypting refresh tokens at rest."""

    def __init__(self, database: Database, encryptor: TokenEncryptor) -> None:
        self._db = database
        self._encryptor = encryptor

    def load(self, env: EbayEnv, token_type: TokenType) -> StoredToken | None:
        with self._db.session() as session:
            row = session.scalar(
                select(OAuthToken).where(
                    OAuthToken.environment == env, OAuthToken.token_type == token_type
                )
            )
            if row is None:
                return None
            refresh = (
                self._encryptor.decrypt(row.refresh_token_encrypted)
                if row.refresh_token_encrypted
                else None
            )
            access_expires_at = _as_aware(row.access_expires_at)
            assert access_expires_at is not None
            return StoredToken(
                access_token=row.access_token,
                access_expires_at=access_expires_at,
                refresh_token=refresh,
                refresh_expires_at=_as_aware(row.refresh_expires_at),
                scopes=row.scopes,
            )

    def save(self, env: EbayEnv, token_type: TokenType, token: StoredToken) -> None:
        encrypted = (
            self._encryptor.encrypt(token.refresh_token) if token.refresh_token else None
        )
        with self._db.session() as session:
            row = session.scalar(
                select(OAuthToken).where(
                    OAuthToken.environment == env, OAuthToken.token_type == token_type
                )
            )
            if row is None:
                row = OAuthToken(environment=env, token_type=token_type)
                session.add(row)
            row.access_token = token.access_token
            row.access_expires_at = token.access_expires_at
            # Keep an existing refresh token if a refresh response omitted one.
            if encrypted is not None:
                row.refresh_token_encrypted = encrypted
                row.refresh_expires_at = token.refresh_expires_at
            row.scopes = token.scopes


class OAuthManager:
    """Acquires and caches eBay OAuth tokens for one environment."""

    def __init__(
        self,
        settings: Settings,
        store: TokenStore,
        *,
        http: httpx.Client | None = None,
        now: Clock = _utcnow,
        env: EbayEnv | None = None,
    ) -> None:
        self.settings = settings
        self.env = env or settings.ebay_env
        self.credentials: EbayCredentials = settings.ebay_credentials(self.env)
        self._store = store
        self._http = http or httpx.Client(timeout=30.0)
        self._now = now

    @property
    def _token_url(self) -> str:
        return f"https://{self.env.api_host}/identity/v1/oauth2/token"

    def _basic_auth_header(self) -> str:
        raw = f"{self.credentials.app_id}:{self.credentials.cert_id}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def _post_token(self, data: dict[str, str]) -> dict[str, Any]:
        response = self._http.post(
            self._token_url,
            data=data,
            headers={
                "Authorization": self._basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if response.status_code != 200:
            raise EbayAuthError(f"token request failed ({response.status_code}): {response.text}")
        result: dict[str, Any] = response.json()
        return result

    def _is_fresh(self, token: StoredToken | None) -> bool:
        return token is not None and token.access_expires_at - _EXPIRY_SKEW > self._now()

    # --- application token (Browse) ------------------------------------------

    def app_token(self) -> str:
        cached = self._store.load(self.env, TokenType.APP)
        if self._is_fresh(cached):
            assert cached is not None
            return cached.access_token

        payload = self._post_token(
            {"grant_type": "client_credentials", "scope": " ".join(APP_SCOPES)}
        )
        token = self._to_stored(payload, scopes=" ".join(APP_SCOPES))
        self._store.save(self.env, TokenType.APP, token)
        return token.access_token

    # --- user token (Inventory / Account / Media) ----------------------------

    def authorization_url(self, *, state: str | None = None) -> str:
        params = {
            "client_id": self.credentials.app_id,
            "redirect_uri": self.credentials.ru_name,
            "response_type": "code",
            "scope": " ".join(USER_SCOPES),
        }
        if state:
            params["state"] = state
        return f"https://{self.env.auth_host}/oauth2/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> StoredToken:
        payload = self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.credentials.ru_name,
            }
        )
        token = self._to_stored(payload, scopes=" ".join(USER_SCOPES))
        self._store.save(self.env, TokenType.USER, token)
        log.info("Stored eBay user token for %s", self.env.value)
        return token

    def stored_user_token(self) -> StoredToken | None:
        """Return the persisted user token (for status display), without refreshing."""
        return self._store.load(self.env, TokenType.USER)

    def user_token(self) -> str:
        cached = self._store.load(self.env, TokenType.USER)
        if self._is_fresh(cached):
            assert cached is not None
            return cached.access_token
        if cached is None or cached.refresh_token is None:
            raise EbayAuthError(
                f"No eBay user token for {self.env.value}. Run `cardlister auth login`."
            )
        if cached.refresh_expires_at and cached.refresh_expires_at <= self._now():
            raise EbayAuthError(
                f"eBay refresh token for {self.env.value} has expired. Run `cardlister auth login`."
            )
        return self._refresh(cached.refresh_token)

    def _refresh(self, refresh_token: str) -> str:
        payload = self._post_token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": " ".join(USER_SCOPES),
            }
        )
        token = self._to_stored(payload, scopes=" ".join(USER_SCOPES))
        self._store.save(self.env, TokenType.USER, token)
        log.debug("Refreshed eBay user token for %s", self.env.value)
        return token.access_token

    def _to_stored(self, payload: dict[str, Any], *, scopes: str) -> StoredToken:
        access_token = str(payload["access_token"])
        expires_in = int(payload.get("expires_in", 7200))
        refresh_token = payload.get("refresh_token")
        refresh_expires_in = payload.get("refresh_token_expires_in")
        refresh_expires_at = (
            self._now() + timedelta(seconds=int(refresh_expires_in))
            if refresh_expires_in is not None
            else None
        )
        return StoredToken(
            access_token=access_token,
            access_expires_at=self._now() + timedelta(seconds=expires_in),
            refresh_token=str(refresh_token) if refresh_token else None,
            refresh_expires_at=refresh_expires_at,
            scopes=scopes,
        )
