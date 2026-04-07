"""Tests for x_cli.auth."""


import pytest

from x_cli.auth import Credentials, generate_oauth_header, inspect_credentials, load_credentials
from x_cli.errors import ConfigurationError


@pytest.fixture
def creds():
    return Credentials(
        api_key="test_key",
        api_secret="test_secret",
        access_token="test_token",
        access_token_secret="test_token_secret",
        bearer_token="test_bearer",
    )


class TestGenerateOAuthHeader:
    def test_returns_oauth_prefix(self, creds):
        header = generate_oauth_header("GET", "https://api.x.com/2/tweets/123", creds)
        assert header.startswith("OAuth ")

    def test_contains_consumer_key(self, creds):
        header = generate_oauth_header("GET", "https://api.x.com/2/tweets/123", creds)
        assert "oauth_consumer_key" in header
        assert "test_key" in header

    def test_contains_signature(self, creds):
        header = generate_oauth_header("POST", "https://api.x.com/2/tweets", creds)
        assert "oauth_signature=" in header

    def test_contains_token(self, creds):
        header = generate_oauth_header("GET", "https://api.x.com/2/users/me", creds)
        assert "oauth_token" in header
        assert "test_token" in header

    def test_different_urls_different_signatures(self, creds):
        h1 = generate_oauth_header("GET", "https://api.x.com/2/tweets/1", creds)
        h2 = generate_oauth_header("GET", "https://api.x.com/2/tweets/2", creds)
        # Extract signatures
        import re
        sig1 = re.search(r'oauth_signature="([^"]+)"', h1).group(1)
        sig2 = re.search(r'oauth_signature="([^"]+)"', h2).group(1)
        assert sig1 != sig2

    def test_url_with_query_params(self, creds):
        url = "https://api.x.com/2/tweets/123?tweet.fields=created_at,public_metrics"
        header = generate_oauth_header("GET", url, creds)
        assert header.startswith("OAuth ")


class TestLoadCredentials:
    def test_inspect_credentials_reports_present_and_missing(self, monkeypatch):
        monkeypatch.setattr("x_cli.auth.load_dotenv", lambda *args, **kwargs: False)
        monkeypatch.setenv("X_API_KEY", "key")
        monkeypatch.setenv("X_API_SECRET", "secret")
        monkeypatch.setenv("X_ACCESS_TOKEN", "token")
        monkeypatch.delenv("X_ACCESS_TOKEN_SECRET", raising=False)
        monkeypatch.delenv("X_BEARER_TOKEN", raising=False)

        status = inspect_credentials()

        assert status.ok is False
        assert "X_API_KEY" in status.present
        assert "X_ACCESS_TOKEN_SECRET" in status.missing

    def test_reports_all_missing_vars(self, monkeypatch):
        monkeypatch.setattr("x_cli.auth.load_dotenv", lambda *args, **kwargs: False)
        for name in (
            "X_API_KEY",
            "X_API_SECRET",
            "X_ACCESS_TOKEN",
            "X_ACCESS_TOKEN_SECRET",
            "X_BEARER_TOKEN",
        ):
            monkeypatch.delenv(name, raising=False)

        with pytest.raises(ConfigurationError, match="X_API_KEY, X_API_SECRET"):
            load_credentials()
