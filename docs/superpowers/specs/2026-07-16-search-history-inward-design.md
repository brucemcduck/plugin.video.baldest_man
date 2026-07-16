# Search History → Inward (Show-Centric) Design

**Date:** 2026-07-16
**Status:** Approved
**Implements:** `ideas.txt` item #1 — "change search history to be more inward (straight into the series, ignore the imdb scrape)"
**Supersedes:** `2026-07-16-search-history-design.md` (query-centric history)

## Problem

Today, Search History (`mode=search_history`, `main.py:861`) shows a flat list of past *query strings* (e.g. `[Shows] Breaking Bad`). Clicking an entry routes to `mode=search` with `q=<query>` (`main.py:874`), which re-runs the **TMDB lookup** (the "imdb scrape") unless a cache hit, then shows the pick-a-match list, then seasons, then episodes. There are two extra hops before the user is "in the series": the TMDB re-search and the show-selection list.

## Goal

Search History shows **the shows/movies the user actually drilled into**, each rendered with its poster as a folder. Clicking an entry jumps **straight to seasons** (shows) or **straight to scrape** (movies) — no TMDB re-search, no pick-a-match list.

## Approach

A single-file change to `main.py`. The history schema shifts from query-centric to show/movie-centric. The record point moves *inward* from `mode=search` (query stage) to `mode=seasons` (shows) and `mode=scrape` (movies). The Search History view becomes a list of show/movie folders with posters, each linking directly to `seasons`/`scrape` — zero TMDB calls anywhere in the history flow.

Only search-derived drill-ins are recorded. A `src=search` flag on the folder URL gates recording so that Trakt, Continue Watching, and episode-drill paths do not pollute *Search* History.

## Files touched

| File | Change |
|------|--------|
| `main.py` | New schema + `_add_search_history(record)` signature; record point moved into `seasons`/`scrape`; `mode=search` no longer records history and no longer reads `q=`; folder URLs carry drill-in metadata + `src=search`; `mode=search_history` renders show/movie folders with posters linking to `seasons`/`scrape` |

No other files change. `resources/lib/tmdb.py` is unchanged — it already returns `{id, title, year, overview, poster_url}` for both shows and movies.

## Data model

History entry (replaces the old `{query, content_type, timestamp}`):

```python
{'kind': 'show'|'movie',
 'show_id': int,
 'title': str,
 'year': str,
 'poster_url': str,
 'content_type': str,
 'timestamp': int}
```

Dedup by `show_id` (replaces case-insensitive query dedup). `_MAX_HISTORY` stays 20. The JSON file path (`_SEARCH_HISTORY`) is unchanged — ephemeral temp file, so the schema break is acceptable.

## Component changes (all in `main.py`)

### 1. `_add_search_history(record)` — `main.py:89`

New signature: takes a single record dict instead of `(query, content_type)`. Dedups by `show_id` (not title). Inserts at front, trims to `_MAX_HISTORY`. Otherwise unchanged.

### 2. `mode=search` — `main.py:586`

- **Remove** the dead `q_param` re-run path (lines 594-606): the `q` query param, the cache-hit check, the `else` TMDB re-search, and the `_add_search_history(query, content_type)` call. History no longer re-runs search.
- **Remove** the second `_add_search_history(query, content_type)` call (line 621) in the dialog branch. Searches no longer record history at all.
- **Enrich** the show-folder URL (`main.py:627`) with `year`, `poster_url`, and `src=search`:
  ```python
  url = build_url({'mode': 'seasons', 'show_id': str(s['id']),
                   'show_title': s['title'], 'year': s.get('year', ''),
                   'poster_url': s.get('poster_url', ''), 'src': 'search'})
  ```
- **Enrich** the movie-folder URL (`main.py:636`) with `poster_url` and `src=search` (year already passed):
  ```python
  url = build_url({'mode': 'scrape', 'show_title': m['title'],
                   'year': m.get('year', ''), 'show_id': str(m['id']),
                   'poster_url': m.get('poster_url', ''),
                   'content_type': 'movies', 'src': 'search'})
  ```
- The `q`-less cache-hit branch (`elif cached…`, line 607) and the dialog branch (`else`, line 612) are unaffected and still serve back-navigation from the current search.

### 3. `mode=seasons` — `main.py:660`

Read the new params. When `src == 'search'`, save a `show` history record:

