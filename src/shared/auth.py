"""Authentication for Google Workspace APIs.

Supports two modes (checked in order):
1. Service Account — set GOOGLE_SERVICE_ACCOUNT_KEY to a JSON key file path
2. OAuth 2.0 — run `google-docs-mcp auth` once to save a refresh token
"""

import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
]

CONFIG_DIR = Path.home() / ".config" / "google-docs-mcp"
TOKEN_PATH = CONFIG_DIR / "token.json"
CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"

FALLBACK_CLIENT_SECRETS = [
    Path.home() / ".config" / "gws" / "client_secret.json",
    Path.home() / ".config" / "google" / "credentials.json",
]

_cached_creds = None
_auth_mode = None


def get_credentials():
    """Get valid credentials, trying service account first, then OAuth."""
    global _cached_creds, _auth_mode

    # Service account creds don't report .valid until first use,
    # so we cache by mode instead of checking .valid
    if _cached_creds is not None:
        if _auth_mode == "service_account":
            return _cached_creds
        if _cached_creds.valid:
            return _cached_creds
        if _cached_creds.expired and _cached_creds.refresh_token:
            try:
                _cached_creds.refresh(Request())
                _save_token(_cached_creds)
                return _cached_creds
            except RefreshError:
                _cached_creds = None

    # Mode 1: Service Account (env var)
    sa_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if sa_key:
        impersonate = os.environ.get("GOOGLE_IMPERSONATE_USER")
        _cached_creds = _get_service_account_creds(sa_key, impersonate)
        _auth_mode = "service_account"
        return _cached_creds

    # Mode 2: OAuth — use saved token
    _cached_creds = _get_oauth_creds()
    _auth_mode = "oauth"
    return _cached_creds


def _get_service_account_creds(key_path: str, impersonate: str | None = None):
    key_file = Path(key_path)
    if not key_file.exists():
        raise FileNotFoundError(
            f"Service account key not found: {key_path}\n"
            "Set GOOGLE_SERVICE_ACCOUNT_KEY to a valid JSON key file path."
        )
    creds = service_account.Credentials.from_service_account_file(
        str(key_file), scopes=SCOPES
    )
    if impersonate:
        creds = creds.with_subject(impersonate)
    return creds


def _get_oauth_creds() -> Credentials:
    creds = None

    if TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
        except (ValueError, KeyError):
            raise RuntimeError(
                f"Token file is corrupt: {TOKEN_PATH}\n"
                "Delete it and re-authenticate:\n\n"
                f"  rm {TOKEN_PATH}\n"
                "  google-docs-mcp auth"
            )

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except RefreshError:
            raise RuntimeError(
                "Google OAuth refresh token expired or revoked.\n"
                "This happens when:\n"
                "  - You revoked access in Google Account settings\n"
                "  - GCP app is in 'testing' mode (tokens expire after 7 days)\n"
                "  - Token hasn't been used for 6 months\n\n"
                "Fix: run `google-docs-mcp auth` to re-authenticate."
            )

    raise RuntimeError(
        "Not authenticated. Run this first:\n\n"
        "  google-docs-mcp auth\n\n"
        "This opens a browser for one-time Google OAuth login.\n"
        f"Token will be saved to {TOKEN_PATH}"
    )


def _find_client_secret() -> Path:
    if CLIENT_SECRET_PATH.exists():
        return CLIENT_SECRET_PATH
    for path in FALLBACK_CLIENT_SECRETS:
        if path.exists():
            return path
    raise FileNotFoundError(
        "No client_secret.json found. Place your OAuth client secret at:\n"
        f"  {CLIENT_SECRET_PATH}\n\n"
        "Or download one from Google Cloud Console:\n"
        "  APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON"
    )


def _save_token(creds: Credentials) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    TOKEN_PATH.chmod(0o600)


def run_auth_flow() -> None:
    """Interactive auth flow — opens browser, saves token. Run once."""
    client_secret = _find_client_secret()
    print(f"Using client secret: {client_secret}", file=sys.stderr)
    print("Opening browser for Google OAuth...", file=sys.stderr)

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)

    print(f"\nAuthenticated successfully!", file=sys.stderr)
    print(f"Token saved to: {TOKEN_PATH}", file=sys.stderr)
    print("You can now use the MCP server with Claude Code.", file=sys.stderr)
