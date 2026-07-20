# CLI Movie Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add movie support to the CLI — searching returns both shows and movies in one merged list, the user picks one, and movies download end-to-end without season/episode pickers.

**Architecture:** New `_search_all_types` helper runs `tmdb.search_shows` and `tmdb.search_movies` in parallel, tags each result with `type`. New `download_movie` function handles the movie flow (no season/episode, `content_type='movies'`, movie-shaped manifest entry). `search_and_pick`/`search_and_pick_fallback` are refactored to render labels via a new `_label_media` helper. `main()` dispatches on the picked item's `type`.

**Tech Stack:** Python 3, `requests`, `concurrent.futures.ThreadPoolExecutor`, `unittest`. No new dependencies.

## Global Constraints

- No new dependencies — use `ThreadPoolExecutor` already imported in `cli.py`.
- All existing flags (`--no-magnet-timeout`, `--dry-run`, `--segments`, `--max-size-gb`) apply to movies unchanged.
- Existing show flow must remain backward compatible — no behavior change for show users except the `[Show]` suffix in picker labels.
- `safe_filename` in `download_manager.py:126` already handles `season=None`/`episode=None` — do not modify it.
- Manifest entries for movies use `mediatype='movie'` and omit `season`/`episode` keys, matching `main.py:486`.
- `_search_with_retry` (cli.py) already accepts a `content_type` param — pass `'movies'` for movies.
- Run tests with: `python3 -m unittest test_cli test_scraper_runner test_alldebrid test_download_manager`

---

## File Structure

- **Modify:** `cli.py` — new helpers (`_label_media`, `_search_all_types`, `build_movie_query`, `download_movie`), refactor `search_and_pick`/`search_and_pick_fallback` label rendering, update `main()` dispatch.
- **Modify:** `test_cli.py` — new test classes (`BuildMovieQueryTests`, `SearchAllTypesTests`, `LabelMediaTests`, `DownloadMovieTests`), update `SearchAndPickFallbackTests` for new label format.

No other files change. `download_manager.py`, `alldebrid.py`, `tmdb.py`, `scraper_runner.py` are all already movie-capable.

---

### Task 1: `build_movie_query` helper

**Files:**
- Modify: `cli.py` (add after `build_query`, around line 113)
- Test: `test_cli.py` (new `BuildMovieQueryTests` class after `BuildQueryTests`)

**Interfaces:**
- Consumes: none (pure helper)
- Produces: `build_movie_query(title: str, year: str) -> str` — `"{title} {year}"` if year else `"{title}"`, apostrophes stripped.

- [ ] **Step 1: Write the failing test**

Add to `test_cli.py` after `BuildQueryTests` (around line 158):

```python
class BuildMovieQueryTests(unittest.TestCase):
    def test_includes_year_when_present(self):
        self.assertEqual(cli.build_movie_query("Inception", "2010"),
                         "Inception 2010")

    def test_omits_year_when_empty(self):
        self.assertEqual(cli.build_movie_query("Inception", ""),
                         "Inception")

    def test_omits_year_when_none(self):
        self.assertEqual(cli.build_movie_query("Inception", None),
                         "Inception")

    def test_strips_apostrophes(self):
        self.assertEqual(cli.build_movie_query("The Boss's Movie", "2020"),
                         "The Boss Movie 2020")

    def test_strips_smart_quotes(self):
        self.assertEqual(cli.build_movie_query("It\u2019s a Movie", "2021"),
                         "Its a Movie 2021")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.BuildMovieQueryTests -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute 'build_movie_query'`

- [ ] **Step 3: Write minimal implementation**

Add to `cli.py` immediately after `build_query` (after line 113):

```python
def build_movie_query(title, year):
    """Build the scraper query for a movie: 'Title Year' (or just Title).

    Strips apostrophes from the title — some scraper APIs (e.g. PirateBay)
    return zero results for queries containing apostrophes.
    """
    clean_title = title.replace("'", '').replace('\u2019', '')
    if year:
        return "{} {}".format(clean_title, year)
    return clean_title
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.BuildMovieQueryTests -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add build_movie_query helper"
```

---

### Task 2: `_label_media` helper

**Files:**
- Modify: `cli.py` (add after `build_movie_query`)
- Test: `test_cli.py` (new `LabelMediaTests` class)

