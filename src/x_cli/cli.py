"""Click CLI entry point for x-cli."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click  # CLI framework

from .agentic import (
    auth_status_payload,
    capabilities_payload,
    command_epilog,
    doctor_payload,
    group_epilog,
)
from .api import XApiClient
from .auth import inspect_credentials, load_credentials
from .errors import ApiError, XCliError
from .formatters import format_output
from .utils import normalize_username, parse_tweet_id

# region Constants
# ============================================================================
# Constants
# ============================================================================

CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "max_content_width": 100,
}

# endregion Constants


# region Helpers
# ============================================================================
# Helpers
# ============================================================================


def _parse_poll_options(poll: str | None) -> list[str] | None:
    """Parse a comma-separated poll string into individual options."""
    if poll is None:
        return None

    options = [option.strip() for option in poll.split(",")]
    if any(not option for option in options):
        raise click.ClickException("Poll options cannot be empty.")
    return options


def _extract_user_id(user_data: dict[str, Any], username: str) -> str:
    """Extract a user ID from a user lookup response."""
    payload = user_data.get("data")
    if isinstance(payload, dict):
        user_id = payload.get("id")
        if isinstance(user_id, str) and user_id:
            return user_id
    raise ApiError(f"X API returned no user id for @{username}.")


def _resolve_media_ids(client: XApiClient, media_path: Path | None) -> list[str] | None:
    """Upload a media file and return a single-element media_ids list, or None."""
    if not media_path:
        return None
    click.echo(f"Uploading {media_path}...", err=True)
    media_id = client.upload_media(media_path)
    click.echo(f"Upload complete (media_id={media_id})", err=True)
    return [media_id]


def _show_click_exception(err: click.ClickException) -> None:
    """Render a Click exception and exit with its status code."""
    err.show()
    raise SystemExit(err.exit_code) from err


def _doctor_api_check(state: State, can_authenticate: bool) -> dict[str, object]:
    """Optionally run a lightweight authenticated-user API check."""
    if not can_authenticate:
        return {
            "name"  : "authenticated_user_lookup",
            "ok"    : False,
            "detail": "Skipped because required credentials are missing.",
        }

    try:
        user_data = state.client.get_authenticated_user()
    except XCliError as err:
        return {
            "name"  : "authenticated_user_lookup",
            "ok"    : False,
            "detail": str(err),
        }

    payload = user_data.get("data")
    username = ""
    user_id = ""
    if isinstance(payload, dict):
        username = str(payload.get("username") or "")
        user_id = str(payload.get("id") or "")

    account_label = f"@{username}" if username else "configured account"
    detail = f"Authenticated as {account_label}."
    if user_id:
        detail = f"{detail} user_id={user_id}"

    return {
        "name"  : "authenticated_user_lookup",
        "ok"    : True,
        "detail": detail,
        "user"  : payload if isinstance(payload, dict) else {},
    }


# endregion Helpers


# region State
# ============================================================================
# CLI State
# ============================================================================


class State:
    """Shared CLI state carrying output mode and a lazily-initialized API client."""

    def __init__(self, mode: str, verbose: bool = False) -> None:
        self.mode = mode
        self.verbose = verbose
        self._client: XApiClient | None = None

    @property
    def client(self) -> XApiClient:
        """Lazily create and cache the API client on first access."""
        if self._client is None:
            creds = load_credentials()
            self._client = XApiClient(creds)
        return self._client

    def close(self) -> None:
        """Close the lazily-created API client when the command exits."""
        if self._client is not None:
            self._client.close()

    def output(self, data: Any, title: str = "") -> None:
        """Route data through the configured formatter."""
        format_output(data, self.mode, title, verbose=self.verbose)


pass_state = click.make_pass_decorator(State)


# endregion State


# region CLI Group
# ============================================================================
# CLI Group
# ============================================================================


@click.group(context_settings=CONTEXT_SETTINGS, epilog=group_epilog())
@click.option(
    "--json",
    "-j",
    "fmt",
    flag_value="json",
    help="Render output as JSON. Place global output flags before the command name.",
)
@click.option(
    "--plain",
    "-p",
    "fmt",
    flag_value="plain",
    help="Render output as TSV/plain text. Place global output flags before the command name.",
)
@click.option(
    "--markdown",
    "-md",
    "fmt",
    flag_value="markdown",
    help="Render output as Markdown. Place global output flags before the command name.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Include extra fields and metadata in output.",
)
@click.pass_context
def cli(ctx, fmt, verbose):
    """Headless X API CLI for agents, scripts, and terminal workflows.

    Use `capabilities` for machine-readable command discovery and `doctor`
    before write operations or new environments.
    """
    ctx.ensure_object(dict)
    ctx.obj = State(fmt or "human", verbose=verbose)
    ctx.call_on_close(ctx.obj.close)


@cli.command("capabilities", short_help="Describe the command surface", epilog=command_epilog("capabilities"))
@pass_state
def capabilities(state: State) -> None:
    """Emit grouped command metadata for agent discovery."""
    state.output(capabilities_payload(), "Capabilities")


@cli.command("doctor", short_help="Run local and optional API checks", epilog=command_epilog("doctor"))
@click.option(
    "--api",
    is_flag=True,
    default=False,
    help="Also call /2/users/me with OAuth 1.0a to verify authenticated access.",
)
@pass_state
def doctor(state: State, api: bool) -> None:
    """Run local diagnostics and optional authenticated API checks."""
    status = inspect_credentials()
    api_check = _doctor_api_check(state, status.ok) if api else None
    state.output(doctor_payload(status, api_check=api_check), "Doctor")


@cli.command("whoami", short_help="Fetch the authenticated profile", epilog=command_epilog("whoami"))
@pass_state
def whoami(state: State) -> None:
    """Fetch the authenticated X account profile."""
    data = state.client.get_authenticated_user()
    state.output(data, "Authenticated User")


# endregion CLI Group


# region Tweet Commands
# ============================================================================
# Tweet Commands
# ============================================================================


@cli.group(short_help="Read, create, and manage posts", epilog=group_epilog("tweet"))
def tweet():
    """Read, create, and manage posts."""


@tweet.command("post", short_help="Create a new post", epilog=command_epilog("tweet", "post"))
@click.argument("text", metavar="TEXT")
@click.option(
    "--media",
    "media_path",
    default=None,
    metavar="PATH",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Path to an image or video file to attach.",
)
@click.option("--poll", default=None, metavar="OPTIONS", help="Comma-separated poll options.")
@click.option(
    "--poll-duration",
    default=1440,
    metavar="MINUTES",
    show_default=True,
    type=click.IntRange(min=5, max=10080),
    help="Poll duration in minutes.",
)
@pass_state
def tweet_post(
    state: State,
    text: str,
    media_path: Path | None,
    poll: str | None,
    poll_duration: int,
) -> None:
    """Create a post with optional media or poll content."""
    poll_options = _parse_poll_options(poll)
    if poll_options and media_path is not None:
        raise click.ClickException("Poll posts cannot include media attachments.")

    media_ids = _resolve_media_ids(state.client, media_path)
    data = state.client.post_tweet(
        text,
        poll_options=poll_options,
        poll_duration_minutes=poll_duration,
        media_ids=media_ids,
    )
    state.output(data, "Posted")


@tweet.command("get", short_help="Fetch a post", epilog=command_epilog("tweet", "get"))
@click.argument("id_or_url", metavar="TWEET_ID_OR_URL")
@pass_state
def tweet_get(state: State, id_or_url: str) -> None:
    """Fetch a post by ID or URL."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.get_tweet(tid)
    state.output(data, f"Tweet {tid}")


