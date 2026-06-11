"""Construct wired eBay clients from settings + the local database."""

from __future__ import annotations

from cardlister.config import ConfigError, EbayEnv, Settings
from cardlister.db.base import Database
from cardlister.ebay.client import EbayClient
from cardlister.ebay.oauth import OAuthManager, TokenEncryptor, TokenStore


def build_token_store(settings: Settings, database: Database) -> TokenStore:
    key = settings.token_encryption_key
    if key is None:
        raise ConfigError(
            "CARDLISTER_TOKEN_ENCRYPTION_KEY is required to store eBay tokens. "
            'Generate one: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return TokenStore(database, TokenEncryptor(key.get_secret_value()))


def build_oauth_manager(
    settings: Settings, database: Database, *, env: EbayEnv | None = None
) -> OAuthManager:
    return OAuthManager(settings, build_token_store(settings, database), env=env)


def build_user_client(manager: OAuthManager) -> EbayClient:
    """A client authenticated with the seller's user token (Inventory/Account/Media)."""
    return EbayClient(manager.env, manager.user_token)


def build_app_client(manager: OAuthManager) -> EbayClient:
    """A client authenticated with the application token (Browse)."""
    return EbayClient(manager.env, manager.app_token)
