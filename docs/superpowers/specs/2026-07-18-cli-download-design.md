# CLI Download Script — Design

**Date:** 2026-07-18
**Status:** Approved (brainstormed 2026-07-18)

## Goal

A standalone terminal script (`cli.py`) that downloads a single episode or a
whole season of a show and registers the result into the addon's downloads
manifest, so the file shows up in Kodi's "Downloads" section without any
manual import.

## Why

Hotel-WiFi download sessions benefit from running on a laptop over SSH where
the parallel-segment downloader can run uninterrupted. The addon's UI is
awkward to drive remotely; a CLI is not.

## Scope

**In scope:**
- Single-episode downloads (interactive: show name → TMDB pick → season → episode → quality menu)
- Whole-season downloads (same prompts, episode blank → all episodes via TMDB episode count)
- Auto-pick best source (sort: quality match → seeders → size; no interactive prompt)
- Arrow-key quality selector (4K → 1080p → 720p → 480p, always shown before scraping)
- Reads API credentials from Kodi's `settings.xml`
- Registers downloads in the addon's `downloads.json` manifest
- Reuses the existing parallel-segment downloader for speed

**Out of scope:**
- Movies (deferred — would widen scope)
- Interactive source picker (auto-pick only)
- Custom config file or env-var credentials (Kodi settings only)
- Re-encode / transcode

## Architecture — Approach A

One new file: `cli.py` at the project root, next to `check_scrapers.py`. It
imports existing addon modules directly — zero code duplication. Same pattern
as `check_scrapers.py`, which already imports `scrapers` as a library.

### Imports from existing modules

- `resources.lib.scraper_runner.search_all` — parallel scraping
- `resources.lib.alldebrid.resolve` — magnet → direct URL (episode-aware)
- `resources.lib.download_manager.download_video`, `add_to_manifest`,
  `safe_filename`, `get_download_dir`, `cache_artwork`, `art_dir`
- `resources.lib.tmdb.search_shows`, `get_episodes` — show + episode lookup

### New code in `cli.py`

1. `read_kodi_settings(path)` — parses
   `~/.kodi/userdata/addon_data/plugin.video.baldest_man/settings.xml` and
   returns a dict. Replaces `xbmcaddon.Addon().getSetting()` for the CLI
   context. Returns `{}` on missing file; caller exits with code 4 if the
   `alldebridtoken` or `tmdb_api_key` keys are empty.
2. Interactive prompt helpers (all curses-based, arrow-key navigation):
   - `search_and_pick(title_prompt)` — split-pane: a search input line at the
     top (type query, Enter to search) and a scrollable results list below
     (arrow keys to highlight, Enter to select, `q`/Esc to cancel). Used for
     the show lookup. TMDB matches are fetched on Enter and rendered as
     `Title (year)  imdb_id`. Returns the chosen match dict.
   - `arrow_select(options, label, default=0)` — generic vertical arrow-key
     menu. `options` is a list of `(value, display_text)` tuples. Up/Down
     move the highlight, Enter selects, `q`/Esc cancels (raises
     `KeyboardInterrupt`). `default` is the initial highlight index. Used
     for seasons, episodes, and quality.
   - `select_quality(default="720p")` — specialization of `arrow_select`
     with the fixed `4K / 1080p / 720p / 480p` list and the addon's
     `offline_quality` as the default highlight.
   - `select_season(seasons)` — `arrow_select` over `seasons` (from
     `tmdb.get_seasons`), rendered as `Season N (X episodes)`.
   - `select_episode(episodes)` — `arrow_select` over a list whose first
     item is `("all", "Whole season")` and remaining items are
     `(episode_number, "E{N} — {episode name}")` from `tmdb.get_episodes`.
     Returns the chosen value (`"all"` for whole-season mode, or the
     episode integer).
   - All helpers raise `KeyboardInterrupt` on `q`/Esc/Ctrl-C (caller exits 130).
   - A non-curses fallback (`arrow_select_fallback`, `search_and_pick_fallback`)
     using numbered lists is provided for non-TTY environments (CI, piped
     stdin). Selected automatically when `sys.stdin.isatty()` is False or
     `curses` is unavailable.
3. `main()` — flag parsing, drives the prompt → quality menu → scrape →
   resolve → download flow, prints terminal progress.
4. A terminal progress callback that prints `123 / 1500 MB (8%)` on the same
   line using `\r` and flushes.

No changes to existing modules. `download_video(num_segments=N)` already
accepts the segment count as a param, so the CLI passes the settings value
through directly instead of relying on `xbmcaddon`.

## Command-line interface

