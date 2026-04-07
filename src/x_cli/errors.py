"""Shared exception types for predictable x-cli error handling."""

from __future__ import annotations


class XCliError(Exception):
    """Base class for expected x-cli failures that should be shown to users."""


class ConfigurationError(XCliError):
    """Raised when local CLI configuration is missing or invalid."""


class InputError(XCliError, ValueError):
    """Raised when a command receives invalid user input."""


class ApiError(XCliError, RuntimeError):
    """Raised when X API requests fail or return unexpected payloads."""
