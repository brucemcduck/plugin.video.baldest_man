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
2. `main()` — argv parsing, flow driver, terminal progress.
3. A terminal progress callback that prints `123 / 1500 MB (8%)` on the same
   line using `\r` and flushes.

No changes to existing modules. `download_video(num_segments=N)` already
accepts the segment count as a param, so the CLI passes the settings value
through directly instead of relying on `xbmcaddon`.

## Command-line interface

```
cli.py "Breaking Bad" S1E3              # single episode
cli.py "Breaking Bad" S1                # whole season (TMDB episode count)
cli.py "Breaking Bad" S1E3 --quality 1080p
cli.py "Breaking Bad" S1 --segments 8
cli.py "Breaking Bad" S1 --dry-run      # list sources, don't download
cli.py "Breaking Bad" S1 --max-size-gb 5
```

### Positional arguments

- `<title>` — show name, quoted if it has spaces. Matched against TMDB; top
  result used (no prompt).
- `<SxxEy>` — single episode, e.g. `S1E3`.
- `<Sxx>` — whole season, e.g. `S1`. Episode count from TMDB.

### Optional flags

- `--quality <480p|720p|1080p>` — overrides `offline_quality` setting.
- `--segments <N>` — overrides `download_segments` setting. `1` = sequential.
- `--max-size-gb <N>` — overrides `max_download_size_gb` setting.
- `--dry-run` — scrape, pick best source per episode, print the choice, skip
  download and manifest write.
- `--help` — usage.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | No sources found |
| 2 | TMDB lookup failed |
| 3 | AllDebrid error |
| 4 | Settings missing (no API key) |
| 5 | Invalid arguments |
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

### Single episode (`S1E3`)

1. `read_kodi_settings()` — exit 4 if `alldebridtoken` or `tmdb_api_key` empty.
2. `tmdb.search_shows(title)` → first result → `show_id`, `imdb_id`, poster.
3. `scraper_runner.search_all(query=build_query(title, 1, 3), content_type="shows")`.
4. `pick_best_source(sources, quality, max_gb)` — filter by size, sort by
   quality match → seeders → size. Take top. Exit 1 if empty.
5. `alldebrid.resolve(url, api_key, season=1, episode=3, progress_callback=...)`.
6. `download_manager.download_video(direct_url, dest, num_segments=N, progress_callback=...)`.
7. `cache_artwork(poster_url, art_dir()/fname.poster.jpg)`.
8. `add_to_manifest({...})` — same entry shape the addon uses:
   `{id, title, show_title, season, episode, file_path, size_bytes,
   date_added, mediatype, plot, poster_path}`.
9. Print `Done: <path>`.

### Whole season (`S1`)

1. Same TMDB lookup.
2. `tmdb.get_episodes(show_id, season=1)` → list of `{episode_number, name}`.
   Episode count = `len(list)`.
3. Loop episodes 1..N. For each: scrape, pick best, resolve, download, manifest.
   - If an episode has zero viable sources → print `[skip] S1E5: no sources`,
     continue (don't abort the whole batch).
   - If the destination file already exists with the expected size → print
     `[skip] S1E3: already downloaded`, continue.
4. End-of-run summary: `Downloaded 8/10 episodes. Skipped: S1E5, S1E9`.

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

- `parse_spec("S1E3")` → `("season", 1, 3)`; `parse_spec("S1")` →
  `("season", 1, None)`; `parse_spec("1E3")` → raises `ValueError`.
- `read_kodi_settings(fixture_xml)` → dict with expected keys; returns `{}`
  on missing file; missing `alldebridtoken` reflected in dict.
- `pick_best_source(sources, quality="720p", max_gb=2)` — with crafted
  source list: prefers sources matching the requested quality (falls back to
  next-best if no exact match), drops oversized sources, breaks ties by
  seeders descending then size descending.
- `build_query("Breaking Bad", 1, 3)` → `"Breaking Bad S01E03"`.
- `episode_already_downloaded(dest_path, expected_size)` — True when file
  exists with matching size, False otherwise.

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
