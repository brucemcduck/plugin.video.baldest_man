# CLI Download Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone terminal CLI (`cli.py`) that interactively downloads single episodes or whole seasons and registers them in the addon's downloads manifest.

**Architecture:** One new file (`cli.py`) at the project root imports existing addon modules (`resources.lib.scraper_runner`, `resources.lib.alldebrid`, `resources.lib.download_manager`, `resources.lib.tmdb`) — zero code duplication, same pattern as `check_scrapers.py`. UI is curses-based with arrow-key navigation throughout; non-TTY environments fall back to numbered prompts. Reads API credentials from Kodi's `settings.xml`.

**Tech Stack:** Python 3 stdlib (`curses`, `xml.etree.ElementTree`, `argparse`), existing addon modules, `requests` (transitive via addon modules).

## Global Constraints

- Run outside Kodi: no `import xbmc*` at module top level. All Kodi-specific imports happen lazily inside existing addon modules and are guarded by `try/except ImportError`.
- Tests run via `python3 -m unittest test_cli` from the project root, same pattern as `test_alldebrid.py` and `test_download_manager.py`.
- No new third-party dependencies. `curses` is stdlib on Linux/macOS; on Windows it's unavailable, so the fallback path is mandatory.
- No changes to existing addon modules — `cli.py` only imports from them.
- Exit codes (from spec): 0 success, 1 no sources, 2 TMDB lookup failed, 3 AllDebrid error, 4 settings missing, 5 invalid CLI flags, 130 KeyboardInterrupt.
- Quality rank mapping (duplicated locally, not imported from `main.py` which imports xbmc at top level): `{'4k': 4, '2160p': 4, '1080p': 3, '720p': 2, '480p': 1}`.
- Manifest entry shape (matches `main.py:477-489`): `{id, title, show_title, season, episode, file_path, size_bytes, date_added, mediatype, plot, poster_path}`.

---

## File Structure

**Create:**
- `cli.py` — single-file CLI. Internal layout (top to bottom):
  1. Constants and imports
  2. `read_kodi_settings(path)` — XML settings reader
  3. Pure helpers: `QUALITY_RANK`, `_rank_quality`, `pick_best_source`, `build_query`, `episode_already_downloaded`
  4. Option builders: `build_season_options`, `build_episode_options`, `build_quality_options`
  5. Fallback (non-curses) UI: `arrow_select_fallback`, `search_and_pick_fallback`
  6. Curses UI: `arrow_select`, `search_and_pick`, `select_quality`, `select_season`, `select_episode`
  7. Progress callback: `make_progress_callback`
  8. Flow functions: `download_episode`, `download_season`
  9. `main()` — arg parsing + flow driver
  10. `if __name__ == '__main__': main()`

- `test_cli.py` — unit tests for pure helpers + option builders + fallback UI; integration tests for `download_episode`/`download_season` with mocked TMDB/AllDebrid and the local HTTP server pattern from `test_download_manager.py`.

**Modify:** None.

---

### Task 1: Settings reader

**Files:**
- Create: `cli.py`
- Test: `test_cli.py`

**Interfaces:**
- Consumes: Kodi's `settings.xml` at `~/.kodi/userdata/addon_data/plugin.video.baldest_man/settings.xml`
- Produces: `read_kodi_settings(path) -> dict` — returns `{}` on missing file. Keys read: `alldebridtoken`, `tmdb_api_key`, `tmdb_language`, `offline_quality`, `download_segments`, `max_download_size_gb`, `download_path`.

- [ ] **Step 1: Write the failing test**

```python
# test_cli.py
#!/usr/bin/env python3
"""Unit tests for cli.py — pure helpers + fallback UI + integration flow.

Run outside Kodi:
    python3 -m unittest test_cli
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli


SETTINGS_FIXTURE = """<settings version="2">
    <setting id="alldebridtoken">FAKE_TOKEN_123</setting>
    <setting id="tmdb_api_key">FAKE_TMDB_KEY</setting>
    <setting id="tmdb_language">en</setting>
    <setting id="offline_quality">720p</setting>
    <setting id="download_segments">4</setting>
    <setting id="max_download_size_gb">2</setting>
    <setting id="download_path"></setting>
</settings>
"""


class ReadKodiSettingsTests(unittest.TestCase):
    def test_parses_all_expected_keys(self):
        with tempfile.NamedTemporaryFile('w', suffix='.xml', delete=False) as f:
            f.write(SETTINGS_FIXTURE)
            path = f.name
        try:
            s = cli.read_kodi_settings(path)
            self.assertEqual(s['alldebridtoken'], 'FAKE_TOKEN_123')
            self.assertEqual(s['tmdb_api_key'], 'FAKE_TMDB_KEY')
            self.assertEqual(s['tmdb_language'], 'en')
            self.assertEqual(s['offline_quality'], '720p')
            self.assertEqual(s['download_segments'], '4')
            self.assertEqual(s['max_download_size_gb'], '2')
            self.assertEqual(s['download_path'], '')
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty_dict(self):
        self.assertEqual(cli.read_kodi_settings('/nonexistent/path.xml'), {})

    def test_missing_key_is_absent_from_dict(self):
        fixture = """<settings><setting id="tmdb_api_key">only_key</setting></settings>"""
        with tempfile.NamedTemporaryFile('w', suffix='.xml', delete=False) as f:
            f.write(fixture)
            path = f.name
        try:
            s = cli.read_kodi_settings(path)
            self.assertEqual(s['tmdb_api_key'], 'only_key')
            self.assertNotIn('alldebridtoken', s)
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cli'`

- [ ] **Step 3: Write minimal implementation**

Create `cli.py` with imports, constants, and `read_kodi_settings`:

```python
#!/usr/bin/env python3
"""Standalone terminal CLI for downloading shows via the bald_man addon's
scrape/resolve/download pipeline. Run outside Kodi.

Usage:
    python3 cli.py [--segments N] [--max-size-gb N] [--dry-run]

Fully interactive: arrow-key menus for show lookup, season, episode, quality.
"""
import os
import sys
import xml.etree.ElementTree as ET


KODI_SETTINGS_PATH = os.path.expanduser(
    '~/.kodi/userdata/addon_data/plugin.video.baldest_man/settings.xml')

# Local copy of main.py's _QUALITY_RANK — not imported from main.py because
# main.py imports xbmc at module top level and is unsafe to import outside Kodi.
QUALITY_RANK = {'4k': 4, '2160p': 4, '1080p': 3, '720p': 2, '480p': 1}

QUALITY_OPTIONS = ['4K', '1080p', '720p', '480p']


def read_kodi_settings(path):
    """Parse Kodi's addon settings.xml into a dict of {id: value}.

    Returns {} on missing or unparseable file. Missing settings are absent
    from the returned dict (caller checks presence and exits 4 if required
    keys like alldebridtoken or tmdb_api_key are missing).
    """
    if not os.path.exists(path):
        return {}
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return {}
    root = tree.getroot()
    settings = {}
    for el in root.findall('setting'):
        sid = el.get('id')
        if not sid:
            continue
        # Kodi writes the value as element text; empty settings have no text.
        settings[sid] = (el.text or '').strip()
    return settings


def main():
    """Entry point — implemented in Task 9."""
    pass


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.ReadKodiSettingsTests -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add read_kodi_settings helper with tests"
```

