"""eBay API error types and transient/permanent classification."""

from __future__ import annotations

from typing import Any

# HTTP statuses worth retrying (eBay-side hiccups, rate limiting).
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


class EbayError(RuntimeError):
    """Base class for all eBay client errors."""


class EbayAuthError(EbayError):
    """OAuth/token acquisition or refresh failed; user re-consent likely needed."""


class EbayApiError(EbayError):
    """A non-2xx response from an eBay REST endpoint.

    ``errors`` holds eBay's structured error array (each item has ``errorId``,
    ``message``, etc.) when present, so callers and the UI can show it verbatim.
    """

    def __init__(
        self,
        status_code: int,
        *,
        errors: list[dict[str, Any]] | None = None,
        message: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.errors = errors or []
        detail = message or "; ".join(e.get("message", "") for e in self.errors)
        super().__init__(f"eBay API error {status_code}: {detail or '(no detail)'}")

    @property
    def is_transient(self) -> bool:
        return self.status_code in TRANSIENT_STATUSES
