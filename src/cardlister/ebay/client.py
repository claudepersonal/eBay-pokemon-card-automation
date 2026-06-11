"""A thin httpx wrapper for eBay REST calls with retry/backoff and auth injection.

The client is deliberately decoupled from token acquisition: it takes a
``token_provider`` callable so it can be tested with a stub and reused for both the
application token (Browse) and user token (Inventory/Account/Media) flows.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from cardlister.config import EbayEnv
from cardlister.ebay.errors import TRANSIENT_STATUSES, EbayApiError
from cardlister.logging import get_logger

log = get_logger(__name__)

TokenProvider = Callable[[], str]
Sleeper = Callable[[float], None]


class EbayClient:
    """Issues authenticated eBay REST requests, retrying transient failures."""

    def __init__(
        self,
        env: EbayEnv,
        token_provider: TokenProvider,
        *,
        http: httpx.Client | None = None,
        max_retries: int = 4,
        base_backoff: float = 0.5,
        max_backoff: float = 8.0,
        sleep: Sleeper = time.sleep,
    ) -> None:
        self.env = env
        self._token_provider = token_provider
        self._http = http or httpx.Client(timeout=30.0)
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self._sleep = sleep

    @property
    def api_base(self) -> str:
        return f"https://{self.env.api_host}"

    @property
    def media_base(self) -> str:
        return f"https://{self.env.media_host}"

    def _backoff(self, attempt: int) -> float:
        jittered: float = self.base_backoff * (2**attempt) + random.uniform(0, 0.25)
        return jittered if jittered < self.max_backoff else self.max_backoff

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        token: str | None = None,
        expected: tuple[int, ...] = (200, 201, 204),
    ) -> httpx.Response:
        """Send a request, retrying transient failures, and raise on unexpected status."""
        final_headers = {"Authorization": f"Bearer {token or self._token_provider()}"}
        if headers:
            final_headers.update(headers)

        last_response: httpx.Response | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._http.request(
                    method,
                    url,
                    headers=final_headers,
                    json=json,
                    data=data,
                    files=files,
                    params=params,
                )
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise EbayApiError(0, message=f"network error: {exc}") from exc
                self._sleep(self._backoff(attempt))
                continue

            if response.status_code in expected:
                return response

            last_response = response
            if response.status_code in TRANSIENT_STATUSES and attempt < self.max_retries:
                wait = _retry_after(response) or self._backoff(attempt)
                log.warning(
                    "eBay %s %s -> %d; retry %d/%d in %.1fs",
                    method,
                    url,
                    response.status_code,
                    attempt + 1,
                    self.max_retries,
                    wait,
                )
                self._sleep(wait)
                continue
            break

        assert last_response is not None
        raise EbayApiError(last_response.status_code, errors=_extract_errors(last_response))

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)


def _retry_after(response: httpx.Response) -> float | None:
    value: str | None = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _extract_errors(response: httpx.Response) -> list[dict[str, Any]]:
    try:
        body = response.json()
    except ValueError:
        return [{"message": response.text[:500]}]
    errors = body.get("errors") if isinstance(body, dict) else None
    return errors if isinstance(errors, list) else [{"message": str(body)[:500]}]