@tweet.command("delete", short_help="Delete one of your posts", epilog=command_epilog("tweet", "delete"))
@click.argument("id_or_url", metavar="TWEET_ID_OR_URL")
@pass_state
def tweet_delete(state: State, id_or_url: str) -> None:
    """Delete a post owned by the authenticated account."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.delete_tweet(tid)
    state.output(data, "Deleted")


@tweet.command("reply", short_help="Reply to a post", epilog=command_epilog("tweet", "reply"))
@click.argument("id_or_url", metavar="TWEET_ID_OR_URL")
@click.argument("text", metavar="TEXT")
@click.option(
    "--media",
    "media_path",
    default=None,
    metavar="PATH",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Path to an image or video file to attach.",
)
@pass_state
def tweet_reply(state: State, id_or_url: str, text: str, media_path: Path | None) -> None:
    """Reply to a post with text and optional media."""
    tid = parse_tweet_id(id_or_url)
    media_ids = _resolve_media_ids(state.client, media_path)
    data = state.client.post_tweet(text, reply_to=tid, media_ids=media_ids)
    state.output(data, "Reply")


@tweet.command("quote", short_help="Quote a post", epilog=command_epilog("tweet", "quote"))
@click.argument("id_or_url", metavar="TWEET_ID_OR_URL")
@click.argument("text", metavar="TEXT")
@click.option(
    "--media",
    "media_path",
    default=None,
    metavar="PATH",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Reserved for future support. Quote posts currently reject media.",
)
@pass_state
def tweet_quote(state: State, id_or_url: str, text: str, media_path: Path | None) -> None:
    """Create a quote post."""
    if media_path is not None:
        raise click.ClickException("Quote posts cannot include media attachments.")

    tid = parse_tweet_id(id_or_url)
    data = state.client.post_tweet(text, quote_tweet_id=tid)
    state.output(data, "Quote")


@tweet.command("search", short_help="Search recent posts", epilog=command_epilog("tweet", "search"))
@click.argument("query", metavar="QUERY")
@click.option(
    "--max",
    "max_results",
    default=10,
    metavar="COUNT",
    show_default=True,
    type=click.IntRange(min=10, max=100),
    help="Maximum number of search results.",
)
@pass_state
def tweet_search(state: State, query: str, max_results: int) -> None:
    """Search recent public posts."""
    data = state.client.search_tweets(query, max_results)
    state.output(data, f"Search: {query}")


@tweet.command("metrics", short_help="Fetch post metrics", epilog=command_epilog("tweet", "metrics"))
@click.argument("id_or_url", metavar="TWEET_ID_OR_URL")
@pass_state
def tweet_metrics(state: State, id_or_url: str) -> None:
    """Fetch detailed metrics for a post."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.get_tweet_metrics(tid)
    state.output(data, f"Metrics {tid}")


