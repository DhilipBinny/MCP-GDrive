"""Authentication for Google Workspace APIs.

Cross-platform credential storage:
- Token: OS keyring (macOS Keychain, Windows Credential Locker, Linux libsecret)
- Fallback: JSON file at platform-correct config path
- Client secret: file at platform-correct config path
- Config path: ~/Library/Application Support/ (macOS), %APPDATA% (Windows), ~/.config/ (Linux)

Supports two modes:
1. Service Account — set GOOGLE_SERVICE_ACCOUNT_KEY env var
2. OAuth 2.0 — run `google-docs-mcp auth` once
"""

import json
import logging
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

logger = logging.getLogger(__name__)

APP_NAME = "google-workspace-mcp"
KEYRING_SERVICE = "google-workspace-mcp"
KEYRING_USERNAME = "oauth-token"


def _get_config_dir() -> Path:
    """Get platform-correct config directory."""
    try:
        from platformdirs import user_config_path
        return user_config_path(APP_NAME, ensure_exists=True)
    except ImportError:
        # Fallback if platformdirs not installed
        config = Path.home() / ".config" / APP_NAME
        config.mkdir(parents=True, exist_ok=True)
        return config


CONFIG_DIR = _get_config_dir()
TOKEN_PATH = CONFIG_DIR / "token.json"
CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"

LEGACY_CONFIG_DIR = Path.home() / ".config" / "google-docs-mcp"
LEGACY_TOKEN_PATH = LEGACY_CONFIG_DIR / "token.json"

FALLBACK_CLIENT_SECRETS = [
    LEGACY_CONFIG_DIR / "client_secret.json",
    Path.home() / ".config" / "gws" / "client_secret.json",
    Path.home() / ".config" / "google" / "credentials.json",
]

_cached_creds = None
_auth_mode = None


def _keyring_available() -> bool:
    """Check if a real keyring backend is available (not null/plaintext)."""
    try:
        import keyring
        backend = type(keyring.get_keyring()).__name__
        if "Null" in backend or "Fail" in backend or "PlainText" in backend:
            return False
        # On headless Linux, D-Bus may be missing — secretstorage will fail
        import platform
        if platform.system() == "Linux":
            import os
            if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
                return False
        return True
    except Exception:
        logger.debug("Keyring availability check failed", exc_info=True)
        return False


def _save_token_to_keyring(creds: Credentials) -> bool:
    """Try to save token to OS keyring. Returns True on success."""
    if not _keyring_available():
        return False
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, creds.to_json())
        return True
    except Exception:
        logger.debug("Failed to save token to keyring", exc_info=True)
        return False


def _load_token_from_keyring() -> Credentials | None:
    """Try to load token from OS keyring. Returns None if unavailable."""
    if not _keyring_available():
        return None
    try:
        import keyring
        token_json = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if token_json:
            return Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
    except Exception:
        logger.debug("Failed to load token from keyring", exc_info=True)
    return None


def _save_token_to_file(creds: Credentials) -> None:
    """Save token to JSON file (fallback when keyring unavailable)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    try:
        TOKEN_PATH.chmod(0o600)
    except OSError:
        pass  # Windows doesn't support Unix permissions


def _load_token_from_file() -> Credentials | None:
    """Load token from JSON file — checks current and legacy paths."""
    for path in [TOKEN_PATH, LEGACY_TOKEN_PATH]:
        if path.exists():
            try:
                return Credentials.from_authorized_user_file(str(path), SCOPES)
            except (ValueError, KeyError):
                continue
    return None


def _save_token(creds: Credentials) -> None:
    """Save token — keyring first, file fallback."""
    if not _save_token_to_keyring(creds):
        _save_token_to_file(creds)


def _load_token() -> Credentials | None:
    """Load token — keyring first, file fallback."""
    creds = _load_token_from_keyring()
    if creds:
        return creds
    return _load_token_from_file()


def get_credentials():
    """Get valid credentials, trying service account first, then OAuth."""
    global _cached_creds, _auth_mode

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
    creds = _load_token()

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
        f"Config directory: {CONFIG_DIR}"
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


def run_auth_flow() -> None:
    """Interactive auth flow — opens browser, saves token. Run once."""
    client_secret = _find_client_secret()
    print(f"Using client secret: {client_secret}", file=sys.stderr)
    print("Opening browser for Google OAuth...", file=sys.stderr)

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)

    # Report where the token was saved
    try:
        import keyring
        keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        location = "OS keyring (secure)"
    except Exception:
        logger.debug("Keyring check after auth flow failed", exc_info=True)
        location = str(TOKEN_PATH)

    print(f"\nAuthenticated successfully!", file=sys.stderr)
    print(f"Token saved to: {location}", file=sys.stderr)
    print(f"Config directory: {CONFIG_DIR}", file=sys.stderr)
    print("You can now use the MCP server with Claude Code.", file=sys.stderr)
