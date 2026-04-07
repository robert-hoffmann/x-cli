"""Twitter API v2 client with OAuth 1.0a and Bearer token auth."""

from __future__ import annotations

from collections.abc import Mapping
import mimetypes
from pathlib import Path
import time
from typing import Any
import urllib.parse

import httpx  # HTTP client

from .auth import Credentials, generate_oauth_header
from .errors import ApiError, InputError

# region Constants
# ============================================================================
# Constants
# ============================================================================

API_BASE = "https://api.x.com/2"
UPLOAD_BASE = "https://upload.twitter.com/1.1/media/upload.json"

# Chunked upload threshold: files > 1 MB use chunked flow (required for video).
_CHUNK_THRESHOLD = 1 * 1024 * 1024
_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB per APPEND segment

# MIME → media_category mapping for chunked INIT
_MEDIA_CATEGORIES: dict[str, str] = {
    "image/gif"      : "tweet_gif",
    "video/mp4"      : "tweet_video",
    "video/quicktime": "tweet_video",
    "video/webm"     : "tweet_video",
}

# endregion Constants


# region Validation Helpers
# ============================================================================
# Validation Helpers
# ============================================================================


def _media_category_for(mime_type: str) -> str:
    """Map a MIME type to the upload API's media category."""
    category = _MEDIA_CATEGORIES.get(mime_type)
    if category:
        return category
    if mime_type.startswith("video/"):
        return "tweet_video"
    return "tweet_image"


def _normalize_media_ids(media_ids: list[str] | None) -> list[str] | None:
    """Validate media IDs for tweet payloads."""
    if not media_ids:
        return None

    normalized = [media_id.strip() for media_id in media_ids]
    if any(not media_id for media_id in normalized):
        raise InputError("Media IDs cannot be empty.")
    if len(normalized) > 4:
        raise InputError("X posts support up to 4 media attachments.")
    return normalized


def _normalize_poll_options(
    poll_options          : list[str] | None,
    poll_duration_minutes : int,
) -> list[str] | None:
    """Validate poll options before sending them to the X API."""
    if not poll_options:
        return None

    normalized = [option.strip() for option in poll_options]
    if any(not option for option in normalized):
        raise InputError("Poll options cannot be empty.")
    if not 2 <= len(normalized) <= 4:
        raise InputError("Polls require between 2 and 4 options.")
    if any(len(option) > 25 for option in normalized):
        raise InputError("Poll options must be 25 characters or fewer.")
    if not 5 <= poll_duration_minutes <= 10080:
        raise InputError("Poll duration must be between 5 and 10080 minutes.")
    return normalized


# endregion Validation Helpers


# region XApiClient
# ============================================================================
# X API Client
# ============================================================================


