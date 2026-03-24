# Web Config Schema v2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the `web:` config section to support per-tool backend selection (`web.search.backend` / `web.extract.backend`), add a SearXNG search backend, and add a native (no-API-key) extract backend.

**Architecture:** The new `_get_search_backend()` / `_get_extract_backend()` helpers replace the single `_get_backend()` call-site in each tool, reading the nested config with a clear three-tier precedence (tool-specific → `web.backend` → env-based fallback). The native extract backend is a self-contained helper that uses `requests` + `html-to-markdown`. The SearXNG search backend is likewise self-contained. `hermes tools` grows a SearXNG provider entry with a free-text URL prompt; detection of "native" for extract is implicit (no API key required).

**Tech Stack:** Python 3.11, `requests` (already in deps), `html-to-markdown` (new dep), `pytest`/`unittest.mock` for tests.

---

## File Map

| File | Change |
|------|--------|
| `tools/web_tools.py` | Add `_get_search_backend()`, `_get_extract_backend()`, `_searxng_search()`, `_native_extract()`. Update `web_search_tool` and `web_extract_tool` dispatch. Update `check_web_api_key()`. Update registry `requires_env`. |
| `hermes_cli/config.py` | Add `web.search` and `web.extract` sub-dicts to `DEFAULT_CONFIG`. Add `SEARXNG_API_KEY` to `OPTIONAL_ENV_VARS` and `ENV_VARS_BY_VERSION[11]`. Bump `_config_version` to 11. Add v10→v11 migration block. |
| `hermes_cli/tools_config.py` | Add SearXNG provider entry to the `"web"` toolset definition. Update `_is_provider_active()` and `_configure_provider()` / `_reconfigure_provider()` for `web_search_backend` key (vs legacy `web_backend`). |
| `pyproject.toml` | Add `html-to-markdown` to `dependencies`. |
| `tests/tools/test_web_tools_config.py` | Add tests for `_get_search_backend()`, `_get_extract_backend()`, `check_web_api_key()` (native path). |
| `tests/tools/test_web_tools_searxng.py` | New file — unit tests for `_searxng_search()`. |
| `tests/tools/test_web_tools_native_extract.py` | New file — unit tests for `_native_extract()`. |
| `tests/hermes_cli/test_config.py` | Add v10→v11 migration tests. |

---

## Chunk 1: pyproject.toml + native extract backend

### Task 1: Add `html-to-markdown` dependency

**Files:**
- Modify: `pyproject.toml` (line ~23, in `dependencies`)

- [ ] **Step 1: Write the failing import test**

```python
# tests/tools/test_web_tools_native_extract.py
def test_html_to_markdown_importable():
    """html-to-markdown library must be installed."""
    import html_to_markdown  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source venv/bin/activate
python -m pytest tests/tools/test_web_tools_native_extract.py::test_html_to_markdown_importable -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'html_to_markdown'`

- [ ] **Step 3: Add dependency to pyproject.toml**

In `pyproject.toml`, in the `dependencies` list after `"requests"`, add:

```toml
  "html-to-markdown",
```

- [ ] **Step 4: Install the new dependency**

```bash
source venv/bin/activate
pip install html-to-markdown
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest tests/tools/test_web_tools_native_extract.py::test_html_to_markdown_importable -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/tools/test_web_tools_native_extract.py
git commit -m "feat: add html-to-markdown dependency for native web extract backend"
```

---

### Task 2: Implement `_native_extract()`

**Files:**
- Modify: `tools/web_tools.py` (add after the `_parallel_extract` function, around line 665)
- Test: `tests/tools/test_web_tools_native_extract.py`

#### What `_native_extract()` does

```python
async def _native_extract(urls: List[str]) -> List[Dict[str, Any]]:
    """Extract content from URLs using requests + html-to-markdown (no API key)."""
```

Per-URL logic (sync, but function is async to match the other backend signatures):

1. Call `check_website_access(url)` — if blocked, append error result and `continue`.
2. Make a `requests.get(url, headers={"Accept": "application/json, text/markdown, text/html"}, timeout=15)` call inside `asyncio.to_thread()` to avoid blocking.
3. Detect content type from `response.headers.get("Content-Type", "")`:
   - If `application/json` or `text/markdown` → `content = response.text`; `title = url`
   - Otherwise → parse with `html-to-markdown`:
     ```python
     import html_to_markdown
     content = html_to_markdown.convert(response.text)
     ```
     Extract `<title>` from raw HTML for the `title` field using a simple regex `re.search(r"<title[^>]*>(.*?)</title>", response.text, re.IGNORECASE | re.DOTALL)`.
4. On `requests.exceptions.RequestException` → append error result.
5. Return list of `{"url": str, "title": str, "content": str, "error": str}` dicts (same shape as other backends).

- [ ] **Step 1: Write failing tests**

```python
# tests/tools/test_web_tools_native_extract.py
import pytest
import asyncio
from unittest.mock import patch, MagicMock


class TestNativeExtract:
    """Unit tests for _native_extract()."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_json_content_type_returned_directly(self):
        """JSON response → content returned as-is, no markdown conversion."""
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = '{"key": "value"}'
        mock_resp.raise_for_status = MagicMock()

        with patch("tools.web_tools.check_website_access", return_value=None), \
             patch("tools.web_tools.is_safe_url", return_value=True), \
             patch("asyncio.to_thread", new=lambda fn, *a, **kw: asyncio.coroutine(lambda: fn(*a, **kw))()):
            # Use simpler approach: mock requests.get directly
            import tools.web_tools as wt
            with patch("requests.get", return_value=mock_resp):
                results = self._run(wt._native_extract(["https://api.example.com/data"]))
        assert len(results) == 1
        assert results[0]["content"] == '{"key": "value"}'
        assert results[0]["error"] == ""

    def test_html_converted_to_markdown(self):
        """HTML response → converted via html-to-markdown."""
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_resp.text = "<html><head><title>Hello World</title></head><body><h1>Hi</h1></body></html>"
        mock_resp.raise_for_status = MagicMock()

        with patch("tools.web_tools.check_website_access", return_value=None), \
             patch("requests.get", return_value=mock_resp):
            import tools.web_tools as wt
            results = self._run(wt._native_extract(["https://example.com"]))
        assert len(results) == 1
        assert "Hi" in results[0]["content"]
        assert results[0]["title"] == "Hello World"
        assert results[0]["error"] == ""

    def test_text_markdown_content_type_returned_directly(self):
        """text/markdown response → returned as-is."""
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/markdown"}
        mock_resp.text = "# My Doc\n\nSome content."
        mock_resp.raise_for_status = MagicMock()

        with patch("tools.web_tools.check_website_access", return_value=None), \
             patch("requests.get", return_value=mock_resp):
            import tools.web_tools as wt
            results = self._run(wt._native_extract(["https://example.com/README.md"]))
        assert results[0]["content"] == "# My Doc\n\nSome content."
        assert results[0]["error"] == ""

    def test_website_policy_block(self):
        """Blocked URL → error result, no HTTP request."""
        import tools.web_tools as wt
        block = {"message": "Blocked by policy", "host": "bad.com", "rule": "r1", "source": "blocklist"}
        with patch("tools.web_tools.check_website_access", return_value=block), \
             patch("requests.get") as mock_get:
            results = self._run(wt._native_extract(["https://bad.com/page"]))
        mock_get.assert_not_called()
        assert "Blocked" in results[0]["error"]

    def test_request_exception_yields_error(self):
        """Network error → error field populated, no crash."""
        import requests
        import tools.web_tools as wt
        with patch("tools.web_tools.check_website_access", return_value=None), \
             patch("requests.get", side_effect=requests.exceptions.ConnectionError("timeout")):
            results = self._run(wt._native_extract(["https://unreachable.example.com"]))
        assert results[0]["error"] != ""
        assert results[0]["content"] == ""

    def test_multiple_urls_processed(self):
        """Multiple URLs → one result per URL."""
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "text/markdown"}
        mock_resp.text = "content"
        mock_resp.raise_for_status = MagicMock()

        import tools.web_tools as wt
        with patch("tools.web_tools.check_website_access", return_value=None), \
             patch("requests.get", return_value=mock_resp):
            results = self._run(wt._native_extract([
                "https://a.example.com",
                "https://b.example.com",
            ]))
        assert len(results) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate
python -m pytest tests/tools/test_web_tools_native_extract.py -v
```

