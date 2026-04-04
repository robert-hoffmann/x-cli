<!-- #region Overview -->
# LLMs.md -- Guide for AI Agents

You are an AI agent working with the x-cli codebase. This file tells you where everything is and how it fits together.

## What This Is

x-cli is a Python CLI that talks directly to the Twitter/X API v2. It uses OAuth 1.0a for write operations and Bearer token auth for read operations. Media uploads use the legacy v1.1 upload endpoint because that is still the required path for media attachments.

It shares the same credentials as x-mcp, the MCP server counterpart. If a user already has x-mcp configured, they can symlink its `.env` to `~/.config/x-cli/.env`.
<!-- #endregion Overview -->

<!-- #region Structure -->
## Project Structure

```text
src/x_cli/
    cli.py          -- Click command groups and entry point
    api.py          -- XApiClient: one method per Twitter/X endpoint
    auth.py         -- Credential loading and OAuth 1.0a HMAC-SHA1 signing
    formatters.py   -- Human, JSON, TSV, and Markdown output modes
    utils.py        -- Tweet ID parsing from URLs and username cleanup
tests/
    test_auth.py
    test_formatters.py
    test_media.py
    test_utils.py
```
<!-- #endregion Structure -->

<!-- #region CodebaseMap -->
## Codebase Map

### `cli.py` -- start here

The entry point. Defines Click command groups: `tweet`, `user`, `me`, plus top-level `like` and `retweet`. Every command follows the same pattern: parse args, call the API client, pass the response to a formatter.

The `State` object holds the output mode (`human`/`json`/`plain`/`markdown`) and verbose flag, and lazily initializes the API client. It is passed via Click's context system with `@pass_state`.

Global flags: `-j` or `--json`, `-p` or `--plain`, `-md` or `--markdown`, and `-v` or `--verbose`. Default output is compact human-readable rich output.

`_resolve_media_ids()` is the shared helper for `tweet post`, `tweet reply`, and `tweet quote`. It uploads one file, prints progress to stderr, and returns a single-element `media_ids` list for `post_tweet()`.

### `api.py` -- API client

`XApiClient` wraps all Twitter/X API operations. Key patterns:

- Read-only endpoints such as `get_tweet`, `search_tweets`, `get_user`, `get_timeline`, `get_followers`, and `get_following` use Bearer token auth.
- Write endpoints such as `post_tweet`, `delete_tweet`, `like_tweet`, `retweet`, and bookmark operations use OAuth 1.0a via `_oauth_request()`.
- Media upload uses `upload.twitter.com/1.1/media/upload.json`. Small images use a simple multipart POST. Videos and files larger than 1 MB use INIT, APPEND, FINALIZE, and STATUS polling automatically.
- Video uploads are always chunked, even when the file is tiny.
- Chunked APPEND requests send 4 MB segments.
- `upload_media(path)` expands `~`, verifies the file exists, chooses the correct flow, and returns a `media_id_string` for `post_tweet(media_ids=)`.
- `get_authenticated_user_id()` resolves and caches the current user's numeric ID for endpoints that require it.

All methods return raw parsed JSON as `dict`. Error handling is centralized in `_handle()`, which raises `RuntimeError` on non-2xx responses and rate limits.

### `auth.py` -- OAuth signing

Two responsibilities:

1. `load_credentials()` loads five env vars with `.env` fallback from `~/.config/x-cli/.env` and the current directory.
2. `generate_oauth_header()` builds an OAuth 1.0a `Authorization` header using HMAC-SHA1.

Query parameters from the URL are included in the signature base string when required by the OAuth spec.

### `formatters.py` -- Output

Four modes route through `format_output(data, mode, title, verbose)`:

- `human` renders rich panels and tables.
- `json` emits compact data by default and the full payload in verbose mode.
- `plain` emits TSV for shell pipelines.
- `markdown` emits Markdown headings and tables.

