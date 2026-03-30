#!/usr/bin/env python3
"""
Custom Web Tools: SearXNG Search and Native Extract

This module provides alternative web tools using:
- SearXNG: A free, self-hosted metasearch engine
- Native HTTP: Direct HTTP requests with HTML-to-markdown conversion

These tools are registered alongside the built-in web tools in the "web" toolset,
providing users with additional options for web search and content extraction.

Configuration:
- SearXNG: Set web.search.url in config.yaml or SEARXNG_URL env var
- Native: No API key required, uses direct HTTP requests

Usage:
    from tools.searxng_native_tools import searxng_search_tool, native_extract_tool
    
    # Search with SearXNG
    results = searxng_search_tool("Python machine learning", limit=5)
    
    # Extract content natively
    content = native_extract_tool(["https://example.com"])
"""

import json
import logging
import os
import re
from typing import List, Dict, Any
import httpx

from tools.registry import registry

logger = logging.getLogger(__name__)


def _load_web_config() -> dict:
    """Load web configuration from config.yaml."""
    try:
        from hermes_cli.config import load_config
        config = load_config()
        return config.get("web", {})
    except Exception:
        return {}


def _has_env(var: str) -> bool:
    """Check if an environment variable is set and non-empty."""
    return bool(os.getenv(var, "").strip())


# ─── SearXNG Search Tool ─────────────────────────────────────────────────────

SEARXNG_SEARCH_SCHEMA = {
    "name": "searxng_search",
    "description": "Search the web using a SearXNG instance. SearXNG is a free, self-hosted metasearch engine that aggregates results from multiple search engines. Configure via web.search.url in config.yaml or SEARXNG_URL environment variable.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5)",
                "default": 5,
                "minimum": 1,
                "maximum": 20
            }
        },
        "required": ["query"]
    }
}


def searxng_search_tool(query: str, limit: int = 5) -> str:
    """Search using a SearXNG instance.
    
    SearXNG is a free, self-hosted metasearch engine. This implementation
    supports both public and authenticated instances.
    
    Args:
        query (str): The search query
        limit (int): Maximum number of results to return (default: 5)
    
    Returns:
        str: JSON string containing search results in standard format
    """
    web = _load_web_config()
    
    # URL: config takes precedence over env var
    url_template = (
        web.get("search", {}).get("url", "").strip()
        or os.getenv("SEARXNG_URL", "").strip()
    )
    if not url_template:
        return json.dumps({
            "success": False,
            "error": "SearXNG backend selected but no URL configured. "
                     "Set web.search.url in config.yaml or SEARXNG_URL env var."
        })
    
    import urllib.parse
    search_url = url_template.replace("%s", urllib.parse.quote_plus(query))
    
    headers = {"Accept": "application/json"}
    api_key = os.getenv("SEARXNG_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(search_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        return json.dumps({"success": False, "error": f"SearXNG request failed: {e}"})
    except Exception as e:
        return json.dumps({"success": False, "error": f"SearXNG error: {e}"})
    
    results = data.get("results", [])[:limit]
    normalized = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("content", ""),
            "position": i + 1,
        }
        for i, r in enumerate(results)
    ]
    return json.dumps({"success": True, "data": {"web": normalized}}, ensure_ascii=False)


def check_searxng_available() -> bool:
    """Check if SearXNG is configured."""
    web = _load_web_config()
    searxng_url = web.get("search", {}).get("url", "") or os.getenv("SEARXNG_URL", "")
    return bool(searxng_url.strip())


# ─── Native HTTP Extract Tool ─────────────────────────────────────────────────

NATIVE_EXTRACT_SCHEMA = {
    "name": "native_extract",
    "description": "Extract content from web pages using native HTTP requests. Converts HTML to markdown using html-to-markdown library. No API key required. Use this as a fallback when other extraction backends are unavailable or for simple content extraction tasks.",
    "parameters": {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of URLs to extract content from (max 5 URLs per call)",
                "maxItems": 5
            }
        },
        "required": ["urls"]
    }
}


def native_extract_tool(urls: List[str]) -> str:
    """Extract web pages using plain HTTP requests.
    
    Uses requests library to fetch content and html-to-markdown (if available)
    to convert HTML to markdown. Falls back to crude regex HTML stripping if
    html-to-markdown is not installed.
    
    Args:
        urls (List[str]): URLs to extract content from
    
    Returns:
        str: JSON string with extracted documents
    """
    import requests
    try:
        import html_to_markdown
        _has_html_to_markdown = True
    except ImportError:
        _has_html_to_markdown = False
    
    results = []
    for url in urls[:5]:  # Max 5 URLs
        try:
            session = requests.Session()
            try:
                import certifi as _certifi
                session.verify = _certifi.where()
            except ImportError:
                pass  # requests defaults to its own bundle
            
            resp = session.get(
                url,
                headers={
                    "Accept": "application/json, text/markdown;q=0.9, text/html;q=0.8",
                    "User-Agent": "Mozilla/5.0 (compatible; HermesAgent/1.0)",
                },
                timeout=30,
                allow_redirects=True,
            )
            resp.raise_for_status()
            ct = resp.headers.get("Content-Type", "").lower()
            
            if "application/json" in ct or "text/markdown" in ct:
                content = resp.text
            elif _has_html_to_markdown:
                content = html_to_markdown.convert(resp.text)
            else:
                # Fallback: strip tags crudely
                content = re.sub(r"<[^>]+>", "", resp.text)
            
            results.append({
                "url": url,
                "title": "",
                "content": content,
                "error": None
            })
        except requests.exceptions.SSLError as e:
            logger.warning("Native extract SSL error for %s: %s", url, e)
            results.append({
                "url": url,
                "title": "",
                "content": "",
                "error": (
                    f"SSL certificate verification failed for {url}. "
                    "This may be a Python SSL configuration issue. "
                    f"Details: {e}"
                ),
            })
        except Exception as e:
            logger.warning("Native extract failed for %s: %s", url, e)
            results.append({
                "url": url,
                "title": "",
                "content": "",
                "error": str(e)
            })
    
    return json.dumps({"success": True, "data": results}, ensure_ascii=False)


def check_native_extract_available() -> bool:
    """Native extract is always available (no API key needed)."""
    return True


# ─── Tool Registration ───────────────────────────────────────────────────────

registry.register(
    name="searxng_search",
    toolset="web",
    schema=SEARXNG_SEARCH_SCHEMA,
    handler=lambda args, **kw: searxng_search_tool(
        args.get("query", ""),
        limit=args.get("limit", 5)
    ),
    check_fn=check_searxng_available,
    requires_env=["SEARXNG_URL"],
    emoji="🔍",
)

registry.register(
    name="native_extract",
    toolset="web",
    schema=NATIVE_EXTRACT_SCHEMA,
    handler=lambda args, **kw: native_extract_tool(
        args.get("urls", [])[:5] if isinstance(args.get("urls"), list) else []
    ),
    check_fn=check_native_extract_available,
    requires_env=[],
    emoji="📄",
)


if __name__ == "__main__":
    # Simple test/demo
    print("SearXNG Search Tool")
    print("===================")
    if check_searxng_available():
        print("✅ SearXNG is configured")
    else:
        print("❌ SearXNG not configured (set SEARXNG_URL or web.search.url)")
    
    print("\nNative Extract Tool")
    print("===================")
    print("✅ Native extract is always available (no API key needed)")