**Interfaces:**
- Consumes: none (pure helper)
- Produces: `_label_media(item: dict) -> str` — `"Title (Year) [Show]"` or `"Title (Year) [Movie]"`; year omitted when absent.

- [ ] **Step 1: Write the failing test**

Add to `test_cli.py` after `BuildMovieQueryTests`:

```python
class LabelMediaTests(unittest.TestCase):
    def test_show_with_year(self):
        item = {'title': 'Breaking Bad', 'year': '2008', 'type': 'show'}
        self.assertEqual(cli._label_media(item), 'Breaking Bad (2008) [Show]')

    def test_movie_with_year(self):
        item = {'title': 'Inception', 'year': '2010', 'type': 'movie'}
        self.assertEqual(cli._label_media(item), 'Inception (2010) [Movie]')

    def test_show_without_year(self):
        item = {'title': 'Some Show', 'year': '', 'type': 'show'}
        self.assertEqual(cli._label_media(item), 'Some Show [Show]')

    def test_movie_without_year(self):
        item = {'title': 'Some Movie', 'year': None, 'type': 'movie'}
        self.assertEqual(cli._label_media(item), 'Some Movie [Movie]')

    def test_missing_type_defaults_to_show(self):
        item = {'title': 'Untitled', 'year': '2020'}
        self.assertEqual(cli._label_media(item), 'Untitled (2020) [Show]')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.LabelMediaTests -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute '_label_media'`

- [ ] **Step 3: Write minimal implementation**

Add to `cli.py` immediately after `build_movie_query`:

```python
def _label_media(item):
    """Format a TMDB result for picker display: 'Title (Year) [Show]' or
    'Title (Year) [Movie]'. Year omitted when absent. Type defaults to
    'show' for backward compatibility with untagged results."""
    title = item.get('title', '?')
    year = item.get('year', '')
    mtype = item.get('type', 'show')
    label = title
    if year:
        label += ' ({})'.format(year)
    label += ' [{}]'.format(mtype.capitalize())
    return label
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.LabelMediaTests -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add _label_media helper for picker labels"
```

---

### Task 3: Refactor `search_and_pick` / `search_and_pick_fallback` to use `_label_media`

**Files:**
- Modify: `cli.py:225-257` (`search_and_pick_fallback`) and `cli.py:320-357` (`search_and_pick`)
- Test: `test_cli.py:371-404` (`SearchAndPickFallbackTests` — update expected labels)

**Interfaces:**
- Consumes: `_label_media` from Task 2
- Produces: `search_and_pick(search_fn)` and `search_and_pick_fallback(search_fn, input_fn=input)` now render labels via `_label_media`. No signature change.

- [ ] **Step 1: Update the existing tests to expect new labels**

In `test_cli.py`, the `SearchAndPickFallbackTests` class (around line 371) doesn't assert on printed output directly — it asserts on the returned match dict. So no test changes needed there. But add a new test to verify the label format is used:

Add to `test_cli.py` after `SearchAndPickFallbackTests`:

```python
class SearchAndPickLabelTests(unittest.TestCase):
    def test_fallback_uses_label_media_for_display(self):
        matches = [
            {'id': 1, 'title': 'Breaking Bad', 'year': '2008', 'type': 'show'},
            {'id': 2, 'title': 'Inception', 'year': '2010', 'type': 'movie'},
        ]
        def fake_search(query):
            return matches
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        inputs = iter(['test', '1'])
        with redirect_stdout(buf):
            result = cli.search_and_pick_fallback(
                fake_search, input_fn=lambda _: next(inputs))
        output = buf.getvalue()
        self.assertIn('[Show]', output)
        self.assertIn('[Movie]', output)
        self.assertEqual(result['id'], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.SearchAndPickLabelTests -v`
Expected: FAIL — output does not contain `[Show]` or `[Movie]`

- [ ] **Step 3: Refactor `search_and_pick_fallback`**

In `cli.py`, replace lines 243-245 (the print loop in `search_and_pick_fallback`):

```python
        print('  TMDB matches:')
        for i, m in enumerate(matches, start=1):
            print('  {}. {} ({})'.format(i, m.get('title', '?'), m.get('year', '')))
```

