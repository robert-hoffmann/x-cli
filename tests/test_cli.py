"""Tests for x_cli.cli error handling and validation."""

from __future__ import annotations

from click.testing import CliRunner
import pytest

from x_cli.cli import cli, main
from x_cli.errors import InputError


class TestCliValidation:
    def test_post_rejects_poll_with_media(self, tmp_path):
        media_path = tmp_path / "photo.jpg"
        media_path.write_bytes(b"binary")

        result = CliRunner().invoke(
            cli,
            ["tweet", "post", "hello", "--poll", "Yes,No", "--media", str(media_path)],
        )

        assert result.exit_code == 1
        assert "Poll posts cannot include media attachments." in result.output

    def test_quote_rejects_media(self, tmp_path):
        media_path = tmp_path / "quote.jpg"
        media_path.write_bytes(b"binary")

        result = CliRunner().invoke(
            cli,
            ["tweet", "quote", "1234567890", "hello", "--media", str(media_path)],
        )

        assert result.exit_code == 1
        assert "Quote posts cannot include media attachments." in result.output


class TestMainErrorHandling:
    def test_main_renders_expected_cli_errors(self, monkeypatch, capsys):
        def raise_error(*args, **kwargs):
            raise InputError("bad input")

        monkeypatch.setattr("x_cli.cli.cli.main", raise_error)

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Error: bad input" in captured.err
