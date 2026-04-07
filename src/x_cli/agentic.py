"""Agent-facing CLI metadata and diagnostic payload helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .auth import REQUIRED_ENV_VARS, CredentialStatus

AuthMode = Literal["none", "bearer", "oauth1"]
AccessMode = Literal["introspect", "read", "write"]


@dataclass(frozen=True, slots=True)
class CapabilityArgument:
    """Structured argument metadata for a CLI command."""

    name        : str
    description : str
    metavar     : str
    required    : bool = True


@dataclass(frozen=True, slots=True)
class CapabilityOption:
    """Structured option metadata for a CLI command."""

    flags        : tuple[str, ...]
    description  : str
    value_name   : str | None = None
    default      : str | int | bool | None = None
    required     : bool = False
    takes_value  : bool = True


@dataclass(frozen=True, slots=True)
class CommandGroup:
    """Structured metadata for a command group."""

    path        : tuple[str, ...]
    summary     : str
    description : str
    examples    : tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommandCapability:
    """Structured metadata for a concrete CLI command."""

    path         : tuple[str, ...]
    summary      : str
    description  : str
    auth         : AuthMode
    access       : AccessMode
    arguments    : tuple[CapabilityArgument, ...] = ()
    options      : tuple[CapabilityOption, ...] = ()
    examples     : tuple[str, ...] = ()
    notes        : tuple[str, ...] = ()
    side_effects : tuple[str, ...] = ()

    @property
    def command_name(self) -> str:
        """Return the full CLI command path."""
        return " ".join(self.path)


AUTH_MODEL = {
    "oauth2_supported" : False,
    "read_default"     : "bearer",
    "write_default"    : "oauth1",
    "agent_profile"    : "headless single-account automation",
}

GLOBAL_OPTIONS: tuple[CapabilityOption, ...] = (
    CapabilityOption(
        flags=("--json", "-j"),
        description="Render command output as JSON. Place before the command name.",
        takes_value=False,
    ),
    CapabilityOption(
        flags=("--plain", "-p"),
        description="Render command output as TSV/plain text. Place before the command name.",
        takes_value=False,
    ),
    CapabilityOption(
        flags=("--markdown", "-md"),
        description="Render command output as Markdown. Place before the command name.",
        takes_value=False,
    ),
    CapabilityOption(
        flags=("--verbose", "-v"),
        description="Include extra fields and metadata in output. Place before the command name.",
        takes_value=False,
    ),
)


GROUPS: tuple[CommandGroup, ...] = (
    CommandGroup(
        path=(),
        summary="Top-level x-cli commands.",
        description=(
            "Inspect capabilities, run diagnostics, and execute X API commands with "
            "Bearer reads and OAuth 1.0a writes."
        ),
        examples=(
            "x-cli --json capabilities",
            "x-cli --json doctor",
            "x-cli whoami",
        ),
    ),
    CommandGroup(
        path=("tweet",),
        summary="Read, create, and manage posts.",
        description=(
            "Use read-only bearer auth for public lookups and OAuth 1.0a for "
            "authenticated post actions."
        ),
        examples=(
            "x-cli tweet post 'hello world'",
            "x-cli tweet get 1234567890",
            "x-cli tweet search 'from:openai lang:en'",
        ),
    ),
    CommandGroup(
        path=("user",),
        summary="Read public user profiles and timelines.",
        description="These commands resolve usernames and query public user endpoints.",
        examples=(
            "x-cli user get openai",
            "x-cli user timeline openai --max 20",
        ),
    ),
    CommandGroup(
        path=("me",),
        summary="Read and manage authenticated-user resources.",
        description=(
            "These commands use OAuth 1.0a user context for mentions, bookmarks, and "
            "other account-scoped actions."
        ),
        examples=(
            "x-cli me mentions --max 20",
            "x-cli me bookmark 1234567890",
        ),
    ),
    CommandGroup(
        path=("auth",),
        summary="Inspect local authentication state.",
        description=(
            "Use these commands to verify credential presence and auth mode without "
            "printing secrets."
        ),
        examples=("x-cli --json auth status",),
    ),
)


CAPABILITIES: tuple[CommandCapability, ...] = (
    CommandCapability(
        path=("capabilities",),
        summary="Describe the CLI command surface in machine-readable form.",
        description=(
            "Emit grouped command metadata, auth requirements, argument semantics, and "
            "examples for agent discovery."
        ),
        auth="none",
        access="introspect",
        examples=("x-cli --json capabilities",),
    ),
    CommandCapability(
        path=("doctor",),
        summary="Run local and optional API health checks.",
        description=(
            "Verify credential presence, auth policy, and optionally the authenticated "
            "user endpoint."
        ),
        auth="none",
        access="introspect",
        options=(
            CapabilityOption(
                flags=("--api",),
                description="Also call /2/users/me with OAuth 1.0a.",
                takes_value=False,
            ),
        ),
        examples=(
            "x-cli doctor",
            "x-cli --json doctor --api",
        ),
    ),
    CommandCapability(
        path=("auth", "status"),
        summary="Inspect local credential presence and auth policy.",
        description=(
            "Report which required environment variables are present and which config "
            "files are available."
        ),
        auth="none",
        access="introspect",
        examples=("x-cli --json auth status",),
    ),
    CommandCapability(
        path=("whoami",),
        summary="Fetch the authenticated X account profile.",
        description="Resolve the account behind the configured OAuth 1.0a credentials.",
        auth="oauth1",
        access="read",
        examples=("x-cli whoami",),
        side_effects=("Calls /2/users/me using OAuth 1.0a user context.",),
    ),
    CommandCapability(
        path=("tweet", "post"),
        summary="Create a new post.",
        description=(
            "Create a post with text and optional media or poll. Poll and media cannot "
            "be combined."
        ),
        auth="oauth1",
        access="write",
        arguments=(
            CapabilityArgument(
                name="text",
                description="Post body text.",
                metavar="TEXT",
            ),
        ),
        options=(
            CapabilityOption(
                flags=("--media",),
                description="Attach an image or video from a local path.",
                value_name="PATH",
            ),
            CapabilityOption(
                flags=("--poll",),
                description="Comma-separated poll options.",
                value_name="OPTIONS",
            ),
            CapabilityOption(
                flags=("--poll-duration",),
                description="Poll duration in minutes.",
                value_name="MINUTES",
                default=1440,
            ),
        ),
        examples=(
            "x-cli tweet post 'hello world'",
            "x-cli tweet post 'Which one?' --poll 'Yes,No' --poll-duration 60",
        ),
        notes=(
            "Poll posts cannot include media attachments.",
            "Quote posts use `tweet quote`, not `tweet post`.",
        ),
        side_effects=("Creates a post on the authenticated account.",),
    ),
    CommandCapability(
        path=("tweet", "get"),
        summary="Fetch a post by ID or URL.",
        description="Accept either a numeric tweet ID or a full x.com/twitter.com status URL.",
        auth="bearer",
        access="read",
        arguments=(
            CapabilityArgument(
                name="id_or_url",
                description="Tweet ID or status URL to resolve.",
                metavar="TWEET_ID_OR_URL",
            ),
        ),
        examples=(
            "x-cli tweet get 1234567890",
            "x-cli tweet get https://x.com/user/status/1234567890",
        ),
    ),
    CommandCapability(
        path=("tweet", "delete"),
        summary="Delete one of your posts.",
        description="Delete a post owned by the authenticated account.",
        auth="oauth1",
        access="write",
        arguments=(
            CapabilityArgument(
                name="id_or_url",
                description="Tweet ID or status URL to delete.",
                metavar="TWEET_ID_OR_URL",
            ),
        ),
        examples=("x-cli tweet delete 1234567890",),
        side_effects=("Deletes a post from the authenticated account.",),
    ),
    CommandCapability(
        path=("tweet", "reply"),
        summary="Reply to a post.",
        description="Reply with text and optional media to an existing post.",
        auth="oauth1",
        access="write",
        arguments=(
            CapabilityArgument(
                name="id_or_url",
                description="Tweet ID or status URL to reply to.",
                metavar="TWEET_ID_OR_URL",
            ),
            CapabilityArgument(
                name="text",
                description="Reply text.",
                metavar="TEXT",
            ),
        ),
        options=(
            CapabilityOption(
                flags=("--media",),
                description="Attach an image or video from a local path.",
                value_name="PATH",
            ),
        ),
        examples=("x-cli tweet reply 1234567890 'Thanks for sharing this.'",),
        side_effects=("Creates a reply from the authenticated account.",),
    ),
    CommandCapability(
        path=("tweet", "quote"),
        summary="Quote a post.",
        description="Create a quote post with commentary and a referenced post ID or URL.",
        auth="oauth1",
        access="write",
        arguments=(
            CapabilityArgument(
                name="id_or_url",
                description="Tweet ID or status URL to quote.",
                metavar="TWEET_ID_OR_URL",
            ),
            CapabilityArgument(
                name="text",
                description="Quote post text.",
                metavar="TEXT",
            ),
        ),
        examples=("x-cli tweet quote 1234567890 'Context for this thread.'",),
        notes=("Quote posts cannot include media attachments.",),
        side_effects=("Creates a quote post from the authenticated account.",),
    ),
    CommandCapability(
        path=("tweet", "search"),
        summary="Search recent public posts.",
        description="Search recent posts using the X API recent search endpoint.",
        auth="bearer",
        access="read",
        arguments=(
            CapabilityArgument(
                name="query",
                description="Recent search query string.",
                metavar="QUERY",
            ),
        ),
        options=(
            CapabilityOption(
                flags=("--max",),
                description="Maximum number of search results.",
                value_name="COUNT",
                default=10,
            ),
        ),
        examples=("x-cli tweet search 'from:openai has:links' --max 20",),
    ),
    CommandCapability(
        path=("tweet", "metrics"),
        summary="Fetch detailed metrics for one of your posts.",
        description="Return public and non-public metrics for a specific post.",
        auth="oauth1",
        access="read",
        arguments=(
            CapabilityArgument(
                name="id_or_url",
                description="Tweet ID or status URL to inspect.",
                metavar="TWEET_ID_OR_URL",
            ),
        ),
        examples=("x-cli tweet metrics 1234567890",),
    ),
    CommandCapability(
        path=("user", "get"),
        summary="Look up a public user profile.",
        description="Resolve a username with or without the leading @ sign.",
        auth="bearer",
        access="read",
        arguments=(
            CapabilityArgument(
                name="username",
                description="Target username.",
                metavar="USERNAME",
            ),
        ),
        examples=("x-cli user get openai",),
    ),
    CommandCapability(
        path=("user", "timeline"),
        summary="Fetch a user's recent posts.",
        description="Resolve a username, then fetch the user's timeline.",
        auth="bearer",
        access="read",
        arguments=(
            CapabilityArgument(
                name="username",
                description="Target username.",
                metavar="USERNAME",
            ),
        ),
        options=(
            CapabilityOption(
                flags=("--max",),
                description="Maximum timeline results.",
                value_name="COUNT",
                default=10,
            ),
        ),
        examples=("x-cli user timeline openai --max 20",),
    ),
    CommandCapability(
        path=("user", "followers"),
        summary="List a user's followers.",
        description="Resolve a username, then list follower profiles.",
        auth="bearer",
        access="read",
        arguments=(
            CapabilityArgument(
                name="username",
                description="Target username.",
                metavar="USERNAME",
            ),
        ),
        options=(
            CapabilityOption(
                flags=("--max",),
                description="Maximum follower results.",
                value_name="COUNT",
                default=100,
            ),
        ),
        examples=("x-cli user followers openai --max 200",),
    ),
    CommandCapability(
        path=("user", "following"),
        summary="List accounts a user follows.",
        description="Resolve a username, then list followed profiles.",
        auth="bearer",
        access="read",
        arguments=(
            CapabilityArgument(
                name="username",
                description="Target username.",
                metavar="USERNAME",
            ),
        ),
        options=(
            CapabilityOption(
                flags=("--max",),
                description="Maximum followed-account results.",
                value_name="COUNT",
                default=100,
            ),
        ),
        examples=("x-cli user following openai --max 200",),
    ),
    CommandCapability(
        path=("me", "mentions"),
        summary="Fetch mentions for the authenticated account.",
        description="Use OAuth 1.0a user context to fetch recent mentions.",
        auth="oauth1",
        access="read",
        options=(
            CapabilityOption(
                flags=("--max",),
                description="Maximum mention results.",
                value_name="COUNT",
                default=10,
            ),
        ),
        examples=("x-cli me mentions --max 20",),
    ),
    CommandCapability(
        path=("me", "bookmarks"),
        summary="Fetch bookmarks for the authenticated account.",
        description="Use OAuth 1.0a user context to fetch the bookmark timeline.",
        auth="oauth1",
        access="read",
        options=(
            CapabilityOption(
                flags=("--max",),
                description="Maximum bookmark results.",
                value_name="COUNT",
                default=10,
            ),
        ),
        examples=("x-cli me bookmarks --max 20",),
    ),
    CommandCapability(
        path=("me", "bookmark"),
        summary="Add a post to bookmarks.",
        description="Bookmark a post for the authenticated account.",
        auth="oauth1",
        access="write",
        arguments=(
            CapabilityArgument(
                name="id_or_url",
                description="Tweet ID or status URL to bookmark.",
                metavar="TWEET_ID_OR_URL",
            ),
        ),
        examples=("x-cli me bookmark 1234567890",),
        side_effects=("Adds the post to the authenticated account's bookmarks.",),
    ),
    CommandCapability(
        path=("me", "unbookmark"),
        summary="Remove a post from bookmarks.",
        description="Remove a bookmarked post for the authenticated account.",
        auth="oauth1",
        access="write",
        arguments=(
            CapabilityArgument(
                name="id_or_url",
                description="Tweet ID or status URL to remove.",
                metavar="TWEET_ID_OR_URL",
            ),
        ),
        examples=("x-cli me unbookmark 1234567890",),
        side_effects=("Removes the post from the authenticated account's bookmarks.",),
    ),
    CommandCapability(
        path=("like",),
        summary="Like a post.",
        description="Like a post as the authenticated account.",
        auth="oauth1",
        access="write",
        arguments=(
            CapabilityArgument(
                name="id_or_url",
                description="Tweet ID or status URL to like.",
                metavar="TWEET_ID_OR_URL",
            ),
        ),
        examples=("x-cli like 1234567890",),
        side_effects=("Likes the post as the authenticated account.",),
    ),
    CommandCapability(
        path=("retweet",),
        summary="Retweet a post.",
        description="Retweet a post as the authenticated account.",
        auth="oauth1",
        access="write",
        arguments=(
            CapabilityArgument(
                name="id_or_url",
                description="Tweet ID or status URL to retweet.",
                metavar="TWEET_ID_OR_URL",
            ),
        ),
        examples=("x-cli retweet 1234567890",),
        side_effects=("Retweets the post as the authenticated account.",),
    ),
)

_GROUP_INDEX = {group.path: group for group in GROUPS}
_CAPABILITY_INDEX = {capability.path: capability for capability in CAPABILITIES}


def group_epilog(*path: str) -> str:
    """Build a compact help epilog for a command group."""
    group = _GROUP_INDEX.get(tuple(path))
    if group is None or not group.examples:
        return ""
    examples = "\n".join(f"  {example}" for example in group.examples)
    return f"\b\nExamples:\n{examples}"


def command_epilog(*path: str) -> str:
    """Build a compact help epilog for a concrete command."""
    capability = _CAPABILITY_INDEX.get(tuple(path))
    if capability is None:
        return ""

    lines: list[str] = []
    if capability.examples:
        lines.append("Examples:")
        lines.extend(f"  {example}" for example in capability.examples)
    lines.append(f"Auth: {capability.auth}")
    lines.append(f"Access: {capability.access}")
    if capability.side_effects:
        lines.append(f"Side effects: {' '.join(capability.side_effects)}")
    if capability.notes:
        lines.append(f"Notes: {' '.join(capability.notes)}")
    return "\b\n" + "\n".join(lines)


def capabilities_payload() -> dict[str, object]:
    """Return the CLI capability registry as a serializable payload."""
    return {
        "tool"          : "x-cli",
        "auth_model"    : AUTH_MODEL,
        "global_options": [asdict(option) for option in GLOBAL_OPTIONS],
        "groups"        : [_group_payload(group) for group in GROUPS if group.path],
        "commands"      : [_capability_payload(capability) for capability in CAPABILITIES],
    }


def auth_status_payload(status: CredentialStatus) -> dict[str, object]:
    """Build a serializable auth status payload from local credential inspection."""
    return {
        "tool"      : "x-cli",
        "auth_model": AUTH_MODEL,
        "credentials": _credential_payload(status),
        "sources"    : _source_payload(status),
    }


def doctor_payload(
    status: CredentialStatus,
    *,
    api_check: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a diagnostic payload for agent preflight checks."""
    checks = [
        {
            "name"  : "credentials_present",
            "ok"    : status.ok,
            "detail": (
                "All required credential variables are present."
                if status.ok
                else f"Missing required credentials: {', '.join(status.missing)}."
            ),
        }
    ]
    if api_check is not None:
        checks.append(api_check)

    return {
        "tool"      : "x-cli",
        "auth_model": AUTH_MODEL,
        "checks"    : checks,
        "credentials": _credential_payload(status),
        "sources"   : _source_payload(status),
    }


def _credential_payload(status: CredentialStatus) -> dict[str, object]:
    """Return the credential-presence portion of a diagnostic payload."""
    return {
        "required"            : list(REQUIRED_ENV_VARS),
        "present"             : list(status.present),
        "missing"             : list(status.missing),
        "all_required_present": status.ok,
    }


def _source_payload(status: CredentialStatus) -> dict[str, object]:
    """Return the credential source portion of a diagnostic payload."""
    return {
        "config_env_path"  : str(status.config_env_path),
        "config_env_exists": status.config_env_exists,
        "cwd_env_path"     : str(status.cwd_env_path),
        "cwd_env_exists"   : status.cwd_env_exists,
    }


def _group_payload(group: CommandGroup) -> dict[str, object]:
    """Serialize a command group for machine-readable output."""
    payload = asdict(group)
    payload["command"] = " ".join(group.path)
    return payload


def _capability_payload(capability: CommandCapability) -> dict[str, object]:
    """Serialize a command capability for machine-readable output."""
    payload = asdict(capability)
    payload["command"] = capability.command_name
    return payload
