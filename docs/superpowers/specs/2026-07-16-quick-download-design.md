# Quick Download Design

**Date:** 2026-07-16
**Status:** Approved (design phase)

## Problem

Currently, downloading requires the user to browse TMDB → select a show/movie → wait for all scrapers to finish → visually scan a source list → pick one → download. This is slow and tedious, especially for offline preparation (e.g., before a flight). The addon already has an unused `_pick_offline_source()` function that was never wired up.

## Solution

Add a "Quick Download" context menu action on movie, episode, and season ListItems that scrapes sources, auto-picks the best one (highest quality, smallest size), and downloads it — with fallback through subsequent sources if the first fails. For seasons, a multi-select dialog lets the user pick specific episodes or default to the whole season.

## Architecture

**Approach:** Add a new `mode=quick_download` handler in `main.py` plus a reusable `_scrape_with_early_termination()` helper extracted from the existing `mode=scrape` handler. Add context menu items to movie (in `mode=search`), episode (in `mode=episodes`), and season (in `mode=seasons`) ListItems. One new setting in `settings.xml`.

### Files changed

| File | Change |
|---|---|
| `main.py` | New `mode=quick_download` handler; `_scrape_with_early_termination()` helper; `_quick_download_one()` helper; `_quick_download_season()` helper; context menu items on movie/episode/season ListItems |
| `resources/settings.xml` | New `quick_download_max_sources` setting in Offline Downloads category |

No new files.

## Quick Download Handler (mode=quick_download)

### Single item (movie or episode)

URL params: same as `mode=scrape` (`show_title`, `show_id`, `year`, `season_number`, `episode_number`, `episode_title`, `content_type`).

1. **Scrape with early termination** — fire `scraper_runner.search_all` + `torrentio.search_imdb` (if IMDB ID available) in parallel via `ThreadPoolExecutor`, same as `mode=scrape`. Stop as soon as `quick_download_max_sources` viable results (passing `_seeder_ok` filter) are collected. Cancel remaining futures. If fewer arrive, proceed once all futures settle.

2. **Filter** — apply existing `_seeder_ok` check (seeder count proportional to file size).

3. **Sort** — quality descending (1080p → 720p → SD → unknown), then size ascending within each quality tier. This yields "highest quality, smallest size first."

4. **Try with fallback** — iterate sorted sources. For each, call `ad_resolve()` to resolve on AllDebrid. If it succeeds, hand the direct URL to `download_manager.download_file()`. If resolution fails (`AllDebridError`), log and try the next source. Continue until one downloads successfully or all sources exhausted.

5. **Progress dialog** — single `DialogProgress` covering the whole flow:
   - "Scraping..." (during scrape)
   - "Resolving source 1/N..." (during each resolve attempt)
   - "Downloading..." (during download)
   - "Downloaded: {label}" (success) or "All sources failed" (exhausted)

6. **No source list shown** — the user never sees scrape results. Straight from context menu → download.

### Season (multi-select)

URL params: `show_id`, `show_title`, `season_number`.

