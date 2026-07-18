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
- Single-episode downloads: `cli.py "Breaking Bad" S1E3`
- Whole-season downloads: `cli.py "Breaking Bad" S1` (TMDB episode count)
- Auto-pick best source (sort: quality match → seeders → size; no interactive prompt)
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
2. Interactive prompt helpers:
   - `prompt_str(label)` — prints `label`, returns stripped input, re-prompts
     on empty.
   - `prompt_int(label, min_val=None, max_val=None)` — parses an int, re-prompts
     on invalid/out-of-range. `min_val`/`max_val` optional bounds.
   - `prompt_pick(matches, label="Pick [1-N]: ")` — prints a numbered list,
     returns the chosen match dict, re-prompts on out-of-range / non-integer.
   All helpers raise `KeyboardInterrupt` naturally on Ctrl-C (caller exits 130).
3. `main()` — flag parsing, drives the prompt → scrape → resolve → download
   flow, prints terminal progress.
4. A terminal progress callback that prints `123 / 1500 MB (8%)` on the same
   line using `\r` and flushes.

No changes to existing modules. `download_video(num_segments=N)` already
accepts the segment count as a param, so the CLI passes the settings value
through directly instead of relying on `xbmcaddon`.

## Command-line interface

Fully interactive: you run `cli.py` and answer prompts. No positional args.

```
$ cli.py
Enter show name: breaking bad
[tmdb] searching...

  1. Breaking Bad (2008)        tt0903747
  2. Breaking Bad: Original Minisodes (2009)
  3. Better Call Saul (2015)
Pick [1-3]: 1

Season: 1
Episode (blank for whole season): 3

[scrape] 6 sources found
[scrape] best: Breaking.Bad.S01E03.720p.BluRay.mkv (4.1GB, 120 seeders)
...
```

### Optional flags (still on the command line)

These stay as CLI flags since they're settings overrides, not the primary
input flow:

- `--quality <480p|720p|1080p>` — overrides `offline_quality` setting.
- `--segments <N>` — overrides `download_segments` setting. `1` = sequential.
- `--max-size-gb <N>` — overrides `max_download_size_gb` setting.
- `--dry-run` — scrape, pick best source per episode, print the choice, skip
  download and manifest write.
- `--help` — usage.

### Interactive prompts

1. **Show name** — `Enter show name: `. Free text. Empty input re-prompts.
2. **TMDB match picker** — top N matches printed as a numbered list
   (`1. Title (year)  imdb_id`). `Pick [1-N]: `. Invalid number re-prompts.
   Default N is 5; if fewer matches, shows all.
3. **Season** — `Season: `. Integer. Invalid input re-prompts.
4. **Episode** — `Episode (blank for whole season): `. Positive integer or
   blank. Blank = whole season (TMDB episode count). Zero, negatives, and
   non-integer input re-prompt.

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

1. Parse CLI flags (`--quality`, `--segments`, `--max-size-gb`, `--dry-run`).
   Invalid flag values → exit 5.
2. `read_kodi_settings()` — exit 4 if `alldebridtoken` or `tmdb_api_key` empty.
3. Prompt `Enter show name: `. Empty input re-prompts.
4. `tmdb.search_shows(title)` → list of matches. Exit 2 if zero matches.
   Print numbered list (`1. Title (year)  imdb_id`). Prompt `Pick [1-N]: `.
   Invalid number re-prompts. User's pick → `show_id`, `imdb_id`, poster.
5. Prompt `Season: `. Invalid input re-prompts.
6. Prompt `Episode (blank for whole season): `. Blank → whole season mode;
   integer → single-episode mode. Invalid input re-prompts.

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

7. `tmdb.get_episodes(show_id, season)` → list of `{episode_number, name}`.
   Episode count = `len(list)`.
8. Loop episodes 1..N. For each: scrape, pick best, resolve, download, manifest.
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
- `pick_best_source(sources, quality="720p", max_gb=2)` — with crafted
  source list: prefers sources matching the requested quality (falls back to
  next-best if no exact match), drops oversized sources, breaks ties by
  seeders descending then size descending.
- `build_query("Breaking Bad", 1, 3)` → `"Breaking Bad S01E03"`.
- `episode_already_downloaded(dest_path, expected_size)` — True when file
  exists with matching size, False otherwise.
- `prompt_int("Season: ", min_val=1)` — monkeypatch `input()` to return
  `"1"` → returns `1`; returns `"0"` → re-prompts and `"2"` → returns `2`.
- `prompt_pick(matches, prompt="Pick [1-N]: ")` — with a 3-item list and
  `input` returning `"2"` → returns the second match; `"4"` → re-prompts,
  `"x"` → re-prompts, `"0"` → re-prompts.

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
