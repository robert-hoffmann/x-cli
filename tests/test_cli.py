"""Tests for x_cli.cli error handling and validation."""

from __future__ import annotations

import json

from click.testing import CliRunner
import pytest

from x_cli.cli import State, cli, main
from x_cli.errors import InputError


class TestCliValidation:
    def test_help_alias_lists_agent_commands(self):
        result = CliRunner().invoke(cli, ["-h"])

        assert result.exit_code == 0
        assert "capabilities" in result.output
        assert "doctor" in result.output
        assert "-h, --help" in result.output

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

    def test_capabilities_json_exposes_auth_model(self):
        result = CliRunner().invoke(cli, ["--json", "capabilities"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["auth_model"]["write_default"] == "oauth1"
        assert any(command["path"] == ["doctor"] for command in payload["commands"])

    def test_auth_status_reports_missing_credentials(self, monkeypatch):
        monkeypatch.setattr("x_cli.auth.load_dotenv", lambda *args, **kwargs: False)
        for name in (
            "X_API_KEY",
            "X_API_SECRET",
            "X_ACCESS_TOKEN",
            "X_ACCESS_TOKEN_SECRET",
            "X_BEARER_TOKEN",
        ):
            monkeypatch.delenv(name, raising=False)

        result = CliRunner().invoke(cli, ["--json", "auth", "status"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["credentials"]["all_required_present"] is False
        assert "X_API_KEY" in payload["credentials"]["missing"]

    def test_doctor_api_check_skips_when_credentials_missing(self, monkeypatch):
        monkeypatch.setattr("x_cli.auth.load_dotenv", lambda *args, **kwargs: False)
        for name in (
            "X_API_KEY",
            "X_API_SECRET",
            "X_ACCESS_TOKEN",
            "X_ACCESS_TOKEN_SECRET",
            "X_BEARER_TOKEN",
        ):
            monkeypatch.delenv(name, raising=False)

        result = CliRunner().invoke(cli, ["--json", "doctor", "--api"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        api_check = next(check for check in payload["checks"] if check["name"] == "authenticated_user_lookup")
        assert api_check["ok"] is False
        assert "Skipped because required credentials are missing." in api_check["detail"]

    def test_whoami_uses_authenticated_user(self, monkeypatch):
        class FakeClient:
            def get_authenticated_user(self):
                return {"data": {"id": "1", "username": "agent", "name": "Agent"}}

        monkeypatch.setattr(State, "client", property(lambda self: FakeClient()))

        result = CliRunner().invoke(cli, ["--json", "whoami"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["id"] == "1"
        assert payload["username"] == "agent"


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
