"""Manual Desktop OAuth sign-in when no browser can reach a loopback listener.

The authorization redirect is a Desktop-client loopback URI on a port this
process does not listen on. After consent, the browser fails to load that
address and the user pastes the address-bar URL (or only the code) back.
State is checked when the paste includes it. PKCE stays on the flow and is
sent with the token request.
"""

from __future__ import annotations

import os
import re
import socket
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

_DEFAULT_TIMEOUT_SECONDS = 600.0
_POLL_SECONDS = 0.1
_MAX_REDIRECT_CHARS = 65536
_MAX_CODE_CHARS = 2048
_ERROR_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


@dataclass(frozen=True)
class ManualAuthOptions:
    """Flags for ``auth --manual``."""

    manual: bool = False
    redirect_from_file: Path | None = None
    auth_url_file: Path | None = None
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS


def parse_manual_cli(argv: list[str]) -> ManualAuthOptions:
    """Parse manual-auth flags. Raises ValueError on a malformed flag."""
    manual = False
    redirect_from_file: str | None = None
    auth_url_file: str | None = None
    timeout_seconds = _DEFAULT_TIMEOUT_SECONDS
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--manual":
            manual = True
        elif arg == "--redirect-from-file":
            i += 1
            if i >= len(argv):
                raise ValueError("--redirect-from-file requires a path")
            redirect_from_file = argv[i]
        elif arg.startswith("--redirect-from-file="):
            redirect_from_file = arg.split("=", 1)[1]
        elif arg == "--auth-url-file":
            i += 1
            if i >= len(argv):
                raise ValueError("--auth-url-file requires a path")
            auth_url_file = argv[i]
        elif arg.startswith("--auth-url-file="):
            auth_url_file = arg.split("=", 1)[1]
        elif arg == "--manual-timeout":
            i += 1
            if i >= len(argv):
                raise ValueError("--manual-timeout requires a number of seconds")
            timeout_seconds = _parse_timeout(argv[i])
        elif arg.startswith("--manual-timeout="):
            timeout_seconds = _parse_timeout(arg.split("=", 1)[1])
        i += 1
    if redirect_from_file == "":
        raise ValueError("--redirect-from-file requires a path")
    if auth_url_file == "":
        raise ValueError("--auth-url-file requires a path")
    return ManualAuthOptions(
        manual=manual,
        redirect_from_file=Path(redirect_from_file) if redirect_from_file else None,
        auth_url_file=Path(auth_url_file) if auth_url_file else None,
        timeout_seconds=timeout_seconds,
    )


def manual_flags_without_command(options: ManualAuthOptions) -> bool:
    """True when a manual-only flag was set without ``--manual`` itself."""
    return bool(
        options.redirect_from_file is not None
        or options.auth_url_file is not None
        or options.timeout_seconds != _DEFAULT_TIMEOUT_SECONDS
    )


def desktop_redirect_uri() -> str:
    """Return a Desktop loopback redirect on a port this process does not hold.

    Google accepts ``http://127.0.0.1:<port>/`` for an installed-app client
    without that port being registered. Closing the socket before returning
    leaves nothing listening, so the browser keeps the redirect in the address bar.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    finally:
        sock.close()
    return f"http://127.0.0.1:{port}/"


def parse_manual_redirect(text: str, expected_state: str) -> str:
    """Return the authorization code from a paste.

    A full redirect or query string must carry the state from this attempt.
    A bare authorization code has no state to compare. The returned code is
    for the token request only; callers must not log it.
    """
    raw = text.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1].strip()
    if not raw:
        raise RuntimeError("No OAuth redirect was provided.")
    if len(raw) > _MAX_REDIRECT_CHARS:
        raise RuntimeError("The OAuth redirect is too long.")
    if not _looks_like_redirect(raw):
        if any(ch.isspace() for ch in raw) or len(raw) > _MAX_CODE_CHARS:
            raise RuntimeError("The authorization code is not valid.")
        return raw

    query = _query_from_paste(raw)
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    if "error" in params:
        err = params["error"][0] if params["error"] else ""
        if not _ERROR_RE.fullmatch(err):
            err = "unrecognized_error"
        raise RuntimeError(f"Google OAuth authorization failed: {err}")
    state_vals = params.get("state") or []
    if not state_vals:
        raise RuntimeError("The redirect URL is missing the OAuth state.")
    if state_vals[0] != expected_state:
        raise RuntimeError(
            "OAuth state does not match this sign-in attempt. "
            "Start auth again and paste the redirect from that attempt."
        )
    codes = params.get("code") or []
    if not codes or not codes[0].strip():
        raise RuntimeError("The redirect did not include an authorization code.")
    return codes[0]


def read_redirect_file(path: Path, timeout_seconds: float) -> str:
    """Poll until ``path`` has text, then delete it and return that text."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        if path.is_file():
            try:
                data = path.read_bytes()[: _MAX_REDIRECT_CHARS + 1]
            except OSError as exc:
                raise RuntimeError(f"Could not read the redirect file: {exc.strerror}") from None
            text = data.decode("utf-8", "replace")
            if text.strip():
                _delete_redirect_file(path)
                return text
        if time.monotonic() >= deadline:
            raise RuntimeError("Timed out waiting for the OAuth redirect file.")
        time.sleep(_POLL_SECONDS)