Expected: All `FAILED` — `_native_extract` not defined.

- [ ] **Step 3: Implement `_native_extract()` in `tools/web_tools.py`**

Add this function after the `_parallel_extract` definition (around line 665). Add `import requests` at the top of the function body (requests is already in deps; also add `import html_to_markdown` locally to keep the optional import contained):

```python
async def _native_extract(urls: List[str]) -> List[Dict[str, Any]]:
    """Extract content from URLs using only requests + html-to-markdown (no API key needed).

    Returns the same per-URL dict format as other backends:
        {"url": str, "title": str, "content": str, "error": str}
    """
    import requests as _requests
    import html_to_markdown as _h2m

    results: List[Dict[str, Any]] = []

    for url in urls:
        # Website policy check
        blocked = check_website_access(url)
        if blocked:
            logger.info("Blocked _native_extract for %s by rule %s", blocked["host"], blocked["rule"])
            results.append({
                "url": url, "title": "", "content": "",
                "error": blocked["message"],
                "blocked_by_policy": {"host": blocked["host"], "rule": blocked["rule"], "source": blocked["source"]},
            })
            continue

        try:
            response = await asyncio.to_thread(
                _requests.get,
                url,
                headers={"Accept": "application/json, text/markdown, text/html"},
                timeout=15,
            )
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "").lower()

            if "application/json" in content_type or "text/markdown" in content_type:
                content = response.text
                title = url
            else:
                # HTML (or unknown) → convert to markdown
                raw_html = response.text
                content = _h2m.convert(raw_html)
                title_match = re.search(
                    r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL
                )
                title = title_match.group(1).strip() if title_match else url

            results.append({"url": url, "title": title, "content": content, "error": ""})

        except _requests.exceptions.RequestException as exc:
            logger.warning("_native_extract failed for %s: %s", url, exc)
            results.append({"url": url, "title": "", "content": "", "error": str(exc)})

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/tools/test_web_tools_native_extract.py -v
```

Expected: All `PASSED`

- [ ] **Step 5: Commit**

```bash
git add tools/web_tools.py tests/tools/test_web_tools_native_extract.py
git commit -m "feat: add _native_extract() backend using requests + html-to-markdown"
```

---

## Chunk 2: Backend selection helpers + SearXNG search

### Task 3: Add `_get_search_backend()` and `_get_extract_backend()`

**Files:**
- Modify: `tools/web_tools.py` (replace `_get_backend()` call-sites; add two new helpers alongside it)
- Test: `tests/tools/test_web_tools_config.py` (extend existing file)

#### Precedence logic

```
_get_search_backend():
  1. web.search.backend (if set and valid)
  2. web.backend (if set and valid)
  3. env-based fallback (existing logic from _get_backend())

_get_extract_backend():
  1. web.extract.backend (if set and valid)
  2. web.backend (if set and valid)
  3. env-based fallback (existing logic from _get_backend())
```

Valid values for search: `"parallel"`, `"firecrawl"`, `"tavily"`, `"searxng"`
Valid values for extract: `"parallel"`, `"firecrawl"`, `"tavily"`, `"native"`

The existing `_get_backend()` function is **kept** for backward compat (the env-based fallback logic is factored into a private `_env_fallback_backend()` helper to avoid duplication).

- [ ] **Step 1: Write failing tests** (extend `tests/tools/test_web_tools_config.py`)

Add a new test class `TestGetSearchBackend` and `TestGetExtractBackend` at the end of the file:

```python
class TestGetSearchBackend:
    """Tests for _get_search_backend() — tool-specific backend selection."""

    # ── web.search.backend takes precedence ──────────────────────────

    def test_search_specific_key_wins_over_web_backend(self):
        """web.search.backend overrides web.backend for search."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={
            "backend": "firecrawl",
            "search": {"backend": "searxng", "url": "https://searx.example.com/search?q=%s"},
        }):
            assert _get_search_backend() == "searxng"

    def test_search_falls_back_to_web_backend(self):
        """No web.search.backend → falls back to web.backend."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={"backend": "tavily"}):
            assert _get_search_backend() == "tavily"

    def test_search_env_fallback_when_nothing_set(self):
        """No config at all → env-based fallback (TAVILY_API_KEY present)."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"TAVILY_API_KEY": "tv-key"}, clear=False):
            for key in ("FIRECRAWL_API_KEY", "FIRECRAWL_API_URL", "PARALLEL_API_KEY"):
                os.environ.pop(key, None)
            assert _get_search_backend() == "tavily"

    def test_invalid_search_backend_ignored(self):
        """Unknown value in web.search.backend → skip and fall through."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={
            "backend": "firecrawl",
            "search": {"backend": "bogus"},
        }):
            assert _get_search_backend() == "firecrawl"

    def test_native_is_not_valid_for_search(self):
        """'native' is not a valid search backend; treated as unknown."""
        from tools.web_tools import _get_search_backend
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"backend": "native"},
            "backend": "parallel",
        }):
            assert _get_search_backend() == "parallel"


class TestGetExtractBackend:
    """Tests for _get_extract_backend() — tool-specific backend selection."""

    def test_extract_specific_key_wins_over_web_backend(self):
        """web.extract.backend overrides web.backend for extract."""
        from tools.web_tools import _get_extract_backend
        with patch("tools.web_tools._load_web_config", return_value={
            "backend": "firecrawl",
            "extract": {"backend": "native"},
        }):
            assert _get_extract_backend() == "native"

    def test_extract_falls_back_to_web_backend(self):
        """No web.extract.backend → falls back to web.backend."""
        from tools.web_tools import _get_extract_backend
        with patch("tools.web_tools._load_web_config", return_value={"backend": "parallel"}):
            assert _get_extract_backend() == "parallel"

    def test_searxng_is_not_valid_for_extract(self):
        """'searxng' is not valid for extract; treated as unknown, falls through."""
        from tools.web_tools import _get_extract_backend
        with patch("tools.web_tools._load_web_config", return_value={
            "extract": {"backend": "searxng"},
            "backend": "tavily",
        }):
            assert _get_extract_backend() == "tavily"

    def test_native_is_valid_for_extract(self):
        """'native' is a valid extract backend."""
        from tools.web_tools import _get_extract_backend
        with patch("tools.web_tools._load_web_config", return_value={
            "extract": {"backend": "native"},
        }):
            assert _get_extract_backend() == "native"

    def test_extract_env_fallback_when_nothing_set(self):
        """No config → env-based fallback."""
        from tools.web_tools import _get_extract_backend
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"PARALLEL_API_KEY": "par-key"}, clear=False):
            for key in ("FIRECRAWL_API_KEY", "FIRECRAWL_API_URL", "TAVILY_API_KEY"):
                os.environ.pop(key, None)
            assert _get_extract_backend() == "parallel"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/tools/test_web_tools_config.py::TestGetSearchBackend tests/tools/test_web_tools_config.py::TestGetExtractBackend -v
```

