"""Authentication for Google Workspace APIs.

Cross-platform credential storage:
- Token: OS keyring (macOS Keychain, Windows Credential Locker, Linux libsecret)
- Fallback: JSON file at platform-correct config path
- Client secret: file at platform-correct config path
- Config path: ~/Library/Application Support/ (macOS), %APPDATA% (Windows), ~/.config/ (Linux)

Supports two modes:
1. Service Account — set GOOGLE_SERVICE_ACCOUNT_KEY env var
2. OAuth 2.0 — run `google-docs-mcp auth` once

Named profiles (optional):
- Set GOOGLE_WORKSPACE_MCP_PROFILE=<name> to use a per-project Google account.
- Each profile stores its token separately (keyring key or file path).
- Client secret falls back to the root config dir (one OAuth app for all accounts).
- No profile set = identical to pre-profile behavior.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
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

_PROFILE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def validate_profile_name(name: str) -> str:
    """Validate a profile name. Raises ValueError on invalid input."""
    if not _PROFILE_PATTERN.match(name):
        raise ValueError(
            f"Invalid profile name: '{name}'. "
            "Must be 1-40 chars, lowercase alphanumeric, hyphens, and underscores. "
            "Must start with a letter or digit."
        )
    return name


def _get_active_profile() -> str | None:
    """Read the active profile from the environment. Returns None for default."""
    profile = os.environ.get("GOOGLE_WORKSPACE_MCP_PROFILE", "").strip()
    if not profile:
        return None
    return validate_profile_name(profile)


def _get_base_config_dir() -> Path:
    """Get the root config directory (before profile subdirectory)."""
    override = os.environ.get("GOOGLE_WORKSPACE_MCP_CONFIG_DIR", "").strip()
    if override:
        config = Path(override)
        config.mkdir(parents=True, exist_ok=True)
        return config
    try:
        from platformdirs import user_config_path
        return user_config_path(APP_NAME, ensure_exists=True)
    except ImportError:
        config = Path.home() / ".config" / APP_NAME
        config.mkdir(parents=True, exist_ok=True)
        return config


def _get_config_dir(profile: str | None = None) -> Path:
    """Get config directory, optionally scoped to a profile."""
    base = _get_base_config_dir()
    if profile:
        profile_dir = base / "profiles" / profile
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir
    return base


def _get_keyring_username(profile: str | None = None) -> str:
    """Get keyring username, scoped to profile if set."""
    if profile:
        return f"oauth-token:{profile}"
    return "oauth-token"


# Resolve profile and paths at module load time
ACTIVE_PROFILE = _get_active_profile()
BASE_CONFIG_DIR = _get_base_config_dir()
CONFIG_DIR = _get_config_dir(ACTIVE_PROFILE)
TOKEN_PATH = CONFIG_DIR / "token.json"
CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"
KEYRING_USERNAME = _get_keyring_username(ACTIVE_PROFILE)

LEGACY_CONFIG_DIR = Path.home() / ".config" / "google-docs-mcp"
LEGACY_TOKEN_PATH = LEGACY_CONFIG_DIR / "token.json"

FALLBACK_CLIENT_SECRETS = [
    BASE_CONFIG_DIR / "client_secret.json",
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
        import platform
        return not (platform.system() == "Linux" and not os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
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
    import contextlib
    with contextlib.suppress(OSError):
        TOKEN_PATH.chmod(0o600)


def _load_token_from_file() -> Credentials | None:
    """Load token from JSON file — checks profile path, then legacy paths."""
    search_paths = [TOKEN_PATH]
    if not ACTIVE_PROFILE:
        search_paths.append(LEGACY_TOKEN_PATH)
    for path in search_paths:
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
            profile_hint = ""
            if ACTIVE_PROFILE:
                profile_hint = f" --profile {ACTIVE_PROFILE}"
            raise RuntimeError(
                "Google OAuth refresh token expired or revoked.\n"
                "This happens when:\n"
                "  - You revoked access in Google Account settings\n"
                "  - GCP app is in 'testing' mode (tokens expire after 7 days)\n"
                "  - Token hasn't been used for 6 months\n\n"
                f"Fix: run `google-docs-mcp auth{profile_hint}` to re-authenticate."
            ) from None

    profile_hint = ""
    if ACTIVE_PROFILE:
        profile_hint = f" --profile {ACTIVE_PROFILE}"
    raise RuntimeError(
        "Not authenticated. Run this first:\n\n"
        f"  google-docs-mcp auth{profile_hint}\n\n"
        "This opens a browser for one-time Google OAuth login.\n"
        f"Config directory: {CONFIG_DIR}"
    )


def _find_client_secret() -> Path:
    """Find client_secret.json — profile dir first, then root config, then legacy paths."""
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
    """Interactive auth flow — opens browser, saves token. Run once per profile."""
    if ACTIVE_PROFILE:
        print(f"Profile: {ACTIVE_PROFILE}", file=sys.stderr)
    client_secret = _find_client_secret()
    print(f"Using client secret: {client_secret}", file=sys.stderr)
    print("Opening browser for Google OAuth...", file=sys.stderr)

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds)

    location = f"OS keyring (key: {KEYRING_USERNAME})" if _keyring_available() else str(TOKEN_PATH)

    print("\nAuthenticated successfully!", file=sys.stderr)
    print(f"Token saved to: {location}", file=sys.stderr)
    print(f"Config directory: {CONFIG_DIR}", file=sys.stderr)
    print("You can now use the MCP server with Claude Code.", file=sys.stderr)


def run_whoami() -> None:
    """Print the email of the currently authenticated Google account."""
    try:
        creds = get_credentials()
    except (RuntimeError, FileNotFoundError) as e:
        print(f"Not authenticated: {e}", file=sys.stderr)
        sys.exit(1)

    from googleapiclient.discovery import build  # noqa: I001

    from shared.utils import execute_with_retry

    service = build("drive", "v3", credentials=creds)
    about = execute_with_retry(
        service.about().get(fields="user(emailAddress,displayName)")
    )
    user = about.get("user", {})
    email = user.get("emailAddress", "unknown")
    name = user.get("displayName", "")

    if ACTIVE_PROFILE:
        print(f"Profile:  {ACTIVE_PROFILE}")
    print(f"Account:  {email}")
    if name:
        print(f"Name:     {name}")
    print(f"Config:   {CONFIG_DIR}")


def parse_cli_args(argv: list[str]) -> tuple[str | None, str | None]:
    """Parse CLI arguments for auth subcommands.

    Returns (command, profile) where command is 'auth', 'whoami', or None,
    and profile is the --profile value or None.
    """
    command = None
    profile = None
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("auth", "whoami") and command is None:
            command = arg
        elif arg == "--profile" and i + 1 < len(argv):
            i += 1
            profile = argv[i]
        elif arg.startswith("--profile="):
            profile = arg.split("=", 1)[1]
        i += 1
    return command, profile


def apply_profile_override(profile: str | None) -> None:
    """Override the active profile from a CLI --profile flag.

    Must be called before any credential access (i.e., at the top of main()).
    """
    global ACTIVE_PROFILE, CONFIG_DIR, TOKEN_PATH, CLIENT_SECRET_PATH
    global KEYRING_USERNAME, FALLBACK_CLIENT_SECRETS

    if profile is not None:
        profile = validate_profile_name(profile)
        os.environ["GOOGLE_WORKSPACE_MCP_PROFILE"] = profile

    resolved = profile or _get_active_profile()
    ACTIVE_PROFILE = resolved
    CONFIG_DIR = _get_config_dir(resolved)
    TOKEN_PATH = CONFIG_DIR / "token.json"
    CLIENT_SECRET_PATH = CONFIG_DIR / "client_secret.json"
    KEYRING_USERNAME = _get_keyring_username(resolved)
    FALLBACK_CLIENT_SECRETS = [
        BASE_CONFIG_DIR / "client_secret.json",
        LEGACY_CONFIG_DIR / "client_secret.json",
        Path.home() / ".config" / "gws" / "client_secret.json",
        Path.home() / ".config" / "google" / "credentials.json",
    ]


def run_cli(mcp_server) -> None:
    """Shared CLI entry point for all three servers.

    Handles auth, whoami, and --profile before falling back to MCP stdio.
    """
    command, profile = parse_cli_args(sys.argv)
    if command or profile:
        apply_profile_override(profile)
    if command == "auth":
        run_auth_flow()
        return
    if command == "whoami":
        run_whoami()
        return
    mcp_server.run(transport="stdio")