def read_redirect_stdin(timeout_seconds: float) -> str:
    """Read one line from stdin, or raise if it does not arrive in time."""
    print(
        "Paste the full redirect URL from the address bar, or only the authorization code, then press Enter.",
        file=sys.stderr,
    )
    holder: dict[str, str] = {}

    def _read() -> None:
        holder["line"] = sys.stdin.readline()

    thread = threading.Thread(target=_read, name="oauth-manual-stdin", daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise RuntimeError("Timed out waiting for the OAuth redirect.")
    line = holder.get("line", "")
    if line == "":
        raise RuntimeError("No OAuth redirect was provided.")
    return line


def write_auth_url_file(path: Path, url: str) -> None:
    """Write the authorization URL (no authorization code) for another process."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, (url + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def complete_manual_oauth(
    flow: InstalledAppFlow,
    options: ManualAuthOptions,
    *,
    redirect_text: str | None = None,
) -> Credentials:
    """Run Desktop OAuth without a listening callback server."""
    if flow.client_type != "installed":
        raise RuntimeError(
            "Manual sign-in requires a Desktop OAuth client "
            f'(top-level "installed" in the client secret). This file is a {flow.client_type} client.'
        )
    redirect_uri = desktop_redirect_uri()
    flow.redirect_uri = redirect_uri
    auth_url, state = flow.authorization_url()
    _emit_auth_url(auth_url, redirect_uri, options)
    if redirect_text is None:
        if options.redirect_from_file is not None:
            redirect_text = read_redirect_file(options.redirect_from_file, options.timeout_seconds)
        else:
            redirect_text = read_redirect_stdin(options.timeout_seconds)
    code = parse_manual_redirect(redirect_text, state)
    try:
        flow.fetch_token(code=code)
    except Exception:
        raise RuntimeError("Google token exchange failed.") from None
    creds = flow.credentials
    if not isinstance(creds, Credentials):
        raise RuntimeError("OAuth flow did not produce credentials.")
    return creds


def _emit_auth_url(auth_url: str, redirect_uri: str, options: ManualAuthOptions) -> None:
    print("Manual sign-in. Nothing is listening for the OAuth redirect.", file=sys.stderr)
    print(
        "Open the URL below in any browser. After consent, the browser fails to load "
        f"{redirect_uri}. Copy the full address-bar URL and paste it back.",
        file=sys.stderr,
    )
    print("Please visit this URL to authorize this application: " + auth_url, file=sys.stderr)
    if options.auth_url_file is not None:
        try:
            write_auth_url_file(options.auth_url_file, auth_url)
        except OSError as exc:
            raise RuntimeError(f"Could not write the authorization URL file: {exc.strerror}") from None
        print(f"Authorization URL also written to: {options.auth_url_file}", file=sys.stderr)


def _parse_timeout(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("--manual-timeout must be a positive number of seconds") from None
    if value <= 0 or value != value or value == float("inf"):
        raise ValueError("--manual-timeout must be a positive number of seconds")
    return value


def _looks_like_redirect(text: str) -> bool:
    lowered = text.lower()
    return (
        "://" in text
        or lowered.startswith("localhost")
        or lowered.startswith("127.0.0.1")
        or "code=" in text
        or "error=" in text
        or "state=" in text
        or text.startswith("?")
    )


def _query_from_paste(text: str) -> str:
    if "://" in text or text.lower().startswith("localhost") or text.lower().startswith("127.0.0.1"):
        candidate = text if "://" in text else "http://" + text
        return urllib.parse.urlsplit(candidate).query
    if text.startswith("?"):
        return text[1:]
    return text


def _delete_redirect_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        print(
            "Could not delete the redirect file. Remove it so the authorization code is not left on disk.",
            file=sys.stderr,
        )
