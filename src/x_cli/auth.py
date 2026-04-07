"""OAuth 1.0a auth and credential loading for the X API."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import time
import urllib.parse

from dotenv import load_dotenv  # .env file loader

# region Types
# ============================================================================
# Types
# ============================================================================


@dataclass
class Credentials:
    """OAuth and bearer credentials loaded from environment variables."""

    api_key: str
    api_secret: str
    access_token: str
    access_token_secret: str
    bearer_token: str


# endregion Types


# region Credential Loading
# ============================================================================
# Credential Loading
# ============================================================================


def load_credentials() -> Credentials:
    """Load credentials from env vars, with .env fallback."""
    # Try ~/.config/x-cli/.env first, then cwd .env
    config_env = Path.home() / ".config" / "x-cli" / ".env"
    if config_env.exists():
        load_dotenv(config_env)
    load_dotenv()  # cwd .env (won't override already-set vars)

    def require(name: str) -> str:
        val = os.environ.get(name)
        if not val:
            raise SystemExit(
                f"Missing env var: {name}. "
                "Set X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET, X_BEARER_TOKEN."
            )
        return val

    return Credentials(
        api_key=require("X_API_KEY"),
        api_secret=require("X_API_SECRET"),
        access_token=require("X_ACCESS_TOKEN"),
        access_token_secret=require("X_ACCESS_TOKEN_SECRET"),
        bearer_token=require("X_BEARER_TOKEN"),
    )


# endregion Credential Loading


# region OAuth
# ============================================================================
# OAuth 1.0a
# ============================================================================


def _percent_encode(s: str) -> str:
    """RFC 5849 percent-encoding (no safe characters)."""
    return urllib.parse.quote(s, safe="")


def generate_oauth_header(
    method: str,
    url: str,
    creds: Credentials,
    params: dict[str, str] | None = None,
) -> str:
    """Generate an OAuth 1.0a Authorization header (HMAC-SHA1)."""
    oauth_params = {
        "oauth_consumer_key": creds.api_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds.access_token,
        "oauth_version": "1.0",
    }

    # Merge oauth, body, and query-string params for the signature base
    all_params = {**oauth_params}
    if params:
        all_params.update(params)

    # Include any query-string params already embedded in the URL
    parsed = urllib.parse.urlparse(url)
    if parsed.query:
        qs_params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        for k, v in qs_params.items():
            all_params[k] = v[0]

    # Lexicographic sort required by OAuth 1.0a spec
    sorted_params = sorted(all_params.items())
    param_string = "&".join(f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted_params)

    # Base URL stripped of query string
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    # Signature base string: METHOD&url&params (each component percent-encoded)
    base_string = f"{method.upper()}&{_percent_encode(base_url)}&{_percent_encode(param_string)}"

    # Signing key: consumer_secret&token_secret
    signing_key = (
        f"{_percent_encode(creds.api_secret)}&{_percent_encode(creds.access_token_secret)}"
    )

    # HMAC-SHA1 signature
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()

    oauth_params["oauth_signature"] = signature

    # Assemble the Authorization header value
    header_parts = ", ".join(
        f'{_percent_encode(k)}="{_percent_encode(v)}"' for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"


# endregion OAuth