# endregion Tweet Commands


# region User Commands
# ============================================================================
# User Commands
# ============================================================================


@cli.group(short_help="Read public user profiles", epilog=group_epilog("user"))
def user():
    """Read public user profiles and timelines."""


@user.command("get", short_help="Look up a profile", epilog=command_epilog("user", "get"))
@click.argument("username", metavar="USERNAME")
@pass_state
def user_get(state: State, username: str) -> None:
    """Look up a public user profile."""
    normalized_username = normalize_username(username)
    data = state.client.get_user(normalized_username)
    state.output(data, f"@{normalized_username}")


@user.command("timeline", short_help="Fetch a user's recent posts", epilog=command_epilog("user", "timeline"))
@click.argument("username", metavar="USERNAME")
@click.option(
    "--max",
    "max_results",
    default=10,
    metavar="COUNT",
    show_default=True,
    type=click.IntRange(min=5, max=100),
    help="Maximum number of timeline results.",
)
@pass_state
def user_timeline(state: State, username: str, max_results: int) -> None:
    """Fetch a user's recent posts."""
    uname = normalize_username(username)
    user_data = state.client.get_user(uname)
    uid = _extract_user_id(user_data, uname)
    data = state.client.get_timeline(uid, max_results)
    state.output(data, f"@{uname} timeline")


@user.command("followers", short_help="List follower profiles", epilog=command_epilog("user", "followers"))
@click.argument("username", metavar="USERNAME")
@click.option(
    "--max",
    "max_results",
    default=100,
    metavar="COUNT",
    show_default=True,
    type=click.IntRange(min=1, max=1000),
    help="Maximum number of follower results.",
)
@pass_state
def user_followers(state: State, username: str, max_results: int) -> None:
    """List a user's followers."""
    uname = normalize_username(username)
    user_data = state.client.get_user(uname)
    uid = _extract_user_id(user_data, uname)
    data = state.client.get_followers(uid, max_results)
    state.output(data, f"@{uname} followers")


