"""Tests for SearXNG and Native extraction tools."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock


class TestSearXNGSearchTool:
    """Test searxng_search_tool functionality."""

    def test_check_searxng_available_with_env(self):
        """Test that check_searxng_available returns True when env var is set."""
        from tools.searxng_native_tools import check_searxng_available
        
        with patch.dict(os.environ, {"SEARXNG_URL": "https://searx.example.com"}):
            assert check_searxng_available() is True

    def test_check_searxng_available_without_env(self):
        """Test that check_searxng_available returns False when env var is not set."""
        from tools.searxng_native_tools import check_searxng_available
        
        with patch.dict(os.environ, {}, clear=True):
            # Mock empty config
            with patch("tools.searxng_native_tools._load_web_config", return_value={}):
                assert check_searxng_available() is False

    def test_searxng_search_no_config(self):
        """Test searxng_search_tool returns error when not configured."""
        from tools.searxng_native_tools import searxng_search_tool
        
        with patch.dict(os.environ, {}, clear=True):
            with patch("tools.searxng_native_tools._load_web_config", return_value={}):
                result = searxng_search_tool("test query")
                data = json.loads(result)
                assert data["success"] is False
                assert "no URL configured" in data["error"]

    def test_searxng_search_success(self):
        """Test successful SearXNG search."""
        from tools.searxng_native_tools import searxng_search_tool
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "content": "Content 1"},
                {"title": "Result 2", "url": "https://example.com/2", "content": "Content 2"},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        
        with patch.dict(os.environ, {"SEARXNG_URL": "https://searx.example.com/search?q=%s"}):
            with patch("httpx.Client") as mock_client:
                mock_client.return_value.__enter__.return_value.get.return_value = mock_response
                
                result = searxng_search_tool("test query", limit=2)
                data = json.loads(result)
                
                assert data["success"] is True
                assert len(data["data"]["web"]) == 2
                assert data["data"]["web"][0]["title"] == "Result 1"


class TestNativeExtractTool:
    """Test native_extract_tool functionality."""

    def test_check_native_extract_available(self):
        """Test that native extract is always available."""
        from tools.searxng_native_tools import check_native_extract_available
        
        assert check_native_extract_available() is True

    def test_native_extract_success(self):
        """Test successful native extraction."""
        from tools.searxng_native_tools import native_extract_tool
        
        mock_response = MagicMock()
        mock_response.text = "<html><body><h1>Test</h1><p>Content</p></body></html>"
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.raise_for_status = MagicMock()
        
        with patch("requests.Session") as mock_session:
            mock_session.return_value.__enter__.return_value.get.return_value = mock_response
            
            # Mock html_to_markdown as not available
            with patch.dict("sys.modules", {"html_to_markdown": None}):
                result = native_extract_tool(["https://example.com"])
                data = json.loads(result)
                
                assert data["success"] is True
                assert len(data["data"]) == 1
                assert "error" in data["data"][0]

    def test_native_extract_with_html_to_markdown(self):
        """Test native extraction when html-to-markdown is available."""
        from tools.searxng_native_tools import native_extract_tool
        
        mock_response = MagicMock()
        mock_response.text = "<html><body><h1>Test</h1></body></html>"
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.raise_for_status = MagicMock()
        
        mock_html_to_markdown = MagicMock()
        mock_html_to_markdown.convert.return_value = "# Test"
        
        with patch("requests.Session") as mock_session:
            mock_session.return_value.__enter__.return_value.get.return_value = mock_response
            
            with patch.dict("sys.modules", {"html_to_markdown": mock_html_to_markdown}):
                # Need to reload the module to pick up the import
                import importlib
                import tools.searxng_native_tools
                importlib.reload(tools.searxng_native_tools)
                
                result = tools.searxng_native_tools.native_extract_tool(["https://example.com"])
                data = json.loads(result)
                
                assert data["success"] is True
                assert len(data["data"]) == 1




class TestToolRegistration:
    """Test that tools are properly registered."""

    def test_searxng_search_registered(self):
        """Test searxng_search is in the registry."""
        # Import model_tools to trigger tool discovery
        import model_tools  # noqa: F401
        from tools.registry import registry
        
        assert "searxng_search" in registry._tools
        entry = registry._tools["searxng_search"]
        assert entry.toolset == "web"
        assert entry.emoji == "🔍"

    def test_native_extract_registered(self):
        """Test native_extract is in the registry."""
        # Import model_tools to trigger tool discovery
        import model_tools  # noqa: F401
        from tools.registry import registry
        
        assert "native_extract" in registry._tools
        entry = registry._tools["native_extract"]
        assert entry.toolset == "web"
        assert entry.emoji == "📄"