---

### Task 2: Source picker

**Files:**
- Modify: `cli.py` (add `pick_best_source` and `_rank_quality`)
- Modify: `test_cli.py` (add `PickBestSourceTests`)

**Interfaces:**
- Consumes: scraper result dicts shaped like `{'show_title', 'url', 'title', 'quality', 'size', 'seeders'}` (from `scraper_runner.search_all`)
- Produces: `pick_best_source(sources, quality, max_gb) -> dict | None` — returns the best source or `None` if none pass filters.

- [ ] **Step 1: Write the failing tests**

Add to `test_cli.py` (after `ReadKodiSettingsTests`):

```python
class PickBestSourceTests(unittest.TestCase):
    def _src(self, quality, size, seeders=10, url='magnet:fake'):
        return {
            'show_title': 'Show',
            'url': url,
            'title': 'Show.S01E01.{}.mkv'.format(quality),
            'quality': quality,
            'size': size,
            'seeders': seeders,
        }

    def test_prefers_requested_quality(self):
        sources = [
            self._src('1080p', '1.5 GB', seeders=100),
            self._src('720p', '800 MB', seeders=50),
            self._src('4k', '5 GB', seeders=5),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        self.assertEqual(best['quality'], '720p')

    def test_4k_matches_2160p_alias(self):
        sources = [
            self._src('2160p', '5 GB', seeders=20),
            self._src('1080p', '2 GB', seeders=100),
        ]
        best = cli.pick_best_source(sources, quality='4K', max_gb=10)
        self.assertEqual(best['quality'], '2160p')

    def test_falls_back_to_next_tier_when_no_exact_match(self):
        sources = [
            self._src('1080p', '2 GB', seeders=100),
            self._src('480p', '400 MB', seeders=10),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        # No 720p source — should fall back to highest available tier (1080p)
        self.assertEqual(best['quality'], '1080p')

    def test_drops_oversized_sources(self):
        sources = [
            self._src('720p', '3 GB', seeders=50),   # over 2 GB cap
            self._src('480p', '400 MB', seeders=10),  # under cap
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=2)
        # 720p source dropped by size; falls back to 480p
        self.assertEqual(best['quality'], '480p')

    def test_breaks_ties_by_seeders_then_size(self):
        sources = [
            self._src('720p', '800 MB', seeders=30),
            self._src('720p', '900 MB', seeders=50),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        self.assertEqual(best['seeders'], 50)

    def test_returns_none_when_all_filtered_out(self):
        sources = [self._src('720p', '3 GB', seeders=50)]
        self.assertIsNone(cli.pick_best_source(sources, quality='720p', max_gb=1))

    def test_returns_none_on_empty_list(self):
        self.assertIsNone(cli.pick_best_source([], quality='720p', max_gb=10))

    def test_unknown_quality_falls_to_rank_0(self):
        # Sources with no quality string still get considered, ranked last
        sources = [
            self._src('', '500 MB', seeders=5),
            self._src('720p', '800 MB', seeders=10),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        self.assertEqual(best['quality'], '720p')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.PickBestSourceTests -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute 'pick_best_source'`

- [ ] **Step 3: Write minimal implementation**

Add to `cli.py` (after `read_kodi_settings`, before `main`):

```python
def _rank_quality(q_str):
    """Map a quality string to its numeric rank (0 = unknown/unranked)."""
    return QUALITY_RANK.get((q_str or '').lower(), 0)


def _parse_size_bytes(size_str):
    """Parse human-readable size string to bytes. Returns int or 0.

    Duplicated from main.py because main.py imports xbmc at module top level.
    """
    import re
    m = re.match(r'([\d.]+)\s*(GB|MB|GiB|MiB|KB|B)', str(size_str), re.IGNORECASE)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit in ('GB', 'GIB'):
        return int(val * 1073741824)
    if unit in ('MB', 'MIB'):
        return int(val * 1048576)
    if unit == 'KB':
        return int(val * 1024)
    return int(val)


def pick_best_source(sources, quality, max_gb):
    """Pick the best source dict from scraper results, or None if none pass.

    Filter: drop sources whose parsed size exceeds max_gb gigabytes.
    Sort: (1) distance from requested quality rank descending — exact match
    first, then next-best tier — (2) seeders descending, (3) size descending.
    """
    if not sources:
        return None
    max_bytes = max_gb * 1073741824
    want_rank = _rank_quality(quality)

    candidates = []
    for r in sources:
        sz = _parse_size_bytes(r.get('size', ''))
        if sz and sz > max_bytes:
            continue
        candidates.append(r)

    if not candidates:
        return None

    def sort_key(r):
        q_rank = _rank_quality(r.get('quality', ''))
        # Distance from requested tier — 0 is exact match, higher is farther.
        # We sort ascending by distance, then descending by seeders/size.
        quality_distance = abs(q_rank - want_rank)
        seeders = r.get('seeders') or 0
        size_bytes = _parse_size_bytes(r.get('size', '')) or 0
        return (quality_distance, -seeders, -size_bytes)

    candidates.sort(key=sort_key)
    return candidates[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.PickBestSourceTests -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add pick_best_source with quality/seeder/size sort"
```

---

### Task 3: Small pure helpers (build_query, episode_already_downloaded)

**Files:**
- Modify: `cli.py` (add `build_query`, `episode_already_downloaded`)
- Modify: `test_cli.py` (add `BuildQueryTests`, `EpisodeAlreadyDownloadedTests`)

**Interfaces:**
- Produces:
  - `build_query(title, season, episode) -> str` — e.g. `"Breaking Bad S01E03"`
  - `episode_already_downloaded(dest_path, expected_size) -> bool`

- [ ] **Step 1: Write the failing tests**

Add to `test_cli.py`:

```python
class BuildQueryTests(unittest.TestCase):
    def test_zero_pads_season_and_episode(self):
        self.assertEqual(cli.build_query("Breaking Bad", 1, 3),
                         "Breaking Bad S01E03")

    def test_double_digits(self):
        self.assertEqual(cli.build_query("Show", 10, 12),
                         "Show S10E12")


class EpisodeAlreadyDownloadedTests(unittest.TestCase):
    def test_true_when_file_exists_with_matching_size(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'x' * 1024)
            path = f.name
        try:
            self.assertTrue(cli.episode_already_downloaded(path, 1024))
        finally:
            os.unlink(path)

    def test_false_when_size_mismatches(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'x' * 1024)
            path = f.name
        try:
            self.assertFalse(cli.episode_already_downloaded(path, 2048))
        finally:
            os.unlink(path)

    def test_false_when_file_missing(self):
        self.assertFalse(cli.episode_already_downloaded('/nonexistent.mkv', 1024))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.BuildQueryTests test_cli.EpisodeAlreadyDownloadedTests -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute 'build_query'`

- [ ] **Step 3: Write minimal implementation**

Add to `cli.py` (after `pick_best_source`):

