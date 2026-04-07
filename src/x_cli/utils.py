"""Utility helpers for x-cli."""

from __future__ import annotations

import re

from .errors import InputError

_TWEET_URL_PATTERN = re.compile(
    r"^(?:https?://)?(?:www\.|mobile\.)?(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/status/(\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)


def parse_tweet_id(input_str: str) -> str:
    """Extract a tweet ID from a URL or raw numeric string."""
    stripped = input_str.strip()
    if not stripped:
        raise InputError("Tweet ID or URL cannot be empty.")

    if re.fullmatch(r"\d+", stripped):
        return stripped

    match = _TWEET_URL_PATTERN.fullmatch(stripped)
    if match:
        return match.group(1)

    raise InputError(f"Invalid tweet ID or URL: {input_str}")


def strip_at(username: str) -> str:
    """Remove leading @ from a username if present."""
    return username.lstrip("@")


def normalize_username(username: str) -> str:
    """Strip whitespace and leading @, and reject empty usernames."""
    normalized = strip_at(username.strip())
    if not normalized:
        raise InputError("Username cannot be empty.")
    return normalized
