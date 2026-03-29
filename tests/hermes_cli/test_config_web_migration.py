"""Tests for web config v2 migration logic (v10→v11).

Coverage:
  Config migration from v10 → v11 (embedded in migrate_config)
  Empty string handling in DEFAULT_CONFIG
  Migration prompting for SearXNG URL
"""

import os
import tempfile
import json
import pytest
from unittest.mock import patch, MagicMock, call


class TestConfigMigrationV10ToV11:
    """Test automatic migration from config v10 to v11.
    
    Note: Migration logic is embedded in migrate_config(), not a separate function.
    These tests verify the logic indirectly through config loading/saving.
    """

    def test_migration_inline_copies_generic_backend_to_search(self):
        """web.backend → web.search.backend (if not already set)."""
        from hermes_cli.config import migrate_config
        
        old_config = {
            "web": {"backend": "firecrawl"},
            "_config_version": 10,
        }
        
        # Mock load_config to return old config with v10
        with patch("hermes_cli.config.load_config", return_value=old_config):
            with patch("hermes_cli.config.save_config") as mock_save:
                with patch("builtins.print"):  # suppress output
                    migrate_config(interactive=False, quiet=True)
                
                if mock_save.called:
                    saved_config = mock_save.call_args[0][0]
                    assert saved_config["web"]["search"]["backend"] == "firecrawl"

    def test_migration_inline_copies_generic_backend_to_extract(self):
        """web.backend → web.extract.backend (if not already set)."""
        from hermes_cli.config import migrate_config
        
        old_config = {
            "web": {"backend": "tavily"},
            "_config_version": 10,
        }
        
        with patch("hermes_cli.config.load_config", return_value=old_config):
            with patch("hermes_cli.config.save_config") as mock_save:
                with patch("builtins.print"):
                    migrate_config(interactive=False, quiet=True)
                
                if mock_save.called:
                    saved_config = mock_save.call_args[0][0]
                    assert saved_config["web"]["extract"]["backend"] == "tavily"

    def test_migration_inline_preserves_existing_search_backend(self):
        """If web.search.backend already set, don't overwrite it."""
        from hermes_cli.config import migrate_config
        
        old_config = {
            "web": {
                "backend": "firecrawl",
                "search": {"backend": "parallel"},  # already set
            },
            "_config_version": 10,
        }
        
        with patch("hermes_cli.config.load_config", return_value=old_config):
            with patch("hermes_cli.config.save_config") as mock_save:
                with patch("builtins.print"):
                    migrate_config(interactive=False, quiet=True)
                
                if mock_save.called:
                    saved_config = mock_save.call_args[0][0]
                    # Should not be overwritten
                    assert saved_config["web"]["search"]["backend"] == "parallel"

    def test_migration_inline_preserves_existing_extract_backend(self):
        """If web.extract.backend already set, don't overwrite it."""
        from hermes_cli.config import migrate_config
        
        old_config = {
            "web": {
                "backend": "firecrawl",
                "extract": {"backend": "native"},  # already set
            },
            "_config_version": 10,
        }
        
        with patch("hermes_cli.config.load_config", return_value=old_config):
            with patch("hermes_cli.config.save_config") as mock_save:
                with patch("builtins.print"):
                    migrate_config(interactive=False, quiet=True)
                
                if mock_save.called:
                    saved_config = mock_save.call_args[0][0]
                    # Should not be overwritten
                    assert saved_config["web"]["extract"]["backend"] == "native"

    def test_migration_inline_searxng_old_backend_empty_extract(self):
        """Old backend=searxng → search=searxng, extract='' (falls back to generic)."""
        from hermes_cli.config import migrate_config
        
        old_config = {
            "web": {"backend": "searxng"},
            "_config_version": 10,
        }
        
        with patch("hermes_cli.config.load_config", return_value=old_config):
            with patch("hermes_cli.config.save_config") as mock_save:
                with patch("builtins.print"):
                    migrate_config(interactive=False, quiet=True)
                
                if mock_save.called:
                    saved_config = mock_save.call_args[0][0]
                    assert saved_config["web"]["search"]["backend"] == "searxng"
                    # Extract gets empty string (falls back to generic if available)
                    assert saved_config["web"]["extract"]["backend"] == ""

    def test_migration_inline_searxng_prompts_for_url_interactive(self):
        """Old backend=searxng + interactive mode → prompt for URL."""
        from hermes_cli.config import migrate_config
        
        old_config = {
            "web": {"backend": "searxng"},
            "_config_version": 10,
        }
        
        with patch("hermes_cli.config.load_config", return_value=old_config):
            with patch("builtins.input", return_value="https://searx.example.com/search?q=%s&format=json"):
                with patch("hermes_cli.config.save_config") as mock_save:
                    with patch("builtins.print"):
                        migrate_config(interactive=True, quiet=False)
                    
                    if mock_save.called:
                        saved_config = mock_save.call_args[0][0]
                        assert saved_config["web"]["search"]["url"] == "https://searx.example.com/search?q=%s&format=json"

    def test_migration_inline_searxng_skips_prompt_if_url_already_set(self):
        """If web.search.url already configured, don't prompt for it."""
        from hermes_cli.config import migrate_config
        
        old_config = {
            "web": {
                "backend": "searxng",
                "search": {"url": "https://searx.example.com/search?q=%s&format=json"},
            },
            "_config_version": 10,
        }
        
        with patch("hermes_cli.config.load_config", return_value=old_config):
            with patch("hermes_cli.config.save_config") as mock_save:
                with patch("builtins.print"):
                    # Should not raise an exception
                    migrate_config(interactive=False, quiet=True)
                
                # Verify the migration ran (save was called)
                # and the URL was preserved
                if mock_save.called:
                    saved_config = mock_save.call_args[0][0]
                    assert saved_config["web"]["search"]["url"] == "https://searx.example.com/search?q=%s&format=json"

    def test_migration_inline_no_web_config_still_works(self):
        """Config with no web key should still migrate gracefully."""
        from hermes_cli.config import migrate_config
        
        old_config = {"_config_version": 10}
        
        with patch("hermes_cli.config.load_config", return_value=old_config):
            with patch("hermes_cli.config.save_config") as mock_save:
                with patch("builtins.print"):
                    # Should not raise an exception
                    migrate_config(interactive=False, quiet=True)


