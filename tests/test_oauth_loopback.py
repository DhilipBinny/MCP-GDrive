"""OAuth callback listener and CLI help. No Google credentials or network."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import sys
import time
import urllib.parse
import webbrowser
from unittest import mock

import pytest
from google_auth_oauthlib.flow import InstalledAppFlow

from shared.auth import SCOPES, apply_profile_override, run_auth_flow, run_cli
from shared.oauth_loopback import LoopbackCallbackServer, diagnose_loopback

_SENTINEL = "SENTINEL_AUTH_CODE"
_CLIENT_SECRET = {
    "installed": {
        "client_id": "test-client.apps.googleusercontent.com",
        "client_secret": "test-secret",
        "auth_uri": "https://example.invalid/o/oauth2/auth",
        "token_uri": "https://example.invalid/token",
        "redirect_uris": ["http://localhost"],
    }
}


def _http_get(host: str, port: int, target: str) -> bytes:
    sock = socket.create_connection((host, port), timeout=5)
    try:
        host_header = f"[{host}]" if ":" in host else host
        request = f"GET {target} HTTP/1.1\r\nHost: {host_header}:{port}\r\nConnection: close\r\n\r\n"
        sock.sendall(request.encode("ascii"))
        data = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        return data
    finally:
        sock.close()


class TestLoopbackCallbackServer:
    def test_same_process_ipv4_and_redirect_host(self):
        with LoopbackCallbackServer() as server:
            assert server.ipv4_ok
            assert server.port > 0
            text = "\n".join(server.describe())
            assert f"127.0.0.1:{server.port} accepted a connection from this process." in text
            assert "does not show whether a browser can connect" in text
            if server.ipv6_listening:
                assert server.redirect_host == "localhost"
                assert server.redirect_uri == f"http://localhost:{server.port}/"
                assert f"::1:{server.port} accepted a connection from this process." in text
            else:
                assert server.redirect_host == "127.0.0.1"

    def test_favicon_does_not_consume_callback(self):
        with LoopbackCallbackServer() as server:
            favicon = _http_get("127.0.0.1", server.port, "/favicon.ico")
            assert favicon.startswith(b"HTTP/1.1 404")
            with pytest.raises(TimeoutError):
                server.wait_for_oauth_redirect(timeout=0.2)
            body = _http_get("127.0.0.1", server.port, "/?code=abc&state=xyz")
            assert body.startswith(b"HTTP/1.1 200")
            assert _SENTINEL.encode() not in body
            uri = server.wait_for_oauth_redirect(timeout=2)
            assert uri.startswith(f"http://{server.redirect_host}:{server.port}/?")
            assert "code=abc" in uri
            assert "state=xyz" in uri
            assert server.callback_peer == "127.0.0.1"

    def test_ipv6_callback_when_listening(self):
        with LoopbackCallbackServer() as server:
            if not server.ipv6_listening:
                pytest.skip("IPv6 loopback is not accepting connections")
            body = _http_get("::1", server.port, "/?code=from-v6&state=s1")
            assert body.startswith(b"HTTP/1.1 200")
            assert b"from-v6" not in body
            uri = server.wait_for_oauth_redirect(timeout=2)
            assert "code=from-v6" in uri
            assert "state=s1" in uri
            assert server.callback_peer == "::1"

    def test_response_does_not_echo_query(self):
        with LoopbackCallbackServer() as server:
            body = _http_get("127.0.0.1", server.port, f"/diag?secret={_SENTINEL}")
            assert _SENTINEL.encode() not in body
            assert server.wait_for_browser(0.5) == "127.0.0.1"


class TestDiagnoseLoopback:
    def test_diagnose_does_not_need_credentials(self, capsys):
        code = diagnose_loopback(wait_seconds=0)
        err = capsys.readouterr().err
        assert code == 0
        assert "does not contact Google" in err
        assert "accepted a connection from this process" in err
        assert "client_secret" not in err
        assert _SENTINEL not in err


class TestAuthHelpDoesNotStartFlow:
    def test_auth_help_does_not_open_oauth(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["google-docs-mcp", "auth", "--help"])
        monkeypatch.setattr(
            "shared.auth._find_client_secret",
            lambda: (_ for _ in ()).throw(AssertionError("secret lookup")),
        )
        called = mock.Mock()
        monkeypatch.setattr("shared.auth.run_auth_flow", called)
        mcp = mock.Mock()
        run_cli(mcp)
        called.assert_not_called()
        mcp.run.assert_not_called()
        assert "do not start authentication" in capsys.readouterr().err

    def test_top_level_help_does_not_start_mcp(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["google-docs-mcp", "-h"])
        mcp = mock.Mock()
        run_cli(mcp)
        mcp.run.assert_not_called()
        assert "usage:" in capsys.readouterr().err

    def test_diagnose_flag_does_not_start_auth(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["google-docs-mcp", "auth", "--diagnose-loopback"])
        called = mock.Mock()
        monkeypatch.setattr("shared.auth.run_auth_flow", called)
        monkeypatch.setattr("shared.auth.diagnose_loopback", lambda: 0)
        with pytest.raises(SystemExit) as exc:
            run_cli(mock.Mock())
        assert exc.value.code == 0
        called.assert_not_called()

    def test_whoami_diagnose_rejected(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["google-docs-mcp", "whoami", "--diagnose-loopback"])
        with pytest.raises(SystemExit) as exc:
            run_cli(mock.Mock())
        assert exc.value.code == 2


class TestRunAuthFlowCallback:
    def test_callback_preserves_pkce_and_hides_code(self, tmp_path, monkeypatch, capsys):
        secret = tmp_path / "client_secret.json"
        secret.write_text(json.dumps(_CLIENT_SECRET))
        monkeypatch.setenv("GOOGLE_WORKSPACE_MCP_CONFIG_DIR", str(tmp_path))
        monkeypatch.delenv("GOOGLE_WORKSPACE_MCP_PROFILE", raising=False)
        apply_profile_override(None)
        monkeypatch.setattr("shared.auth._find_client_secret", lambda: secret)
        monkeypatch.setattr("shared.auth._keyring_available", lambda: False)
        saved: list[object] = []
        monkeypatch.setattr("shared.auth._save_token", lambda creds: saved.append(creds))

        def fail_library_server(self, *args, **kwargs):
            raise AssertionError("run_local_server must not be used")

        monkeypatch.setattr(InstalledAppFlow, "run_local_server", fail_library_server)

        captured: dict[str, str] = {}

        def fake_fetch(self, **kwargs):
            response = kwargs["authorization_response"]
            captured["response"] = response
            verifier = self.code_verifier
            assert isinstance(verifier, str) and len(verifier) >= 43
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            captured["challenge"] = challenge
            captured["verifier"] = verifier
            self.oauth2session.token = {
                "access_token": "ya29.mock-access",
                "refresh_token": "mock-refresh",
                "token_type": "Bearer",
                "expires_at": time.time() + 3600,
                "scope": " ".join(SCOPES),
            }
            return self.oauth2session.token

        monkeypatch.setattr(InstalledAppFlow, "fetch_token", fake_fetch)

        def fake_open(url, new=0, autoraise=True):
            captured["url"] = url
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            redirect = urllib.parse.urlsplit(qs["redirect_uri"][0])
            state = qs["state"][0]
            assert redirect.port is not None
            # Use the first address getaddrinfo returns for the redirect host.
            host = redirect.hostname or "127.0.0.1"
            body = _http_get(host, redirect.port, f"/?state={urllib.parse.quote(state)}&code={_SENTINEL}")
            assert body.startswith(b"HTTP/1.1 200")
            assert _SENTINEL.encode() not in body
            return True

        monkeypatch.setattr(webbrowser, "get", lambda browser=None: mock.Mock(open=fake_open))

        run_auth_flow()
        err = capsys.readouterr().err
        assert _SENTINEL not in err
        assert captured["challenge"] in captured["url"]
        assert captured["response"].startswith("https://")
        assert f"code={_SENTINEL}" in captured["response"]
        assert "state=" in captured["response"]
        assert "No authorization response has been received yet." in err
        assert "OAuth callback received from" in err
        assert saved
        assert saved[0].token == "ya29.mock-access"
        assert saved[0].refresh_token == "mock-refresh"