```python
src = args.get('src', [''])[0]
if src == 'search':
    _add_search_history({
        'kind': 'show',
        'show_id': show_id,
        'title': show_title,
        'year': args.get('year', [''])[0],
        'poster_url': args.get('poster_url', [''])[0],
        'content_type': 'shows',
        'timestamp': int(time.time()),
    })
```

This runs once per drill-in. Re-entering a show from Search History also carries `src=search`, so the entry re-bumps to front (dedup by `show_id`).

### 4. `mode=scrape` — `main.py:726`

Read `src`. When `src == 'search'` **and** `content_type == 'movies'`, save a `movie` record. Show-episode scrapes carry `content_type='shows'`, so they are excluded — only the movie scrape records.

```python
src = args.get('src', [''])[0]
if src == 'search' and content_type == 'movies':
    _add_search_history({
        'kind': 'movie',
        'show_id': int(args.get('show_id', ['0'])[0]),
        'title': show_title,
        'year': year,
        'poster_url': args.get('poster_url', [''])[0],
        'content_type': 'movies',
        'timestamp': int(time.time()),
    })
```

### 5. `mode=search_history` — `main.py:861`

Render show/movie ListItems with posters via the existing `set_info()` helper, each linking **directly** to the inward mode:

- **Show entries** → `mode=seasons` with `show_id`, `show_title`, `year`, `poster_url` (and `src=search` so re-entry re-bumps). `set_info(li, {'title': title, 'poster_url': poster_url}, is_folder=True)` — history records carry no `overview`, and `set_info` guards on its absence.
- **Movie entries** → `mode=scrape` with movie params + `src=search`. Same `set_info` call with the movie's `title`/`poster_url`.
- **Legacy entries** (no `show_id` or `kind`): skipped silently — no crash, no render.
- **Empty state**: unchanged ("No search history yet").
- **Context menus**: Delete (`mode=delete_history` with `index`) and Clear All (`mode=clear_history`) unchanged — index-based deletion is unaffected by the schema change.

### 6. `delete_history` / `clear_history` — `main.py:890`, `main.py:901`

No changes. Index-based pop and full-clear both work identically against the new schema.

## Data flow

```
Search (dialog) → TMDB → pick show  → seasons  [RECORDS show history]  → seasons list
Search (dialog) → TMDB → pick movie → scrape   [RECORDS movie history] → scrape results

Search History → show/movie folders (poster) → seasons / scrape   [re-bumps to front]
```

No TMDB call occurs on viewing Search History or on clicking an entry.

## Error handling

- **Legacy entries** (no `show_id`/`kind`): skipped on render, no crash, no log spam.
- **Corrupt/missing JSON**: `_load_search_history()` returns `[]` (existing behavior).
- **Write failures**: `_save_search_history()` silently ignores (existing).
- **Missing poster/year**: renders with available fields; `set_info` guards on `poster_url`/`overview` presence (existing).

## Scope boundary

Only paths carrying `src=search` record history. This excludes:
- Trakt browse (`mode=trakt_browse`) — folder URLs don't carry `src=search`.
- Continue Watching (`mode=continue_watching`) — links to `mode=scrape` without `src=search`.
- Episode drill from seasons/episodes — `mode=scrape` with `content_type='shows'` is excluded by the movie-only gate.

If a future need arises to track those, the gate is the single knob to relax.

## Verification

No test framework — the plugin runs inside Kodi. Manual checklist:

1. **Show records** — search a show → open seasons → open Search History → entry appears with poster, labeled `Title (Year)`.
2. **Movie records** — search a movie → click it (scrape) → open Search History → entry appears with poster.
3. **Inward navigation** — click a show entry → lands directly in seasons (no TMDB re-search, no pick-a-match list). Click a movie entry → lands directly in scrape results.
4. **Re-bump** — re-open a history show → it moves to the front of Search History (dedup by `show_id`).
5. **No TMDB on view** — open Search History with the network disabled → list still renders (posters may fail, labels remain).
6. **Delete single** — long-press a history item → Delete → item removed, list refreshes.
7. **Clear all** — long-press → Clear All → history empty, "No search history yet" shown.
8. **Legacy entries** — put an old `{query, content_type, timestamp}` entry in the JSON → it is skipped on render, no crash.
9. **Corrupt JSON** — put garbage in the JSON file → history loads as empty, no crash.
10. **Scope gate** — browse Trakt watchlist → drill into a show → Search History is unchanged (no new entry).