Fully interactive: you run `cli.py` and answer prompts. No positional args.

```
$ cli.py
  Search: breaking bad|
                                    
    Breaking Bad (2008)        tt0903747
    Breaking Bad: Original Minisodes (2009)
  > Better Call Saul (2015)
    
  (type to search, ↑/↓ move, Enter select, q cancel)

  Seasons:
    Season 1 (7 episodes)
  > Season 2 (13 episodes)
    Season 3 (13 episodes)

  Episodes:
  > Whole season
    E1 — Seven Thirty-Seven
    E2 — Grilled
    ...

  Select preferred quality:
    4K
    1080p
  > 720p
    480p

[scrape] 6 sources found
[scrape] best: Breaking.Bad.S02E03.720p.BluRay.mkv (4.1GB, 120 seeders)
...
```

### Optional flags (still on the command line)

These stay as CLI flags since they're settings overrides, not the primary
input flow:

- `--segments <N>` — overrides `download_segments` setting. `1` = sequential.
- `--max-size-gb <N>` — overrides `max_download_size_gb` setting.
- `--dry-run` — scrape, pick best source per episode, print the choice, skip
  download and manifest write.
- `--help` — usage.

### Interactive prompts (all arrow-key navigation)

1. **Show lookup** — split-pane search UI. Type a query on the search line,
   press Enter to fetch TMDB matches, arrow keys to highlight a result,
   Enter to select. `q`/Esc cancels.
2. **Season selector** — arrow-key menu over the show's seasons (fetched via
   `tmdb.get_seasons`), rendered as `Season N (X episodes)`. No typing.
3. **Episode selector** — arrow-key menu whose first item is always
   `Whole season`; remaining items are `E{N} — {episode name}` from
   `tmdb.get_episodes`. Selecting `Whole season` enters batch mode.
4. **Quality selector** — arrow-key menu, always shown. Options top-to-
   bottom: `4K`, `1080p`, `720p`, `480p`. Default highlight is the
   `offline_quality` addon setting (typically `720p`).

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | No sources found |
| 2 | TMDB lookup failed (zero matches) |
| 3 | AllDebrid error |
| 4 | Settings missing (no API key) |
| 5 | Invalid CLI flags (e.g. `--segments 99`) |
| 130 | KeyboardInterrupt |

### Output style

Plain text, minimal. Each step prefixed with its stage:
```
[tmdb] Breaking Bad -> show_id=1396, imdb=tt0903747
[scrape] 6 sources found
[scrape] best: Breaking.Bad.S01E03.720p.BluRay.mkv (4.1GB, 120 seeders)
[alldebrid] uploading magnet...
[alldebrid] waiting for magnet... 25%
[alldebrid] ready
[download] 123 / 4100 MB (3%)
...
Done: /home/bryce/.bald_man/downloads/Breaking.Bad.S01E03.mp4
```

## Flow

### Startup (both modes)

1. Parse CLI flags (`--segments`, `--max-size-gb`, `--dry-run`).
   Invalid flag values → exit 5.
2. `read_kodi_settings()` — exit 4 if `alldebridtoken` or `tmdb_api_key` empty.
3. `search_and_pick("Search: ")` — user types a show name, presses Enter,
   arrow-keys through TMDB matches. Exit 2 if TMDB returns zero matches.
   User's pick → `show_id`, `imdb_id`, poster.
4. `tmdb.get_seasons(show_id)` → `select_season(seasons)` — arrow-key menu.
   Returns the chosen `season_number`.
5. `tmdb.get_episodes(show_id, season)` → `select_episode(episodes)` —
   arrow-key menu with `Whole season` as the first option. Returns either
   `"all"` (whole-season mode) or an `episode_number` (single-episode mode).
6. `select_quality(default=settings.offline_quality)` — curses arrow-key
   menu. Returns the chosen quality string (`4K`, `1080p`, `720p`, or
   `480p`). Cancellation → exit 130.

### Single episode

7. `scraper_runner.search_all(query=build_query(title, season, episode), content_type="shows")`.
8. `pick_best_source(sources, quality, max_gb)` — filter by size, sort by
   quality match → seeders → size. Take top. Exit 1 if empty.
9. `alldebrid.resolve(url, api_key, season, episode, progress_callback=...)`.
10. `download_manager.download_video(direct_url, dest, num_segments=N, progress_callback=...)`.
11. `cache_artwork(poster_url, art_dir()/fname.poster.jpg)`.
12. `add_to_manifest({...})` — same entry shape the addon uses:
    `{id, title, show_title, season, episode, file_path, size_bytes,
    date_added, mediatype, plot, poster_path}`.
