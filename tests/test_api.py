"""Tests for x_cli.api error handling and request validation."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from x_cli.api import API_BASE, XApiClient
from x_cli.auth import Credentials
from x_cli.errors import ApiError, InputError


@pytest.fixture
def creds():
    return Credentials(
        api_key             = "key",
        api_secret          = "secret",
        access_token        = "token",
        access_token_secret = "token-secret",
        bearer_token        = "bearer",
    )


@pytest.fixture
def client(creds):
    api_client = XApiClient(creds)
    api_client._http = MagicMock()
    return api_client


def _response(
    *,
    status_code: int = 200,
    is_success: bool = True,
    json_data=None,
    text: str = "",
    json_error: bool = False,
):
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = is_success
    resp.headers = {}
    resp.text = text
    if json_error:
        resp.json.side_effect = ValueError("invalid json")
    else:
        resp.json.return_value = json_data
    return resp


class TestResponseHandling:
    def test_non_json_error_uses_response_text(self, client):
        resp = _response(
            status_code=502,
            is_success=False,
            text="bad gateway",
            json_error=True,
        )

        with pytest.raises(ApiError, match=r"HTTP 502.*bad gateway"):
            client._handle(resp)

    def test_non_json_success_raises_api_error(self, client):
        resp = _response(status_code=200, is_success=True, json_error=True)

        with pytest.raises(ApiError, match="non-JSON success response"):
            client._handle(resp)


class TestTransportHandling:
    def test_search_tweets_wraps_transport_errors(self, client):
        request = httpx.Request("GET", f"{API_BASE}/tweets/search/recent")
        client._http.get.side_effect = httpx.ConnectError("network down", request=request)

        with pytest.raises(ApiError, match="network down"):
            client.search_tweets("hello")


class TestPostValidation:
    def test_rejects_poll_and_media_together(self, client):
        with pytest.raises(InputError, match="Poll posts cannot include media attachments"):
            client.post_tweet("hello", poll_options=["Yes", "No"], media_ids=["1"])

    def test_rejects_quote_with_media(self, client):
        with pytest.raises(InputError, match="Quote posts cannot include media attachments"):
            client.post_tweet("hello", quote_tweet_id="123", media_ids=["1"])

    def test_rejects_empty_poll_options(self, client):
        with pytest.raises(InputError, match="Poll options cannot be empty"):
            client.post_tweet("hello", poll_options=["Yes", ""])

    def test_rejects_too_many_media_ids(self, client):
        with pytest.raises(InputError, match="up to 4 media attachments"):
            client.post_tweet("hello", media_ids=["1", "2", "3", "4", "5"])
