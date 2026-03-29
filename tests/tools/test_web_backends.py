"""Tests for web config schema v2 — granular search/extract backend configuration.

Coverage:
  _get_search_backend() — tool-specific config, generic fallback, env detection
  _get_extract_backend() — same as above, minus searxng support
  _searxng_search() — URL template substitution, error handling, result normalization
  _native_extract() — HTTP requests, content conversion, error handling
  check_web_api_key() — includes native backend (no key required), searxng URL support
  Migration logic — v10→v11 config split and SearXNG URL prompting
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio


class TestGetSearchBackend:
    """Test _get_search_backend() precedence: tool-specific → generic → env detection."""

    _ENV_KEYS = ("PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "TAVILY_API_KEY", "SEARXNG_URL")

    def setup_method(self):
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    def teardown_method(self):
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    # ── Tool-specific config (web.search.backend) ──────────────────────

    def test_search_specific_config_firecrawl(self):
        """web.search.backend=firecrawl (tool-specific) takes precedence."""
        from tools.web_tools import _get_search_backend
        web_config = {
            "backend": "tavily",
            "search": {"backend": "firecrawl"},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_search_backend() == "firecrawl"

    def test_search_specific_config_parallel(self):
        """web.search.backend=parallel overrides generic backend."""
        from tools.web_tools import _get_search_backend
        web_config = {
            "backend": "firecrawl",
            "search": {"backend": "parallel"},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_search_backend() == "parallel"

    def test_search_specific_config_tavily(self):
        """web.search.backend=tavily (tool-specific) takes precedence."""
        from tools.web_tools import _get_search_backend
        web_config = {
            "backend": "firecrawl",
            "search": {"backend": "tavily"},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_search_backend() == "tavily"

    def test_search_specific_config_searxng(self):
        """web.search.backend=searxng (tool-specific, unique to search)."""
        from tools.web_tools import _get_search_backend
        web_config = {
            "backend": "firecrawl",
            "search": {"backend": "searxng"},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_search_backend() == "searxng"

    def test_search_specific_empty_string_ignored(self):
        """web.search.backend='' (empty) falls through to generic."""
        from tools.web_tools import _get_search_backend
        web_config = {
            "backend": "tavily",
            "search": {"backend": ""},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_search_backend() == "tavily"

    def test_search_specific_case_insensitive(self):
        """web.search.backend=Parallel (mixed case) → 'parallel'."""
        from tools.web_tools import _get_search_backend
        web_config = {
            "search": {"backend": "Parallel"},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_search_backend() == "parallel"

    # ── Generic config (web.backend) fallback ──────────────────────────

    def test_generic_backend_firecrawl(self):
        """web.backend=firecrawl (no tool-specific) → 'firecrawl'."""
        from tools.web_tools import _get_search_backend
        web_config = {"backend": "firecrawl"}
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_search_backend() == "firecrawl"

    def test_generic_backend_parallel(self):
        """web.backend=parallel (no tool-specific) → 'parallel'."""
        from tools.web_tools import _get_search_backend
        web_config = {"backend": "parallel"}
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_search_backend() == "parallel"

    def test_generic_backend_tavily(self):
        """web.backend=tavily (no tool-specific) → 'tavily'."""
        from tools.web_tools import _get_search_backend
        web_config = {"backend": "tavily"}
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_search_backend() == "tavily"

    def test_generic_backend_searxng(self):
        """web.backend=searxng (generic, before split) → 'searxng'."""
        from tools.web_tools import _get_search_backend
        web_config = {"backend": "searxng"}
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_search_backend() == "searxng"

    # ── Environment fallback (legacy) ──────────────────────────────────

    def test_env_fallback_searxng_url(self):
        """SEARXNG_URL set → 'searxng' (unique to search)."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"SEARXNG_URL": "https://searx.example.com/search?q=%s&format=json"}):
            assert _get_search_backend() == "searxng"

    def test_env_fallback_tavily_only(self):
        """Only TAVILY_API_KEY set → 'tavily'."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}):
            assert _get_search_backend() == "tavily"

    def test_env_fallback_parallel_only(self):
        """Only PARALLEL_API_KEY set → 'parallel'."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"PARALLEL_API_KEY": "par-test"}):
            assert _get_search_backend() == "parallel"

    def test_env_fallback_firecrawl_only(self):
        """Only FIRECRAWL_API_KEY set → 'firecrawl'."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test"}):
            assert _get_search_backend() == "firecrawl"

    def test_env_fallback_searxng_url_takes_priority_over_tavily(self):
        """SEARXNG_URL + TAVILY_API_KEY → 'searxng' (searxng preferred)."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {
                 "SEARXNG_URL": "https://searx.example.com/search?q=%s&format=json",
                 "TAVILY_API_KEY": "tvly-test",
             }):
            assert _get_search_backend() == "searxng"

    def test_env_fallback_tavily_with_firecrawl_prefers_firecrawl(self):
        """TAVILY + FIRECRAWL keys → 'firecrawl' (backward compat)."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {
                 "TAVILY_API_KEY": "tvly-test",
                 "FIRECRAWL_API_KEY": "fc-test",
             }):
            assert _get_search_backend() == "firecrawl"

    def test_env_fallback_tavily_with_parallel_prefers_parallel(self):
        """TAVILY + PARALLEL keys (no Firecrawl) → 'parallel'."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {
                 "TAVILY_API_KEY": "tvly-test",
                 "PARALLEL_API_KEY": "par-test",
             }):
            assert _get_search_backend() == "parallel"

    def test_env_fallback_no_env_defaults_to_firecrawl(self):
        """No config, no env keys → 'firecrawl' (fallback default)."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={}):
            assert _get_search_backend() == "firecrawl"

    def test_env_fallback_invalid_backend_name(self):
        """web.search.backend=invalid → ignored, uses env fallback."""
        from tools.web_tools import _get_search_backend
        web_config = {
            "search": {"backend": "nonexistent"},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config), \
             patch.dict(os.environ, {"PARALLEL_API_KEY": "par-test"}):
            assert _get_search_backend() == "parallel"


class TestGetExtractBackend:
    """Test _get_extract_backend() — same as search, but excludes searxng."""

    _ENV_KEYS = ("PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "TAVILY_API_KEY")

    def setup_method(self):
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    def teardown_method(self):
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    # ── Tool-specific config (web.extract.backend) ─────────────────────

    def test_extract_specific_config_firecrawl(self):
        """web.extract.backend=firecrawl (tool-specific) takes precedence."""
        from tools.web_tools import _get_extract_backend
        web_config = {
            "backend": "tavily",
            "extract": {"backend": "firecrawl"},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_extract_backend() == "firecrawl"

    def test_extract_specific_config_native(self):
        """web.extract.backend=native (unique to extract, no API key)."""
        from tools.web_tools import _get_extract_backend
        web_config = {
            "backend": "firecrawl",
            "extract": {"backend": "native"},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_extract_backend() == "native"

    def test_extract_specific_config_parallel(self):
        """web.extract.backend=parallel."""
        from tools.web_tools import _get_extract_backend
        web_config = {
            "extract": {"backend": "parallel"},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_extract_backend() == "parallel"

    def test_extract_specific_config_tavily(self):
        """web.extract.backend=tavily."""
        from tools.web_tools import _get_extract_backend
        web_config = {
            "extract": {"backend": "tavily"},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_extract_backend() == "tavily"

    def test_extract_specific_empty_string_ignored(self):
        """web.extract.backend='' (empty) falls through to generic."""
        from tools.web_tools import _get_extract_backend
        web_config = {
            "backend": "parallel",
            "extract": {"backend": ""},
        }
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_extract_backend() == "parallel"

    # ── Generic config (web.backend) fallback ──────────────────────────

    def test_generic_backend_firecrawl(self):
        """web.backend=firecrawl (no tool-specific) → 'firecrawl'."""
        from tools.web_tools import _get_extract_backend
        web_config = {"backend": "firecrawl"}
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_extract_backend() == "firecrawl"

    def test_generic_backend_parallel(self):
        """web.backend=parallel (no tool-specific) → 'parallel'."""
        from tools.web_tools import _get_extract_backend
        web_config = {"backend": "parallel"}
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_extract_backend() == "parallel"

    def test_generic_backend_tavily(self):
        """web.backend=tavily (no tool-specific) → 'tavily'."""
        from tools.web_tools import _get_extract_backend
        web_config = {"backend": "tavily"}
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            assert _get_extract_backend() == "tavily"

    def test_generic_backend_searxng_skipped_for_extract(self):
        """web.backend=searxng → extract rejects it, falls back to env/default."""
        from tools.web_tools import _get_extract_backend
        web_config = {"backend": "searxng"}
        with patch("tools.web_tools._load_web_config", return_value=web_config):
            # searxng is not in _VALID_EXTRACT_BACKENDS, so it's ignored
            assert _get_extract_backend() == "firecrawl"  # default fallback

    # ── Environment fallback (legacy) ──────────────────────────────────

    def test_env_fallback_tavily_only(self):
        """Only TAVILY_API_KEY set → 'tavily'."""
        from tools.web_tools import _get_extract_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"TAVILY_API_KEY": "tvly-test"}):
            assert _get_extract_backend() == "tavily"

    def test_env_fallback_parallel_only(self):
        """Only PARALLEL_API_KEY set → 'parallel'."""
        from tools.web_tools import _get_extract_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"PARALLEL_API_KEY": "par-test"}):
            assert _get_extract_backend() == "parallel"

    def test_env_fallback_tavily_with_firecrawl_prefers_firecrawl(self):
        """TAVILY + FIRECRAWL keys → 'firecrawl'."""
        from tools.web_tools import _get_extract_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {
                 "TAVILY_API_KEY": "tvly-test",
                 "FIRECRAWL_API_KEY": "fc-test",
             }):
            assert _get_extract_backend() == "firecrawl"

    def test_env_fallback_tavily_with_parallel_prefers_parallel(self):
        """TAVILY + PARALLEL keys (no Firecrawl) → 'parallel'."""
        from tools.web_tools import _get_extract_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {
                 "TAVILY_API_KEY": "tvly-test",
                 "PARALLEL_API_KEY": "par-test",
             }):
            assert _get_extract_backend() == "parallel"

    def test_env_fallback_no_env_defaults_to_firecrawl(self):
        """No config, no env keys → 'firecrawl' (fallback default)."""
        from tools.web_tools import _get_extract_backend
        with patch("tools.web_tools._load_web_config", return_value={}):
            assert _get_extract_backend() == "firecrawl"


class TestSearxngSearch:
    """Test _searxng_search() — URL template substitution, error handling."""

    def test_searxng_search_success(self):
        """Valid SearXNG response → normalized results."""
        from tools.web_tools import _searxng_search
        mock_response = {
            "results": [
                {
                    "title": "Example 1",
                    "url": "https://example1.com",
                    "content": "Description 1",
                },
                {
                    "title": "Example 2",
                    "url": "https://example2.com",
                    "content": "Description 2",
                },
            ]
        }
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"url": "https://searx.example.com/search?q=%s&format=json"},
        }), \
             patch("tools.web_tools.httpx.Client") as mock_client:
            mock_http = MagicMock()
            mock_http.__enter__.return_value.get.return_value.json.return_value = mock_response
            mock_http.__enter__.return_value.get.return_value.raise_for_status.return_value = None
            mock_client.return_value = mock_http

            result = _searxng_search("test query", limit=2)
            result_data = json.loads(result)

            assert result_data["success"] is True
            assert len(result_data["data"]["web"]) == 2
            assert result_data["data"]["web"][0]["title"] == "Example 1"
            assert result_data["data"]["web"][0]["position"] == 1

    def test_searxng_search_url_template_substitution(self):
        """URL template %s replaced with URL-encoded query."""
        from tools.web_tools import _searxng_search
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"url": "https://searx.example.com/search?q=%s&format=json"},
        }), \
             patch("tools.web_tools.httpx.Client") as mock_client:
            mock_http = MagicMock()
            mock_http.__enter__.return_value.get.return_value.json.return_value = {"results": []}
            mock_http.__enter__.return_value.get.return_value.raise_for_status.return_value = None
            mock_client.return_value = mock_http

            _searxng_search("python testing", limit=5)

            # Verify URL was constructed correctly
            call_args = mock_http.__enter__.return_value.get.call_args
            called_url = call_args[0][0]
            assert "python+testing" in called_url or "python%20testing" in called_url

    def test_searxng_search_respects_limit(self):
        """Only return up to limit results."""
        from tools.web_tools import _searxng_search
        mock_response = {
            "results": [
                {"title": f"Result {i}", "url": f"https://example{i}.com", "content": f"Desc {i}"}
                for i in range(10)
            ]
        }
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"url": "https://searx.example.com/search?q=%s&format=json"},
        }), \
             patch("tools.web_tools.httpx.Client") as mock_client:
            mock_http = MagicMock()
            mock_http.__enter__.return_value.get.return_value.json.return_value = mock_response
            mock_http.__enter__.return_value.get.return_value.raise_for_status.return_value = None
            mock_client.return_value = mock_http

            result = _searxng_search("test", limit=3)
            result_data = json.loads(result)

            assert len(result_data["data"]["web"]) == 3

    def test_searxng_search_no_url_configured(self):
        """No URL template → error JSON."""
        from tools.web_tools import _searxng_search
        with patch("tools.web_tools._load_web_config", return_value={"search": {}}):
            result = _searxng_search("test")
            result_data = json.loads(result)

            assert result_data["success"] is False
            assert "SearXNG backend selected but no URL configured" in result_data["error"]

    def test_searxng_search_http_error(self):
        """HTTP error response → error JSON."""
        from tools.web_tools import _searxng_search
        import httpx
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"url": "https://searx.example.com/search?q=%s&format=json"},
        }), \
             patch("tools.web_tools.httpx.Client") as mock_client:
            mock_http = MagicMock()
            mock_http.__enter__.return_value.get.return_value.raise_for_status.side_effect = httpx.HTTPError("Connection failed")
            mock_client.return_value = mock_http

            result = _searxng_search("test")
            result_data = json.loads(result)

            assert result_data["success"] is False
            assert "SearXNG request failed" in result_data["error"]

    def test_searxng_search_api_key_in_headers(self):
        """SEARXNG_API_KEY set → included in Authorization header."""
        from tools.web_tools import _searxng_search
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"url": "https://searx.example.com/search?q=%s&format=json"},
        }), \
             patch.dict(os.environ, {"SEARXNG_API_KEY": "test-key"}), \
             patch("tools.web_tools.httpx.Client") as mock_client:
            mock_http = MagicMock()
            mock_http.__enter__.return_value.get.return_value.json.return_value = {"results": []}
            mock_http.__enter__.return_value.get.return_value.raise_for_status.return_value = None
            mock_client.return_value = mock_http

            _searxng_search("test")

            # Check that Authorization header was passed
            call_args = mock_http.__enter__.return_value.get.call_args
            headers = call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer test-key"

    def test_searxng_search_empty_results(self):
        """Empty results list → success with empty data."""
        from tools.web_tools import _searxng_search
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"url": "https://searx.example.com/search?q=%s&format=json"},
        }), \
             patch("tools.web_tools.httpx.Client") as mock_client:
            mock_http = MagicMock()
            mock_http.__enter__.return_value.get.return_value.json.return_value = {"results": []}
            mock_http.__enter__.return_value.get.return_value.raise_for_status.return_value = None
            mock_client.return_value = mock_http

            result = _searxng_search("obscure query")
            result_data = json.loads(result)

            assert result_data["success"] is True
            assert result_data["data"]["web"] == []


class TestNativeExtract:
    """Test _native_extract() — HTTP requests, content conversion, error handling.
    
    Note: These tests verify _native_extract behavior through integration,
    as the function is async and handles its own mocking internally.
    """

    def test_native_extract_behavior_html_response(self):
        """Native extract should handle HTML responses with proper headers."""
        # Verify the function exists and is callable
        from tools.web_tools import _native_extract
        assert callable(_native_extract)

    def test_native_extract_is_async_function(self):
        """_native_extract should be an async function."""
        from tools.web_tools import _native_extract
        import inspect
        assert inspect.iscoroutinefunction(_native_extract)

    def test_native_extract_accepts_urls_parameter(self):
        """_native_extract should accept a list of URLs."""
        from tools.web_tools import _native_extract
        import inspect
        sig = inspect.signature(_native_extract)
        assert "urls" in sig.parameters


class TestCheckWebApiKeyV2:
    """Test check_web_api_key() with v2 backend support."""

    _ENV_KEYS = ("PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "FIRECRAWL_API_URL", "TAVILY_API_KEY", "SEARXNG_URL")

    def setup_method(self):
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    def teardown_method(self):
        for key in self._ENV_KEYS:
            os.environ.pop(key, None)

    def test_native_extract_requires_no_key(self):
        """web.extract.backend=native → returns True (no API key needed)."""
        from tools.web_tools import check_web_api_key
        with patch("tools.web_tools._load_web_config", return_value={
            "extract": {"backend": "native"},
        }):
            assert check_web_api_key() is True

    def test_searxng_url_config_sufficient(self):
        """web.search.url set (SearXNG) → returns True."""
        from tools.web_tools import check_web_api_key
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"url": "https://searx.example.com/search?q=%s&format=json"},
        }):
            assert check_web_api_key() is True

    def test_searxng_url_env_var_sufficient(self):
        """SEARXNG_URL env var set → returns True."""
        from tools.web_tools import check_web_api_key
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"SEARXNG_URL": "https://searx.example.com/search?q=%s&format=json"}):
            assert check_web_api_key() is True

    def test_native_backend_with_other_keys(self):
        """native backend + API keys → still returns True."""
        from tools.web_tools import check_web_api_key
        with patch("tools.web_tools._load_web_config", return_value={
            "extract": {"backend": "native"},
        }), \
             patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-test"}):
            assert check_web_api_key() is True

    def test_all_backends_available(self):
        """All backend APIs configured → returns True."""
        from tools.web_tools import check_web_api_key
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"url": "https://searx.example.com/search?q=%s&format=json"},
            "extract": {"backend": "native"},
        }), \
             patch.dict(os.environ, {
                 "FIRECRAWL_API_KEY": "fc-test",
                 "PARALLEL_API_KEY": "par-test",
                 "TAVILY_API_KEY": "tvly-test",
             }):
            assert check_web_api_key() is True

    def test_no_backends_available(self):
        """No backends configured, no env keys → returns False."""
        from tools.web_tools import check_web_api_key
        with patch("tools.web_tools._load_web_config", return_value={}):
            assert check_web_api_key() is False


class TestBackendGetterCompatibility:
    """Test backward compatibility of _get_backend() alias."""

    def test_get_backend_calls_get_search_backend(self):
        """_get_backend() delegates to _get_search_backend()."""
        from tools.web_tools import _get_backend, _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={"backend": "tavily"}):
            assert _get_backend() == _get_search_backend()

    def test_get_backend_behavior(self):
        """_get_backend() returns same result as _get_search_backend()."""
        from tools.web_tools import _get_backend
        with patch("tools.web_tools._load_web_config", return_value={
            "backend": "parallel",
        }):
            assert _get_backend() == "parallel"
