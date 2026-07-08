# Speed Optimizations — Scrape and Playback

**Date:** 2026-07-08
**Status:** Design approved

## Problem

Users wait unnecessarily due to serial execution, fixed polling intervals, and lack of progress feedback during scraping and magnet resolution.

## Optimizations

### 1. Parallel Scrape + TMDB + Torrentio

**Current:** `scraper_runner.search_all()` → `tmdb.get_imdb_id()` → `torrentio.search_imdb()` → `tmdb.get_poster()` — all serial. Torrentio (24+ trackers) starts only after all HTML scrapers finish.

**Fix:** Launch all four as overlapping `ThreadPoolExecutor` futures:
- `search_all()` in one future
- `get_imdb_id()` in another
- `get_poster()` in another
- When IMDB ID resolves, chain `search_imdb()` as a 4th future
- Join all, merge results

**Result:** Wall time ≈ max(slowest scraper, TMDB calls) instead of sum.

**Files:** `main.py` scrape handler.

### 2. Scrape Progress Dialog

**Current:** Kodi shows a frozen "Working..." dialog for the entire scrape (10-15s).

**Fix:** `DialogProgress` during scrape:
- Title: "Searching for sources..."
- Updates as each scraper/Torrentio completes: "piratebay ✓", "torrentz2 ✓"
- Progress bar: completed / total
- Cancel button returns partial results

**Files:** `main.py` scrape handler.

### 3. AllDebrid Exponential Backoff

**Current:** Fixed 1s polling — 60 calls for a 60s magnet download.

**Fix:** 
- Attempts 1-5: 1s interval
- Attempts 6-10: 2s interval
- Attempts 11-15: 4s interval
- Attempts 16+: 8s interval (capped)

**Result:** ~12 calls for a 60s magnet instead of ~60. Progress callback still fires each poll with accurate ETA.

**Files:** `resources/lib/alldebrid.py` — polling loop interval logic.

### 4. Torrentz2 Parallel Detail Fetches

**Current:** Sequential `for r in results[:10]: detail = _fetch(...)` — only 1-2 complete before 15s scraper timeout kills everything.

**Fix:** `ThreadPoolExecutor(max_workers=5)` for detail page fetches. Return all results that got a magnet (partial results are better than none).

**Files:** `scrapers/torrentz2.py` — search function.

## Edge Cases

- **Cancel during scrape:** Dialog closes, partial results shown, remaining futures abandoned.
- **IMDB ID unavailable:** Torrentio future skipped, scrapers still run.
- **All 10 Torrentz2 detail fetches fail:** Results filtered out, no crash.
- **Backoff interval exceeds timeout:** Timeout takes precedence — loop exits on deadline, not interval.