Expected: `FAILED` — `_get_search_backend` / `_get_extract_backend` not defined.

- [ ] **Step 3: Implement the helpers in `tools/web_tools.py`**

Replace the `_get_backend()` function block (lines 69–91) with:

```python
# ─── Backend Selection ────────────────────────────────────────────────────────

_VALID_SEARCH_BACKENDS = frozenset({"parallel", "firecrawl", "tavily", "searxng"})
_VALID_EXTRACT_BACKENDS = frozenset({"parallel", "firecrawl", "tavily", "native"})


def _env_fallback_backend() -> str:
    """Return best backend based solely on which API keys are present.

    Used when neither web.search.backend / web.extract.backend nor web.backend
    is configured. Preserves existing behaviour from the original _get_backend().
    """
    has_firecrawl = _has_env("FIRECRAWL_API_KEY") or _has_env("FIRECRAWL_API_URL")
    has_parallel = _has_env("PARALLEL_API_KEY")
    has_tavily = _has_env("TAVILY_API_KEY")

    if has_tavily and not has_firecrawl and not has_parallel:
        return "tavily"
    if has_parallel and not has_firecrawl:
        return "parallel"
    return "firecrawl"


def _get_backend() -> str:
    """Legacy helper — returns backend for callers that don't distinguish search/extract.

    Reads ``web.backend`` with env-based fallback.  Kept for backward compat.
    """
    web_cfg = _load_web_config()
    configured = web_cfg.get("backend", "").lower().strip()
    if configured in _VALID_SEARCH_BACKENDS | _VALID_EXTRACT_BACKENDS:
        return configured
    return _env_fallback_backend()


def _get_search_backend() -> str:
    """Determine which backend to use for web_search.

    Precedence:
      1. web.search.backend (tool-specific override)
      2. web.backend (shared fallback)
      3. env-based auto-detection
    """
    web_cfg = _load_web_config()
    specific = web_cfg.get("search", {}).get("backend", "").lower().strip()
    if specific in _VALID_SEARCH_BACKENDS:
        return specific
    shared = web_cfg.get("backend", "").lower().strip()
    if shared in _VALID_SEARCH_BACKENDS:
        return shared
    return _env_fallback_backend()


def _get_extract_backend() -> str:
    """Determine which backend to use for web_extract.

    Precedence:
      1. web.extract.backend (tool-specific override)
      2. web.backend (shared fallback)
      3. env-based auto-detection
    """
    web_cfg = _load_web_config()
    specific = web_cfg.get("extract", {}).get("backend", "").lower().strip()
    if specific in _VALID_EXTRACT_BACKENDS:
        return specific
    shared = web_cfg.get("backend", "").lower().strip()
    if shared in _VALID_EXTRACT_BACKENDS:
        return shared
    return _env_fallback_backend()
```

- [ ] **Step 4: Update `web_search_tool` to call `_get_search_backend()`**

Inside `web_search_tool` (around line 690), replace:
```python
backend = _get_backend()
```
with:
```python
backend = _get_search_backend()
```

- [ ] **Step 5: Update `web_extract_tool` to call `_get_extract_backend()`**

Inside `web_extract_tool` (around line 880), replace:
```python
backend = _get_backend()
```
with:
```python
backend = _get_extract_backend()
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python -m pytest tests/tools/test_web_tools_config.py -v
```

Expected: All `PASSED` (existing tests still pass; new classes pass too).

- [ ] **Step 7: Commit**

```bash
git add tools/web_tools.py tests/tools/test_web_tools_config.py
git commit -m "feat: add _get_search_backend() and _get_extract_backend() with per-tool config precedence"
```

---

### Task 4: Implement `_searxng_search()`

**Files:**
- Modify: `tools/web_tools.py` (add after `_env_fallback_backend`, around line 150)
- Create: `tests/tools/test_web_tools_searxng.py`

#### What `_searxng_search()` does

```python
def _searxng_search(query: str, limit: int = 5) -> dict:
    """Search via a SearXNG instance.

    URL template comes from (in order):
      1. web.search.url config key (must contain %s placeholder)
      2. SEARXNG_URL env var (same %s convention)

    Optional auth: SEARXNG_API_KEY env var → sent as Authorization: Bearer <key>.

    Returns the standard {"success": True, "data": {"web": [...]}} dict.
    Each result: {"title": str, "url": str, "description": str, "position": int}
    """
```

Implementation notes:
- Get URL template: `_load_web_config().get("search", {}).get("url")` first, then `os.getenv("SEARXNG_URL")`.
- If neither is set → raise `ValueError("SearXNG backend requires web.search.url in config or SEARXNG_URL env var")`.
- Validate `%s` present in template → raise `ValueError("web.search.url must contain %s placeholder")`.
- Build URL: `url = template % urllib.parse.quote_plus(query)`.
- Build headers: `{"Accept": "application/json"}` + optionally `"Authorization": f"Bearer {api_key}"` if `SEARXNG_API_KEY` is set.
- Use existing `httpx` (already imported at top of file) for the GET request with `timeout=10`.
- Parse JSON response. SearXNG's JSON format has `response["results"]` — each entry has `title`, `url`, `content` (description).
- Normalize to standard format:
  ```python
  web_results = [
      {
          "title": r.get("title", ""),
          "url": r.get("url", ""),
          "description": r.get("content", ""),
          "position": i + 1,
      }
      for i, r in enumerate(raw_results[:limit])
  ]
  return {"success": True, "data": {"web": web_results}}
  ```
