"""Tests for shared.auth — profile resolution, validation, path routing, CLI parsing."""

from __future__ import annotations

import os
import re
from unittest import mock

import pytest

from shared.auth import (
    _find_client_secret,
    _get_active_profile,
    _get_base_config_dir,
    _get_config_dir,
    _get_keyring_username,
    _load_token_from_file,
    apply_profile_override,
    parse_cli_args,
    validate_profile_name,
)

# ---------------------------------------------------------------------------
# Profile name validation
# ---------------------------------------------------------------------------

class TestValidateProfileName:
    def test_simple_name(self):
        assert validate_profile_name("oriak") == "oriak"

    def test_name_with_hyphens(self):
        assert validate_profile_name("my-project") == "my-project"

    def test_name_with_underscores(self):
        assert validate_profile_name("my_project") == "my_project"

    def test_name_with_digits(self):
        assert validate_profile_name("project1") == "project1"

    def test_name_starts_with_digit(self):
        assert validate_profile_name("1project") == "1project"

    def test_max_length_40(self):
        name = "a" * 40
        assert validate_profile_name(name) == name

    def test_too_long_41_chars(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("a" * 41)

    def test_empty_string(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("")

    def test_uppercase_rejected(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("Oriak")

    def test_spaces_rejected(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("my project")

    def test_path_traversal_dots(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("../etc")

    def test_path_traversal_slash(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("a/b")

    def test_path_traversal_backslash(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("a\\b")

    def test_starts_with_hyphen(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("-bad")

    def test_starts_with_underscore(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("_bad")

    def test_special_chars(self):
        with pytest.raises(ValueError, match="Invalid profile name"):
            validate_profile_name("oriak!")


# ---------------------------------------------------------------------------
# Profile resolution from environment
# ---------------------------------------------------------------------------

class TestGetActiveProfile:
    def test_no_env_var(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            # Remove the var if present
            os.environ.pop("GOOGLE_WORKSPACE_MCP_PROFILE", None)
            assert _get_active_profile() is None

    def test_empty_env_var(self):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_PROFILE": ""}):
            assert _get_active_profile() is None

    def test_whitespace_only(self):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_PROFILE": "  "}):
            assert _get_active_profile() is None

    def test_valid_profile(self):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_PROFILE": "oriak"}):
            assert _get_active_profile() == "oriak"

    def test_strips_whitespace(self):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_PROFILE": "  oriak  "}):
            assert _get_active_profile() == "oriak"

    def test_invalid_profile_raises(self):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_PROFILE": "../bad"}), pytest.raises(ValueError):
            _get_active_profile()


# ---------------------------------------------------------------------------
# Config directory resolution
# ---------------------------------------------------------------------------

class TestGetConfigDir:
    def test_no_profile_returns_base(self):
        base = _get_base_config_dir()
        assert _get_config_dir(None) == base

    def test_profile_returns_subdirectory(self, tmp_path):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            result = _get_config_dir("oriak")
            assert result == tmp_path / "profiles" / "oriak"
            assert result.is_dir()

    def test_profile_dir_created(self, tmp_path):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            result = _get_config_dir("test-project")
            assert result.exists()
            assert result.name == "test-project"
            assert result.parent.name == "profiles"

    def test_config_dir_override(self, tmp_path):
        custom = tmp_path / "custom"
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(custom)}):
            result = _get_base_config_dir()
            assert result == custom
            assert result.is_dir()


# ---------------------------------------------------------------------------
# Keyring username routing
# ---------------------------------------------------------------------------

class TestGetKeyringUsername:
    def test_no_profile(self):
        assert _get_keyring_username(None) == "oauth-token"

    def test_with_profile(self):
        assert _get_keyring_username("oriak") == "oauth-token:oriak"

    def test_with_different_profile(self):
        assert _get_keyring_username("team-b") == "oauth-token:team-b"


# ---------------------------------------------------------------------------
# Path consistency: no profile = same as pre-profile behavior
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_no_profile_token_path(self, tmp_path):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            os.environ.pop("GOOGLE_WORKSPACE_MCP_PROFILE", None)
            base = _get_base_config_dir()
            config = _get_config_dir(None)
            assert config == base
            assert (config / "token.json") == base / "token.json"

    def test_profile_token_path_differs(self, tmp_path):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            base = _get_base_config_dir()
            config = _get_config_dir("oriak")
            assert config != base
            assert config / "token.json" != base / "token.json"

    def test_profile_client_secret_fallback(self, tmp_path):
        """Profile dir should fall back to base dir for client_secret.json."""
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            base = _get_base_config_dir()
            profile_dir = _get_config_dir("oriak")
            # client_secret.json NOT in profile dir
            assert not (profile_dir / "client_secret.json").exists()
            # But base dir could have it — and it's in FALLBACK_CLIENT_SECRETS
            base_secret = base / "client_secret.json"
            assert base_secret == tmp_path / "client_secret.json"


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

class TestParseCliArgs:
    def test_no_args(self):
        cmd, profile = parse_cli_args(["google-docs-mcp"])
        assert cmd is None
        assert profile is None

    def test_auth_only(self):
        cmd, profile = parse_cli_args(["google-docs-mcp", "auth"])
        assert cmd == "auth"
        assert profile is None

    def test_whoami_only(self):
        cmd, profile = parse_cli_args(["google-docs-mcp", "whoami"])
        assert cmd == "whoami"
        assert profile is None

    def test_auth_with_profile_flag(self):
        cmd, profile = parse_cli_args(["google-docs-mcp", "auth", "--profile", "oriak"])
        assert cmd == "auth"
        assert profile == "oriak"

    def test_auth_with_profile_equals(self):
        cmd, profile = parse_cli_args(["google-docs-mcp", "auth", "--profile=oriak"])
        assert cmd == "auth"
        assert profile == "oriak"

    def test_profile_before_command(self):
        cmd, profile = parse_cli_args(["google-docs-mcp", "--profile", "oriak", "auth"])
        assert cmd == "auth"
        assert profile == "oriak"

    def test_whoami_with_profile(self):
        cmd, profile = parse_cli_args(["google-docs-mcp", "whoami", "--profile", "oriak"])
        assert cmd == "whoami"
        assert profile == "oriak"

    def test_unknown_args_ignored(self):
        cmd, profile = parse_cli_args(["google-docs-mcp", "--verbose", "auth"])
        assert cmd == "auth"
        assert profile is None

    def test_profile_at_end_no_value(self):
        cmd, profile = parse_cli_args(["google-docs-mcp", "auth", "--profile"])
        assert cmd == "auth"
        assert profile is None

    def test_double_commands_first_wins(self):
        cmd, profile = parse_cli_args(["google-docs-mcp", "auth", "whoami"])
        assert cmd == "auth"

    def test_profile_equals_empty(self):
        cmd, profile = parse_cli_args(["google-docs-mcp", "auth", "--profile="])
        assert cmd == "auth"
        assert profile == ""


# ---------------------------------------------------------------------------
# apply_profile_override
# ---------------------------------------------------------------------------

class TestApplyProfileOverride:
    def test_override_updates_globals(self, tmp_path):
        import shared.auth as auth_mod
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            apply_profile_override("test-proj")
            assert auth_mod.ACTIVE_PROFILE == "test-proj"
            assert tmp_path / "profiles" / "test-proj" == auth_mod.CONFIG_DIR
            assert tmp_path / "profiles" / "test-proj" / "token.json" == auth_mod.TOKEN_PATH
            assert auth_mod.KEYRING_USERNAME == "oauth-token:test-proj"

    def test_override_clears_cached_creds(self, tmp_path):
        import shared.auth as auth_mod
        auth_mod._cached_creds = "stale"
        auth_mod._auth_mode = "oauth"
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            apply_profile_override("fresh")
            assert auth_mod._cached_creds is None
            assert auth_mod._auth_mode is None

    def test_override_invalid_profile_raises(self, tmp_path):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}), pytest.raises(ValueError, match="Invalid profile name"):
            apply_profile_override("../bad")

    def test_override_none_with_env_var(self, tmp_path):
        import shared.auth as auth_mod
        with mock.patch.dict(os.environ, {
            "GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path),
            "GOOGLE_WORKSPACE_MCP_PROFILE": "from-env",
        }):
            apply_profile_override(None)
            assert auth_mod.ACTIVE_PROFILE == "from-env"
            assert auth_mod.KEYRING_USERNAME == "oauth-token:from-env"


# ---------------------------------------------------------------------------
# _find_client_secret fallback with profiles
# ---------------------------------------------------------------------------

class TestFindClientSecretFallback:
    def test_profile_falls_back_to_root(self, tmp_path):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            apply_profile_override("myproj")
            # Place secret in root, not profile dir
            root_secret = tmp_path / "client_secret.json"
            root_secret.write_text('{"installed":{}}')
            found = _find_client_secret()
            assert found == root_secret

    def test_profile_prefers_own_secret(self, tmp_path):
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            apply_profile_override("myproj")
            # Place secret in both locations
            root_secret = tmp_path / "client_secret.json"
            root_secret.write_text('{"installed":{}}')
            profile_secret = tmp_path / "profiles" / "myproj" / "client_secret.json"
            profile_secret.write_text('{"installed":{}}')
            found = _find_client_secret()
            assert found == profile_secret

    def test_no_secret_error_shows_root_path(self, tmp_path):
        import shared.auth as auth_mod
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            apply_profile_override("myproj")
            # Override legacy fallbacks to avoid finding real secrets on the filesystem
            auth_mod.FALLBACK_CLIENT_SECRETS = [tmp_path / "client_secret.json"]
            with pytest.raises(FileNotFoundError, match=re.escape(str(tmp_path / "client_secret.json"))):
                _find_client_secret()


# ---------------------------------------------------------------------------
# _load_token_from_file with profile
# ---------------------------------------------------------------------------

class TestLoadTokenFromFileWithProfile:
    def test_profile_skips_legacy_path(self, tmp_path):
        import shared.auth as auth_mod
        with mock.patch.dict(os.environ, {"GOOGLE_WORKSPACE_MCP_CONFIG_DIR": str(tmp_path)}):
            apply_profile_override("isolated")
            # ACTIVE_PROFILE is set, so legacy path should NOT be searched
            assert auth_mod.ACTIVE_PROFILE == "isolated"
            result = _load_token_from_file()
            assert result is None