class XApiClient:
    """High-level client wrapping Twitter API v2 and v1.1 media upload."""

    def __init__(self, creds: Credentials) -> None:
        self.creds = creds
        self._user_id             : str | None = None
        self._authenticated_user  : dict[str, Any] | None = None
        self._http                = httpx.Client(timeout=30.0)

    def close(self) -> None:
        """Shut down the underlying HTTP connection pool."""
        self._http.close()

    # region Internal Helpers
    # --------------------------------------------------------------------
    # Internal Helpers
    # --------------------------------------------------------------------

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send an HTTP request and translate transport failures."""
        try:
            sender = getattr(self._http, method.lower())
            return sender(url, **kwargs)
        except httpx.RequestError as err:
            request_url = str(err.request.url) if err.request is not None else url
            raise ApiError(f"{method.upper()} request to {request_url} failed: {err}") from err

    def _bearer_get(
        self,
        url          : str,
        query_params : Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET with Bearer token auth (read-only endpoints)."""
        resp = self._send(
            "GET",
            url,
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
            params=query_params,
        )
        return self._handle(resp)

    def _oauth_request(
        self,
        method       : str,
        url          : str,
        query_params : Mapping[str, str] | None = None,
        json_body    : dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """HTTP request with OAuth 1.0a signature (write endpoints)."""
        auth_header = generate_oauth_header(method, url, self.creds, params=dict(query_params or {}))
        headers: dict[str, str] = {"Authorization": auth_header}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self._send(
            method,
            url,
            headers=headers,
            params=query_params,
            json=json_body or None,
        )
        return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> dict[str, Any]:
        """Raise on error responses; return parsed JSON on success."""
        data: Any | None = None
        try:
            data = resp.json()
        except ValueError:
            data = None

        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset", "unknown")
            raise ApiError(f"Rate limited by X API. Resets at {reset}.")

        if not resp.is_success:
            message = self._response_error_message(resp, data)
            raise ApiError(f"X API error (HTTP {resp.status_code}): {message}")

        if data is None:
            raise ApiError(
                f"X API returned a non-JSON success response (HTTP {resp.status_code})."
            )
        if not isinstance(data, dict):
            raise ApiError("X API returned an unexpected response payload.")
        return data

    def get_authenticated_user(self) -> dict[str, Any]:
        """Return the authenticated user's profile (cached after first call)."""
        if self._authenticated_user is not None:
            return self._authenticated_user

        params = {
            "user.fields": (
                "created_at,description,location,name,profile_image_url,"
                "public_metrics,url,username,verified"
            )
        }
        data = self._oauth_request("GET", f"{API_BASE}/users/me", query_params=params)
        self._user_id = self._require_data_id(data, context="loading the authenticated user")
        self._authenticated_user = data
        return data

    def get_authenticated_user_id(self) -> str:
        """Return the authenticated user's ID (cached after first call)."""
        if self._user_id is not None:
            return self._user_id
        data = self.get_authenticated_user()
        return self._require_data_id(data, context="loading the authenticated user")

    def _response_error_message(self, resp: httpx.Response, data: Any | None) -> str:
        """Extract the clearest available error message from a response."""
        if isinstance(data, dict):
            errors = data.get("errors")
            if isinstance(errors, list):
                details = [
                    detail
                    for item in errors
                    if isinstance(item, dict)
                    for detail in [item.get("detail") or item.get("message") or item.get("title")]
                    if isinstance(detail, str) and detail
                ]
                if details:
                    return "; ".join(details)

            for key in ("detail", "message", "title"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value

        response_text = getattr(resp, "text", "")
        if isinstance(response_text, str) and response_text.strip():
            return response_text.strip()[:500]
        return "Unknown API error."

    def _require_data_id(self, data: Mapping[str, Any], context: str) -> str:
        """Extract a required `data.id` field from an API response."""
        payload = data.get("data")
        if isinstance(payload, dict):
            response_id = payload.get("id")
            if isinstance(response_id, str) and response_id:
                return response_id
        raise ApiError(f"X API returned an unexpected response while {context}.")

    # endregion Internal Helpers

    # region Media Upload
    # --------------------------------------------------------------------
    # Media Upload (v1.1 Chunked)
    # --------------------------------------------------------------------

    def _upload_oauth_header(
        self,
        method : str,
        params : dict[str, str] | None = None,
    ) -> str:
        """Build OAuth header for the v1.1 upload endpoint.

        For INIT/FINALIZE/STATUS the form-encoded params are included in the
        signature base string.  For APPEND (multipart) *no* body params are
        included — the OAuth spec excludes multipart entities.
        """
        return generate_oauth_header(method, UPLOAD_BASE, self.creds, params=params)

    def upload_media(self, file_path: str | Path) -> str:
        """Upload a media file and return its *media_id_string*.

        Uses the simple upload path for small images and the INIT / APPEND /
        FINALIZE / (STATUS) chunked flow for large files and video.
        """
        path = Path(file_path).expanduser()
        if not path.exists():
            raise InputError(f"Media file not found: {path}")
        if not path.is_file():
            raise InputError(f"Media path is not a file: {path}")

        try:
            file_size = path.stat().st_size
        except OSError as err:
            raise InputError(f"Unable to read media file metadata: {path}") from err

        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        is_video = mime_type.startswith("video/")

        # Video *must* use chunked; images may use simple if small enough.
        if is_video or file_size > _CHUNK_THRESHOLD:
            return self._chunked_upload(path, file_size, mime_type)
        return self._simple_upload(path, mime_type)

    def _simple_upload(self, path: str | Path, mime_type: str) -> str:
        """Upload a small image via the simple (non-chunked) endpoint."""
        file_path = Path(path)
        auth = self._upload_oauth_header("POST")
        try:
            with file_path.open("rb") as fh:
                files = {"media": (file_path.name, fh, mime_type)}
                resp = self._send(
                    "POST",
                    UPLOAD_BASE,
                    headers={"Authorization": auth},
                    files=files,
                )
        except OSError as err:
            raise InputError(f"Unable to read media file: {file_path}") from err

        data = self._handle(resp)
        return str(data["media_id_string"])

    def _chunked_upload(self, path: str | Path, total_bytes: int, mime_type: str) -> str:
        """Upload via INIT → APPEND → FINALIZE chunked flow."""
        file_path = Path(path)
        media_category = _media_category_for(mime_type)
        media_id = self._upload_init(total_bytes, mime_type, media_category)
        self._upload_append_all(media_id, file_path)
        return self._upload_finalize_and_wait(media_id)

    def _upload_init(self, total_bytes: int, media_type: str, media_category: str) -> str:
        """Send the INIT command and return the allocated media_id."""
        params = {
            "command": "INIT",
            "total_bytes": str(total_bytes),
            "media_type": media_type,
            "media_category": media_category,
        }
        auth = self._upload_oauth_header("POST", params=params)
        resp = self._send("POST", UPLOAD_BASE, headers={"Authorization": auth}, data=params)
        data = self._handle(resp)
        return str(data["media_id_string"])

    def _upload_append_all(self, media_id: str, path: str | Path) -> None:
        """Stream file chunks via successive APPEND commands."""
        file_path = Path(path)
        segment = 0
        try:
            with file_path.open("rb") as fh:
                while True:
                    chunk = fh.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    # APPEND is multipart → body params excluded from OAuth sig
                    auth = self._upload_oauth_header("POST")
                    resp = self._send(
                        "POST",
                        UPLOAD_BASE,
                        headers={"Authorization": auth},
                        data={
                            "command"      : "APPEND",
                            "media_id"     : media_id,
                            "segment_index": str(segment),
                        },
                        files={"media": ("blob", chunk, "application/octet-stream")},
                    )
                    if not resp.is_success:
                        self._handle(resp)  # raises
                    segment += 1
        except OSError as err:
            raise InputError(f"Unable to read media file: {file_path}") from err

    def _upload_finalize_and_wait(self, media_id: str) -> str:
        """Send FINALIZE and poll STATUS until processing completes."""
        params = {"command": "FINALIZE", "media_id": media_id}
        auth = self._upload_oauth_header("POST", params=params)
        resp = self._send("POST", UPLOAD_BASE, headers={"Authorization": auth}, data=params)
        data = self._handle(resp)

        # Video processing is async — poll STATUS until done.
        processing = data.get("processing_info")
        if processing:
            self._poll_processing(media_id, processing)

        return str(data["media_id_string"])

    def _poll_processing(
        self,
        media_id  : str,
        processing: Mapping[str, Any],
        max_polls : int = 60,
    ) -> None:
        """Poll async video processing until succeeded or failed."""
        for _ in range(max_polls):
            state = processing.get("state", "")
            if state == "succeeded":
                return
            if state == "failed":
                error = processing.get("error", {})
                msg = error.get("message", "Media processing failed")
                raise ApiError(f"Media processing failed: {msg}")

            wait_raw = processing.get("check_after_secs", 5)
            try:
                wait_seconds = max(0, int(wait_raw))
            except (TypeError, ValueError):
                wait_seconds = 5

            time.sleep(wait_seconds)

            params = {"command": "STATUS", "media_id": media_id}
            auth = self._upload_oauth_header("GET", params=params)
            resp = self._send(
                "GET",
                UPLOAD_BASE,
                headers={"Authorization": auth},
                params=params,
            )
            data = self._handle(resp)
            processing = data.get("processing_info", {})

        raise ApiError("Media processing timed out.")

    # endregion Media Upload

    # region Tweets
    # --------------------------------------------------------------------
    # Tweets
    # --------------------------------------------------------------------

    def post_tweet(
        self,
        text                  : str,
        reply_to              : str | None = None,
        quote_tweet_id        : str | None = None,
        poll_options          : list[str] | None = None,
        poll_duration_minutes : int = 1440,
        media_ids             : list[str] | None = None,
    ) -> dict[str, Any]:
        """Post a tweet with optional reply, quote, poll, or media attachments."""
        normalized_poll_options = _normalize_poll_options(poll_options, poll_duration_minutes)
        normalized_media_ids = _normalize_media_ids(media_ids)

        if normalized_poll_options and normalized_media_ids:
            raise InputError("Poll posts cannot include media attachments.")
        if normalized_poll_options and quote_tweet_id:
            raise InputError("Poll posts cannot be quote posts.")
        if normalized_media_ids and quote_tweet_id:
            raise InputError("Quote posts cannot include media attachments.")

        body: dict[str, Any] = {"text": text}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        if quote_tweet_id:
            body["quote_tweet_id"] = quote_tweet_id
        if normalized_poll_options:
            body["poll"] = {
                "options"         : normalized_poll_options,
                "duration_minutes": poll_duration_minutes,
            }
        if normalized_media_ids:
            body["media"] = {"media_ids": normalized_media_ids}
        return self._oauth_request("POST", f"{API_BASE}/tweets", json_body=body)

    def delete_tweet(self, tweet_id: str) -> dict[str, Any]:
        """Delete a tweet by ID."""
        return self._oauth_request("DELETE", f"{API_BASE}/tweets/{tweet_id}")

    def get_tweet(self, tweet_id: str) -> dict[str, Any]:
        """Fetch a single tweet with full field expansions."""
        params = {
            "tweet.fields": (
                "created_at,public_metrics,author_id,conversation_id,"
                "in_reply_to_user_id,referenced_tweets,attachments,entities,lang,note_tweet"
            ),
            "expansions"  : "author_id,referenced_tweets.id,attachments.media_keys",
            "user.fields" : "name,username,verified,profile_image_url,public_metrics",
            "media.fields": "url,preview_image_url,type,width,height,alt_text",
        }
        return self._bearer_get(f"{API_BASE}/tweets/{tweet_id}", query_params=params)

    def search_tweets(self, query: str, max_results: int = 10) -> dict[str, Any]:
        """Search recent tweets matching a query."""
        max_results = max(10, min(max_results, 100))
        params = {
            "query"       : query,
            "max_results" : str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions"  : "author_id,attachments.media_keys",
            "user.fields" : "name,username,verified,profile_image_url",
            "media.fields": "url,preview_image_url,type",
        }
        return self._bearer_get(f"{API_BASE}/tweets/search/recent", query_params=params)

    def get_tweet_metrics(self, tweet_id: str) -> dict[str, Any]:
        """Fetch public, non-public, and organic metrics for a tweet."""
        params = {
            "tweet.fields": "public_metrics,non_public_metrics,organic_metrics",
        }
        return self._oauth_request(
            "GET",
            f"{API_BASE}/tweets/{tweet_id}",
            query_params=params,
        )

    # endregion Tweets

    # region Users
    # --------------------------------------------------------------------
    # Users
    # --------------------------------------------------------------------

    def get_user(self, username: str) -> dict[str, Any]:
        """Look up a user profile by username."""
        encoded_username = urllib.parse.quote(username, safe="")
        params = {
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url,url,location,pinned_tweet_id",
        }
        return self._bearer_get(
            f"{API_BASE}/users/by/username/{encoded_username}",
            query_params=params,
        )

    def get_timeline(self, user_id: str, max_results: int = 10) -> dict[str, Any]:
        """Fetch a user's recent tweets."""
        max_results = max(5, min(max_results, 100))
        params = {
            "max_results" : str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions"  : "author_id,attachments.media_keys,referenced_tweets.id",
            "user.fields" : "name,username,verified",
            "media.fields": "url,preview_image_url,type",
        }
        return self._bearer_get(f"{API_BASE}/users/{user_id}/tweets", query_params=params)

    def get_followers(self, user_id: str, max_results: int = 100) -> dict[str, Any]:
        """List a user's followers."""
        max_results = max(1, min(max_results, 1000))
        params = {
            "max_results": str(max_results),
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url",
        }
        return self._bearer_get(f"{API_BASE}/users/{user_id}/followers", query_params=params)

    def get_following(self, user_id: str, max_results: int = 100) -> dict[str, Any]:
        """List who a user follows."""
        max_results = max(1, min(max_results, 1000))
        params = {
            "max_results": str(max_results),
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url",
        }
        return self._bearer_get(f"{API_BASE}/users/{user_id}/following", query_params=params)

    def get_mentions(self, max_results: int = 10) -> dict[str, Any]:
        """Fetch recent mentions of the authenticated user."""
        user_id = self.get_authenticated_user_id()
        max_results = max(5, min(max_results, 100))
        params = {
            "max_results" : str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,note_tweet",
            "expansions"  : "author_id",
            "user.fields" : "name,username,verified",
        }
        return self._oauth_request(
            "GET",
            f"{API_BASE}/users/{user_id}/mentions",
            query_params=params,
        )

    # endregion Users

    # region Engagement
    # --------------------------------------------------------------------
    # Engagement
    # --------------------------------------------------------------------

    def like_tweet(self, tweet_id: str) -> dict[str, Any]:
        """Like a tweet."""
        user_id = self.get_authenticated_user_id()
        return self._oauth_request(
            "POST",
            f"{API_BASE}/users/{user_id}/likes",
            json_body={"tweet_id": tweet_id},
        )

    def retweet(self, tweet_id: str) -> dict[str, Any]:
        """Retweet a tweet."""
        user_id = self.get_authenticated_user_id()
        return self._oauth_request(
            "POST",
            f"{API_BASE}/users/{user_id}/retweets",
            json_body={"tweet_id": tweet_id},
        )

    # endregion Engagement

    # region Bookmarks
    # --------------------------------------------------------------------
    # Bookmarks
    # --------------------------------------------------------------------

    def get_bookmarks(self, max_results: int = 10) -> dict[str, Any]:
        """Fetch the authenticated user's bookmarks."""
        user_id = self.get_authenticated_user_id()
        max_results = max(1, min(max_results, 100))
        params = {
            "max_results" : str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions"  : "author_id,attachments.media_keys",
            "user.fields" : "name,username,verified,profile_image_url",
            "media.fields": "url,preview_image_url,type",
        }
        return self._oauth_request(
            "GET",
            f"{API_BASE}/users/{user_id}/bookmarks",
            query_params=params,
        )

    def bookmark_tweet(self, tweet_id: str) -> dict[str, Any]:
        """Bookmark a tweet."""
        user_id = self.get_authenticated_user_id()
        return self._oauth_request(
            "POST",
            f"{API_BASE}/users/{user_id}/bookmarks",
            json_body={"tweet_id": tweet_id},
        )

    def unbookmark_tweet(self, tweet_id: str) -> dict[str, Any]:
        """Remove a bookmark."""
        user_id = self.get_authenticated_user_id()
        return self._oauth_request("DELETE", f"{API_BASE}/users/{user_id}/bookmarks/{tweet_id}")

    # endregion Bookmarks


# endregion XApiClient