- On `httpx.HTTPError` → return `{"success": False, "error": str(exc)}`.

> **Note:** `_searxng_search` is synchronous (like `_parallel_search` and the Tavily path in `web_search_tool`). The `web_search_tool` dispatcher already runs synchronously.

- [ ] **Step 1: Write failing tests**

Create `tests/tools/test_web_tools_searxng.py`:

```python
"""Unit tests for the SearXNG search backend."""

import os
import pytest
from unittest.mock import patch, MagicMock
import httpx


class TestSearxngSearch:
    """Tests for _searxng_search()."""

    SAMPLE_RESPONSE = {
        "results": [
            {"title": "Result One", "url": "https://one.example.com", "content": "Snippet one"},
            {"title": "Result Two", "url": "https://two.example.com", "content": "Snippet two"},
        ]
    }

    def _make_mock_response(self, data):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.json.return_value = data
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    # ── URL resolution ────────────────────────────────────────────────

    def test_uses_config_url_over_env(self):
        """web.search.url config takes precedence over SEARXNG_URL env var."""
        from tools.web_tools import _searxng_search
        cfg_url = "https://searx.cfg.com/search?q=%s&format=json"
        env_url = "https://searx.env.com/search?q=%s&format=json"

        with patch("tools.web_tools._load_web_config", return_value={"search": {"url": cfg_url}}), \
             patch.dict(os.environ, {"SEARXNG_URL": env_url}), \
             patch("httpx.get", return_value=self._make_mock_response(self.SAMPLE_RESPONSE)) as mock_get:
            _searxng_search("test query")
        called_url = mock_get.call_args[0][0]
        assert "searx.cfg.com" in called_url

    def test_falls_back_to_env_url(self):
        """SEARXNG_URL env var used when config URL not set."""
        from tools.web_tools import _searxng_search
        env_url = "https://searx.env.com/search?q=%s&format=json"

        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"SEARXNG_URL": env_url}), \
             patch("httpx.get", return_value=self._make_mock_response(self.SAMPLE_RESPONSE)) as mock_get:
            _searxng_search("python")
        called_url = mock_get.call_args[0][0]
        assert "searx.env.com" in called_url

    def test_no_url_raises_value_error(self):
        """Neither config URL nor env var → ValueError."""
        from tools.web_tools import _searxng_search
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SEARXNG_URL", None)
            with pytest.raises(ValueError, match="SEARXNG_URL"):
                _searxng_search("anything")

    def test_url_without_placeholder_raises(self):
        """URL missing %s placeholder → ValueError."""
        from tools.web_tools import _searxng_search
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"url": "https://searx.example.com/search?q=hardcoded"}
        }):
            with pytest.raises(ValueError, match="%s"):
                _searxng_search("anything")

    # ── Query encoding ────────────────────────────────────────────────

    def test_query_is_url_encoded(self):
        """Spaces and special chars in query are percent-encoded."""
        from tools.web_tools import _searxng_search
        url_tmpl = "https://searx.example.com/search?q=%s&format=json"

        with patch("tools.web_tools._load_web_config", return_value={"search": {"url": url_tmpl}}), \
             patch("httpx.get", return_value=self._make_mock_response(self.SAMPLE_RESPONSE)) as mock_get:
            _searxng_search("hello world")
        called_url = mock_get.call_args[0][0]
        assert "hello+world" in called_url or "hello%20world" in called_url

    # ── Auth ──────────────────────────────────────────────────────────

    def test_api_key_sent_as_bearer(self):
        """SEARXNG_API_KEY present → Authorization: Bearer header sent."""
        from tools.web_tools import _searxng_search
        url_tmpl = "https://searx.example.com/search?q=%s&format=json"

        with patch("tools.web_tools._load_web_config", return_value={"search": {"url": url_tmpl}}), \
             patch.dict(os.environ, {"SEARXNG_API_KEY": "secret-key"}), \
             patch("httpx.get", return_value=self._make_mock_response(self.SAMPLE_RESPONSE)) as mock_get:
            _searxng_search("test")
        headers = mock_get.call_args[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer secret-key"

    def test_no_auth_header_when_no_api_key(self):
        """No SEARXNG_API_KEY → no Authorization header."""
        from tools.web_tools import _searxng_search
        url_tmpl = "https://searx.example.com/search?q=%s&format=json"

        with patch("tools.web_tools._load_web_config", return_value={"search": {"url": url_tmpl}}), \
             patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SEARXNG_API_KEY", None)
            with patch("httpx.get", return_value=self._make_mock_response(self.SAMPLE_RESPONSE)) as mock_get:
                _searxng_search("test")
        headers = mock_get.call_args[1].get("headers", {})
        assert "Authorization" not in headers

    # ── Result normalization ──────────────────────────────────────────

    def test_results_normalized_to_standard_format(self):
        """SearXNG results normalized to {"success": True, "data": {"web": [...]}}."""
        from tools.web_tools import _searxng_search
        url_tmpl = "https://searx.example.com/search?q=%s&format=json"

        with patch("tools.web_tools._load_web_config", return_value={"search": {"url": url_tmpl}}), \
             patch("httpx.get", return_value=self._make_mock_response(self.SAMPLE_RESPONSE)):
            result = _searxng_search("query", limit=5)

        assert result["success"] is True
        web = result["data"]["web"]
        assert len(web) == 2
        assert web[0]["title"] == "Result One"
        assert web[0]["url"] == "https://one.example.com"
        assert web[0]["description"] == "Snippet one"
        assert web[0]["position"] == 1

    def test_limit_respected(self):
        """limit parameter caps the number of returned results."""
        from tools.web_tools import _searxng_search
        url_tmpl = "https://searx.example.com/search?q=%s"
        many_results = {"results": [
            {"title": f"R{i}", "url": f"https://r{i}.com", "content": ""}
            for i in range(10)
        ]}

        with patch("tools.web_tools._load_web_config", return_value={"search": {"url": url_tmpl}}), \
             patch("httpx.get", return_value=self._make_mock_response(many_results)):
            result = _searxng_search("query", limit=3)

        assert len(result["data"]["web"]) == 3

    def test_http_error_returns_failure(self):
        """HTTP error → {"success": False, "error": ...}."""
        from tools.web_tools import _searxng_search
        url_tmpl = "https://searx.example.com/search?q=%s"

        with patch("tools.web_tools._load_web_config", return_value={"search": {"url": url_tmpl}}), \
             patch("httpx.get", side_effect=httpx.HTTPError("connection refused")):
            result = _searxng_search("query")

        assert result["success"] is False
        assert "error" in result
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/tools/test_web_tools_searxng.py -v
```

Expected: All `FAILED` — `_searxng_search` not defined.

- [ ] **Step 3: Implement `_searxng_search()` in `tools/web_tools.py`**

Add the import at the top of the file (alongside existing imports):
```python
import urllib.parse
```

Add the function after `_env_fallback_backend()`:

```python
def _searxng_search(query: str, limit: int = 5) -> dict:
    """Search via a SearXNG instance.

    URL template is resolved from (in priority order):
      1. web.search.url in config.yaml (must contain ``%s`` placeholder)
      2. SEARXNG_URL environment variable

    Optional: set SEARXNG_API_KEY for authenticated SearXNG instances
    (sent as ``Authorization: Bearer <key>``).

    Returns the standard {"success": bool, "data": {"web": [...]}} format.
    """
    web_cfg = _load_web_config()
    url_template = web_cfg.get("search", {}).get("url") or os.getenv("SEARXNG_URL")

    if not url_template:
        raise ValueError(
            "SearXNG backend requires web.search.url in config.yaml or "
            "the SEARXNG_URL environment variable. "
            "Example: https://searx.example.com/search?q=%s&format=json"
        )
    if "%s" not in url_template:
        raise ValueError(
            "web.search.url (or SEARXNG_URL) must contain a %s placeholder "
            "for the search query. "
            f"Got: {url_template!r}"
        )

    encoded_query = urllib.parse.quote_plus(query)
    url = url_template % encoded_query

    headers: dict = {"Accept": "application/json"}
    api_key = os.getenv("SEARXNG_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        raw = response.json()
    except httpx.HTTPError as exc:
        logger.warning("SearXNG request failed: %s", exc)
        return {"success": False, "error": str(exc)}

    raw_results = raw.get("results", [])
    web_results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("content", ""),
            "position": i + 1,
        }
        for i, r in enumerate(raw_results[:limit])
    ]
    return {"success": True, "data": {"web": web_results}}
```

- [ ] **Step 4: Wire SearXNG into `web_search_tool` dispatch**

Inside `web_search_tool`, find the backend dispatch block (where `if backend == "parallel"` / `"tavily"` / else-firecrawl live). Add the SearXNG branch before the firecrawl else:

```python
if backend == "parallel":
    response_data = _parallel_search(query, limit)
    ...
elif backend == "tavily":
    ...
elif backend == "searxng":
    logger.info("SearXNG search: '%s' (limit: %d)", query, limit)
    response_data = _searxng_search(query, limit)
    debug_call_data["results_count"] = len(response_data.get("data", {}).get("web", []))
    result_json = json.dumps(response_data, indent=2, ensure_ascii=False)
    debug_call_data["final_response_size"] = len(result_json)
    _debug.log_call("web_search_tool", debug_call_data)
    _debug.save()
    return result_json
else:
    # Firecrawl (default)
    ...
```

- [ ] **Step 5: Wire native into `web_extract_tool` dispatch**

Inside `web_extract_tool`, find the dispatch block starting `if backend == "parallel"`. Add the native branch before the firecrawl else:

```python
if not safe_urls:
    results = []
else:
    backend = _get_extract_backend()
    if backend == "parallel":
        results = await _parallel_extract(safe_urls)
    elif backend == "tavily":
        ...
    elif backend == "native":
        logger.info("Native extract: %d URL(s)", len(safe_urls))
        results = await _native_extract(safe_urls)
    else:
        # Firecrawl (default)
        ...
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/tools/test_web_tools_searxng.py tests/tools/test_web_tools_native_extract.py tests/tools/test_web_tools_config.py -v
```

Expected: All `PASSED`

- [ ] **Step 7: Commit**

```bash
git add tools/web_tools.py tests/tools/test_web_tools_searxng.py
git commit -m "feat: add SearXNG search backend and wire native/searxng into dispatch"
```

---

### Task 5: Update `check_web_api_key()` and registry `requires_env`

**Files:**
- Modify: `tools/web_tools.py` (lines ~1554–1565 and ~1708–1727)
- Test: `tests/tools/test_web_tools_config.py`

The `check_web_api_key` function must return `True` when:
- Any of the existing API keys is present, OR
- SearXNG is configured (config URL or `SEARXNG_URL` env var), OR
- The native extract backend is configured (`web.extract.backend == "native"`)

The registry `requires_env` list is advisory (shown in `hermes tools`). Add `SEARXNG_URL` alongside the existing keys. Since native needs no env var at all, the availability check function is the right gate.

- [ ] **Step 1: Write failing tests**

Add to `tests/tools/test_web_tools_config.py`:

```python
class TestCheckWebApiKey:
    """Tests for check_web_api_key() — covers new native and SearXNG paths."""

    def test_true_when_searxng_url_in_config(self):
        """SearXNG URL in config → web tools available."""
        from tools.web_tools import check_web_api_key
        with patch("tools.web_tools._load_web_config", return_value={
            "search": {"url": "https://searx.example.com/search?q=%s"}
        }), patch.dict(os.environ, {}, clear=True):
            for k in ("PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "FIRECRAWL_API_URL", "TAVILY_API_KEY", "SEARXNG_URL"):
                os.environ.pop(k, None)
            assert check_web_api_key() is True

    def test_true_when_searxng_url_env(self):
        """SEARXNG_URL env var → web tools available."""
        from tools.web_tools import check_web_api_key
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {"SEARXNG_URL": "https://searx.example.com/search?q=%s"}):
            for k in ("PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "FIRECRAWL_API_URL", "TAVILY_API_KEY"):
                os.environ.pop(k, None)
            assert check_web_api_key() is True

    def test_true_when_native_extract_configured(self):
        """web.extract.backend=native → web tools available (extract needs no API key)."""
        from tools.web_tools import check_web_api_key
        with patch("tools.web_tools._load_web_config", return_value={
            "extract": {"backend": "native"}
        }), patch.dict(os.environ, {}, clear=True):
            for k in ("PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "FIRECRAWL_API_URL", "TAVILY_API_KEY", "SEARXNG_URL"):
                os.environ.pop(k, None)
            assert check_web_api_key() is True

    def test_false_when_nothing_configured(self):
        """No API keys, no SearXNG URL, no native config → False."""
        from tools.web_tools import check_web_api_key
        with patch("tools.web_tools._load_web_config", return_value={}), \
             patch.dict(os.environ, {}, clear=True):
            for k in ("PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "FIRECRAWL_API_URL",
                       "TAVILY_API_KEY", "SEARXNG_URL"):
                os.environ.pop(k, None)
            assert check_web_api_key() is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/tools/test_web_tools_config.py::TestCheckWebApiKey -v
```

Expected: `FAILED` — existing `check_web_api_key` doesn't handle the new paths.

- [ ] **Step 3: Update `check_web_api_key()` in `tools/web_tools.py`**

Replace the existing function body:

```python
def check_web_api_key() -> bool:
    """Check if any web backend is usable (API key, SearXNG URL, or native extract)."""
    # Existing API-key-based backends
    if (
        os.getenv("PARALLEL_API_KEY")
        or os.getenv("FIRECRAWL_API_KEY")
        or os.getenv("FIRECRAWL_API_URL")
        or os.getenv("TAVILY_API_KEY")
        or os.getenv("SEARXNG_URL")
    ):
        return True

    # SearXNG configured via config.yaml (no API key needed)
    web_cfg = _load_web_config()
    if web_cfg.get("search", {}).get("url"):
        return True

    # Native extract backend — works with no credentials
    if web_cfg.get("extract", {}).get("backend") == "native":
        return True

    return False
```