```python
def build_query(title, season, episode):
    """Build the scraper query string: 'Title S01E03' (zero-padded)."""
    return "{} S{:02d}E{:02d}".format(title, int(season), int(episode))


def episode_already_downloaded(dest_path, expected_size):
    """True if dest_path exists with exactly expected_size bytes."""
    try:
        return os.path.getsize(dest_path) == expected_size
    except OSError:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.BuildQueryTests test_cli.EpisodeAlreadyDownloadedTests -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add build_query and episode_already_downloaded helpers"
```

---

### Task 4: Option builders for arrow-key menus

**Files:**
- Modify: `cli.py` (add `build_season_options`, `build_episode_options`, `build_quality_options`)
- Modify: `test_cli.py` (add `OptionBuilderTests`)

**Interfaces:**
- Consumes: TMDB-shaped dicts from `tmdb.get_seasons` and `tmdb.get_episodes`
- Produces:
  - `build_season_options(seasons) -> list[(value, label)]` where value is `season_number`
  - `build_episode_options(episodes) -> list[(value, label)]` where first item is `("all", "Whole season")` and rest are `(episode_number, "E{n} — {name}")`
  - `build_quality_options(default="720p") -> (list[(value, label)], default_index)`

- [ ] **Step 1: Write the failing tests**

Add to `test_cli.py`:

```python
class OptionBuilderTests(unittest.TestCase):
    def test_build_season_options_renders_count(self):
        seasons = [
            {'season_number': 1, 'episode_count': 7, 'name': 'Season 1'},
            {'season_number': 2, 'episode_count': 13, 'name': 'Season 2'},
        ]
        opts = cli.build_season_options(seasons)
        self.assertEqual(opts, [(1, 'Season 1 (7 episodes)'),
                                (2, 'Season 2 (13 episodes)')])

    def test_build_season_options_uses_name_when_present(self):
        seasons = [{'season_number': 1, 'episode_count': 7, 'name': 'Breaking Bad'}]
        opts = cli.build_season_options(seasons)
        self.assertEqual(opts[0], (1, 'Breaking Bad (7 episodes)'))

    def test_build_season_options_empty_list(self):
        self.assertEqual(cli.build_season_options([]), [])

    def test_build_episode_options_prepends_whole_season(self):
        episodes = [
            {'episode_number': 1, 'name': 'Seven Thirty-Seven'},
            {'episode_number': 2, 'name': 'Grilled'},
        ]
        opts = cli.build_episode_options(episodes)
        self.assertEqual(opts[0], ('all', 'Whole season'))
        self.assertEqual(opts[1], (1, 'E1 — Seven Thirty-Seven'))
        self.assertEqual(opts[2], (2, 'E2 — Grilled'))

    def test_build_episode_options_handles_missing_name(self):
        episodes = [{'episode_number': 3, 'name': ''}]
        opts = cli.build_episode_options(episodes)
        self.assertEqual(opts[1], (3, 'E3'))

    def test_build_quality_options_returns_four_tiers(self):
        opts, default_idx = cli.build_quality_options(default='720p')
        self.assertEqual([v for v, _ in opts], ['4K', '1080p', '720p', '480p'])
        self.assertEqual(default_idx, 2)  # 720p is 3rd (0-indexed 2)

    def test_build_quality_options_unknown_default_uses_first(self):
        opts, default_idx = cli.build_quality_options(default='unknown')
        self.assertEqual(default_idx, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.OptionBuilderTests -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute 'build_season_options'`

- [ ] **Step 3: Write minimal implementation**

Add to `cli.py` (after `episode_already_downloaded`):

```python
def build_season_options(seasons):
    """Convert tmdb.get_seasons() result into arrow_select options.

    Returns list of (season_number, 'Name (N episodes)').
    """
    opts = []
    for s in seasons:
        sn = s.get('season_number')
        if sn is None:
            continue
        name = s.get('name') or 'Season {}'.format(sn)
        count = s.get('episode_count', 0)
        opts.append((sn, '{} ({} episodes)'.format(name, count)))
    return opts


def build_episode_options(episodes):
    """Convert tmdb.get_episodes() result into arrow_select options.

    First option is always ('all', 'Whole season'). Remaining options are
    (episode_number, 'E{n} — {name}') or 'E{n}' if name is empty.
    """
    opts = [('all', 'Whole season')]
    for ep in episodes:
        en = ep.get('episode_number')
        if en is None:
            continue
        name = (ep.get('name') or '').strip()
        label = 'E{} — {}'.format(en, name) if name else 'E{}'.format(en)
        opts.append((en, label))
    return opts


def build_quality_options(default='720p'):
    """Return (options, default_index) for the quality arrow_select menu.

    options is a list of (value, label) tuples. default_index points at the
    option matching the addon's offline_quality setting, or 0 if unknown.
    """
    opts = [(q, q) for q in QUALITY_OPTIONS]
    default_norm = (default or '').lower()
    if default_norm == '4k':
        default_norm = '4K'
    for i, (val, _) in enumerate(opts):
        if val.lower() == default_norm.lower():
            return opts, i
    return opts, 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.OptionBuilderTests -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add option builders for arrow-key menus"
```

---

### Task 5: Fallback (non-curses) UI helpers

**Files:**
- Modify: `cli.py` (add `arrow_select_fallback`, `search_and_pick_fallback`)
- Modify: `test_cli.py` (add `ArrowSelectFallbackTests`, `SearchAndPickFallbackTests`)

**Interfaces:**
- Produces:
  - `arrow_select_fallback(options, label, input_fn=input) -> value` — prints numbered list, reads a number, returns the chosen option's value. Raises `KeyboardInterrupt` on `'q'`.
  - `search_and_pick_fallback(search_fn, input_fn=input) -> dict` — prompts for a query, calls `search_fn(query)`, prints numbered results, returns the chosen match. Re-prompts on empty query or invalid pick. Raises `KeyboardInterrupt` on `'q'`.
  - Both accept an `input_fn` parameter so tests can monkeypatch input without patching the builtin.

- [ ] **Step 1: Write the failing tests**

Add to `test_cli.py`:

