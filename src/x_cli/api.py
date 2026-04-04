"""Twitter API v2 client with OAuth 1.0a and Bearer token auth."""

from __future__ import annotations

import mimetypes
import os
import time
from typing import Any

import httpx

from .auth import Credentials, generate_oauth_header

API_BASE = "https://api.x.com/2"
UPLOAD_BASE = "https://upload.twitter.com/1.1/media/upload.json"

# Chunked upload threshold: files > 1 MB use chunked flow (required for video).
_CHUNK_THRESHOLD = 1 * 1024 * 1024
_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB per APPEND segment

# MIME → media_category mapping for chunked INIT
_MEDIA_CATEGORIES: dict[str, str] = {
    "image/gif": "tweet_gif",
    "video/mp4": "tweet_video",
    "video/quicktime": "tweet_video",
    "video/webm": "tweet_video",
}


class XApiClient:
    def __init__(self, creds: Credentials) -> None:
        self.creds = creds
        self._user_id: str | None = None
        self._http = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._http.close()

    # ---- internal ----

    def _bearer_get(self, url: str) -> dict[str, Any]:
        resp = self._http.get(url, headers={"Authorization": f"Bearer {self.creds.bearer_token}"})
        return self._handle(resp)

    def _oauth_request(self, method: str, url: str, json_body: dict | None = None) -> dict[str, Any]:
        auth_header = generate_oauth_header(method, url, self.creds)
        headers: dict[str, str] = {"Authorization": auth_header}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        resp = self._http.request(method, url, headers=headers, json=json_body or None)
        return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset", "unknown")
            raise RuntimeError(f"Rate limited. Resets at {reset}.")
        data = resp.json()
        if not resp.is_success:
            errors = data.get("errors", [])
            msg = "; ".join(e.get("detail") or e.get("message", "") for e in errors) or resp.text[:500]
            raise RuntimeError(f"API error (HTTP {resp.status_code}): {msg}")
        return data

    def get_authenticated_user_id(self) -> str:
        if self._user_id is not None:
            return self._user_id
        data = self._oauth_request("GET", f"{API_BASE}/users/me")
        user_id = data["data"]["id"]
        self._user_id = user_id
        return user_id

    # ---- media upload (v1.1 chunked) ----

    def _upload_oauth_header(self, method: str, params: dict[str, str] | None = None) -> str:
        """Build OAuth header for the v1.1 upload endpoint.

        For INIT/FINALIZE/STATUS the form-encoded params are included in the
        signature base string.  For APPEND (multipart) *no* body params are
        included — the OAuth spec excludes multipart entities.
        """
        return generate_oauth_header(method, UPLOAD_BASE, self.creds, params=params)

    def upload_media(self, file_path: str) -> str:
        """Upload a media file and return its *media_id_string*.

        Uses the simple upload path for small images and the INIT / APPEND /
        FINALIZE / (STATUS) chunked flow for large files and video.
        """
        path = os.path.expanduser(file_path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Media file not found: {path}")

        file_size = os.path.getsize(path)
        mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        is_video = mime_type.startswith("video/")

        # Video *must* use chunked; images may use simple if small enough.
        if is_video or file_size > _CHUNK_THRESHOLD:
            return self._chunked_upload(path, file_size, mime_type)
        return self._simple_upload(path, mime_type)

    # -- simple (small images) --

    def _simple_upload(self, path: str, mime_type: str) -> str:
        auth = self._upload_oauth_header("POST")
        with open(path, "rb") as fh:
            files = {"media": (os.path.basename(path), fh, mime_type)}
            resp = self._http.post(
                UPLOAD_BASE,
                headers={"Authorization": auth},
                files=files,
            )
        data = self._handle(resp)
        return str(data["media_id_string"])

    # -- chunked (video / large files) --

    def _chunked_upload(self, path: str, total_bytes: int, mime_type: str) -> str:
        media_category = _MEDIA_CATEGORIES.get(mime_type, "tweet_image")
        media_id = self._upload_init(total_bytes, mime_type, media_category)
        self._upload_append_all(media_id, path)
        return self._upload_finalize_and_wait(media_id)

    def _upload_init(self, total_bytes: int, media_type: str, media_category: str) -> str:
        params = {
            "command": "INIT",
            "total_bytes": str(total_bytes),
            "media_type": media_type,
            "media_category": media_category,
        }
        auth = self._upload_oauth_header("POST", params=params)
        resp = self._http.post(UPLOAD_BASE, headers={"Authorization": auth}, data=params)
        data = self._handle(resp)
        return str(data["media_id_string"])

    def _upload_append_all(self, media_id: str, path: str) -> None:
        segment = 0
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(_CHUNK_SIZE)
                if not chunk:
                    break
                # APPEND is multipart → body params excluded from OAuth sig
                auth = self._upload_oauth_header("POST")
                resp = self._http.post(
                    UPLOAD_BASE,
                    headers={"Authorization": auth},
                    data={"command": "APPEND", "media_id": media_id, "segment_index": str(segment)},
                    files={"media": ("blob", chunk, "application/octet-stream")},
                )
                if not resp.is_success:
                    self._handle(resp)  # raises
                segment += 1

    def _upload_finalize_and_wait(self, media_id: str) -> str:
        params = {"command": "FINALIZE", "media_id": media_id}
        auth = self._upload_oauth_header("POST", params=params)
        resp = self._http.post(UPLOAD_BASE, headers={"Authorization": auth}, data=params)
        data = self._handle(resp)

        # Video processing is async — poll STATUS until done.
        processing = data.get("processing_info")
        if processing:
            self._poll_processing(media_id, processing)

        return str(data["media_id_string"])

    def _poll_processing(self, media_id: str, processing: dict, max_polls: int = 60) -> None:
        for _ in range(max_polls):
            state = processing.get("state", "")
            if state == "succeeded":
                return
            if state == "failed":
                error = processing.get("error", {})
                msg = error.get("message", "Media processing failed")
                raise RuntimeError(f"Media processing failed: {msg}")

            wait = processing.get("check_after_secs", 5)
            time.sleep(wait)

            params = {"command": "STATUS", "media_id": media_id}
            auth = self._upload_oauth_header("GET", params=params)
            resp = self._http.get(UPLOAD_BASE, headers={"Authorization": auth}, params=params)
            data = self._handle(resp)
            processing = data.get("processing_info", {})

        raise RuntimeError("Media processing timed out")

    # ---- tweets ----

    def post_tweet(
        self,
        text: str,
        reply_to: str | None = None,
        quote_tweet_id: str | None = None,
        poll_options: list[str] | None = None,
        poll_duration_minutes: int = 1440,
        media_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        if quote_tweet_id:
            body["quote_tweet_id"] = quote_tweet_id
        if poll_options:
            body["poll"] = {"options": poll_options, "duration_minutes": poll_duration_minutes}
        if media_ids:
            body["media"] = {"media_ids": media_ids}
        return self._oauth_request("POST", f"{API_BASE}/tweets", body)

    def delete_tweet(self, tweet_id: str) -> dict[str, Any]:
        return self._oauth_request("DELETE", f"{API_BASE}/tweets/{tweet_id}")

    def get_tweet(self, tweet_id: str) -> dict[str, Any]:
        params = {
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,in_reply_to_user_id,referenced_tweets,attachments,entities,lang,note_tweet",
            "expansions": "author_id,referenced_tweets.id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url,public_metrics",
            "media.fields": "url,preview_image_url,type,width,height,alt_text",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return self._bearer_get(f"{API_BASE}/tweets/{tweet_id}?{qs}")

    def search_tweets(self, query: str, max_results: int = 10) -> dict[str, Any]:
        max_results = max(10, min(max_results, 100))
        params = {
            "query": query,
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url",
            "media.fields": "url,preview_image_url,type",
        }
        url = f"{API_BASE}/tweets/search/recent"
        resp = self._http.get(url, params=params, headers={"Authorization": f"Bearer {self.creds.bearer_token}"})
        return self._handle(resp)

    def get_tweet_metrics(self, tweet_id: str) -> dict[str, Any]:
        params = "tweet.fields=public_metrics,non_public_metrics,organic_metrics"
        return self._oauth_request("GET", f"{API_BASE}/tweets/{tweet_id}?{params}")

    # ---- users ----

    def get_user(self, username: str) -> dict[str, Any]:
        fields = "user.fields=created_at,description,public_metrics,verified,profile_image_url,url,location,pinned_tweet_id"
        return self._bearer_get(f"{API_BASE}/users/by/username/{username}?{fields}")

    def get_timeline(self, user_id: str, max_results: int = 10) -> dict[str, Any]:
        max_results = max(5, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys,referenced_tweets.id",
            "user.fields": "name,username,verified",
            "media.fields": "url,preview_image_url,type",
        }
        resp = self._http.get(
            f"{API_BASE}/users/{user_id}/tweets",
            params=params,
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
        )
        return self._handle(resp)

    def get_followers(self, user_id: str, max_results: int = 100) -> dict[str, Any]:
        max_results = max(1, min(max_results, 1000))
        params = {
            "max_results": str(max_results),
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url",
        }
        resp = self._http.get(
            f"{API_BASE}/users/{user_id}/followers",
            params=params,
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
        )
        return self._handle(resp)

    def get_following(self, user_id: str, max_results: int = 100) -> dict[str, Any]:
        max_results = max(1, min(max_results, 1000))
        params = {
            "max_results": str(max_results),
            "user.fields": "created_at,description,public_metrics,verified,profile_image_url",
        }
        resp = self._http.get(
            f"{API_BASE}/users/{user_id}/following",
            params=params,
            headers={"Authorization": f"Bearer {self.creds.bearer_token}"},
        )
        return self._handle(resp)

    def get_mentions(self, max_results: int = 10) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        max_results = max(5, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,note_tweet",
            "expansions": "author_id",
            "user.fields": "name,username,verified",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{API_BASE}/users/{user_id}/mentions?{qs}"
        return self._oauth_request("GET", url)

    # ---- engagement ----

    def like_tweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        return self._oauth_request("POST", f"{API_BASE}/users/{user_id}/likes", {"tweet_id": tweet_id})

    def retweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        return self._oauth_request("POST", f"{API_BASE}/users/{user_id}/retweets", {"tweet_id": tweet_id})

    # ---- bookmarks (OAuth 1.0a -- basic tier may not support these) ----

    def get_bookmarks(self, max_results: int = 10) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        max_results = max(1, min(max_results, 100))
        params = {
            "max_results": str(max_results),
            "tweet.fields": "created_at,public_metrics,author_id,conversation_id,entities,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "name,username,verified,profile_image_url",
            "media.fields": "url,preview_image_url,type",
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{API_BASE}/users/{user_id}/bookmarks?{qs}"
        return self._oauth_request("GET", url)

    def bookmark_tweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        return self._oauth_request("POST", f"{API_BASE}/users/{user_id}/bookmarks", {"tweet_id": tweet_id})

    def unbookmark_tweet(self, tweet_id: str) -> dict[str, Any]:
        user_id = self.get_authenticated_user_id()
        return self._oauth_request("DELETE", f"{API_BASE}/users/{user_id}/bookmarks/{tweet_id}")
