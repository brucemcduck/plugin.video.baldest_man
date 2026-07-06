# Scraper Content-Type Filtering & Parallel Execution

**Date:** 2026-07-06
**Status:** approved

## Problem

Every search runs all 12 scrapers sequentially. With 15s timeouts per scraper,
a single search can take up to 180 seconds. Half the scrapers are irrelevant
for a given query (e.g., YTS returns only movies, wasted when searching shows).

## Solution

Two changes, both in `scraper_runner.py`:

### 1. Content-type declaration

Each scraper optionally declares `CONTENT_TYPES` — a list of which modes it
supports. Omit for "both" (default).

```python
# yts.py — movies only
CONTENT_TYPES = ["movies"]

# eztv.py — shows only
CONTENT_TYPES = ["shows"]

# piratebay.py — both (omit or ["movies", "shows"])
CONTENT_TYPES = ["movies", "shows"]
```

Values: `"movies"` or `"shows"`. Any scraper without the attribute is treated
as supporting both (backwards compatible, no breakage).

### 2. Parallel execution with content-type filter

`scraper_runner.search_all()` gains two things:

**Filter:** Only run scrapers whose `CONTENT_TYPES` includes the requested mode.
When mode is `"all"`, run everything.

**Thread pool:** Run remaining scrapers concurrently via
`concurrent.futures.ThreadPoolExecutor`. Worker count comes from a Kodi addon
setting (`scraper_workers`), defaulting to 6.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

def search_all(query, content_type="all"):
    scrapers = [m for m in get_scrapers()
                if content_type == "all"
                or content_type in getattr(m, "CONTENT_TYPES", ["movies", "shows"])]

    results = []
    with ThreadPoolExecutor(max_workers=_worker_count()) as pool:
        futures = {pool.submit(m.search, query): m for m in scrapers}
        for future in as_completed(futures):
            mod = futures[future]
            try:
                raw = future.result(timeout=15)
            except Exception:
                _log("scraper_runner: {} crashed".format(mod.SITE_NAME))
                continue
            # ... existing validation + relevance filter ...
    return results
```

### 3. Kodi addon setting

New integer setting `scraper_workers` in `resources/settings.xml`, default 6,
range 1–20. Adjustable from Kodi's addon settings UI without touching code.

## Scraper assignments

| Scraper | CONTENT_TYPES | Reason |
|---------|--------------|--------|
| nyaa | `["shows"]` | Anime episodes primarily |
| yts | `["movies"]` | Movies only |
| eztv | `["shows"]` | TV shows only |
| piratebay | both (default) | General purpose |
| 1337x | both (default) | General purpose |
| kickass | both (default) | General purpose |
| torlock | both (default) | General purpose |
| torrentgalaxy | both (default) | General purpose |
| limetorrents | both (default) | General purpose |
| torrentdownloads | both (default) | General purpose |
| yourbittorrent | both (default) | General purpose |

## Impact

| Scenario | Before | After |
|----------|--------|-------|
| "Search Shows" | 12 scrapers, ~180s seq | 8 scrapers (skips yts), ~30s parallel |
| "Search Movies" | 12 scrapers, ~180s seq | 8 scrapers (skips nyaa, eztv), ~30s parallel |
| "Search All" | 12 scrapers, ~180s seq | 12 scrapers, ~30s parallel |

When content_type is passed through from main.py's existing modes, the filter
kicks in automatically. The thread pool provides the real speed win —
parallelism dominates the gains, filtering is a free cherry on top.

## Non-changes

- `main.py` already has `content_type` flowing through — no changes needed
- Scraper interface unchanged — `CONTENT_TYPES` is optional
- Relevance filter unchanged — still runs after results come back
- No new dependencies — `ThreadPoolExecutor` is stdlib

## Risks

- **Thread safety:** Each scraper creates its own `requests.Session` implicitly
  via `requests.get()`. No shared state between scrapers. Thread-safe.
- **Rate limiting:** 6 concurrent requests to different sites is negligible.
  User can lower the worker count via Kodi setting if needed.
- **Kodi threading:** `ThreadPoolExecutor` creates daemon threads that are
  safe inside Kodi's Python runtime. Tested pattern in other Kodi addons.