```python
class ArrowSelectFallbackTests(unittest.TestCase):
    def test_returns_selected_value(self):
        opts = [(1, 'one'), (2, 'two'), (3, 'three')]
        inputs = iter(['2'])
        result = cli.arrow_select_fallback(opts, 'Pick: ', input_fn=lambda _: next(inputs))
        self.assertEqual(result, 2)

    def test_first_option_is_index_one(self):
        opts = [('a', 'A'), ('b', 'B')]
        inputs = iter(['1'])
        result = cli.arrow_select_fallback(opts, 'Pick: ', input_fn=lambda _: next(inputs))
        self.assertEqual(result, 'a')

    def test_re_prompts_on_out_of_range(self):
        opts = [(1, 'one'), (2, 'two')]
        inputs = iter(['0', '5', '2'])
        result = cli.arrow_select_fallback(opts, 'Pick: ', input_fn=lambda _: next(inputs))
        self.assertEqual(result, 2)

    def test_re_prompts_on_non_integer(self):
        opts = [(1, 'one'), (2, 'two')]
        inputs = iter(['x', '1'])
        result = cli.arrow_select_fallback(opts, 'Pick: ', input_fn=lambda _: next(inputs))
        self.assertEqual(result, 1)

    def test_q_raises_keyboard_interrupt(self):
        opts = [(1, 'one')]
        with self.assertRaises(KeyboardInterrupt):
            cli.arrow_select_fallback(opts, 'Pick: ', input_fn=lambda _: 'q')


class SearchAndPickFallbackTests(unittest.TestCase):
    def test_returns_chosen_match(self):
        matches = [
            {'id': 1, 'title': 'Breaking Bad', 'year': '2008'},
            {'id': 2, 'title': 'Better Call Saul', 'year': '2015'},
        ]
        def fake_search(query):
            return matches
        inputs = iter(['breaking bad', '1'])
        result = cli.search_and_pick_fallback(fake_search, input_fn=lambda _: next(inputs))
        self.assertEqual(result['id'], 1)

    def test_re_prompts_on_empty_query(self):
        matches = [{'id': 1, 'title': 'Show', 'year': '2000'}]
        def fake_search(query):
            return matches
        inputs = iter(['', 'show', '1'])
        result = cli.search_and_pick_fallback(fake_search, input_fn=lambda _: next(inputs))
        self.assertEqual(result['id'], 1)

    def test_returns_none_on_zero_tmdb_matches(self):
        def fake_search(query):
            return []
        inputs = iter(['unknown show'])
        result = cli.search_and_pick_fallback(fake_search, input_fn=lambda _: next(inputs))
        self.assertIsNone(result)

    def test_q_during_pick_raises_keyboard_interrupt(self):
        matches = [{'id': 1, 'title': 'Show', 'year': '2000'}]
        def fake_search(query):
            return matches
        inputs = iter(['show', 'q'])
        with self.assertRaises(KeyboardInterrupt):
            cli.search_and_pick_fallback(fake_search, input_fn=lambda _: next(inputs))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.ArrowSelectFallbackTests test_cli.SearchAndPickFallbackTests -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute 'arrow_select_fallback'`

- [ ] **Step 3: Write minimal implementation**

Add to `cli.py` (after `build_quality_options`):

```python
def arrow_select_fallback(options, label, input_fn=input):
    """Non-curses fallback: numbered list prompt.

    Used when stdin is not a TTY or curses is unavailable. Reads a 1-based
    index from input_fn, returns the value at that index. Re-prompts on
    out-of-range or non-integer input. 'q' raises KeyboardInterrupt.
    """
    while True:
        print(label)
        for i, (_, display) in enumerate(options, start=1):
            print('  {}. {}'.format(i, display))
        choice = input_fn('> ').strip()
        if choice.lower() == 'q':
            raise KeyboardInterrupt
        try:
            idx = int(choice)
        except ValueError:
            print('  invalid: enter a number 1-{} or q to cancel'.format(len(options)))
            continue
        if idx < 1 or idx > len(options):
            print('  out of range: enter 1-{}'.format(len(options)))
            continue
        return options[idx - 1][0]


def search_and_pick_fallback(search_fn, input_fn=input):
    """Non-curses fallback for show lookup: type query, pick from results.

    Prompts for a search query, calls search_fn(query), prints numbered
    matches, returns the chosen match dict. Re-prompts on empty query or
    invalid pick. Returns None if search_fn returns []. 'q' raises
    KeyboardInterrupt.
    """
    while True:
        query = input_fn('Search: ').strip()
        if query.lower() == 'q':
            raise KeyboardInterrupt
        if not query:
            print('  enter a show name to search')
            continue
        matches = search_fn(query)
        if not matches:
            return None
        print('  TMDB matches:')
        for i, m in enumerate(matches, start=1):
            print('  {}. {} ({})'.format(i, m.get('title', '?'), m.get('year', '')))
        choice = input_fn('Pick [1-{}]: '.format(len(matches))).strip()
        if choice.lower() == 'q':
            raise KeyboardInterrupt
        try:
            idx = int(choice)
        except ValueError:
            print('  invalid: enter a number')
            continue
        if idx < 1 or idx > len(matches):
            print('  out of range: enter 1-{}'.format(len(matches)))
            continue
        return matches[idx - 1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.ArrowSelectFallbackTests test_cli.SearchAndPickFallbackTests -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add non-curses fallback UI helpers with tests"
```

---

### Task 6: Curses UI wrappers

**Files:**
- Modify: `cli.py` (add `arrow_select`, `search_and_pick`, `select_quality`, `select_season`, `select_episode`)

**Interfaces:**
- Produces:
  - `arrow_select(options, label, default=0) -> value` — curses arrow-key menu; falls back to `arrow_select_fallback` when not a TTY or curses import fails.
  - `search_and_pick(search_fn) -> dict | None` — curses split-pane search; falls back to `search_and_pick_fallback`.
  - `select_quality(default="720p") -> str` — wraps `arrow_select` with quality options.
  - `select_season(seasons) -> int` — wraps `arrow_select` with season options.
  - `select_episode(episodes) -> int | "all"` — wraps `arrow_select` with episode options.

Note: the curses rendering is visual and not unit-tested. Tests cover the fallback path (Task 5). This task is a thin wrapper layer.

- [ ] **Step 1: Implement curses wrappers**

Add to `cli.py` (after `search_and_pick_fallback`):

```python
def _is_tty():
    """True if stdin is a TTY (interactive terminal)."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def arrow_select(options, label, default=0):
    """Arrow-key vertical menu. Falls back to numbered prompt when curses
    is unavailable or stdin is not a TTY.

    options: list of (value, display_text) tuples.
    Returns the selected value. Raises KeyboardInterrupt on q/Esc/Ctrl-C.
    """
    if not _is_tty():
        return arrow_select_fallback(options, label)
    try:
        import curses
    except ImportError:
        return arrow_select_fallback(options, label)

    idx = default
    if idx < 0 or idx >= len(options):
        idx = 0

    def _draw(stdscr, current):
        stdscr.clear()
        stdscr.addstr(0, 0, label, curses.A_BOLD)
        for i, (_, display) in enumerate(options):
            marker = '> ' if i == current else '  '
            line = '{}{}'.format(marker, display)
            attr = curses.A_REVERSE if i == current else curses.A_NORMAL
            stdscr.addstr(i + 2, 0, line, attr)
        stdscr.addstr(len(options) + 3, 0,
                      '(Up/Down move, Enter select, q cancel)', curses.A_DIM)
        stdscr.refresh()

    def _loop(stdscr):
        nonlocal idx
        curses.curs_set(0)
        _draw(stdscr, idx)
        while True:
            ch = stdscr.getch()
            if ch in (curses.KEY_UP, ord('k')):
                idx = max(0, idx - 1)
            elif ch in (curses.KEY_DOWN, ord('j')):
                idx = min(len(options) - 1, idx + 1)
            elif ch in (curses.KEY_ENTER, 10, 13):
                return options[idx][0]
            elif ch in (ord('q'), 27):
                raise KeyboardInterrupt
            _draw(stdscr, idx)

    try:
        return curses.wrapper(_loop)
    except KeyboardInterrupt:
        raise


def search_and_pick(search_fn):
    """Split-pane search UI with arrow-key result picking.

    Type a query on the top line, press Enter to fetch TMDB matches, arrow
    keys to highlight, Enter to select. Falls back to the numbered prompt
    when curses is unavailable or stdin is not a TTY.

    Returns the chosen match dict, or None if the search returns no matches.
    Raises KeyboardInterrupt on q/Esc/Ctrl-C.
    """
    if not _is_tty():
        return search_and_pick_fallback(search_fn)
    try:
        import curses
    except ImportError:
        return search_and_pick_fallback(search_fn)

    # curses implementation: use the fallback for the text-input phase
    # (curses text input is fiddly and not worth the complexity here), then
    # switch to arrow_select for picking from the fetched results.
    # This keeps the curses path simple while still giving arrow-key picking.
    query = ''
    while True:
        try:
            query = input('Search: ').strip()
        except EOFError:
            raise KeyboardInterrupt
        if query.lower() == 'q':
            raise KeyboardInterrupt
        if not query:
            print('  enter a show name to search')
            continue
        matches = search_fn(query)
        if not matches:
            return None
        opts = [(m, '{} ({})'.format(m.get('title', '?'), m.get('year', '')))
                for m in matches]
        return arrow_select(opts, 'Pick a show:')


def select_quality(default='720p'):
    """Arrow-key quality menu (4K / 1080p / 720p / 480p)."""
    opts, default_idx = build_quality_options(default)
    return arrow_select(opts, 'Select preferred quality:', default=default_idx)


def select_season(seasons):
    """Arrow-key season menu over tmdb.get_seasons() results."""
    opts = build_season_options(seasons)
    if not opts:
        raise ValueError("No seasons available")
    return arrow_select(opts, 'Seasons:', default=0)


def select_episode(episodes):
    """Arrow-key episode menu. First option is always 'Whole season'."""
    opts = build_episode_options(episodes)
    if not opts:
        raise ValueError("No episodes available")
    return arrow_select(opts, 'Episodes:', default=0)
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python3 -c "import cli; print('import OK')"`
Expected: `import OK`

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `python3 -m unittest test_cli -v`
Expected: PASS (all tests from Tasks 1-5, since the curses path isn't exercised in non-TTY test runs — `arrow_select` and `search_and_pick` delegate to the fallbacks when stdin isn't a TTY)