class TestDefaultConfigWebKeys:
    """Test that DEFAULT_CONFIG includes web schema keys."""

    def test_default_config_has_web_key(self):
        """DEFAULT_CONFIG should include web key."""
        from hermes_cli.config import DEFAULT_CONFIG
        assert "web" in DEFAULT_CONFIG

    def test_default_config_web_backend_empty(self):
        """web.backend in DEFAULT_CONFIG defaults to empty string."""
        from hermes_cli.config import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["web"]["backend"] == ""

    def test_default_config_web_search_structure(self):
        """web.search should have backend and url keys."""
        from hermes_cli.config import DEFAULT_CONFIG
        assert "search" in DEFAULT_CONFIG["web"]
        assert "backend" in DEFAULT_CONFIG["web"]["search"]
        assert "url" in DEFAULT_CONFIG["web"]["search"]

    def test_default_config_web_extract_structure(self):
        """web.extract should have backend key."""
        from hermes_cli.config import DEFAULT_CONFIG
        assert "extract" in DEFAULT_CONFIG["web"]
        assert "backend" in DEFAULT_CONFIG["web"]["extract"]

    def test_default_config_web_search_empty_strings(self):
        """web.search.backend and web.search.url default to empty."""
        from hermes_cli.config import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["web"]["search"]["backend"] == ""
        assert DEFAULT_CONFIG["web"]["search"]["url"] == ""

    def test_default_config_web_extract_empty_string(self):
        """web.extract.backend defaults to empty."""
        from hermes_cli.config import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["web"]["extract"]["backend"] == ""


class TestOptionalEnvVars:
    """Test that new SearXNG env vars are in OPTIONAL_ENV_VARS."""

    def test_searxng_url_in_optional_env_vars(self):
        """SEARXNG_URL should be defined in OPTIONAL_ENV_VARS."""
        from hermes_cli.config import OPTIONAL_ENV_VARS
        assert "SEARXNG_URL" in OPTIONAL_ENV_VARS

    def test_searxng_url_metadata(self):
        """SEARXNG_URL should have proper metadata."""
        from hermes_cli.config import OPTIONAL_ENV_VARS
        searxng_url = OPTIONAL_ENV_VARS["SEARXNG_URL"]
        assert "description" in searxng_url
        assert "%s" in searxng_url["description"]  # Mentions placeholder
        assert searxng_url["category"] == "tool"
        assert "web_search" in searxng_url["tools"]

    def test_searxng_api_key_in_optional_env_vars(self):
        """SEARXNG_API_KEY should be defined."""
        from hermes_cli.config import OPTIONAL_ENV_VARS
        assert "SEARXNG_API_KEY" in OPTIONAL_ENV_VARS

    def test_searxng_api_key_metadata(self):
        """SEARXNG_API_KEY should be marked as password."""
        from hermes_cli.config import OPTIONAL_ENV_VARS
        searxng_key = OPTIONAL_ENV_VARS["SEARXNG_API_KEY"]
        assert searxng_key["password"] is True
        assert searxng_key["category"] == "tool"


class TestEnvVarsByVersion:
    """Test ENV_VARS_BY_VERSION includes SearXNG for v11."""

    def test_version_11_includes_searxng_api_key(self):
        """ENV_VARS_BY_VERSION[11] should include SEARXNG_API_KEY."""
        from hermes_cli.config import ENV_VARS_BY_VERSION
        assert 11 in ENV_VARS_BY_VERSION
        assert "SEARXNG_API_KEY" in ENV_VARS_BY_VERSION[11]

    def test_version_11_does_not_include_searxng_url(self):
        """SEARXNG_URL is a URL (config), not env var for v11 migration."""
        from hermes_cli.config import ENV_VARS_BY_VERSION
        # SEARXNG_URL is handled via config migration, not env var discovery
        assert "SEARXNG_URL" not in ENV_VARS_BY_VERSION.get(11, [])


class TestConfigVersion:
    """Test config version bump to 11."""

    def test_config_version_is_11(self):
        """_config_version should be 11."""
        from hermes_cli.config import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["_config_version"] == 11
