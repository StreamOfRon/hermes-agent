# Web Config Schema v2 Implementation — Todo List

**Plan:** `.opencode/plans/1774319582434-stellar-lagoon.md`  
**Last Updated:** 2026-03-23  
**Status:** In Progress

## Completed Tasks

- ✅ Install html-to-markdown dependency
- ✅ Test migration logic manually (v10→v11 config migration works correctly)
- ✅ Test backend selection functions (_get_search_backend, _get_extract_backend)

## In Progress

- ⏳ Run full pytest suite

## Pending

- ⏰ Commit changes to git

## Implementation Summary

All code modifications are complete and syntax-verified:

### Modified Files
- `pyproject.toml` — Added `html-to-markdown` dependency
- `tools/web_tools.py` — Added backend selection functions, SearXNG search, native extract, updated dispatchers
- `hermes_cli/config.py` — Updated DEFAULT_CONFIG, OPTIONAL_ENV_VARS, ENV_VARS_BY_VERSION, added v10→v11 migration
- `hermes_cli/tools_config.py` — Added SearXNG and Native HTTP providers

### Test Results

**Manual Testing:**
- Backend selection functions work correctly (returns 'firecrawl' by default)
- Migration from v10 to v11 works correctly (web.backend → web.search.backend + web.extract.backend)
- All Python files compile without syntax errors

**Pending:**
- Full pytest suite run (needs completion)

## Next Steps

1. Complete pytest suite execution
2. Commit all changes with appropriate message
3. Document any test failures or edge cases