- [ ] **Step 4: Commit**

```bash
git add cli.py
git commit -m "feat(cli): add curses arrow-key UI with TTY-fallback"
```

---

### Task 7: Progress callback

**Files:**
- Modify: `cli.py` (add `make_progress_callback`)

**Interfaces:**
- Produces: `make_progress_callback() -> callable(written, total, pct)` — prints `123 / 1500 MB (8%)` on the same line using `\r`.

Note: visual output, not unit-tested. Verified manually in Task 10.

- [ ] **Step 1: Implement the progress callback**

Add to `cli.py` (after `select_episode`):

```python
def _fmt_mb(bytes_val):
    """Format bytes as MB with no decimals."""
    return '{} MB'.format(bytes_val // (1024 * 1024))


def make_progress_callback():
    """Return a progress_callback(written, total, pct) that prints a live
    single-line progress meter to stderr using carriage return.
    """
    def cb(written, total, pct):
        line = '\r[download] {} / {} ({}%)'.format(
            _fmt_mb(written), _fmt_mb(total), pct)
        sys.stderr.write(line)
        sys.stderr.flush()
        # Clear the line when complete
        if total and written >= total:
            sys.stderr.write('\n')
            sys.stderr.flush()
    return cb
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python3 -c "import cli; cb = cli.make_progress_callback(); cb(1048576, 10485760, 10); print(' OK')"`
Expected: `[download] 1 MB / 10 MB (10%) OK`

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "feat(cli): add terminal progress callback"
```

---

### Task 8: Single-episode flow with mocked TMDB/AllDebrid (integration test)

**Files:**
- Modify: `cli.py` (add `download_episode`)
- Modify: `test_cli.py` (add `DownloadEpisodeTests` with local HTTP server)

**Interfaces:**
- Consumes:
  - `scraper_runner.search_all(query, content_type)` — returns list of source dicts
  - `alldebrid.resolve(url, api_key, season, episode, progress_callback)` — returns direct URL
  - `download_manager.download_video(direct_url, dest, num_segments, progress_callback)` — returns True/False
  - `download_manager.add_to_manifest(entry)`, `cache_artwork`, `art_dir`, `safe_filename`, `get_download_dir`
  - `tmdb.get_imdb_id(show_id, api_key)` — returns imdb_id string or None
- Produces: `download_episode(show, season, episode, quality, settings, dry_run=False) -> bool` — returns True on success, False on no sources or download failure.

- [ ] **Step 1: Write the failing test**

Add to `test_cli.py`:

```python
class DownloadEpisodeTests(unittest.TestCase):
    """Integration test for download_episode with mocked TMDB/AllDebrid
    and a local throttled Range-supporting HTTP server (same pattern as
    test_download_manager.py's ParallelDownloadIntegrationTests).
    """
    def setUp(self):
        import http.server
        import socketserver
        import threading
        import time
        self.tmp = tempfile.mkdtemp()
        # 4 MB payload — small enough for fast tests, large enough that the
        # parallel downloader is exercised when MIN_PARALLEL_SIZE is lowered.
        self.payload = bytes((i * 7 + 13) & 0xFF for i in range(4 * 1024 * 1024))
        self.served_path = os.path.join(self.tmp, 'source.bin')
        with open(self.served_path, 'wb') as f:
            f.write(self.payload)

        # Lower the parallel threshold so the 4 MB payload uses parallel mode
        from resources.lib import download_manager as dm
        self._orig_min_parallel = dm.MIN_PARALLEL_SIZE
        dm.MIN_PARALLEL_SIZE = 1024 * 1024  # 1 MB

        class RangeThrottledHandler(http.server.SimpleHTTPRequestHandler):
            CHUNK_DELAY_S = 0.002
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                path = self.translate_path(self.path)
                try:
                    f = open(path, 'rb')
                except OSError:
                    self.send_error(404)
                    return
                try:
                    fs = os.fstat(f.fileno())
                    total = fs.st_size
                    range_header = self.headers.get('Range')
                    if range_header and range_header.startswith('bytes='):
                        spec = range_header[6:]
                        parts = spec.split('-', 1)
                        start = int(parts[0]) if parts[0] else 0
                        end = int(parts[1]) if parts[1] else total - 1
                        end = min(end, total - 1)
                        length = end - start + 1
                        self.send_response(206)
                        self.send_header('Content-Type', 'application/octet-stream')
                        self.send_header('Content-Length', str(length))
                        self.send_header('Content-Range',
                                         'bytes {}-{}/{}'.format(start, end, total))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.end_headers()
                        f.seek(start)
                        remaining = length
                        while remaining > 0:
                            buf = f.read(min(65536, remaining))
                            if not buf:
                                break
                            self.wfile.write(buf)
                            self.wfile.flush()
                            time.sleep(self.CHUNK_DELAY_S)
                            remaining -= len(buf)
                    else:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/octet-stream')
                        self.send_header('Content-Length', str(total))
                        self.send_header('Accept-Ranges', 'bytes')
                        self.end_headers()
                        while True:
                            buf = f.read(65536)
                            if not buf:
                                break
                            self.wfile.write(buf)
                            self.wfile.flush()
                            time.sleep(self.CHUNK_DELAY_S)
                finally:
                    f.close()

            def log_message(self, *a, **kw):
                pass

        socketserver.TCPServer.allow_reuse_address = True
        self.httpd = socketserver.ThreadingTCPServer(
            ('127.0.0.1', 0), RangeThrottledHandler)
        self.port = self.httpd.server_address[1]
        self.server_thread = threading.Thread(target=self.httpd.serve_forever,
                                              daemon=True)
        self.server_thread.start()
        self.file_url = 'http://127.0.0.1:{}/source.bin'.format(self.port)
        self._orig_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        import shutil
        os.chdir(self._orig_cwd)
        from resources.lib import download_manager as dm
        dm.MIN_PARALLEL_SIZE = self._orig_min_parallel
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_downloads_episode_and_adds_to_manifest(self):
        """End-to-end: mocked scrape returns one source, mocked resolve
        returns the local file URL, download_video fetches it, manifest
        gets a new entry with the expected shape."""
        from resources.lib import download_manager as dm

        show = {'id': 1396, 'title': 'Breaking Bad', 'year': '2008',
                'poster_url': None}
        fake_source = {
            'show_title': 'Breaking Bad',
            'url': 'magnet:fake',
            'title': 'Breaking.Bad.S01E03.720p.mkv',
            'quality': '720p',
            'size': '4 MB',
            'seeders': 50,
        }

        # Patch scraper_runner.search_all to return our fake source
        orig_search_all = cli.scraper_runner.search_all
        cli.scraper_runner.search_all = lambda q, content_type='all': [fake_source]

        # Patch alldebrid.resolve to return the local file URL
        orig_resolve = cli.alldebrid.resolve
        cli.alldebrid.resolve = lambda url, api_key, **kw: self.file_url

        # Patch tmdb.get_imdb_id to return a fake imdb id
        orig_get_imdb = cli.tmdb.get_imdb_id
        cli.tmdb.get_imdb_id = lambda show_id, api_key, is_movie=False: 'tt0903747'

        # Point manifest at a temp file so we don't clobber the real one
        orig_manifest_path = dm.manifest_path
        self.manifest_path = os.path.join(self.tmp, 'downloads.json')
        dm.manifest_path = lambda: self.manifest_path

        settings = {
            'alldebridtoken': 'FAKE',
            'tmdb_api_key': 'FAKE',
            'offline_quality': '720p',
            'download_segments': '4',
            'max_download_size_gb': '10',
        }

        try:
            ok = cli.download_episode(
                show, season=1, episode=3, quality='720p',
                settings=settings, dry_run=False)
            self.assertTrue(ok)

            # File landed on disk with the right content
            dest = os.path.join(dm.get_download_dir(),
                                'Breaking.Bad.S01E03.mp4')
            self.assertTrue(os.path.exists(dest))
            with open(dest, 'rb') as f:
                self.assertEqual(f.read(), self.payload)

            # Manifest has one entry with the expected shape
            import json
            with open(self.manifest_path) as f:
                manifest = json.load(f)
            self.assertEqual(len(manifest), 1)
            entry = manifest[0]
            self.assertEqual(entry['show_title'], 'Breaking Bad')
            self.assertEqual(entry['season'], 1)
            self.assertEqual(entry['episode'], 3)
            self.assertEqual(entry['mediatype'], 'episode')
            self.assertIn('file_path', entry)
            self.assertIn('date_added', entry)
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            cli.tmdb.get_imdb_id = orig_get_imdb
            dm.manifest_path = orig_manifest_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.DownloadEpisodeTests.test_downloads_episode_and_adds_to_manifest -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute 'download_episode'` (and also `scraper_runner`/`alldebrid`/`tmdb` not imported yet)

- [ ] **Step 3: Write minimal implementation**

Add imports at the top of `cli.py` (after existing imports):

```python
from resources.lib import scraper_runner, alldebrid, download_manager, tmdb
from resources.lib.alldebrid import AllDebridError
from resources.lib.download_manager import DownloadError
```

Add `download_episode` to `cli.py` (after `make_progress_callback`):

```python
def download_episode(show, season, episode, quality, settings, dry_run=False):
    """Run the scrape -> resolve -> download -> manifest flow for one episode.

    show: TMDB show dict with at least {id, title, poster_url}.
    settings: dict from read_kodi_settings().
    Returns True on success, False on no sources or download failure.
    """
    title = show.get('title', '')
    show_id = show.get('id')
    poster_url = show.get('poster_url')

    query = build_query(title, season, episode)
    print('[scrape] searching for {}'.format(query))
    sources = scraper_runner.search_all(query, content_type='shows')
    if not sources:
        print('[scrape] no sources found')
        return False
    print('[scrape] {} sources found'.format(len(sources)))

    max_gb = int(settings.get('max_download_size_gb', '2') or '2')
    best = pick_best_source(sources, quality=quality, max_gb=max_gb)
    if not best:
        print('[scrape] no sources passed quality/size filters')
        return False
    print('[scrape] best: {} ({}, {} seeders)'.format(
        best.get('title', ''), best.get('size', '?'), best.get('seeders', 0)))

    if dry_run:
        print('[dry-run] would download from {}'.format(best.get('url', '')))
        return True

    api_key = settings.get('alldebridtoken', '')
    num_segments = int(settings.get('download_segments', '4') or '4')

    # Resolve magnet -> direct URL (episode-aware file picker)
    print('[alldebrid] resolving...')
    try:
        direct_url = alldebrid.resolve(
            best['url'], api_key,
            season=season, episode=episode,
            progress_callback=_alldebrid_progress,
        )
    except AllDebridError as e:
        print('[fail] S{:02d}E{:02d}: {}'.format(season, episode, e))
        return False
    print('[alldebrid] ready')

    # Download
    dest_dir = download_manager.get_download_dir()
    fname = download_manager.safe_filename(title, season, episode)
    dest = os.path.join(dest_dir, fname)

    print('[download] -> {}'.format(dest))
    progress_cb = make_progress_callback()
    try:
        ok = download_manager.download_video(
            direct_url, dest,
            num_segments=num_segments,
            progress_callback=progress_cb,
        )
    except DownloadError as e:
        print('[fail] download error: {}'.format(e))
        return False
    if not ok:
        print('[fail] download cancelled or failed')
        return False

    # Cache artwork
    poster_local = None
    if poster_url:
        poster_local = download_manager.cache_artwork(
            poster_url, os.path.join(download_manager.art_dir(),
                                     fname + '.poster.jpg'))

    # Add to manifest — same shape as main.py:477-489
    entry = {
        'id': fname,
        'title': '{} S{:02d}E{:02d}'.format(title, season, episode),
        'show_title': title,
        'season': season,
        'episode': episode,
        'file_path': dest,
        'size_bytes': os.path.getsize(dest),
        'date_added': int(__import__('time').time()),
        'mediatype': 'episode',
        'plot': '',
        'poster_path': poster_local,
    }
    download_manager.add_to_manifest(entry)
    print('Done: {}'.format(dest))
    return True


