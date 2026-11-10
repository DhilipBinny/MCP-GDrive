"""Manual Desktop OAuth paste flow. No Google calls and no listening callback."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from unittest import mock

import pytest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from shared.auth import SCOPES, apply_profile_override, run_auth_flow, run_cli
from shared.manual_auth import (
    ManualAuthOptions,
    complete_manual_oauth,
    desktop_redirect_uri,
    parse_manual_redirect,
    read_redirect_file,
    read_redirect_stdin,
)

_CODE = "SENTINEL_MANUAL_CODE"
_INSTALLED = {
    "installed": {
        "client_id": "test-client.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "auth_uri": "https://example.invalid/o/oauth2/auth",
        "token_uri": "https://example.invalid/token",
        "redirect_uris": ["http://localhost"],
    }
}
_WEB = {
    "web": {
        "client_id": "web-client.apps.googleusercontent.com",
        "client_secret": "web-secret",
        "auth_uri": "https://example.invalid/o/oauth2/auth",
        "token_uri": "https://example.invalid/token",
        "redirect_uris": ["https://example.invalid/callback"],
    }
}


def _flow(obj: dict, directory: Path) -> InstalledAppFlow:
    path = directory / "client_secret.json"
    path.write_text(json.dumps(obj))
    return InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)


def _install_token(flow: InstalledAppFlow, captured: dict) -> None:
    def fake_session_fetch(token_url, code=None, authorization_response=None, **kwargs):
        captured["token_url"] = token_url
        captured["code"] = code
        captured["verifier"] = kwargs.get("code_verifier")
        captured["authorization_response"] = authorization_response
        captured["redirect_uri"] = flow.redirect_uri
        flow.oauth2session.token = {
            "access_token": "ya29.mock-access",
            "refresh_token": "mock-refresh",
            "token_type": "Bearer",
            "expires_at": time.time() + 3600,
            "scope": " ".join(SCOPES),
        }
        return flow.oauth2session.token

    flow.oauth2session.fetch_token = fake_session_fetch


class TestParseManualRedirect:
    def test_full_url_returns_code_when_state_matches(self):
        code = parse_manual_redirect(
            "http://127.0.0.1:9/?state=abc&code=the-code&scope=email",
            "abc",
        )
        assert code == "the-code"

    def test_state_mismatch_hides_code(self):
        pasted = f"http://127.0.0.1:9/?code={_CODE}&state=WRONGSTATE"
        with pytest.raises(RuntimeError, match="does not match") as exc:
            parse_manual_redirect(pasted, "expected-state")
        assert _CODE not in str(exc.value)
        assert "WRONGSTATE" not in str(exc.value)

    def test_missing_state_on_url(self):
        with pytest.raises(RuntimeError, match="missing the OAuth state"):
            parse_manual_redirect("http://127.0.0.1:9/?code=only-code", "expected-state")

    def test_error_param(self):
        pasted = "http://127.0.0.1:9/?error=access_denied&state=abc"
        with pytest.raises(RuntimeError, match="access_denied") as exc:
            parse_manual_redirect(pasted, "abc")
        assert "127.0.0.1" not in str(exc.value)

    def test_code_only(self):
        assert parse_manual_redirect(f"  {_CODE}\n", "ignored-for-bare-code") == _CODE

    def test_query_without_scheme(self):
        code = parse_manual_redirect("code=raw-code&state=sss", "sss")
        assert code == "raw-code"


class TestDesktopRedirect:
    def test_nothing_is_listening(self):
        uri = desktop_redirect_uri()
        parsed = urllib.parse.urlsplit(uri)
        assert parsed.scheme == "http"
        assert parsed.hostname == "127.0.0.1"
        assert parsed.path == "/"
        assert parsed.port is not None
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            assert sock.connect_ex(("127.0.0.1", parsed.port)) != 0
        finally:
            sock.close()


class TestManualFileAndStdin:
    def test_file_is_polled_and_deleted(self, tmp_path):
        path = tmp_path / "redirect.txt"

        def write_later() -> None:
            time.sleep(0.2)
            path.write_text(f"http://127.0.0.1:9/?code={_CODE}&state=st\n")

        threading.Thread(target=write_later, daemon=True).start()
        got = read_redirect_file(path, timeout_seconds=2)
        assert _CODE in got
        assert not path.exists()

    def test_file_timeout(self, tmp_path):
        missing = tmp_path / "missing.txt"
        with pytest.raises(RuntimeError, match="Timed out waiting for the OAuth redirect file"):
            read_redirect_file(missing, timeout_seconds=0.3)

    def test_stdin_line_is_not_echoed(self, monkeypatch, capsys):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, f"{_CODE}\n".encode())
        os.close(write_fd)
        monkeypatch.setattr(sys, "stdin", os.fdopen(read_fd))
        line = read_redirect_stdin(timeout_seconds=2)
        assert line.strip() == _CODE
        assert _CODE not in capsys.readouterr().err


class TestCompleteManualOAuth:
    def test_code_only_keeps_pkce_and_hides_code(self, tmp_path, capsys):
        flow = _flow(_INSTALLED, tmp_path)
        captured: dict = {}
        _install_token(flow, captured)
        creds = complete_manual_oauth(
            flow,
            ManualAuthOptions(manual=True),
            redirect_text=_CODE,
        )
        err = capsys.readouterr().err
        assert captured["code"] == _CODE
        assert captured["authorization_response"] is None
        assert captured["verifier"]
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(captured["verifier"].encode()).digest()).decode().rstrip("=")
        )
        assert challenge in err
        assert captured["redirect_uri"].startswith("http://127.0.0.1:")
        assert captured["redirect_uri"].endswith("/")
        assert _CODE not in err
        assert "ya29.mock-access" not in err
        assert creds.token == "ya29.mock-access"

    def test_state_mismatch_does_not_exchange(self, tmp_path, capsys):
        flow = _flow(_INSTALLED, tmp_path)
        captured: dict = {}
        _install_token(flow, captured)

        def auth_url(self, **kwargs):
            self.code_verifier = "v" * 64
            return "https://example.invalid/auth?state=good", "good"

        with (
            mock.patch.object(InstalledAppFlow, "authorization_url", auth_url),
            pytest.raises(RuntimeError, match="does not match"),
        ):
            complete_manual_oauth(
                flow,
                ManualAuthOptions(manual=True),
                redirect_text=f"http://127.0.0.1:9/?code={_CODE}&state=bad",
            )
        assert "code" not in captured
        assert _CODE not in capsys.readouterr().err

    def test_error_param_does_not_exchange(self, tmp_path):
        flow = _flow(_INSTALLED, tmp_path)
        captured: dict = {}
        _install_token(flow, captured)

        def auth_url(self, **kwargs):
            self.code_verifier = "v" * 64
            return "https://example.invalid/auth?state=good", "good"

        with (
            mock.patch.object(InstalledAppFlow, "authorization_url", auth_url),
            pytest.raises(RuntimeError, match="access_denied"),
        ):
            complete_manual_oauth(
                flow,
                ManualAuthOptions(manual=True),
                redirect_text="http://127.0.0.1:9/?error=access_denied&state=good",
            )
        assert "code" not in captured

    def test_token_exchange_failure_hides_code(self, tmp_path):
        flow = _flow(_INSTALLED, tmp_path)

        def explode(token_url, code=None, **kwargs):
            raise RuntimeError(f"upstream leaked {code}")

        flow.oauth2session.fetch_token = explode
        with pytest.raises(RuntimeError, match="token exchange failed") as exc:
            complete_manual_oauth(flow, ManualAuthOptions(manual=True), redirect_text=_CODE)
        assert exc.value.__cause__ is None
        assert _CODE not in str(exc.value)

    def test_web_client_is_rejected(self, tmp_path):
        flow = _flow(_WEB, tmp_path)
        with pytest.raises(RuntimeError, match="Desktop OAuth client"):
            complete_manual_oauth(flow, ManualAuthOptions(manual=True), redirect_text=_CODE)

    def test_redirect_file_deletes_and_exchanges(self, tmp_path, capsys):
        flow = _flow(_INSTALLED, tmp_path)
        captured: dict = {}
        _install_token(flow, captured)
        redirect_path = tmp_path / "pasted.txt"
        url_path = tmp_path / "url.txt"
        real = InstalledAppFlow.authorization_url

        def wrapped(self, **kwargs):
            url, state = real(self, **kwargs)
            redirect_path.write_text(f"http://127.0.0.1:9/?state={urllib.parse.quote(state)}&code={_CODE}\n")
            return url, state

        with mock.patch.object(InstalledAppFlow, "authorization_url", wrapped):
            complete_manual_oauth(
                flow,
                ManualAuthOptions(
                    manual=True,
                    redirect_from_file=redirect_path,
                    auth_url_file=url_path,
                    timeout_seconds=2,
                ),
            )
        assert not redirect_path.exists()
        stored = url_path.read_text()
        assert "example.invalid" in stored or "state=" in stored
        assert _CODE not in stored
        assert url_path.stat().st_mode & 0o777 == 0o600
        assert captured["code"] == _CODE
        assert captured["verifier"]
        assert _CODE not in capsys.readouterr().err

    def test_bad_file_is_still_deleted(self, tmp_path):
        flow = _flow(_INSTALLED, tmp_path)
        redirect_path = tmp_path / "pasted.txt"
        real = InstalledAppFlow.authorization_url

        def wrapped(self, **kwargs):
            url, state = real(self, **kwargs)
            redirect_path.write_text(f"http://127.0.0.1:9/?error=access_denied&state={state}\n")
            return url, state

        with (
            mock.patch.object(InstalledAppFlow, "authorization_url", wrapped),
            pytest.raises(RuntimeError, match="access_denied"),
        ):
            complete_manual_oauth(
                flow,
                ManualAuthOptions(manual=True, redirect_from_file=redirect_path, timeout_seconds=2),
            )
        assert not redirect_path.exists()


class TestManualCli:
    def test_help_mentions_manual(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["google-docs-mcp", "auth", "--help"])
        run_cli(mock.Mock())
        err = capsys.readouterr().err
        assert "--manual" in err
        assert "--redirect-from-file" in err
        assert "do not start authentication" in err

    def test_manual_profile_reaches_auth(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["google-docs-mcp", "auth", "--manual", "--profile", "work"])
        seen: dict = {}

        def fake_run(options=None):
            import shared.auth as auth_mod

            seen["manual"] = options.manual if options else False
            seen["profile"] = auth_mod.ACTIVE_PROFILE

        monkeypatch.setattr("shared.auth.run_auth_flow", fake_run)
        run_cli(mock.Mock())
        assert seen == {"manual": True, "profile": "work"}

    def test_file_flag_requires_manual(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["google-docs-mcp", "auth", "--redirect-from-file", "x"])
        with pytest.raises(SystemExit) as exc:
            run_cli(mock.Mock())
        assert exc.value.code == 2

    def test_success_output_and_profile_token_path(self, tmp_path, monkeypatch, capsys):
        secret = tmp_path / "client_secret.json"
        secret.write_text(json.dumps(_INSTALLED))
        monkeypatch.setenv("GOOGLE_WORKSPACE_MCP_CONFIG_DIR", str(tmp_path))
        monkeypatch.delenv("GOOGLE_WORKSPACE_MCP_PROFILE", raising=False)
        apply_profile_override("work")
        monkeypatch.setattr("shared.auth._find_client_secret", lambda: secret)
        monkeypatch.setattr("shared.auth._keyring_available", lambda: False)
        saved: list[Credentials] = []
        monkeypatch.setattr("shared.auth._save_token", saved.append)
        redirect_path = tmp_path / "pasted.txt"
        real = InstalledAppFlow.authorization_url

        def wrapped(self, **kwargs):
            url, state = real(self, **kwargs)
            redirect_path.write_text(f"http://127.0.0.1:9/?state={urllib.parse.quote(state)}&code={_CODE}\n")
            return url, state

        captured: dict = {}

        def fake_from_file(*_args, **_kwargs):
            flow = InstalledAppFlow.from_client_config(_INSTALLED, SCOPES)
            _install_token(flow, captured)
            return flow

        monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", staticmethod(fake_from_file))
        monkeypatch.setattr(InstalledAppFlow, "authorization_url", wrapped)
        run_auth_flow(
            ManualAuthOptions(manual=True, redirect_from_file=redirect_path, timeout_seconds=2),
        )
        err = capsys.readouterr().err
        assert "Authenticated successfully!" in err
        assert "profiles/work/token.json" in err
        assert _CODE not in err
        assert "ya29.mock-access" not in err
        assert saved and saved[0].token == "ya29.mock-access"
        assert saved[0].refresh_token == "mock-refresh"
        assert not redirect_path.exists()