1. **Fetch episode list** from TMDB via `tmdb.get_episodes(show_id, season_number, ...)`.
2. **Show `xbmcgui.Dialog().multiselect()`** — episode titles as checkboxes.
3. **User selects specific episodes** → download only those, sequentially.
4. **User presses OK with nothing selected** → download entire season.
5. **User cancels (back button)** → abort, nothing happens.
6. **Download sequentially** — each episode runs the same scrape→sort→fallback flow as single-item. Progress dialog: "Episode 2/24: Resolving..." → "Episode 2/24: Downloading..." → next episode.
7. Continue through all selected episodes. If one episode fails all sources, notify and continue to the next (don't abort the whole season).

## Reusable Helper: _scrape_with_early_termination()

Extracted from the existing `mode=scrape` handler (main.py:448-544). Both `mode=scrape` and `mode=quick_download` call it.

```python
def _scrape_with_early_termination(query, content_type, show_id=None,
                                    is_movie=False, season_number=None,
                                    episode_number=None, max_sources=None):
    """Scrape sources with optional early termination.
    Returns (results, poster_url, imdb_id, meta).
    If max_sources is set, stops collecting once that many viable results
    (passing _seeder_ok) are found. If None, waits for all scrapers."""
```

- `mode=scrape` calls it with `max_sources=None` (collect all, current behavior unchanged).
- `mode=quick_download` calls it with `max_sources=int(ADDON.getSetting('quick_download_max_sources') or '10')`.

The existing `mode=scrape` handler is refactored to call this helper instead of inlining the scrape logic. Its behavior remains identical (collect all, sort largest-first, show list).

## Sort Order

```python
QUALITY_RANK = {'4k': 4, '2160p': 4, '1080p': 3, '720p': 2, '480p': 1}

def _quality_sort_key(r):
    q = (r.get('quality') or '').lower()
    rank = QUALITY_RANK.get(q, 0)
    size = _parse_size_bytes(r.get('size', '')) or 0
    return (-rank, size)  # negative rank = descending, size ascending
```

Sort key: `(-quality_rank, size)` — highest quality first, smallest size within each quality tier.

## Context Menu Items

| Location | Mode | Menu item | URL params |
|---|---|---|---|
| Movie ListItem (`mode=search`, line ~346) | `search` | "Quick Download" | Same as scrape URL for that movie |
| Episode ListItem (`mode=episodes`, line ~396) | `episodes` | "Quick Download" | Same as scrape URL for that episode |
| Season ListItem (`mode=seasons`, line ~371) | `seasons` | "Quick Download Season" | `mode=quick_download`, `show_id`, `show_title`, `season_number`, `content_type=shows` |

Added via `li.addContextMenuItems([('Quick Download', 'RunPlugin({})'.format(url))])` — same pattern as the existing "Download for Offline" item at main.py:203.

## Setting

Added to `settings.xml` in the Offline Downloads category:

```xml
<setting id="quick_download_max_sources" type="integer"
         label="Quick Download: max sources to collect" default="10">
  <constraints>
    <minimum>2</minimum>
    <maximum>50</maximum>
  </constraints>
</setting>
```

## Error Handling

- **No sources found** — notify "No sources found for {title}" and stop.
- **All sources fail to resolve** — notify "All {N} sources failed for {title}" and stop (or continue to next episode in season mode).
- **Network errors** — `clean_error()` surfaces readable messages (existing helper).
- **Download cancellation** — user cancels progress dialog, abort immediately. Already downloaded episodes in a season batch are kept.
- **Individual episode failure in season** — notify "{episode} failed", continue to next episode. Don't abort the batch.

## Out of Scope

- **No parallel episode downloads** — season downloads are sequential to avoid hammering AllDebrid and to keep progress UI clear.
- **No resume of interrupted season batch** — if cancelled mid-season, completed episodes are in the manifest; the user re-triggers and re-selects remaining episodes.
- **No quality preference setting for quick download** — the sort always tries highest quality first. The existing `offline_quality` setting applies to the manual download flow only.
- **No dedup across episodes** — each episode scrapes independently.

## Testing


1. **Movie quick download** — search a movie → long-press → Quick Download → progress dialog shows scrape/resolve/download → file appears in My Downloads
2. **Episode quick download** — browse show → season → episode → long-press → Quick Download → same flow
3. **Season quick download (all)** — browse show → season → long-press → Quick Download Season → multiselect dialog → OK with nothing selected → all episodes download sequentially
4. **Season quick download (selective)** — same flow → select 3 episodes → only those 3 download
5. **Season quick download (cancel)** — same flow → back button → nothing happens
6. **Source fallback** — find a title where the first source fails to resolve (bad magnet) → verify it tries the next source automatically
7. **Early termination** — set `quick_download_max_sources` to 2 → verify scraping stops after 2 viable results
8. **All sources fail** — search a nonexistent title → "No sources found" notification
9. **Episode failure in season** — if one episode has no sources → notify + continue to next episode
10. **Cancel mid-download** — cancel during a season batch → already-downloaded episodes remain in manifest
