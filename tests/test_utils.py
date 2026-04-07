"""Tests for x_cli.utils."""

import pytest

from x_cli.utils import normalize_username, parse_tweet_id, strip_at


class TestParseTweetId:
    def test_raw_numeric(self):
        assert parse_tweet_id("1234567890") == "1234567890"

    def test_raw_with_whitespace(self):
        assert parse_tweet_id("  1234567890  ") == "1234567890"

    def test_x_url(self):
        assert parse_tweet_id("https://x.com/user/status/1234567890") == "1234567890"

    def test_twitter_url(self):
        assert parse_tweet_id("https://twitter.com/elonmusk/status/9999") == "9999"

    def test_mobile_x_url(self):
        assert parse_tweet_id("https://mobile.x.com/user/status/1234567890") == "1234567890"

    def test_url_with_query_params(self):
        assert parse_tweet_id("https://x.com/user/status/123?s=20") == "123"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid tweet ID"):
            parse_tweet_id("not-a-tweet")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_tweet_id("")

    def test_too_long_numeric_id_raises(self):
        with pytest.raises(ValueError, match="Invalid tweet ID"):
            parse_tweet_id("1" * 20)


class TestStripAt:
    def test_with_at(self):
        assert strip_at("@elonmusk") == "elonmusk"

    def test_without_at(self):
        assert strip_at("elonmusk") == "elonmusk"

    def test_empty(self):
        assert strip_at("") == ""


class TestNormalizeUsername:
    def test_strips_whitespace_and_at(self):
        assert normalize_username("  @elonmusk  ") == "elonmusk"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Username cannot be empty"):
            normalize_username("   @   ")

    def test_rejects_invalid_chars(self):
        with pytest.raises(ValueError, match="letters, numbers, or underscores"):
            normalize_username("bad-name")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="1-15 characters"):
            normalize_username("a" * 16)
