"""Tests for media upload functionality."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch, call

import pytest

from x_cli.api import (
    XApiClient,
    UPLOAD_BASE,
    _CHUNK_THRESHOLD,
    _CHUNK_SIZE,
    _MEDIA_CATEGORIES,
)
from x_cli.auth import Credentials


@pytest.fixture
def creds():
    return Credentials(
        api_key="k",
        api_secret="s",
        access_token="t",
        access_token_secret="ts",
        bearer_token="bt",
    )


@pytest.fixture
def client(creds):
    c = XApiClient(creds)
    c._http = MagicMock()
    return c


# -- helpers --

def _make_file(suffix: str, size: int) -> str:
    """Create a temp file of *size* bytes and return its path."""
    f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    f.write(b"\x00" * size)
    f.close()
    return f.name


def _ok_response(json_data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = True
    resp.json.return_value = json_data
    resp.headers = {}
    return resp


# ============================================================
# upload_media — routing
# ============================================================

class TestUploadMediaRouting:
    def test_raises_on_missing_file(self, client):
        with pytest.raises(FileNotFoundError, match="Media file not found"):
            client.upload_media("/nonexistent/photo.jpg")

    def test_small_image_uses_simple(self, client):
        path = _make_file(".jpg", 500)
        try:
            client._simple_upload = MagicMock(return_value="111")
            client._chunked_upload = MagicMock()
            mid = client.upload_media(path)
            assert mid == "111"
            client._simple_upload.assert_called_once()
            client._chunked_upload.assert_not_called()
        finally:
            os.unlink(path)

    def test_large_image_uses_chunked(self, client):
        path = _make_file(".png", _CHUNK_THRESHOLD + 1)
        try:
            client._simple_upload = MagicMock()
            client._chunked_upload = MagicMock(return_value="222")
            mid = client.upload_media(path)
            assert mid == "222"
            client._chunked_upload.assert_called_once()
            client._simple_upload.assert_not_called()
        finally:
            os.unlink(path)

    def test_video_always_uses_chunked(self, client):
        path = _make_file(".mp4", 100)  # tiny but still video
        try:
            client._simple_upload = MagicMock()
            client._chunked_upload = MagicMock(return_value="333")
            mid = client.upload_media(path)
            assert mid == "333"
            client._chunked_upload.assert_called_once()
        finally:
            os.unlink(path)


# ============================================================
# _simple_upload
# ============================================================

class TestSimpleUpload:
    def test_returns_media_id_string(self, client):
        client._http.post.return_value = _ok_response({"media_id_string": "456"})
        path = _make_file(".jpg", 100)
        try:
            mid = client._simple_upload(path, "image/jpeg")
            assert mid == "456"
            client._http.post.assert_called_once()
            _, kwargs = client._http.post.call_args
            assert kwargs.get("files") is not None
        finally:
            os.unlink(path)


# ============================================================
# chunked upload flow
# ============================================================

class TestChunkedUpload:
    def test_init_sends_correct_params(self, client):
        client._http.post.return_value = _ok_response({"media_id_string": "789"})
        mid = client._upload_init(1024, "video/mp4", "tweet_video")
        assert mid == "789"
        _, kwargs = client._http.post.call_args
        assert kwargs["data"]["command"] == "INIT"
        assert kwargs["data"]["total_bytes"] == "1024"
        assert kwargs["data"]["media_type"] == "video/mp4"

    def test_append_sends_chunks(self, client):
        path = _make_file(".mp4", _CHUNK_SIZE + 100)
        try:
            resp_ok = MagicMock()
            resp_ok.is_success = True
            client._http.post.return_value = resp_ok

            client._upload_append_all("789", path)

            # Should have been called twice (one full chunk + one partial)
            assert client._http.post.call_count == 2
        finally:
            os.unlink(path)

    def test_finalize_without_processing(self, client):
        client._http.post.return_value = _ok_response({"media_id_string": "789"})
        mid = client._upload_finalize_and_wait("789")
        assert mid == "789"

    @patch("x_cli.api.time.sleep")
    def test_finalize_polls_processing(self, mock_sleep, client):
        finalize_resp = _ok_response({
            "media_id_string": "789",
            "processing_info": {"state": "pending", "check_after_secs": 1},
        })
        status_resp = _ok_response({
            "media_id_string": "789",
            "processing_info": {"state": "succeeded"},
        })
        client._http.post.return_value = finalize_resp
        client._http.get.return_value = status_resp

        mid = client._upload_finalize_and_wait("789")
        assert mid == "789"
        mock_sleep.assert_called_once_with(1)

    @patch("x_cli.api.time.sleep")
    def test_finalize_raises_on_failed_processing(self, mock_sleep, client):
        finalize_resp = _ok_response({
            "media_id_string": "789",
            "processing_info": {"state": "pending", "check_after_secs": 1},
        })
        status_resp = _ok_response({
            "media_id_string": "789",
            "processing_info": {
                "state": "failed",
                "error": {"message": "Invalid media"},
            },
        })
        client._http.post.return_value = finalize_resp
        client._http.get.return_value = status_resp

        with pytest.raises(RuntimeError, match="Invalid media"):
            client._upload_finalize_and_wait("789")


# ============================================================
# post_tweet with media_ids
# ============================================================

class TestPostTweetWithMedia:
    def test_includes_media_ids_in_body(self, client):
        client._http.request.return_value = _ok_response({"data": {"id": "999"}})
        client.post_tweet("hello", media_ids=["123", "456"])
        _, kwargs = client._http.request.call_args
        body = kwargs.get("json")
        assert body["media"] == {"media_ids": ["123", "456"]}

    def test_omits_media_when_none(self, client):
        client._http.request.return_value = _ok_response({"data": {"id": "999"}})
        client.post_tweet("hello")
        _, kwargs = client._http.request.call_args
        body = kwargs.get("json")
        assert "media" not in body


# ============================================================
# MIME → category mapping
# ============================================================

class TestMediaCategories:
    def test_mp4_is_tweet_video(self):
        assert _MEDIA_CATEGORIES["video/mp4"] == "tweet_video"

    def test_gif_is_tweet_gif(self):
        assert _MEDIA_CATEGORIES["image/gif"] == "tweet_gif"

    def test_unknown_falls_back_to_tweet_image(self):
        assert _MEDIA_CATEGORIES.get("image/png", "tweet_image") == "tweet_image"
