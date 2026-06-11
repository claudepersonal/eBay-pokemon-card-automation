"""Opt-in end-to-end check against the eBay sandbox.

Skipped automatically unless real sandbox credentials are configured. Exercises the
application-token OAuth flow and a live (read-only) Browse search — no listing.

Run with: uv run pytest -m e2e
"""

from __future__ import annotations

import pytest

from cardlister.config import EbayEnv, Settings
from cardlister.db.base import Database
from cardlister.ebay.browse import search_active
from cardlister.factory import build_app_client, build_oauth_manager

pytestmark = pytest.mark.e2e


def _sandbox_settings() -> Settings:
    settings = Settings(ebay_env=EbayEnv.SANDBOX)
    if settings.ebay_sandbox_app_id is None or settings.token_encryption_key is None:
        pytest.skip("no eBay sandbox credentials configured")
    return settings


def test_browse_search_against_sandbox() -> None:
    settings = _sandbox_settings()
    database = Database("sqlite://")
    database.create_all()
    manager = build_oauth_manager(settings, database, env=EbayEnv.SANDBOX)
    client = build_app_client(manager)

    comps = search_active(
        client, "charizard pokemon card", settings.ebay_marketplace_id, limit=3
    )
    assert isinstance(comps, list)
