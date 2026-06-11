"""Application configuration, loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class EbayEnv(enum.StrEnum):
    """Which eBay environment a run targets. Never mixed within one run."""

    SANDBOX = "sandbox"
    PRODUCTION = "production"

    @property
    def api_host(self) -> str:
        return "api.sandbox.ebay.com" if self is EbayEnv.SANDBOX else "api.ebay.com"

    @property
    def media_host(self) -> str:
        return "apim.sandbox.ebay.com" if self is EbayEnv.SANDBOX else "apim.ebay.com"

    @property
    def auth_host(self) -> str:
        return "auth.sandbox.ebay.com" if self is EbayEnv.SANDBOX else "auth.ebay.com"

    @property
    def view_host(self) -> str:
        """Host for the public listing URL shown to the seller."""
        return "www.sandbox.ebay.com" if self is EbayEnv.SANDBOX else "www.ebay.com"


@dataclass(frozen=True)
class EbayCredentials:
    """The eBay developer keyset for one environment."""

    app_id: str
    cert_id: str
    ru_name: str


class Settings(BaseSettings):
    """All runtime configuration. Read once via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_prefix="CARDLISTER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ebay_env: EbayEnv = EbayEnv.SANDBOX

    ebay_sandbox_app_id: SecretStr | None = None
    ebay_sandbox_cert_id: SecretStr | None = None
    ebay_sandbox_ru_name: str | None = None

    ebay_production_app_id: SecretStr | None = None
    ebay_production_cert_id: SecretStr | None = None
    ebay_production_ru_name: str | None = None

    ebay_marketplace_id: str = "EBAY_US"
    ebay_category_id: str = "183454"
    origin_postal_code: str = "54007"

    anthropic_api_key: SecretStr | None = None
    vision_model: str = "claude-haiku-4-5"

    token_encryption_key: SecretStr | None = None

    data_dir: Path = Path("data")
    cards_root: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cardlister.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def derived_dir(self) -> Path:
        return self.data_dir / "derived"

    def ebay_credentials(self, env: EbayEnv | None = None) -> EbayCredentials:
        """Return the keyset for ``env`` (defaults to the active environment).

        Raises a clear error if any of the three required values is missing.
        """
        env = env or self.ebay_env
        if env is EbayEnv.SANDBOX:
            app_id, cert_id, ru_name = (
                self.ebay_sandbox_app_id,
                self.ebay_sandbox_cert_id,
                self.ebay_sandbox_ru_name,
            )
        else:
            app_id, cert_id, ru_name = (
                self.ebay_production_app_id,
                self.ebay_production_cert_id,
                self.ebay_production_ru_name,
            )

        missing = [
            name
            for name, value in (
                (f"ebay_{env.value}_app_id", app_id),
                (f"ebay_{env.value}_cert_id", cert_id),
                (f"ebay_{env.value}_ru_name", ru_name),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                f"Missing eBay {env.value} credentials: "
                + ", ".join(f"CARDLISTER_{m.upper()}" for m in missing)
            )

        assert app_id is not None and cert_id is not None and ru_name is not None
        return EbayCredentials(
            app_id=app_id.get_secret_value(),
            cert_id=cert_id.get_secret_value(),
            ru_name=ru_name,
        )


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once and cache them for the process."""
    return Settings()