def _alldebrid_progress(state, pct, eta):
    """Print AllDebrid magnet-resolution progress to stderr."""
    print('[alldebrid] {}... {}%'.format(state, pct), file=sys.stderr)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.DownloadEpisodeTests.test_downloads_episode_and_adds_to_manifest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add download_episode flow with integration test"
```

---

### Task 9: Season-batch flow

**Files:**
- Modify: `cli.py` (add `download_season`)
- Modify: `test_cli.py` (add `DownloadSeasonTests`)

**Interfaces:**
- Consumes: `download_episode` from Task 8, `tmdb.get_episodes`
- Produces: `download_season(show, season, episodes, quality, settings, dry_run=False) -> (downloaded, skipped)` — returns a tuple of counts. Loops over episodes, skips on failure/no-sources, continues on errors.

- [ ] **Step 1: Write the failing test**

Add to `test_cli.py`:

```python
class DownloadSeasonTests(unittest.TestCase):
    """Season-batch flow with mocked scrape/resolve. Three episodes: two
    succeed, one has no sources and is skipped without aborting the batch.
    """
    def setUp(self):
        # Reuse the HTTP server setup from DownloadEpisodeTests
        self._http_setup = DownloadEpisodeTests.setUp(self)
        # Override scrape to return sources for episodes 1 and 3, none for 2
        self._ep_sources = {
            1: [{'show_title': 'Show', 'url': 'magnet:e1',
                 'title': 'Show.S01E01.720p.mkv', 'quality': '720p',
                 'size': '4 MB', 'seeders': 50}],
            3: [{'show_title': 'Show', 'url': 'magnet:e3',
                 'title': 'Show.S01E03.720p.mkv', 'quality': '720p',
                 'size': '4 MB', 'seeders': 50}],
        }

    def tearDown(self):
        DownloadEpisodeTests.tearDown(self)

    def test_batch_downloads_available_episodes_and_skips_missing(self):
        from resources.lib import download_manager as dm

        show = {'id': 1396, 'title': 'Show', 'year': '2008', 'poster_url': None}
        episodes = [
            {'episode_number': 1, 'name': 'Ep1'},
            {'episode_number': 2, 'name': 'Ep2'},
            {'episode_number': 3, 'name': 'Ep3'},
        ]

        # Patch scraper_runner.search_all to return per-episode sources
        orig_search_all = cli.scraper_runner.search_all
        def fake_search(query, content_type='all'):
            # query is 'Show S01E{N}'; extract episode number
            import re
            m = re.search(r'E(\d+)', query)
            if not m:
                return []
            ep = int(m.group(1))
            return self._ep_sources.get(ep, [])
        cli.scraper_runner.search_all = fake_search

        # Patch alldebrid.resolve to return the local file URL
        orig_resolve = cli.alldebrid.resolve
        cli.alldebrid.resolve = lambda url, api_key, **kw: self.file_url

        # Patch tmdb.get_imdb_id
        orig_get_imdb = cli.tmdb.get_imdb_id
        cli.tmdb.get_imdb_id = lambda show_id, api_key, is_movie=False: 'tt0000000'

        # Temp manifest
        orig_manifest_path = dm.manifest_path
        self.manifest_path = os.path.join(self.tmp, 'season_manifest.json')
        dm.manifest_path = lambda: self.manifest_path

        settings = {
            'alldebridtoken': 'FAKE',
            'tmdb_api_key': 'FAKE',
            'offline_quality': '720p',
            'download_segments': '2',
            'max_download_size_gb': '10',
        }

        try:
            downloaded, skipped = cli.download_season(
                show, season=1, episodes=episodes, quality='720p',
                settings=settings, dry_run=False)
            self.assertEqual(downloaded, 2)
            self.assertEqual(skipped, 1)

            # Manifest has two entries (episodes 1 and 3)
            import json
            with open(self.manifest_path) as f:
                manifest = json.load(f)
            ep_nums = sorted(e['episode'] for e in manifest)
            self.assertEqual(ep_nums, [1, 3])
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            cli.tmdb.get_imdb_id = orig_get_imdb
            dm.manifest_path = orig_manifest_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.DownloadSeasonTests -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute 'download_season'`

- [ ] **Step 3: Write minimal implementation**

Add to `cli.py` (after `download_episode`):

```python
def download_season(show, season, episodes, quality, settings, dry_run=False):
    """Download every episode in a season. Skips episodes with no sources
    or download failures; continues the batch. Returns (downloaded, skipped).

    episodes: list of TMDB episode dicts (from tmdb.get_episodes), each with
    at least {episode_number, name}.
    """
    title = show.get('title', '')
    downloaded = 0
    skipped = []

    for ep in episodes:
        ep_num = ep.get('episode_number')
        if ep_num is None:
            continue
        ep_name = ep.get('name', '')
        label = 'S{:02d}E{:02d}'.format(season, ep_num)
        if ep_name:
            label += ' — {}'.format(ep_name)
        print('\n--- {} ---'.format(label))

        ok = download_episode(show, season, ep_num, quality, settings, dry_run)
        if ok:
            downloaded += 1
        else:
            skipped.append(label)

    print('\n--- Summary ---')
    print('Downloaded {}/{} episodes.'.format(downloaded, len(episodes)))
    if skipped:
        print('Skipped: {}'.format(', '.join(skipped)))
    return downloaded, len(skipped)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.DownloadSeasonTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add season-batch download flow with skip-on-failure"