@user.command("following", short_help="List followed accounts", epilog=command_epilog("user", "following"))
@click.argument("username", metavar="USERNAME")
@click.option(
    "--max",
    "max_results",
    default=100,
    metavar="COUNT",
    show_default=True,
    type=click.IntRange(min=1, max=1000),
    help="Maximum number of followed-account results.",
)
@pass_state
def user_following(state: State, username: str, max_results: int) -> None:
    """List accounts a user follows."""
    uname = normalize_username(username)
    user_data = state.client.get_user(uname)
    uid = _extract_user_id(user_data, uname)
    data = state.client.get_following(uid, max_results)
    state.output(data, f"@{uname} following")


# endregion User Commands


# region Me Commands
# ============================================================================
# Me Commands (Authenticated User)
# ============================================================================


@cli.group(short_help="Read and manage account-scoped resources", epilog=group_epilog("me"))
def me():
    """Read and manage authenticated-user resources."""


@me.command("mentions", short_help="Fetch recent mentions", epilog=command_epilog("me", "mentions"))
@click.option(
    "--max",
    "max_results",
    default=10,
    metavar="COUNT",
    show_default=True,
    type=click.IntRange(min=5, max=100),
    help="Maximum number of mention results.",
)
@pass_state
def me_mentions(state: State, max_results: int) -> None:
    """Fetch recent mentions for the authenticated account."""
    data = state.client.get_mentions(max_results)
    state.output(data, "Mentions")


@me.command("bookmarks", short_help="Fetch bookmarks", epilog=command_epilog("me", "bookmarks"))
@click.option(
    "--max",
    "max_results",
    default=10,
    metavar="COUNT",
    show_default=True,
    type=click.IntRange(min=1, max=100),
    help="Maximum number of bookmark results.",
)
@pass_state
def me_bookmarks(state: State, max_results: int) -> None:
    """Fetch bookmarks for the authenticated account."""
    data = state.client.get_bookmarks(max_results)
    state.output(data, "Bookmarks")


@me.command("bookmark", short_help="Add a bookmark", epilog=command_epilog("me", "bookmark"))
@click.argument("id_or_url", metavar="TWEET_ID_OR_URL")
@pass_state
def me_bookmark(state: State, id_or_url: str) -> None:
    """Bookmark a post."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.bookmark_tweet(tid)
    state.output(data, "Bookmarked")


@me.command("unbookmark", short_help="Remove a bookmark", epilog=command_epilog("me", "unbookmark"))
@click.argument("id_or_url", metavar="TWEET_ID_OR_URL")
@pass_state
def me_unbookmark(state: State, id_or_url: str) -> None:
    """Remove a bookmark."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.unbookmark_tweet(tid)
    state.output(data, "Unbookmarked")


# endregion Me Commands


# region Auth Commands
# ============================================================================
# Auth Commands
# ============================================================================


@cli.group(short_help="Inspect local auth state", epilog=group_epilog("auth"))
def auth():
    """Inspect local authentication state."""


@auth.command("status", short_help="Report credential presence", epilog=command_epilog("auth", "status"))
@pass_state
def auth_status(state: State) -> None:
    """Report credential presence and auth policy without printing secrets."""
    state.output(auth_status_payload(inspect_credentials()), "Auth Status")


# endregion Auth Commands


# region Quick Actions
# ============================================================================
# Quick Actions (Top-Level)
# ============================================================================


@cli.command("like", short_help="Like a post", epilog=command_epilog("like"))
@click.argument("id_or_url", metavar="TWEET_ID_OR_URL")
@pass_state
def like(state: State, id_or_url: str) -> None:
    """Like a post."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.like_tweet(tid)
    state.output(data, "Liked")


@cli.command("retweet", short_help="Retweet a post", epilog=command_epilog("retweet"))
@click.argument("id_or_url", metavar="TWEET_ID_OR_URL")
@pass_state
def retweet(state: State, id_or_url: str) -> None:
    """Retweet a post."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.retweet(tid)
    state.output(data, "Retweeted")


# endregion Quick Actions


# region Entry Point
# ============================================================================
# Entry Point
# ============================================================================


def main() -> None:
    """CLI entry point."""
    try:
        cli.main(standalone_mode=False)
    except click.ClickException as err:
        _show_click_exception(err)
    except (click.Abort, EOFError, KeyboardInterrupt):
        click.echo("Aborted!", err=True)
        raise SystemExit(1) from None
    except XCliError as err:
        _show_click_exception(click.ClickException(str(err)))


if __name__ == "__main__":
    main()


# endregion Entry Point