13. Print `Done: <path>`.

### Whole season

7. Episode count = `len(episodes)` (already fetched in step 5).
8. Loop episodes 1..N. For each: scrape, pick best (using the quality
   chosen in step 6 — asked once, applied to every episode), resolve,
   download, manifest.
   - If an episode has zero viable sources → print `[skip] S1E5: no sources`,
     continue (don't abort the whole batch).
   - If the destination file already exists with the expected size → print
     `[skip] S1E3: already downloaded`, continue.
9. End-of-run summary: `Downloaded 8/10 episodes. Skipped: S1E5, S1E9`.

## Error handling

| Failure | Behavior |
|---------|----------|
| TMDB lookup fails (no show) | Exit 2 immediately, nothing downloaded |
| Scrape returns nothing for an episode | Skip that episode, continue |
| AllDebrid resolve fails | Skip, log `[fail] S1E3: <error>`, continue |
| Download failure (network) | Skip, log, continue |
| KeyboardInterrupt | Stop current episode cleanly, print what completed, exit 130 |

Resume: `download_video` already handles `.part` resume per-source, so
re-running the CLI after an interrupted download continues where it left off.

## Testing

Unit tests in `test_cli.py`, stdlib `unittest` only (same pattern as
`test_alldebrid.py`, `test_download_manager.py`).

### Pure helper tests (no network)

- `read_kodi_settings(fixture_xml)` → dict with expected keys; returns `{}`
  on missing file; missing `alldebridtoken` reflected in dict.
- `pick_best_source(sources, quality, max_gb)` — with crafted
  source list:
  - `quality="720p"`: prefers 720p over 1080p and 4K, drops oversized
    sources, breaks ties by seeders descending then size descending.
  - `quality="4K"`: prefers sources whose `quality` field is `4k` or
    `2160p` (both map to the 4K tier — matching the addon's
    `_QUALITY_RANK` in `main.py:268`).
  - No exact-quality match: falls back to the next-best available tier
    rather than returning `None`.
- `QUALITY_RANK` dict — local copy of the addon's rank mapping
  (`{'4k': 4, '2160p': 4, '1080p': 3, '720p': 2, '480p': 1}`). Duplicated
  in `cli.py` rather than imported from `main.py` (which imports xbmc at
  module top level and is unsafe to import outside Kodi).
- `build_query("Breaking Bad", 1, 3)` → `"Breaking Bad S01E03"`.
- `episode_already_downloaded(dest_path, expected_size)` — True when file
  exists with matching size, False otherwise.
- `build_season_options(seasons)` — given TMDB-shaped
  `[{season_number: 1, episode_count: 7, name: "Season 1"}, ...]` returns
  `[(1, "Season 1 (7 episodes)"), ...]` for `arrow_select`.
- `build_episode_options(episodes)` — given TMDB-shaped
  `[{episode_number: 1, name: "Seven Thirty-Seven"}, ...]` returns
  `[("all", "Whole season"), (1, "E1 — Seven Thirty-Seven"), ...]`.
- `build_quality_options(default="720p")` — returns
  `[("4K", "4K"), ("1080p", "1080p"), ("720p", "720p"), ("480p", "480p")]`
  with the default's index noted for the initial highlight.
- `arrow_select_fallback(options, label, input_seq)` — the non-curses path
  used when stdin is not a TTY or curses is unavailable. Monkeypatch
  `input()` to yield `"2"` → returns the third option's value; `"0"`,
  `"99"`, and `"x"` re-prompt; `"q"` raises `KeyboardInterrupt`. The
  curses rendering itself is not unit-tested (visual; covered by manual run).
- `search_and_pick_fallback(search_fn, input_seq)` — the non-curses path
  for show lookup. First `input()` is the search query, second is the
  pick number. Verifies that `search_fn` is called with the query and
  the correct match is returned; empty query re-prompts; invalid pick
  re-prompts.

### Integration tests (local HTTP server)

- End-to-end single-episode flow with TMDB + AllDebrid mocked (inject fake
  `search_shows` + fake `resolve` that returns a local file URL from the
  throttled Range handler). Verify the manifest gets the new entry and the
  file lands on disk byte-identical.
- Season-batch with 3 fake episodes: verify all 3 are downloaded and
  manifested; one episode with no sources is skipped without aborting the
  batch.

### Out of scope for tests

- Real TMDB/AllDebrid network calls (credentials, flaky). The existing
  `test_alldebrid.py` already covers AllDebrid's file-picker logic.
- Live progress-line rendering (visual; covered by manual run).

## Open questions

None — all resolved during brainstorming.
