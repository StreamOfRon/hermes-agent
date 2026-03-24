# SearXNG Web Search Backend Design

**Date:** 2026-03-23  
**Status:** Approved  
**Approach:** Option 1 - Backend Selection

## Overview

Add SearXNG as a 4th web search backend option alongside Firecrawl, Parallel, and Tavily. This allows users to self-host their search infrastructure while maintaining the existing backend selection pattern in Hermes.

## Requirements

1. Support SearXNG as a configurable web search backend
2. Allow specifying SearXNG instance URL via environment variable (`SEARXNG_URL`) or config (`web.searxng_url`)
3. Support both authenticated (via optional `SEARXNG_API_KEY`) and unauthenticated SearXNG instances
4. SearXNG only supports `web_search` (not `web_extract` or `web_crawl`)
5. Use standard SearXNG JSON format (`format=json`)
6. Single URL configuration (no fallback support for now)

## Design

### Configuration Schema

```yaml
# ~/.hermes/config.yaml
web:
  backend: "searxng"  # Options: firecrawl, parallel, tavily, searxng
  searxng_url: "https://searx.example.com"  # Optional: falls back to SEARXNG_URL env var
```

### Environment Variables

- `SEARXNG_URL` - URL of the SearXNG instance (required when backend is searxng)
- `SEARXNG_API_KEY` - Optional API key for authenticated instances

### Files to Modify

1. **`tools/web_tools.py`** (~200 lines)
   - Add `_searxng_search()` helper function
   - Add `_normalize_searxng_search_results()` to convert SearXNG response to standard format
   - Update `_get_backend()` to recognize "searxng" backend
   - Update `web_search_tool()` to dispatch to SearXNG backend
   - Update `check_web_api_key()` to include SearXNG checks
   - Update registry registration to include SEARXNG_URL in requires_env

2. **`hermes_cli/config.py`** (~10 lines)
   - Add `SEARXNG_URL` and `SEARXNG_API_KEY` to `OPTIONAL_ENV_VARS`
   - Add ENV_VARS_BY_VERSION entry for config migration

3. **`hermes_cli/tools_config.py`** (~30 lines)
   - Add SearXNG provider entry to `TOOL_CATEGORIES["web"]["providers"]`

### SearXNG API Integration

**Endpoint:** `GET {SEARXNG_URL}/search`

**Query Parameters:**
- `q` - Search query
- `format=json` - Request JSON response
- `categories=general` - Search categories
- `language=en-US` - Language
- `safesearch=0` - Safe search setting

**Headers:**
- `Authorization: Bearer {SEARXNG_API_KEY}` (only if API key is configured)

**Response Format:**
```json
{
  "query": "search terms",
  "number_of_results": 10,
  "results": [
    {
      "url": "https://example.com",
      "title": "Page Title",
      "content": "Snippet or description",
      "engine": "google",
      "score": 1.0
    }
  ]
}
```

**Normalized Format:**
```json
{
  "success": true,
  "data": {
    "web": [
      {
        "title": "Page Title",
        "url": "https://example.com",
        "description": "Snippet or description",
        "position": 1
      }
    ]
  }
}
```

### Error Handling

- **Missing URL:** Raise `ValueError` with clear message about setting SEARXNG_URL
- **Connection Error:** Return `{"error": "Failed to connect to SearXNG instance", "success": false}`
- **HTTP Error:** Return error with status code and response body
- **Invalid Response:** Return error if JSON parsing fails

### UI/UX

**Provider Selection in `hermes tools`:**

When SearXNG is selected, prompt for:
1. SearXNG URL (e.g., `https://searx.example.com` or `http://localhost:8080`)
2. SearXNG API Key (optional - press Enter to skip)

### Implementation Notes

1. **HTTP Client:** Use existing `httpx` dependency (already imported in web_tools.py)
2. **Timeout:** Use 30-second timeout (consistent with Tavily)
3. **Result Limiting:** SearXNG may return more results than requested; truncate to `limit` parameter
4. **SSL Verification:** Use default SSL verification (can be disabled via env if needed for self-signed certs)
5. **Content Extraction:** SearXNG returns snippets in the `content` field, which maps to `description` in normalized format

### Testing Considerations

1. Test with public SearXNG instance (no auth)
2. Test with authenticated instance
3. Test error handling for unreachable URL
4. Test response normalization edge cases (missing fields, empty results)
5. Verify provider selection appears in `hermes tools` UI

### Migration

Users with existing configs will see SearXNG as a new option in `hermes tools` without any breaking changes. Config version bump to trigger migration notification about new optional env vars.

## Alternatives Considered

Option 1 (Backend Selection) was selected for consistency with existing patterns and simplicity.

## Security Considerations

1. SearXNG URL should be validated as a proper HTTP/HTTPS URL
2. API key (if provided) should be sent in Authorization header, not query params
3. No PII in search queries is logged (follow existing patterns)
4. SSRF protection should apply to SearXNG URLs (use existing `is_safe_url` check)

## Future Enhancements

- Support for SearXNG instance discovery/fallback
- Configurable language/time_range parameters
- Support for SearXNG categories (general, images, news, etc.)
- Web extract via direct HTTP fallback when SearXNG is primary backend