with:

```python
        print('  TMDB matches:')
        for i, m in enumerate(matches, start=1):
            print('  {}. {}'.format(i, _label_media(m)))
```

- [ ] **Step 4: Refactor `search_and_pick` (curses path)**

In `cli.py`, replace lines 355-356 (the `opts` construction in `search_and_pick`):

```python
        opts = [(m, '{} ({})'.format(m.get('title', '?'), m.get('year', '')))
                for m in matches]
        return arrow_select(opts, 'Pick a show:')
```

with:

```python
        opts = [(m, _label_media(m)) for m in matches]
        return arrow_select(opts, 'Pick a title:')
```

- [ ] **Step 5: Run all picker tests to verify they pass**

Run: `python3 -m unittest test_cli.SearchAndPickFallbackTests test_cli.SearchAndPickLabelTests -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Run full suite to check for regressions**

Run: `python3 -m unittest test_cli test_scraper_runner test_alldebrid test_download_manager`
Expected: PASS (all existing tests still pass)

- [ ] **Step 7: Commit**

```bash
git add cli.py test_cli.py
git commit -m "refactor(cli): search_and_pick uses _label_media for labels

Picker now shows [Show]/[Movie] suffix on each entry. Show users see
[Show] on every entry — minor label change, no behavior change."
```

---

### Task 4: `_search_all_types` helper

**Files:**
- Modify: `cli.py` (add after `_label_media`)
- Test: `test_cli.py` (new `SearchAllTypesTests` class)

**Interfaces:**
- Consumes: `tmdb.search_shows(query, api_key, language)`, `tmdb.search_movies(query, api_key, language)` — both already exist in `resources/lib/tmdb.py`.
- Produces: `_search_all_types(query: str, settings: dict) -> list[dict]` — each item has `type: 'show'|'movie'` plus the TMDB fields (`id`, `title`, `year`, `overview`, `poster_url`).

- [ ] **Step 1: Write the failing test**

Add to `test_cli.py` after `SearchAndPickLabelTests`:

```python
class SearchAllTypesTests(unittest.TestCase):
    def test_merges_shows_and_movies_with_type_tag(self):
        shows = [{'id': 1, 'title': 'Breaking Bad', 'year': '2008'}]
        movies = [{'id': 2, 'title': 'Inception', 'year': '2010'}]
        orig_shows = cli.tmdb.search_shows
        orig_movies = cli.tmdb.search_movies
        cli.tmdb.search_shows = lambda q, k, l: shows
        cli.tmdb.search_movies = lambda q, k, l: movies
        try:
            results = cli._search_all_types('test', {'tmdb_api_key': 'x'})
        finally:
            cli.tmdb.search_shows = orig_shows
            cli.tmdb.search_movies = orig_movies
        self.assertEqual(len(results), 2)
        types = {r.get('type') for r in results}
        self.assertEqual(types, {'show', 'movie'})
        show_item = [r for r in results if r['type'] == 'show'][0]
        self.assertEqual(show_item['title'], 'Breaking Bad')
        movie_item = [r for r in results if r['type'] == 'movie'][0]
        self.assertEqual(movie_item['title'], 'Inception')

    def test_empty_results_when_both_empty(self):
        orig_shows = cli.tmdb.search_shows
        orig_movies = cli.tmdb.search_movies
        cli.tmdb.search_shows = lambda q, k, l: []
        cli.tmdb.search_movies = lambda q, k, l: []
        try:
            results = cli._search_all_types('test', {'tmdb_api_key': 'x'})
        finally:
            cli.tmdb.search_shows = orig_shows
            cli.tmdb.search_movies = orig_movies
        self.assertEqual(results, [])

    def test_calls_both_apis_with_same_query(self):
        calls = {'shows': [], 'movies': []}
        orig_shows = cli.tmdb.search_shows
        orig_movies = cli.tmdb.search_movies
        cli.tmdb.search_shows = lambda q, k, l: calls['shows'].append(q) or []
        cli.tmdb.search_movies = lambda q, k, l: calls['movies'].append(q) or []
        try:
            cli._search_all_types('inception', {'tmdb_api_key': 'x', 'tmdb_language': 'en'})
        finally:
            cli.tmdb.search_shows = orig_shows
            cli.tmdb.search_movies = orig_movies
        self.assertEqual(calls['shows'], ['inception'])
        self.assertEqual(calls['movies'], ['inception'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.SearchAllTypesTests -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute '_search_all_types'`

- [ ] **Step 3: Write minimal implementation**

Add to `cli.py` immediately after `_label_media`:

```python
def _search_all_types(query, settings):
    """Search TMDB for both shows and movies in parallel, return merged list.

    Each result is tagged with 'type': 'show' or 'movie' so the caller
    can dispatch on it. Uses ThreadPoolExecutor so both API calls run
    concurrently.
    """
    from concurrent.futures import ThreadPoolExecutor
    api_key = settings.get('tmdb_api_key', '')
    language = settings.get('tmdb_language', 'en')

    with ThreadPoolExecutor(max_workers=2) as pool:
        shows_future = pool.submit(tmdb.search_shows, query, api_key, language)
        movies_future = pool.submit(tmdb.search_movies, query, api_key, language)
        shows = shows_future.result()
        movies = movies_future.result()

    for s in shows:
        s.setdefault('type', 'show')
    for m in movies:
        m.setdefault('type', 'movie')
    return shows + movies
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.SearchAllTypesTests -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add _search_all_types for parallel show+movie search"
```

---

### Task 5: `download_movie` function

**Files:**
- Modify: `cli.py` (add after `download_episode`, around line 530)
- Test: `test_cli.py` (new `DownloadMovieTests` class after `DownloadEpisodeTests`)

**Interfaces:**
- Consumes: `build_movie_query` (Task 1), `_search_with_retry` (existing), `pick_best_source` (existing), `alldebrid.resolve` (existing), `download_manager.download_video` (existing), `_cleanup_part_files` (existing), `_alldebrid_progress` (existing), `download_manager.add_to_manifest`/`cache_artwork`/`safe_filename`/`get_download_dir`/`art_dir` (all existing).
- Produces: `download_movie(movie: dict, quality: str, settings: dict, dry_run: bool=False) -> bool` — True on success, False on no sources or download failure. Raises `AllDebridError` on magnet resolution failure (caller handles).

- [ ] **Step 1: Write the failing test**

Add to `test_cli.py` after `DownloadEpisodeTests` (before `DownloadSeasonTests`):

```python
class DownloadMovieTests(unittest.TestCase):
    """Integration test for download_movie with mocked scrape/resolve
    and a local throttled Range-supporting HTTP server. Same setUp/tearDown
    pattern as DownloadEpisodeTests."""
    def setUp(self):
        # Reuse the same HTTP server setup as DownloadEpisodeTests.
        # Inline copy because DownloadEpisodeTests.setUp isn't inherited.
        import http.server
        import socketserver
        import threading
        import time
        self.tmp = tempfile.mkdtemp()
        self.payload = b'X' * (4 * 1024 * 1024)
        src = os.path.join(self.tmp, 'source.bin')
        with open(src, 'wb') as f:
            f.write(self.payload)

        outer = self
        class RangeThrottledHandler(http.server.BaseHTTPRequestHandler):
            CHUNK_DELAY_S = 0.005
            def do_GET(self):
                with open(src, 'rb') as f:
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
        from resources.lib import download_manager as dm
        self._orig_min_parallel = dm.MIN_PARALLEL_SIZE
        dm.MIN_PARALLEL_SIZE = 0
        self._orig_get_download_dir = dm.get_download_dir
        dm.get_download_dir = lambda: self.tmp
        self._orig_art_dir = dm.art_dir
        dm.art_dir = lambda: self.tmp

    def tearDown(self):
        import shutil
        os.chdir(self._orig_cwd)
        from resources.lib import download_manager as dm
        dm.MIN_PARALLEL_SIZE = self._orig_min_parallel
        dm.get_download_dir = self._orig_get_download_dir
        dm.art_dir = self._orig_art_dir
        self.httpd.shutdown()
        self.httpd.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_downloads_movie_and_adds_to_manifest(self):
        from resources.lib import download_manager as dm
        movie = {'id': 27205, 'title': 'Inception', 'year': '2010',
                 'poster_url': None, 'type': 'movie'}
        settings = {
            'alldebridtoken': 'x',
            'tmdb_api_key': 'x',
            'tmdb_language': 'en',
            'offline_quality': '720p',
            'download_segments': '4',
            'max_download_size_gb': '2',
            'magnet_timeout': '120',
        }
        fake_source = {
            'show_title': 'Inception',
            'url': 'magnet:?fake',
            'title': 'Inception.2010.1080p',
            'quality': '1080p',
            'size': '800 MB',
            'seeders': 10,
        }
        orig_search_all = cli.scraper_runner.search_all
        orig_resolve = cli.alldebrid.resolve
        orig_manifest_path = dm.manifest_path
        cli.scraper_runner.search_all = lambda q, content_type='all': [fake_source]
        cli.alldebrid.resolve = lambda url, api_key, **kw: self.file_url
        dm.manifest_path = os.path.join(self.tmp, 'manifest.json')
        try:
            result = cli.download_movie(movie, '720p', settings)
            self.assertTrue(result)
            manifest = json.loads(open(dm.manifest_path).read())
            self.assertEqual(len(manifest), 1)
            entry = manifest[0]
            self.assertEqual(entry['mediatype'], 'movie')
            self.assertEqual(entry['title'], 'Inception')
            self.assertNotIn('season', entry)
            self.assertNotIn('episode', entry)
            self.assertTrue(os.path.exists(entry['file_path']))
            self.assertEqual(os.path.getsize(entry['file_path']), len(self.payload))
            # filename has no SxxExx
            self.assertNotIn('S0', entry['id'])
            self.assertNotIn('E0', entry['id'])
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            dm.manifest_path = orig_manifest_path

    def test_no_sources_returns_false(self):
        movie = {'id': 1, 'title': 'Unknown', 'year': '2020', 'type': 'movie'}
        settings = {
            'alldebridtoken': 'x', 'tmdb_api_key': 'x', 'tmdb_language': 'en',
            'offline_quality': '720p', 'download_segments': '4',
            'max_download_size_gb': '2', 'magnet_timeout': '120',
        }
        orig_search_all = cli.scraper_runner.search_all
        cli.scraper_runner.search_all = lambda q, content_type='all': []
        try:
            result = cli.download_movie(movie, '720p', settings)
            self.assertFalse(result)
        finally:
            cli.scraper_runner.search_all = orig_search_all

    def test_dry_run_does_not_download(self):
        from resources.lib import download_manager as dm
        movie = {'id': 27205, 'title': 'Inception', 'year': '2010', 'type': 'movie'}
        settings = {
            'alldebridtoken': 'x', 'tmdb_api_key': 'x', 'tmdb_language': 'en',
            'offline_quality': '720p', 'download_segments': '4',
            'max_download_size_gb': '2', 'magnet_timeout': '120',
        }
        fake_source = {
            'show_title': 'Inception', 'url': 'magnet:?fake',
            'title': 'Inception.2010.1080p', 'quality': '1080p',
            'size': '800 MB', 'seeders': 10,
        }
        orig_search_all = cli.scraper_runner.search_all
        orig_resolve = cli.alldebrid.resolve
        orig_manifest_path = dm.manifest_path
        cli.scraper_runner.search_all = lambda q, content_type='all': [fake_source]
        cli.alldebrid.resolve = lambda url, api_key, **kw: self.file_url
        dm.manifest_path = os.path.join(self.tmp, 'manifest.json')
        try:
            result = cli.download_movie(movie, '720p', settings, dry_run=True)
            self.assertTrue(result)
            self.assertFalse(os.path.exists(dm.manifest_path))
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            dm.manifest_path = orig_manifest_path

    def test_uses_movies_content_type_for_scrape(self):
        movie = {'id': 27205, 'title': 'Inception', 'year': '2010', 'type': 'movie'}
        settings = {
            'alldebridtoken': 'x', 'tmdb_api_key': 'x', 'tmdb_language': 'en',
            'offline_quality': '720p', 'download_segments': '4',
            'max_download_size_gb': '2', 'magnet_timeout': '120',
        }
        fake_source = {
            'show_title': 'Inception', 'url': 'magnet:?fake',
            'title': 'Inception.2010.1080p', 'quality': '1080p',
            'size': '800 MB', 'seeders': 10,
        }
        captured = {}
        def fake_search_all(query, content_type='all'):
            captured['content_type'] = content_type
            return [fake_source]
        orig_search_all = cli.scraper_runner.search_all
        orig_resolve = cli.alldebrid.resolve
        from resources.lib import download_manager as dm
        orig_manifest_path = dm.manifest_path
        cli.scraper_runner.search_all = fake_search_all
        cli.alldebrid.resolve = lambda url, api_key, **kw: self.file_url
        dm.manifest_path = os.path.join(self.tmp, 'manifest.json')
        try:
            cli.download_movie(movie, '720p', settings, dry_run=True)
            self.assertEqual(captured.get('content_type'), 'movies')
        finally:
            cli.scraper_runner.search_all = orig_search_all
            cli.alldebrid.resolve = orig_resolve
            dm.manifest_path = orig_manifest_path
```

Also add `import json` to the top of `test_cli.py` if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.DownloadMovieTests -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute 'download_movie'`

- [ ] **Step 3: Write minimal implementation**

Add to `cli.py` immediately after `download_episode` (after the line `return True` that ends `download_episode`, around line 530):

```python
def download_movie(movie, quality, settings, dry_run=False):
    """Run the scrape -> resolve -> download -> manifest flow for one movie.

    movie: TMDB movie dict with at least {id, title, year, poster_url, type}.
    settings: dict from read_kodi_settings().
    Returns True on success, False on no sources or download failure.
    Raises AllDebridError if the magnet resolution fails (caller decides
    whether to abort or skip-and-continue).
    """
    title = movie.get('title', '')
    poster_url = movie.get('poster_url')
    year = movie.get('year', '')

    query = build_movie_query(title, year)
    print('[scrape] searching for {}'.format(query))
    sources = _search_with_retry(query, content_type='movies')
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
        best.get('title', '?'), best.get('size', '?'), best.get('seeders', '?')))

    if dry_run:
        print('[dry-run] would download: {}'.format(best.get('url', '?')))
        return True

    api_key = settings.get('alldebridtoken', '')
    num_segments = int(settings.get('download_segments', '4') or '4')
    magnet_timeout = int(settings.get('magnet_timeout', '120') or '120')

    if magnet_timeout:
        print('[alldebrid] resolving... (timeout={}s)'.format(magnet_timeout))
    else:
        print('[alldebrid] resolving... (no timeout)')
    direct_url = alldebrid.resolve(
        best['url'], api_key,
        timeout=magnet_timeout,
        progress_callback=_alldebrid_progress,
    )
    print('[alldebrid] ready')

    dest_dir = download_manager.get_download_dir()
    fname = download_manager.safe_filename(title)
    dest = os.path.join(dest_dir, fname)

    print('[download] -> {}'.format(dest))
    progress_cb = make_progress_callback()
    try:
        ok = download_manager.download_video(
            direct_url, dest,
            num_segments=num_segments,
            progress_callback=progress_cb,
        )
    except KeyboardInterrupt:
        _cleanup_part_files(dest)
        print('[download] cancelled, partial files removed')
        raise
    except DownloadError as e:
        print('[fail] download error: {}'.format(e))
        _cleanup_part_files(dest)
        return False
    if not ok:
        print('[fail] download cancelled or failed')
        _cleanup_part_files(dest)
        return False

    poster_local = None
    if poster_url:
        poster_local = download_manager.cache_artwork(
            poster_url, os.path.join(download_manager.art_dir(),
                                     fname + '.poster.jpg'))

    entry = {
        'id': fname,
        'title': title,
        'show_title': title,
        'file_path': dest,
        'size_bytes': os.path.getsize(dest),
        'date_added': int(__import__('time').time()),
        'mediatype': 'movie',
        'plot': '',
        'poster_path': poster_local,
    }
    download_manager.add_to_manifest(entry)
    print('Done: {}'.format(dest))
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.DownloadMovieTests -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run full suite to check for regressions**

Run: `python3 -m unittest test_cli test_scraper_runner test_alldebrid test_download_manager`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add cli.py test_cli.py
git commit -m "feat(cli): add download_movie for movie downloads

Scrape with content_type='movies', resolve without season/episode,
write manifest entry with mediatype='movie' and no season/episode
fields. Reuses _search_with_retry, pick_best_source, partial-file
cleanup, and --no-magnet-timeout from the show flow."
```

---

### Task 6: Wire `main()` to search both types and dispatch on `type`

**Files:**
- Modify: `cli.py:642-692` (the `main()` flow after settings load)
- Test: no new test class — `main()` is interactive and covered by manual verification. Existing `MainArgsTests` still pass.

**Interfaces:**
- Consumes: `_search_all_types` (Task 4), `download_movie` (Task 5), all existing show-flow functions.
- Produces: `main()` now returns movie results in searches and routes movie picks to `download_movie`.

- [ ] **Step 1: Update `main()` to use `_search_all_types`**

In `cli.py`, replace the `search_fn` definition and `show = search_and_pick(...)` block (lines 643-654):

```python
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
```

with:

```python
        # 1. Title lookup (interactive) — searches both shows and movies
        def search_fn(query):
            return _search_all_types(query, settings)
        picked = search_and_pick(search_fn)
        if picked is None:
            print('[tmdb] no matches')
            return 2
        print('[tmdb] {} -> id={} type={}'.format(
            picked.get('title', '?'), picked.get('id'), picked.get('type')))
```

- [ ] **Step 2: Update the dispatch to branch on `type`**

In `cli.py`, replace the show-only block (lines 656-692, from `# 2. Season picker` through the end of the `try`):

```python
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
            downloaded, skipped = download_season(
                show, season, episodes, quality, settings,
                dry_run=args.dry_run)
            if downloaded == 0:
                return 1
        else:
            ok = download_episode(show, season, ep_choice, quality, settings,
                                  dry_run=args.dry_run)
            if not ok:
                return 1
        return 0
```

with:

```python
        if picked.get('type') == 'movie':
            # Movie path: no season/episode picker
            quality = select_quality(default=settings.get('offline_quality', '720p'))
            print('[quality] {}'.format(quality))
            ok = download_movie(picked, quality, settings,
                                dry_run=args.dry_run)
            if not ok:
                return 1
            return 0

        # Show path: existing season/episode flow
        show = picked
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
            downloaded, skipped = download_season(
                show, season, episodes, quality, settings,
                dry_run=args.dry_run)
            if downloaded == 0:
                return 1
        else:
            ok = download_episode(show, season, ep_choice, quality, settings,
                                  dry_run=args.dry_run)
            if not ok:
                return 1
        return 0
```

- [ ] **Step 3: Run full suite to verify no regressions**

Run: `python3 -m unittest test_cli test_scraper_runner test_alldebrid test_download_manager`
Expected: PASS (all tests)

- [ ] **Step 4: Commit**

```bash
git add cli.py
git commit -m "feat(cli): main() searches both shows and movies, dispatches on type

main() now calls _search_all_types (parallel TMDB show+movie search),
labels results with [Show]/[Movie] via search_and_pick, and routes
movie picks to download_movie (skipping season/episode pickers).
Show picks use the existing flow unchanged."
```

---

### Task 7: Manual end-to-end verification

**Files:** none modified — verification only.

- [ ] **Step 1: Verify movie search and dry-run**

Run: `python3 cli.py --dry-run`
Search: `Inception`
Expected: results list shows `Inception (2010) [Movie]` (and possibly `[Show]` entries if any show is named "Inception")
Pick the movie entry. Pick any quality. Expected: `[scrape] N sources found` and `[dry-run] would download: ...` — no season/episode prompts.

- [ ] **Step 2: Verify show search still works (no regression)**

Run: `python3 cli.py --dry-run`
Search: `Breaking Bad`
Expected: results list shows `Breaking Bad (2008) [Show]`
Pick it. Expected: season picker appears → pick a season → episode picker appears → pick an episode → quality → dry-run output. No `[Movie]` labels on show entries.

- [ ] **Step 3: Verify a real movie download (optional, if AllDebrid key set)**

Run: `python3 cli.py --no-magnet-timeout`
Search: pick a small movie. Pick quality. Let it download.
Expected: file appears in `~/.bald_man/downloads/`, filename has no `SxxExx`, manifest entry has `mediatype: movie`.

- [ ] **Step 4: Commit verification note (optional)**

No commit needed — verification only. If issues found, file as new tasks.
