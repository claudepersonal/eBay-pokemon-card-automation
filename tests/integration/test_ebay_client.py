"""EbayClient: retries transient failures, raises structured errors on permanent ones."""

from __future__ import annotations

import httpx
import pytest
import respx

from cardlister.config import EbayEnv
from cardlister.ebay.client import EbayClient
from cardlister.ebay.errors import EbayApiError

URL = "https://api.sandbox.ebay.com/probe"


def _client() -> EbayClient:
    return EbayClient(EbayEnv.SANDBOX, lambda: "TOKEN", max_retries=3, sleep=lambda _: None)


def test_retries_then_succeeds_on_429() -> None:
    client = _client()
    with respx.mock:
        route = respx.get(URL).mock(
            side_effect=[
                httpx.Response(429, headers={"retry-after": "0"}, json={"errors": []}),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        response = client.get(URL)
    assert response.json() == {"ok": True}
    assert route.call_count == 2


def test_injects_bearer_token() -> None:
    client = _client()
    with respx.mock:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
        client.get(URL)
    assert route.calls.last.request.headers["authorization"] == "Bearer TOKEN"


def test_permanent_error_raises_structured() -> None:
    client = _client()
    with respx.mock:
        respx.get(URL).mock(
            return_value=httpx.Response(
                400, json={"errors": [{"errorId": 25001, "message": "bad"}]}
            )
        )
        with pytest.raises(EbayApiError) as exc_info:
            client.get(URL)
    error = exc_info.value
    assert error.status_code == 400
    assert error.errors[0]["message"] == "bad"
    assert error.is_transient is False


def test_gives_up_after_max_retries() -> None:
    client = _client()
    with respx.mock:
        route = respx.get(URL).mock(return_value=httpx.Response(503))
        with pytest.raises(EbayApiError):
            client.get(URL)
    assert route.call_count == 4  # initial + 3 retries