Hints and progress output go to stderr so stdout stays safe for piping.

### `utils.py` -- Helpers

- `parse_tweet_id(input)` extracts a numeric tweet ID from an `x.com` or `twitter.com` URL, or validates a raw numeric string.
- `strip_at(username)` removes a leading `@` when present.
<!-- #endregion CodebaseMap -->

<!-- #region Commands -->
## Command Reference

### Tweet commands (`x-cli tweet <action>`)

- `post`: args `TEXT`; flags `--media PATH`, `--poll OPTIONS`, `--poll-duration MINS`; API path `upload_media()` + `post_tweet()`
- `get`: args `ID_OR_URL`; API path `get_tweet()`
- `delete`: args `ID_OR_URL`; API path `delete_tweet()`
- `reply`: args `ID_OR_URL TEXT`; flags `--media PATH`; API path `upload_media()` + `post_tweet(reply_to=)`
- `quote`: args `ID_OR_URL TEXT`; flags `--media PATH`; API path `upload_media()` + `post_tweet(quote_tweet_id=)`
- `search`: args `QUERY`; flags `--max N`; API path `search_tweets()`
- `metrics`: args `ID_OR_URL`; API path `get_tweet_metrics()`

### User commands (`x-cli user <action>`)

- `get`: args `USERNAME`; API path `get_user()`
- `timeline`: args `USERNAME`; flags `--max N`; API path `get_user()` then `get_timeline()`
- `followers`: args `USERNAME`; flags `--max N`; API path `get_user()` then `get_followers()`
- `following`: args `USERNAME`; flags `--max N`; API path `get_user()` then `get_following()`

`timeline`, `followers`, and `following` resolve a username to a numeric ID automatically before calling the timeline-style endpoint.

### Self commands (`x-cli me <action>`)

- `mentions`: flags `--max N`; API path `get_mentions()`
- `bookmarks`: flags `--max N`; API path `get_bookmarks()`
- `bookmark`: args `ID_OR_URL`; API path `bookmark_tweet()`
- `unbookmark`: args `ID_OR_URL`; API path `unbookmark_tweet()`

### Top-level commands

- `like`: args `ID_OR_URL`; API path `like_tweet()`
- `retweet`: args `ID_OR_URL`; API path `retweet()`
<!-- #endregion Commands -->

<!-- #region Patterns -->
## Common Patterns

### Adding a new API endpoint

1. Add the method to `XApiClient` in `api.py`.
2. Add a Click command in `cli.py` that calls it.
3. Let `formatters.py` handle the response unless the payload needs a new presentation rule.

### User commands that need a numeric ID

The API requires numeric user IDs for timeline, followers, and following endpoints. The CLI resolves usernames to IDs automatically before making those calls.

### Search query syntax

`search_tweets()` accepts X query operators such as `from:user`, `to:user`, `#hashtag`, `"exact phrase"`, `has:media`, `is:reply`, `-is:retweet`, and `lang:en`.
<!-- #endregion Patterns -->

<!-- #region Testing -->
## Testing

```bash
uv run pytest tests/ -v
```

Tests cover auth, formatters, tweet ID utilities, and the full mocked media-upload flow in `tests/test_media.py`. There are no live API calls in the test suite.
<!-- #endregion Testing -->

<!-- #region Troubleshooting -->
## Troubleshooting

- `403 oauth1-permissions`: Access Token is read-only. Enable `Read and write`, then regenerate the Access Token.
- `401 Unauthorized`: credentials are bad or stale. Verify all five values in `.env`.
- `429 Rate Limited`: too many requests. Wait until the reset timestamp returned by the API.
- `Media file not found`: the `--media` path does not exist. Fix the path before retrying.
- `RuntimeError: API error`: X returned an application error. Inspect the detail for permissions, invalid IDs, or payload issues.
- `Media processing timed out`: video processing never completed. Retry with a smaller or simpler video file.
<!-- #endregion Troubleshooting -->
