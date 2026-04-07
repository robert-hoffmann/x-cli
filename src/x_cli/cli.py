"""Click CLI entry point for x-cli."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click  # CLI framework

from .api import XApiClient
from .auth import load_credentials
from .errors import ApiError, XCliError
from .formatters import format_output
from .utils import normalize_username, parse_tweet_id

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


@click.group()
@click.option("--json", "-j", "fmt", flag_value="json", help="JSON output")
@click.option("--plain", "-p", "fmt", flag_value="plain", help="TSV output for piping")
@click.option("--markdown", "-md", "fmt", flag_value="markdown", help="Markdown output")
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Verbose output (show metrics, timestamps, metadata)",
)
@click.pass_context
def cli(ctx, fmt, verbose):
    """x-cli: CLI for X/Twitter API v2."""
    ctx.ensure_object(dict)
    ctx.obj = State(fmt or "human", verbose=verbose)
    ctx.call_on_close(ctx.obj.close)


# endregion CLI Group


# region Tweet Commands
# ============================================================================
# Tweet Commands
# ============================================================================


@cli.group()
def tweet():
    """Tweet operations."""


@tweet.command("post")
@click.argument("text")
@click.option(
    "--media",
    "media_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Path to image or video file to attach",
)
@click.option("--poll", default=None, help="Comma-separated poll options")
@click.option(
    "--poll-duration",
    default=1440,
    type=click.IntRange(min=5, max=10080),
    help="Poll duration in minutes",
)
@pass_state
def tweet_post(state, text, media_path, poll, poll_duration):
    """Post a tweet, optionally with an image or video attachment."""
    poll_options = _parse_poll_options(poll)
    if poll_options and media_path is not None:
        raise click.ClickException("Poll posts cannot include media attachments.")

    media_ids = _resolve_media_ids(state.client, media_path)
    data = state.client.post_tweet(
        text, poll_options=poll_options, poll_duration_minutes=poll_duration, media_ids=media_ids
    )
    state.output(data, "Posted")


@tweet.command("get")
@click.argument("id_or_url")
@pass_state
def tweet_get(state, id_or_url):
    """Fetch a tweet by ID or URL."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.get_tweet(tid)
    state.output(data, f"Tweet {tid}")


@tweet.command("delete")
@click.argument("id_or_url")
@pass_state
def tweet_delete(state, id_or_url):
    """Delete a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.delete_tweet(tid)
    state.output(data, "Deleted")


@tweet.command("reply")
@click.argument("id_or_url")
@click.argument("text")
@click.option(
    "--media",
    "media_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Path to image or video file to attach",
)
@pass_state
def tweet_reply(state, id_or_url, text, media_path):
    """Reply to a tweet."""
    tid = parse_tweet_id(id_or_url)
    media_ids = _resolve_media_ids(state.client, media_path)
    data = state.client.post_tweet(text, reply_to=tid, media_ids=media_ids)
    state.output(data, "Reply")


@tweet.command("quote")
@click.argument("id_or_url")
@click.argument("text")
@click.option(
    "--media",
    "media_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Path to image or video file to attach",
)
@pass_state
def tweet_quote(state, id_or_url, text, media_path):
    """Quote tweet."""
    if media_path is not None:
        raise click.ClickException("Quote posts cannot include media attachments.")

    tid = parse_tweet_id(id_or_url)
    data = state.client.post_tweet(text, quote_tweet_id=tid)
    state.output(data, "Quote")


@tweet.command("search")
@click.argument("query")
@click.option(
    "--max",
    "max_results",
    default=10,
    type=click.IntRange(min=10, max=100),
    help="Max results (10-100)",
)
@pass_state
def tweet_search(state, query, max_results):
    """Search recent tweets."""
    data = state.client.search_tweets(query, max_results)
    state.output(data, f"Search: {query}")


@tweet.command("metrics")
@click.argument("id_or_url")
@pass_state
def tweet_metrics(state, id_or_url):
    """Get tweet engagement metrics."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.get_tweet_metrics(tid)
    state.output(data, f"Metrics {tid}")


# endregion Tweet Commands


# region User Commands
# ============================================================================
# User Commands
# ============================================================================


@cli.group()
def user():
    """User operations."""


@user.command("get")
@click.argument("username")
@pass_state
def user_get(state, username):
    """Look up a user profile."""
    normalized_username = normalize_username(username)
    data = state.client.get_user(normalized_username)
    state.output(data, f"@{normalized_username}")


@user.command("timeline")
@click.argument("username")
@click.option(
    "--max",
    "max_results",
    default=10,
    type=click.IntRange(min=5, max=100),
    help="Max results (5-100)",
)
@pass_state
def user_timeline(state, username, max_results):
    """Fetch a user's recent tweets."""
    uname = normalize_username(username)
    user_data = state.client.get_user(uname)
    uid = _extract_user_id(user_data, uname)
    data = state.client.get_timeline(uid, max_results)
    state.output(data, f"@{uname} timeline")


@user.command("followers")
@click.argument("username")
@click.option(
    "--max",
    "max_results",
    default=100,
    type=click.IntRange(min=1, max=1000),
    help="Max results (1-1000)",
)
@pass_state
def user_followers(state, username, max_results):
    """List a user's followers."""
    uname = normalize_username(username)
    user_data = state.client.get_user(uname)
    uid = _extract_user_id(user_data, uname)
    data = state.client.get_followers(uid, max_results)
    state.output(data, f"@{uname} followers")


@user.command("following")
@click.argument("username")
@click.option(
    "--max",
    "max_results",
    default=100,
    type=click.IntRange(min=1, max=1000),
    help="Max results (1-1000)",
)
@pass_state
def user_following(state, username, max_results):
    """List who a user follows."""
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


@cli.group()
def me():
    """Self operations (authenticated user)."""


@me.command("mentions")
@click.option(
    "--max",
    "max_results",
    default=10,
    type=click.IntRange(min=5, max=100),
    help="Max results (5-100)",
)
@pass_state
def me_mentions(state, max_results):
    """Fetch your recent mentions."""
    data = state.client.get_mentions(max_results)
    state.output(data, "Mentions")


@me.command("bookmarks")
@click.option(
    "--max",
    "max_results",
    default=10,
    type=click.IntRange(min=1, max=100),
    help="Max results (1-100)",
)
@pass_state
def me_bookmarks(state, max_results):
    """Fetch your bookmarks."""
    data = state.client.get_bookmarks(max_results)
    state.output(data, "Bookmarks")


@me.command("bookmark")
@click.argument("id_or_url")
@pass_state
def me_bookmark(state, id_or_url):
    """Bookmark a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.bookmark_tweet(tid)
    state.output(data, "Bookmarked")


@me.command("unbookmark")
@click.argument("id_or_url")
@pass_state
def me_unbookmark(state, id_or_url):
    """Remove a bookmark."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.unbookmark_tweet(tid)
    state.output(data, "Unbookmarked")


# endregion Me Commands


# region Quick Actions
# ============================================================================
# Quick Actions (Top-Level)
# ============================================================================


@cli.command("like")
@click.argument("id_or_url")
@pass_state
def like(state, id_or_url):
    """Like a tweet."""
    tid = parse_tweet_id(id_or_url)
    data = state.client.like_tweet(tid)
    state.output(data, "Liked")


@cli.command("retweet")
@click.argument("id_or_url")
@pass_state
def retweet(state, id_or_url):
    """Retweet a tweet."""
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