- [ ] **Step 4: Update registry `requires_env` for both tools**

Find the `registry.register` calls for `web_search` and `web_extract` (around lines 1708–1727) and add `"SEARXNG_URL"` to `requires_env`:

```python
registry.register(
    name="web_search",
    ...
    requires_env=["PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "TAVILY_API_KEY", "SEARXNG_URL"],
)
registry.register(
    name="web_extract",
    ...
    requires_env=["PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "TAVILY_API_KEY", "SEARXNG_URL"],
)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/tools/test_web_tools_config.py -v
```

Expected: All `PASSED`

- [ ] **Step 6: Commit**

```bash
git add tools/web_tools.py tests/tools/test_web_tools_config.py
git commit -m "feat: update check_web_api_key() to cover SearXNG and native extract backends"
```

---

## Chunk 3: Config schema + migration

### Task 6: Extend `DEFAULT_CONFIG` and bump version

**Files:**
- Modify: `hermes_cli/config.py`
- Test: `tests/hermes_cli/test_config.py`

#### Changes to `DEFAULT_CONFIG`

In the `DEFAULT_CONFIG` dict (after or alongside the `"security"` block, before `"_config_version"`), add:

```python
"web": {
    "search": {
        "backend": "",   # empty = use web.backend fallback
        "url": "",       # SearXNG URL template (must contain %s); required when backend=searxng
    },
    "extract": {
        "backend": "",   # empty = use web.backend fallback; valid values: firecrawl, parallel, tavily, native
    },
},
```

Bump:
```python
"_config_version": 11,
```

Add to `ENV_VARS_BY_VERSION`:
```python
11: ["SEARXNG_API_KEY"],
```

Add to `OPTIONAL_ENV_VARS`:
```python
"SEARXNG_URL": {
    "description": "SearXNG instance search URL template (must contain %s for the query)",
    "prompt": "SearXNG search URL template",
    "url": "https://searxng.github.io/searxng/",
    "password": False,
    "tools": ["web_search"],
    "category": "tool",
},
"SEARXNG_API_KEY": {
    "description": "Optional API key for authenticated SearXNG instances",
    "prompt": "SearXNG API key (optional)",
    "url": None,
    "password": True,
    "tools": ["web_search"],
    "category": "tool",
    "advanced": True,
},
```

- [ ] **Step 1: Write failing tests**

Add to `tests/hermes_cli/test_config.py`:

```python
class TestConfigV11Schema:
    """Tests for DEFAULT_CONFIG v11 additions."""

    def test_web_search_section_in_default_config(self):
        """DEFAULT_CONFIG has web.search.backend and web.search.url."""
        from hermes_cli.config import DEFAULT_CONFIG
        assert "web" in DEFAULT_CONFIG
        assert "search" in DEFAULT_CONFIG["web"]
        assert "backend" in DEFAULT_CONFIG["web"]["search"]
        assert "url" in DEFAULT_CONFIG["web"]["search"]

    def test_web_extract_section_in_default_config(self):
        """DEFAULT_CONFIG has web.extract.backend."""
        from hermes_cli.config import DEFAULT_CONFIG
        assert "extract" in DEFAULT_CONFIG["web"]
        assert "backend" in DEFAULT_CONFIG["web"]["extract"]

    def test_config_version_is_11(self):
        """_config_version must be 11."""
        from hermes_cli.config import DEFAULT_CONFIG
        assert DEFAULT_CONFIG["_config_version"] == 11

    def test_searxng_api_key_in_env_vars_by_version(self):
        """SEARXNG_API_KEY is listed under version 11 in ENV_VARS_BY_VERSION."""
        from hermes_cli.config import ENV_VARS_BY_VERSION
        assert 11 in ENV_VARS_BY_VERSION
        assert "SEARXNG_API_KEY" in ENV_VARS_BY_VERSION[11]

    def test_searxng_vars_in_optional_env_vars(self):
        """SEARXNG_URL and SEARXNG_API_KEY present in OPTIONAL_ENV_VARS."""
        from hermes_cli.config import OPTIONAL_ENV_VARS
        assert "SEARXNG_URL" in OPTIONAL_ENV_VARS
        assert "SEARXNG_API_KEY" in OPTIONAL_ENV_VARS
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/hermes_cli/test_config.py::TestConfigV11Schema -v
```

Expected: All `FAILED`

- [ ] **Step 3: Apply all DEFAULT_CONFIG, ENV_VARS, OPTIONAL_ENV_VARS changes**

Edit `hermes_cli/config.py` as described above (four separate edits: `DEFAULT_CONFIG["web"]`, `_config_version`, `ENV_VARS_BY_VERSION[11]`, and the two `OPTIONAL_ENV_VARS` entries).

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/hermes_cli/test_config.py::TestConfigV11Schema -v
```

Expected: All `PASSED`

- [ ] **Step 5: Commit**

```bash
git add hermes_cli/config.py tests/hermes_cli/test_config.py
git commit -m "feat: add web.search/extract to DEFAULT_CONFIG, bump config version to 11"
```

---

### Task 7: Add v10→v11 migration logic

**Files:**
- Modify: `hermes_cli/config.py` (`migrate_config` function)
- Test: `tests/hermes_cli/test_config.py`

#### Migration behaviour (v10 → v11)

The `migrate_config` function currently has version-specific blocks around lines 995–1090 for versions 3, 4, 5. Add a new block for `10 → 11`:

```python
# ── Version 10 → 11: split web.backend into web.search.backend + web.extract.backend ──
if current_ver < 11:
    existing_web_backend = config.get("web", {}).get("backend", "")
    if existing_web_backend:
        search_cfg = config.setdefault("web", {}).setdefault("search", {})
        extract_cfg = config.setdefault("web", {}).setdefault("extract", {})

        if not search_cfg.get("backend"):
            search_cfg["backend"] = existing_web_backend
            results["config_added"].append(
                f"web.search.backend={existing_web_backend} (copied from web.backend)"
            )
        if not extract_cfg.get("backend"):
            extract_cfg["backend"] = existing_web_backend
            results["config_added"].append(
                f"web.extract.backend={existing_web_backend} (copied from web.backend)"
            )

    # If backend was searxng (from old plan), prompt for search URL if missing
    if existing_web_backend == "searxng":
        search_cfg = config.setdefault("web", {}).setdefault("search", {})
        if not search_cfg.get("url") and not os.getenv("SEARXNG_URL"):
            if interactive:
                print("\n  Your web.backend was 'searxng'. Please provide the search URL:")
                url_val = input("  SearXNG search URL template (e.g. https://searx.example.com/search?q=%s): ").strip()
                if url_val:
                    search_cfg["url"] = url_val
                    results["config_added"].append(f"web.search.url={url_val}")
            else:
                results["warnings"].append(
                    "web.backend=searxng but web.search.url is not set. "
                    "Set web.search.url in config.yaml or SEARXNG_URL env var."
                )
