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

from .errors import ConfigurationError

# region Types
# ============================================================================
# Types
# ============================================================================


REQUIRED_ENV_VARS = (
    "X_API_KEY",
    "X_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
    "X_BEARER_TOKEN",
)


@dataclass(frozen=True, slots=True)
class Credentials:
    """OAuth and bearer credentials loaded from environment variables."""

    api_key             : str
    api_secret          : str
    access_token        : str
    access_token_secret : str
    bearer_token        : str


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    """Presence-only credential report for diagnostics and help output."""

    config_env_path   : Path
    cwd_env_path      : Path
    config_env_exists : bool
    cwd_env_exists    : bool
    present           : tuple[str, ...]
    missing           : tuple[str, ...]

    @property
    def ok(self) -> bool:
        """Return True when all required credential variables are present."""
        return not self.missing


# endregion Types


# region Credential Loading
# ============================================================================
# Credential Loading
# ============================================================================


def _load_env_sources() -> tuple[Path, Path]:
    """Load config and cwd `.env` files without overriding existing variables."""
    config_env = Path.home() / ".config" / "x-cli" / ".env"
    cwd_env = Path.cwd() / ".env"
    if config_env.exists():
        load_dotenv(config_env)
    load_dotenv()  # cwd .env (won't override already-set vars)
    return config_env, cwd_env


def _env_values() -> dict[str, str]:
    """Return stripped required credential values from the current environment."""
    return {name: (os.environ.get(name) or "").strip() for name in REQUIRED_ENV_VARS}


def inspect_credentials() -> CredentialStatus:
    """Inspect credential presence without constructing a Credentials object."""
    config_env, cwd_env = _load_env_sources()
    env_values = _env_values()
    present = tuple(name for name, value in env_values.items() if value)
    missing = tuple(name for name, value in env_values.items() if not value)
    return CredentialStatus(
        config_env_path   = config_env,
        cwd_env_path      = cwd_env,
        config_env_exists = config_env.exists(),
        cwd_env_exists    = cwd_env.exists(),
        present           = present,
        missing           = missing,
    )


def load_credentials() -> Credentials:
    """Load credentials from env vars, with config and cwd `.env` fallbacks."""
    status = inspect_credentials()
    env_values = _env_values()

    if status.missing:
        missing_text = ", ".join(status.missing)
        raise ConfigurationError(
            "Missing required credentials: "
            f"{missing_text}. "
            "Checked ~/.config/x-cli/.env, ./.env, and the current environment."
        )

    return Credentials(
        api_key             = env_values["X_API_KEY"],
        api_secret          = env_values["X_API_SECRET"],
        access_token        = env_values["X_ACCESS_TOKEN"],
        access_token_secret = env_values["X_ACCESS_TOKEN_SECRET"],
        bearer_token        = env_values["X_BEARER_TOKEN"],
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
    method : str,
    url    : str,
    creds  : Credentials,
    params : dict[str, str] | None = None,
) -> str:
    """Generate an OAuth 1.0a Authorization header (HMAC-SHA1)."""
    oauth_params = {
        "oauth_consumer_key"    : creds.api_key,
        "oauth_nonce"           : secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp"       : str(int(time.time())),
        "oauth_token"           : creds.access_token,
        "oauth_version"         : "1.0",
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