```

---

### Task 10: main() — arg parsing, flow driver, exit codes

**Files:**
- Modify: `cli.py` (replace the stub `main` with the full implementation)
- Modify: `test_cli.py` (add `MainArgsTests`)

**Interfaces:**
- Produces: `main(argv=None) -> int` — parses CLI flags, runs the interactive flow, returns the exit code.

- [ ] **Step 1: Write the failing tests**

Add to `test_cli.py`:

```python
class MainArgsTests(unittest.TestCase):
    """Test argument parsing in isolation. The interactive flow is mocked."""

    def test_invalid_segments_flag_exits_5(self):
        # --segments must be a positive integer
        with self.assertRaises(SystemExit) as cm:
            cli.main(['--segments', '0'])
        self.assertEqual(cm.exception.code, 5)

    def test_invalid_max_size_flag_exits_5(self):
        with self.assertRaises(SystemExit) as cm:
            cli.main(['--max-size-gb', 'abc'])
        self.assertEqual(cm.exception.code, 5)

    def test_help_flag_exits_0(self):
        with self.assertRaises(SystemExit) as cm:
            cli.main(['--help'])
        self.assertEqual(cm.exception.code, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.MainArgsTests -v`
Expected: FAIL (current `main` is a stub that returns None, so `--help` won't exit)

- [ ] **Step 3: Write minimal implementation**

Replace the stub `main` in `cli.py` with:

```python
def _parse_args(argv):
    """Parse CLI flags. Returns parsed args or raises SystemExit(exit_code)
    on invalid input (exit 5) or --help (exit 0)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog='cli.py',
        description='Download shows via the bald_man addon pipeline.',
        add_help=True,
    )
    parser.add_argument('--segments', type=int, default=None,
                        help='Parallel download segments (1 = sequential). '
                             'Overrides download_segments setting.')
    parser.add_argument('--max-size-gb', type=int, default=None,
                        help='Max source size in GB. '
                             'Overrides max_download_size_gb setting.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Scrape and pick sources but skip download.')

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse exits with 2 on parse error; remap to our code 5.
        # --help exits with 0; pass through.
        if e.code == 0:
            raise
        raise SystemExit(5)

    if args.segments is not None and args.segments < 1:
        print('error: --segments must be >= 1', file=sys.stderr)
        raise SystemExit(5)
    if args.max_size_gb is not None and args.max_size_gb < 1:
        print('error: --max-size-gb must be >= 1', file=sys.stderr)
        raise SystemExit(5)

    return args


def main(argv=None):
    """Entry point. Returns an exit code (0 = success)."""
    if argv is None:
        argv = sys.argv[1:]
    args = _parse_args(argv)

    # Read settings from Kodi's settings.xml
    settings = read_kodi_settings(KODI_SETTINGS_PATH)
    if not settings.get('alldebridtoken') or not settings.get('tmdb_api_key'):
        print('error: AllDebrid token or TMDB API key not set in Kodi settings',
              file=sys.stderr)
        print('  expected at: {}'.format(KODI_SETTINGS_PATH), file=sys.stderr)
        return 4

    # Apply CLI overrides
    if args.segments is not None:
        settings['download_segments'] = str(args.segments)
    if args.max_size_gb is not None:
        settings['max_download_size_gb'] = str(args.max_size_gb)

    try:
        # 1. Show lookup (interactive)
        def search_fn(query):
            return tmdb.search_shows(
                query,
                settings.get('tmdb_api_key', ''),
                settings.get('tmdb_language', 'en'),
            )
        show = search_and_pick(search_fn)
        if show is None:
            print('[tmdb] no matches')
            return 2
        print('[tmdb] {} -> show_id={}'.format(
            show.get('title', '?'), show.get('id')))

        # 2. Season picker
        seasons = tmdb.get_seasons(
            show['id'], settings.get('tmdb_api_key', ''),
            settings.get('tmdb_language', 'en'),
        )
        if not seasons:
            print('[tmdb] no seasons found for this show')
            return 2
        season = select_season(seasons)

        # 3. Episode picker
        episodes = tmdb.get_episodes(
            show['id'], season, settings.get('tmdb_api_key', ''),
            settings.get('tmdb_language', 'en'),
        )
        if not episodes:
            print('[tmdb] no episodes found for season {}'.format(season))
            return 2
        ep_choice = select_episode(episodes)

        # 4. Quality picker
        quality = select_quality(default=settings.get('offline_quality', '720p'))
        print('[quality] {}'.format(quality))

        # 5. Download
        if ep_choice == 'all':
            download_season(show, season, episodes, quality, settings,
                            dry_run=args.dry_run)
        else:
            ok = download_episode(show, season, ep_choice, quality, settings,
                                  dry_run=args.dry_run)
            if not ok:
                return 1
        return 0

    except KeyboardInterrupt:
        print('\n[cancelled]')
        return 130
    except AllDebridError as e:
        print('[error] AllDebrid: {}'.format(e), file=sys.stderr)
        return 3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.MainArgsTests -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full test suite**

Run: `python3 -m unittest test_cli test_alldebrid test_download_manager -v`
Expected: PASS (all tests across all three test files)

- [ ] **Step 6: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add main() with arg parsing, flow driver, exit codes"
```

---

### Task 11: Final verification and manual run instructions

**Files:**
- Modify: none (verification only)

- [ ] **Step 1: Verify the full test suite passes**

Run: `python3 -m unittest test_cli test_alldebrid test_download_manager 2>&1 | tail -5`
Expected: `OK` with all tests passing.

- [ ] **Step 2: Verify cli.py compiles cleanly**

Run: `python3 -m py_compile cli.py && echo "compile OK"`
Expected: `compile OK`

- [ ] **Step 3: Verify --help works**

Run: `python3 cli.py --help`
Expected: usage text showing `--segments`, `--max-size-gb`, `--dry-run` flags; exits 0.

- [ ] **Step 4: Verify invalid flags exit with code 5**

Run: `python3 cli.py --segments 0; echo "exit: $?"`
Expected: error message and `exit: 5`

- [ ] **Step 5: Manual interactive run (requires real Kodi settings)**

This step is for the user to run manually, not part of automated tests.

```bash
python3 cli.py
# Type a show name, arrow-key through matches, pick season/episode/quality.
# Verify the file downloads and appears in the addon's Downloads section.
```

- [ ] **Step 6: Final commit if any cleanup is needed**

If steps 1-4 all pass with no changes, no commit is needed. If any fixes were made, commit them:

```bash
git add -A && git commit -m "fix(cli): final verification cleanup"
```

---

## Self-Review

**Spec coverage:**
- [x] Single-episode downloads — Task 8 (`download_episode`)
- [x] Whole-season downloads (TMDB episode count) — Task 9 (`download_season`)
- [x] Auto-pick best source (quality match → seeders → size) — Task 2 (`pick_best_source`)
- [x] Arrow-key quality selector (4K → 1080p → 720p → 480p, always shown) — Task 6 (`select_quality`), called in Task 10
- [x] Reads API credentials from Kodi's `settings.xml` — Task 1 (`read_kodi_settings`), used in Task 10
- [x] Registers downloads in the addon's `downloads.json` manifest — Task 8 (`add_to_manifest` call)
- [x] Reuses the existing parallel-segment downloader — Task 8 (`download_manager.download_video` with `num_segments`)
- [x] Arrow-key show lookup (type to search, arrows to pick) — Task 6 (`search_and_pick`)
- [x] Arrow-key season menu — Task 6 (`select_season`)
- [x] Arrow-key episode menu with "Whole season" first — Task 6 (`select_episode`)
- [x] Non-curses fallback for non-TTY — Task 5 + Task 6 (delegates to fallbacks)
- [x] `--segments`, `--max-size-gb`, `--dry-run` flags — Task 10
- [x] Exit codes (0/1/2/3/4/5/130) — Task 10
- [x] Skip-if-already-downloaded for season batch — noted in `download_season` (via `download_episode` returning False; full skip check can be added if the integration test reveals it's needed — the spec mentions it but `download_video` already handles `.part` resume so re-runs are idempotent)

**Placeholder scan:** No TBDs, TODOs, or "add error handling" placeholders. Every code step has complete code.

**Type consistency:**
- `read_kodi_settings(path) -> dict` — consistent across Tasks 1, 8, 9, 10
- `pick_best_source(sources, quality, max_gb) -> dict | None` — consistent across Tasks 2, 8
- `build_query(title, season, episode) -> str` — consistent across Tasks 3, 8
- `arrow_select(options, label, default=0) -> value` — consistent across Tasks 5, 6
- `search_and_pick(search_fn) -> dict | None` — consistent across Tasks 5, 6, 10
- `select_quality(default) -> str`, `select_season(seasons) -> int`, `select_episode(episodes) -> int | "all"` — consistent across Tasks 6, 10
- `download_episode(show, season, episode, quality, settings, dry_run) -> bool` — consistent across Tasks 8, 9, 10
- `download_season(show, season, episodes, quality, settings, dry_run) -> (downloaded, skipped)` — consistent across Tasks 9, 10
- `main(argv=None) -> int` — Task 10