```

**Important placement:** This block must come BEFORE the generic "add missing config fields" loop (the `for field in missing_config` block at line ~1134) so that the copied values are already present when `_set_nested` runs, preventing it from overwriting them with the empty-string defaults from `DEFAULT_CONFIG`.

- [ ] **Step 1: Write failing tests**

Add to `tests/hermes_cli/test_config.py`:

```python
import yaml


class TestMigrateV10ToV11:
    """Tests for config migration from version 10 to 11."""

    def _write_config(self, tmp_path, data: dict):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.safe_dump(data))

    def test_web_backend_copied_to_search_and_extract(self, tmp_path):
        """Existing web.backend is propagated to web.search.backend and web.extract.backend."""
        self._write_config(tmp_path, {"_config_version": 10, "web": {"backend": "tavily"}})
        with patch("hermes_cli.config.HERMES_HOME", str(tmp_path)):
            results = migrate_config(interactive=False, quiet=True)
        from hermes_cli.config import load_config
        with patch("hermes_cli.config.HERMES_HOME", str(tmp_path)):
            config = load_config()
        assert config["web"]["search"]["backend"] == "tavily"
        assert config["web"]["extract"]["backend"] == "tavily"

    def test_existing_search_backend_not_overwritten(self, tmp_path):
        """Pre-existing web.search.backend is preserved during migration."""
        self._write_config(tmp_path, {
            "_config_version": 10,
            "web": {
                "backend": "firecrawl",
                "search": {"backend": "parallel"},
            }
        })
        with patch("hermes_cli.config.HERMES_HOME", str(tmp_path)):
            migrate_config(interactive=False, quiet=True)
        with patch("hermes_cli.config.HERMES_HOME", str(tmp_path)):
            config = load_config()
        assert config["web"]["search"]["backend"] == "parallel"
        assert config["web"]["extract"]["backend"] == "firecrawl"

    def test_no_web_backend_no_migration(self, tmp_path):
        """No web.backend set → web.search.backend and web.extract.backend stay empty."""
        self._write_config(tmp_path, {"_config_version": 10})
        with patch("hermes_cli.config.HERMES_HOME", str(tmp_path)):
            migrate_config(interactive=False, quiet=True)
        with patch("hermes_cli.config.HERMES_HOME", str(tmp_path)):
            config = load_config()
        assert config.get("web", {}).get("search", {}).get("backend", "") == ""
        assert config.get("web", {}).get("extract", {}).get("backend", "") == ""

    def test_searxng_backend_issues_warning_when_url_missing_non_interactive(self, tmp_path):
        """web.backend=searxng without URL → warning emitted in non-interactive mode."""
        self._write_config(tmp_path, {"_config_version": 10, "web": {"backend": "searxng"}})
        with patch("hermes_cli.config.HERMES_HOME", str(tmp_path)), \
             patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SEARXNG_URL", None)
            results = migrate_config(interactive=False, quiet=True)
        assert any("web.search.url" in w for w in results["warnings"])

    def test_version_bumped_to_11(self, tmp_path):
        """After migration, _config_version is 11."""
        self._write_config(tmp_path, {"_config_version": 10})
        with patch("hermes_cli.config.HERMES_HOME", str(tmp_path)):
            migrate_config(interactive=False, quiet=True)
        with patch("hermes_cli.config.HERMES_HOME", str(tmp_path)):
            config = load_config()
        assert config["_config_version"] == 11
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/hermes_cli/test_config.py::TestMigrateV10ToV11 -v
```

Expected: All `FAILED`

- [ ] **Step 3: Implement the v10→v11 migration block**

Edit `hermes_cli/config.py` `migrate_config()` function. Find the existing version-specific blocks (around line 995). Add the new block immediately before the generic `missing_config` loop:

```python
# ── Version 10 → 11: split web.backend into per-tool backends ──
if current_ver < 11:
    existing_web_backend = config.get("web", {}).get("backend", "")
    if existing_web_backend:
        search_cfg = config.setdefault("web", {}).setdefault("search", {})
        extract_cfg = config.setdefault("web", {}).setdefault("extract", {})

        if not search_cfg.get("backend"):
            search_cfg["backend"] = existing_web_backend
            results["config_added"].append(
                f"web.search.backend={existing_web_backend} (copied from web.backend)"
            )
        if not extract_cfg.get("backend"):
            extract_cfg["backend"] = existing_web_backend
            results["config_added"].append(
                f"web.extract.backend={existing_web_backend} (copied from web.backend)"
            )

        if existing_web_backend == "searxng":
            search_cfg = config.setdefault("web", {}).setdefault("search", {})
            if not search_cfg.get("url") and not os.getenv("SEARXNG_URL"):
                if interactive:
                    print("\n  Your web.backend was 'searxng'. Please provide the search URL template:")
                    print("  (Must contain %s — e.g. https://searx.example.com/search?q=%s&format=json)")
                    url_val = input("  SearXNG search URL: ").strip()
                    if url_val:
                        search_cfg["url"] = url_val
                        results["config_added"].append(f"web.search.url={url_val}")
                else:
                    results["warnings"].append(
                        "web.backend=searxng but web.search.url is not set. "
                        "Set web.search.url in config.yaml or SEARXNG_URL env var."
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/hermes_cli/test_config.py::TestMigrateV10ToV11 -v
```

Expected: All `PASSED`

- [ ] **Step 5: Commit**

```bash
git add hermes_cli/config.py tests/hermes_cli/test_config.py
git commit -m "feat: add v10→v11 config migration to split web.backend into per-tool backends"
```

---

## Chunk 4: `hermes tools` UI (tools_config.py)

### Task 8: Add SearXNG provider to tools_config

**Files:**
- Modify: `hermes_cli/tools_config.py`

#### Changes

**A) Add provider entry** to the `"web"` providers list (after the `"Firecrawl Self-Hosted"` entry):

```python
{
    "name": "SearXNG",
    "tag": "Free, self-hosted or public instance — no API key required",
    "web_search_backend": "searxng",  # NEW key — distinct from legacy web_backend
    "env_vars": [],  # URL is handled via custom prompt, not env_vars
    "requires_url_prompt": True,      # Signal to configure functions to ask for URL
},
{
    "name": "Native (extract only)",
    "tag": "Use requests + html-to-markdown; no API key. Search still needs a provider.",
    "web_extract_backend": "native",  # NEW key for extract-only override
    "env_vars": [],
},
```

**B) Update `_is_provider_active()`** to handle the new keys:

```python
def _is_provider_active(provider: dict, config: dict) -> bool:
    ...
    if provider.get("web_search_backend"):
        current = config.get("web", {}).get("search", {}).get("backend") \
                  or config.get("web", {}).get("backend")
        return current == provider["web_search_backend"]
    if provider.get("web_extract_backend"):
        current = config.get("web", {}).get("extract", {}).get("backend")
        return current == provider["web_extract_backend"]
    if provider.get("web_backend"):
        current = config.get("web", {}).get("backend")
        return current == provider["web_backend"]
    ...
```

**C) Update `_configure_provider()`** to handle `web_search_backend`, `web_extract_backend`, and `requires_url_prompt`:

```python
# Set web search backend (new per-tool key)
if provider.get("web_search_backend"):
    config.setdefault("web", {}).setdefault("search", {})["backend"] = provider["web_search_backend"]
    _print_success(f"  Web search backend set to: {provider['web_search_backend']}")

# Set web extract backend (new per-tool key)
if provider.get("web_extract_backend"):
    config.setdefault("web", {}).setdefault("extract", {})["backend"] = provider["web_extract_backend"]
    _print_success(f"  Web extract backend set to: {provider['web_extract_backend']}")

# Prompt for SearXNG URL if needed
if provider.get("requires_url_prompt"):
    existing_url = config.get("web", {}).get("search", {}).get("url", "")
    if not existing_url:
        print("  SearXNG requires a search URL template (must contain %s for the query).")
        print("  Example: https://searx.example.com/search?q=%s&format=json")
        url_val = _prompt("  SearXNG search URL template").strip()
        if url_val:
            config.setdefault("web", {}).setdefault("search", {})["url"] = url_val
            _print_success(f"  web.search.url set")
        # Optional API key
        api_key = _prompt("  SearXNG API key (optional, press Enter to skip)", password=True).strip()
        if api_key:
            save_env_value("SEARXNG_API_KEY", api_key)
            _print_success("  SEARXNG_API_KEY saved")
    else:
        _print_success(f"  web.search.url already set: {existing_url[:40]}...")
```

Apply the same pattern for `_reconfigure_provider()` (update URL and optionally API key).

> **Note:** The legacy `web_backend` key and its handling remain untouched. Existing providers (firecrawl, parallel, tavily, firecrawl-self-hosted) continue using `web_backend` which writes to `web.backend`. The new SearXNG and native entries use the new keys and write to the nested paths. This is intentional: legacy providers keep working without any change to backward compat.

- [ ] **Step 1: Apply all three changes to `hermes_cli/tools_config.py`**

  - Add SearXNG and Native provider entries to the `"web"` providers list.
  - Update `_is_provider_active()`.
  - Update `_configure_provider()` and `_reconfigure_provider()`.

- [ ] **Step 2: Smoke-test the UI manually** (no automated test for curses UI; do a quick import check)

```bash
source venv/bin/activate
python -c "from hermes_cli.tools_config import TOOLSET_CONFIG; providers = TOOLSET_CONFIG['web']['providers']; print([p['name'] for p in providers])"
```

Expected output includes `SearXNG` and `Native (extract only)`.

- [ ] **Step 3: Commit**

```bash
git add hermes_cli/tools_config.py
git commit -m "feat: add SearXNG and native extract providers to hermes tools web UI"
```

---

## Chunk 5: Full test suite verification

### Task 9: Run full test suite and fix regressions

- [ ] **Step 1: Run the full test suite**

```bash
source venv/bin/activate
python -m pytest tests/ -q --tb=short 2>&1 | tail -40
```

- [ ] **Step 2: Triage any failures**

  - Failures in `test_web_tools_config.py` related to `_get_backend` tests: verify the existing `_get_backend` tests still pass (the function is kept; its internal logic is now delegated to `_env_fallback_backend`).
  - Failures in `test_config.py` related to version checks: ensure the `check_config_version` tests reference 11 if they hardcode 10.

- [ ] **Step 3: Fix any regressions**

For each failing test, read the failure message, make the minimal fix, run that test class alone to confirm it passes, then re-run the full suite.

- [ ] **Step 4: Final full suite run**

```bash
python -m pytest tests/ -q
```

Expected: All tests pass (same pass count as before this feature, plus the new tests).

- [ ] **Step 5: Commit any regression fixes**

```bash
git add -A
git commit -m "fix: update existing tests to handle config v11 and new backend helpers"
```

---

## Edge Cases Reference

| Scenario | Behaviour |
|----------|-----------|
| `web.search.backend = "native"` | `_get_search_backend()` treats it as unknown (not in `_VALID_SEARCH_BACKENDS`), falls through to `web.backend` |
| `web.extract.backend = "searxng"` | `_get_extract_backend()` treats it as unknown (not in `_VALID_EXTRACT_BACKENDS`), falls through to `web.backend` |
| `web.backend = "searxng"` but no `web.search.url` and no `SEARXNG_URL` | `_searxng_search()` raises `ValueError`; `web_search_tool` catches it and returns `{"error": "..."}` — **verify the existing try/except in `web_search_tool` covers this** |
| `web.search.backend = "searxng"` but `web.extract.backend` not set, `web.backend = "firecrawl"` | Extract uses firecrawl; search uses searxng |
| `_native_extract` with SSRF-private URL | `is_safe_url()` is NOT checked in `_native_extract` (it's already been checked before dispatch in `web_extract_tool`). **Do not double-check.** |
| SearXNG returns no `results` key | `raw.get("results", [])` returns `[]`; search returns `{"success": True, "data": {"web": []}}` |
| `html-to-markdown` raises on malformed HTML | Let it propagate as-is (the try/except around `_requests.get` won't catch it). Add an inner `try/except Exception` around the conversion call and fall back to `response.text[:5000]` |
| Config file has `web.backend: ""` (empty string) | Both `_get_search_backend` and `_get_extract_backend` treat it as unset (empty string fails the `in _VALID_*_BACKENDS` check) and fall through to env |
| `web.search.url` has `%s` but URL isn't reachable | `_searxng_search` raises `httpx.HTTPError` → returns `{"success": False, "error": ...}` |

---

## Verification Commands (after all tasks complete)

```bash
source venv/bin/activate

# New unit tests
python -m pytest tests/tools/test_web_tools_searxng.py -v
python -m pytest tests/tools/test_web_tools_native_extract.py -v
python -m pytest tests/tools/test_web_tools_config.py -v
python -m pytest tests/hermes_cli/test_config.py -v

# Full suite
python -m pytest tests/ -q

# Sanity import check
python -c "from tools.web_tools import _get_search_backend, _get_extract_backend, _searxng_search, _native_extract, check_web_api_key; print('all imports OK')"
python -c "from hermes_cli.config import DEFAULT_CONFIG; assert DEFAULT_CONFIG['_config_version'] == 11; print('version OK')"
python -c "from hermes_cli.tools_config import TOOLSET_CONFIG; names = [p['name'] for p in TOOLSET_CONFIG['web']['providers']]; assert 'SearXNG' in names; print('SearXNG in tools UI OK')"
```
