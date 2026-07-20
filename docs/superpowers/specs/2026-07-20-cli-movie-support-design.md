# CLI Movie Support — Design

**Date:** 2026-07-20
**Status:** Approved
**Supersedes:** None (extends 2026-07-18-cli-download-design.md)

## Problem

The CLI (`cli.py`) only supports TV shows. It calls `tmdb.search_shows`,
hardcodes `content_type='shows'` in scraper calls, and routes every pick
through season/episode pickers. The Kodi addon (`main.py`) already supports
movies — the CLI just never grew that path.

## Goals

- Searching the CLI returns both shows and movies in one merged list.
- User picks one; movies skip season/episode pickers and download directly.
- Movie manifest entries are correct (`mediatype='movie'`, no season/episode).
- Existing show flow, flags, and partial-file cleanup unchanged.

## Non-Goals

- Movie "batch" downloads (a movie is one file — no batch analog).
- Trakt integration in the CLI (addon-only today).
- Search history (addon has it; CLI doesn't — separate feature).
- Changes to the Kodi addon (it already supports movies).

## Design

### Overall Flow

```
Search input
  → tmdb.search_shows() + tmdb.search_movies() (parallel via ThreadPoolExecutor)
  → merge into one list, each item tagged {type: 'show'|'movie', ...tmdb_fields}
  → search_and_pick renders labels via _label_media: "Title (Year) [Show]" / "[Movie]"
  → user picks one
  → BRANCH on type:
      show  → season picker → episode picker → quality → download_episode (existing, unchanged)
      movie → quality → download_movie (new)
```

The current show flow is untouched. A movie pick skips season/episode
pickers entirely and calls a new `download_movie()`.

### New / Changed Functions in `cli.py`

**New helpers:**

- `_search_all_types(query, settings) -> list[dict]` — runs
  `tmdb.search_shows` and `tmdb.search_movies` in parallel via
  `ThreadPoolExecutor`, tags each result with
  `'type': 'show'|'movie'`, merges into one list.
- `_label_media(item) -> str` — formats a TMDB result as
  `"Title (Year) [Show]"` or `"Title (Year) [Movie]"` for the picker.
  Year omitted if absent.
- `build_movie_query(title, year) -> str` — `"{title} {year}"` if year
  else `"{title}"`. Strips apostrophes (reuses `build_query`'s strip
  logic). Matches what `main.py:400` does for movies.
- `download_movie(movie, quality, settings, dry_run=False) -> bool` —
  the movie-specific flow (detailed below).

**Unchanged:** `build_query`, `_search_with_retry`, `download_episode`,
`download_season`, all pickers, `_cleanup_part_files`, all flags. The
existing `--no-magnet-timeout` and partial-file cleanup apply to movies
too.

**`search_and_pick` refactor:** the current function hand-rolls its
print loop at lines 244-245, hardcoding `"Title (Year)"`. It will be
changed to render labels via `_label_media` and route through
`arrow_select`/`arrow_select_fallback` (which already accept
`(value, display_text)` tuples). This gives movies their `[Movie]` tag
and shows their `[Show]` tag. Existing `search_and_pick` tests need
their expected output format updated.

**`main()` change:** the search step currently calls `tmdb.search_shows`
directly. It'll call `_search_all_types` instead, then dispatch on the
picked item's `type`.

### `download_movie()` Flow

```
download_movie(movie, quality, settings, dry_run=False):
  1. title, year, poster_url = movie fields
  2. query = build_movie_query(title, year)
  3. sources = _search_with_retry(query, content_type='movies')   # reuses retry logic
  4. if no sources → print, return False
  5. best = pick_best_source(sources, quality, max_gb)             # existing helper
  6. if dry_run → print best, return True
  7. api_key, num_segments, magnet_timeout = settings
  8. direct_url = alldebrid.resolve(best['url'], api_key,
            timeout=magnet_timeout,
            progress_callback=_alldebrid_progress)   # NO season/episode — AllDebrid picks largest video file
  9. dest = download_dir / safe_filename(title)     # safe_filename already handles no-season case (download_manager.py:126)
 10. download_video(...) with KeyboardInterrupt/DownloadError cleanup (same pattern as download_episode)
 11. cache artwork, add_to_manifest with mediatype='movie', no season/episode fields
 12. return True
```

Key differences from `download_episode`:

- **No season/episode** anywhere — not in query, not in AllDebrid, not
  in filename, not in manifest.
- **`content_type='movies'`** in `_search_with_retry` so movie-only
  scrapers run and show-only ones (eztv, nyaa) are filtered out.
- **Manifest entry** omits `season`/`episode`, sets `mediatype='movie'`,
  `title` = just the movie title (no `SxxExx`).

The retry-with-shorter-query logic from `_search_with_retry` works for
movies too — "The Lord of the Rings: The Fellowship of the Ring 2001"
would retry as "Fellowship of the Ring 2001", etc.

### `main()` Dispatch

```python
results = _search_all_types(query, settings)        # both shows + movies
picked = search_and_pick(lambda q: results)         # arrow_select labels via _label_media
if picked is None: ...
if picked['type'] == 'show':
    seasons = tmdb.get_seasons(picked['id'], ...)
    season = select_season(seasons)
    episodes = tmdb.get_episodes(...)
    ep_choice = select_episode(episodes)
    quality = select_quality(...)
    # existing show branch unchanged
else:  # movie
    quality = select_quality(...)
    ok = download_movie(picked, quality, settings, dry_run=args.dry_run)
    return 0 if ok else 1
```

One subtlety: `search_and_pick` currently takes a `search_fn` callable
and calls it inside a re-prompt loop (so the user can re-search on
empty results). With the merged search we want to fetch both types
once per search query. The refactor: `search_and_pick` keeps its
re-prompt loop and `search_fn` callable, but `main()` passes a
`search_fn` that wraps `_search_all_types` — so each user search query
triggers one parallel show+movie fetch. The picked item then carries
its `type` tag into the branch below.

## Testing Strategy

**New tests in `test_cli.py`:**

- `BuildMovieQueryTests` — `build_movie_query("Inception", "2010")` →
  `"Inception 2010"`; with year `""` → `"Inception"`; apostrophe
  stripping.
- `SearchAllTypesTests` — mock `tmdb.search_shows` and
  `tmdb.search_movies`, verify both called, results tagged with `type`,
  merge order doesn't matter.
- `LabelMediaTests` — `_label_media` produces
  `"Inception (2010) [Movie]"`, `"Breaking Bad (2008) [Show]"`, omits
  year when absent.
- `DownloadMovieTests` — mocked scrape/resolve/download (same pattern
  as `DownloadEpisodeTests`): verifies manifest entry has
  `mediatype='movie'`, no `season`/`episode`, filename has no `SxxExx`,
  `content_type='movies'` passed to `search_all`.
- `SearchAndPickTests` (update existing) — expected display format now
  includes `[Show]`/`[Movie]` suffix.

**Unchanged:** all existing show tests, `CleanupPartFilesTests`,
`SearchWithRetryTests`, `MainArgsTests`.

**Manual verification:** `python3 cli.py` → search "Inception" → pick
the movie → quality picker → dry-run shows picked source. Same for a
show to confirm no regression.

## Scope Boundaries

**In scope:** CLI searches both shows and movies, picks one, downloads
movies end-to-end, manifest entry correct, partial-file cleanup applies.

**Out of scope (YAGNI):**

- Movie "batch" downloads (movies are one file).
- Trakt integration in the CLI (addon-only today).
- Search history (separate feature).
- Changes to the Kodi addon (it already supports movies).
