# CLI Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three bugs found during real-world CLI usage: wrong-show sources passing relevance filter, no-quality sources being deprioritized, and dead magnets stalling resolve indefinitely.

**Architecture:** Three independent fixes — (1) a CLI-specific post-scrape title filter with safety-net fallback, (2) a sort-key change in `pick_best_source` to make no-quality sources compete equally, (3) download-progress stall detection in `alldebrid.resolve` using the AllDebrid `downloaded` field.

**Tech Stack:** Python 3, `unittest`, `unittest.mock.patch` for AllDebrid API mocking. No new dependencies.

## Global Constraints

- No new dependencies.
- Existing show flow must remain backward compatible.
- Fix 1 must NOT be too strict — if the title filter drops ALL sources, fall back to the unfiltered list (safety net).
- Fix 3 stall timeout is 10 seconds (user-specified).
- Run tests with: `python3 -m unittest test_cli test_scraper_runner test_alldebrid test_download_manager`
- `_relevant` in `scraper_runner.py` must NOT be modified — it's shared with the addon, which shows a list for user picking. The CLI filter is separate.
- `QUALITY_RANK = {'4k': 4, '2160p': 4, '1080p': 3, '720p': 2, '480p': 1}` (cli.py:24). No-quality sources get rank 0.

---

## File Structure

- **Modify:** `cli.py` — new `_filter_by_title` function (Task 1), modified `pick_best_source` sort key (Task 2), wired into `download_episode` and `download_movie` (Task 1).
- **Modify:** `test_cli.py` — new `FilterByTitleTests` class (Task 1), new tests in `PickBestSourceTests` (Task 2).
- **Modify:** `resources/lib/alldebrid.py` — stall detection in `resolve` (Task 3).
- **Modify:** `test_alldebrid.py` — new `StallDetectionTests` class (Task 3).

---

### Task 1: `_filter_by_title` — CLI-specific post-scrape title filter

**Files:**
- Modify: `cli.py` (add `_filter_by_title` after `_search_with_retry` around line 475; wire into `download_episode` around line 497 and `download_movie` around line 599)
- Test: `test_cli.py` (new `FilterByTitleTests` class after `PickBestSourceTests`)

**Interfaces:**
- Consumes: `sources` (list of dicts from `scraper_runner.search_all`), `tmdb_title` (string from TMDB). Sources have a `show_title` field.
- Produces: `_filter_by_title(sources, tmdb_title) -> list[dict]` — filtered list. If filter drops ALL sources, returns the original unfiltered list (safety net).

- [ ] **Step 1: Write the failing test**

Add to `test_cli.py` after `PickBestSourceTests` (after line 142):

```python
class FilterByTitleTests(unittest.TestCase):
    def _src(self, show_title):
        return {'show_title': show_title, 'url': 'magnet:fake',
                'title': show_title, 'quality': '720p', 'size': '1 GB',
                'seeders': 10}

    def test_drops_source_with_extra_words(self):
        """'Walking Dead Beyond' dropped when TMDB title is 'The Walking Dead'."""
        sources = [self._src('Walking Dead Beyond'), self._src('Walking Dead')]
        result = cli._filter_by_title(sources, 'The Walking Dead')
        titles = [s['show_title'] for s in result]
        self.assertIn('Walking Dead', titles)
        self.assertNotIn('Walking Dead Beyond', titles)

    def test_keeps_exact_match(self):
        """'Breaking Bad' kept when TMDB title is 'Breaking Bad'."""
        sources = [self._src('Breaking Bad')]
        result = cli._filter_by_title(sources, 'Breaking Bad')
        self.assertEqual(len(result), 1)

    def test_keeps_shorter_source_for_long_title(self):
        """'Its Always Sunny' kept when TMDB title is 'It's Always Sunny in Philadelphia'."""
        sources = [self._src('Its Always Sunny')]
        result = cli._filter_by_title(sources, "It's Always Sunny in Philadelphia")
        self.assertEqual(len(result), 1)

    def test_drops_different_show_with_overlap(self):
        """'Fear the Walking Dead' dropped when TMDB title is 'The Walking Dead'."""
        sources = [self._src('Fear the Walking Dead')]
        result = cli._filter_by_title(sources, 'The Walking Dead')
        self.assertEqual(len(result), 0)

    def test_falls_back_to_unfiltered_when_all_dropped(self):
        """If filter drops everything, return original list (safety net)."""
        sources = [self._src('Completely Different Show')]
        result = cli._filter_by_title(sources, 'The Walking Dead')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['show_title'], 'Completely Different Show')

    def test_empty_sources_returns_empty(self):
        self.assertEqual(cli._filter_by_title([], 'The Walking Dead'), [])

    def test_strips_episode_code_from_source_title(self):
        """Source show_title with S01E03 still matches (episode code stripped)."""
        sources = [self._src('Walking Dead S01E03')]
        result = cli._filter_by_title(sources, 'The Walking Dead')
        self.assertEqual(len(result), 1)

    def test_case_insensitive(self):
        sources = [self._src('walking dead')]
        result = cli._filter_by_title(sources, 'The Walking Dead')
        self.assertEqual(len(result), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.FilterByTitleTests -v`
Expected: FAIL with `AttributeError: module 'cli' has no attribute '_filter_by_title'`

- [ ] **Step 3: Write minimal implementation**

Add to `cli.py` immediately after `_search_with_retry` (after line 474):

```python
def _filter_by_title(sources, tmdb_title):
    """Drop sources whose show_title has meaningful words not in tmdb_title.

    Normalizes both titles (lowercase, strip punctuation/apostrophes, remove
    stop words and short tokens), then checks if every source word is in the
    TMDB title's word set. Sources with extra words (e.g. 'Walking Dead
    Beyond' when searching for 'The Walking Dead') are dropped.

    Safety net: if filtering drops ALL sources, returns the original list
    unchanged — better to try wrong-show sources than to give up.
    """
    import re
    if not sources or not tmdb_title:
        return sources

    stop_words = {'the', 'a', 'an', 'in', 'of', 'and', 'is', 'it', 's',
                  'to', 'for', 'on', 'at', 'by', 'with', 'its'}

    def normalize(title):
        t = re.sub(r"[^\w\s']", ' ', title.lower()).replace("'", ' ')
        t = re.sub(r'\bs\d+e\d+\b', '', t)
        return {w for w in t.split() if w not in stop_words and len(w) > 1}

    tmdb_words = normalize(tmdb_title)
    if not tmdb_words:
        return sources

    filtered = []
    for s in sources:
        src_words = normalize(s.get('show_title', ''))
        if not src_words:
            filtered.append(s)
            continue
        if src_words.issubset(tmdb_words):
            filtered.append(s)

    if not filtered:
        return sources
    return filtered
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest test_cli.FilterByTitleTests -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Wire into `download_episode`**

In `cli.py`, find the `download_episode` function. After `_search_with_retry` and the "no sources" check, before `pick_best_source`, add the filter call. Replace:

```python
    print('[scrape] {} sources found'.format(len(sources)))

    max_gb = int(settings.get('max_download_size_gb', '2') or '2')
    best = pick_best_source(sources, quality=quality, max_gb=max_gb)
```

with:

```python
    print('[scrape] {} sources found'.format(len(sources)))
    sources = _filter_by_title(sources, title)
    print('[scrape] {} sources after title filter'.format(len(sources)))

    max_gb = int(settings.get('max_download_size_gb', '2') or '2')
    best = pick_best_source(sources, quality=quality, max_gb=max_gb)
```

- [ ] **Step 6: Wire into `download_movie`**

In `cli.py`, find the `download_movie` function. Same change — after `_search_with_retry` and the "no sources" check, before `pick_best_source`, add:

```python
    print('[scrape] {} sources found'.format(len(sources)))
    sources = _filter_by_title(sources, title)
    print('[scrape] {} sources after title filter'.format(len(sources)))

    max_gb = int(settings.get('max_download_size_gb', '2') or '2')
    best = pick_best_source(sources, quality=quality, max_gb=max_gb)
```

- [ ] **Step 7: Run full suite to check for regressions**

Run: `python3 -m unittest test_cli test_scraper_runner test_alldebrid test_download_manager`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add cli.py test_cli.py
git commit -m "fix(cli): filter wrong-show sources by TMDB title

Adds _filter_by_title() which drops sources whose show_title has
meaningful words not in the TMDB title (e.g. 'Walking Dead Beyond'
when searching for 'The Walking Dead'). Falls back to unfiltered
list if all sources are dropped, so it's never too strict."
```

---

### Task 2: Make no-quality sources compete equally in `pick_best_source`

**Files:**
- Modify: `cli.py:100-105` (`sort_key` function inside `pick_best_source`)
- Test: `test_cli.py` (new tests in `PickBestSourceTests`)

**Interfaces:**
- Consumes: none (modifies existing function internals)
- Produces: `pick_best_source` now treats no-quality sources (rank 0) as having `quality_distance = 0` instead of `abs(0 - want_rank)`. The existing `-q_rank` secondary sort ensures exact quality matches still beat no-quality sources.

- [ ] **Step 1: Write the failing test**

Add to `test_cli.py` inside `PickBestSourceTests` (after `test_unknown_quality_falls_to_rank_0`, around line 141):

```python
    def test_no_quality_beats_different_quality(self):
        """No-quality source beats 1080p when 720p is requested —
        no-quality is treated as universal (distance 0), not rank 0."""
        sources = [
            self._src('', '800 MB', seeders=50),
            self._src('1080p', '2 GB', seeders=100),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        self.assertEqual(best['quality'], '')

    def test_no_quality_beats_4k_when_720p_requested(self):
        sources = [
            self._src('', '800 MB', seeders=50),
            self._src('4k', '5 GB', seeders=100),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        self.assertEqual(best['quality'], '')

    def test_exact_quality_still_beats_no_quality(self):
        """When exact match exists, it beats no-quality source
        (secondary -q_rank sort puts exact match first)."""
        sources = [
            self._src('', '800 MB', seeders=100),
            self._src('720p', '900 MB', seeders=5),
        ]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        self.assertEqual(best['quality'], '720p')

    def test_no_quality_only_source_is_picked(self):
        sources = [self._src('', '500 MB', seeders=10)]
        best = cli.pick_best_source(sources, quality='720p', max_gb=10)
        self.assertEqual(best['quality'], '')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_cli.PickBestSourceTests.test_no_quality_beats_different_quality test_cli.PickBestSourceTests.test_no_quality_beats_4k_when_720p_requested -v`
Expected: FAIL — no-quality source loses to 1080p/4K (current behavior: distance 2 vs distance 1)

- [ ] **Step 3: Modify the sort key**

In `cli.py`, replace the `sort_key` function inside `pick_best_source` (lines 100-105):

```python
    def sort_key(r):
        q_rank = _rank_quality(r.get('quality', ''))
        quality_distance = abs(q_rank - want_rank)
        seeders = r.get('seeders') or 0
        size_bytes = _parse_size_bytes(r.get('size', '')) or 0
        return (quality_distance, -q_rank, -seeders, -size_bytes)
```

with:

```python
    def sort_key(r):
        q_rank = _rank_quality(r.get('quality', ''))
        if q_rank == 0:
            quality_distance = 0
        else:
            quality_distance = abs(q_rank - want_rank)
        seeders = r.get('seeders') or 0
        size_bytes = _parse_size_bytes(r.get('size', '')) or 0
        return (quality_distance, -q_rank, -seeders, -size_bytes)
```

- [ ] **Step 4: Run all PickBestSource tests to verify they pass**

Run: `python3 -m unittest test_cli.PickBestSourceTests -v`
Expected: PASS (all 12 tests — 8 existing + 4 new)

Note: `test_unknown_quality_falls_to_rank_0` (existing) should still pass — exact 720p beats no-quality on the `-q_rank` secondary sort (−2 < 0).

- [ ] **Step 5: Run full suite to check for regressions**

Run: `python3 -m unittest test_cli test_scraper_runner test_alldebrid test_download_manager`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add cli.py test_cli.py
git commit -m "fix(cli): no-quality sources compete equally in pick_best_source

No-quality sources (rank 0) now get quality_distance=0 instead of
abs(0-want_rank), so they beat mismatched-quality sources (e.g.
no-quality beats 1080p when 720p is requested). Exact quality
matches still win on the -q_rank secondary sort."
```

---

### Task 3: Dead-magnet stall detection in `alldebrid.resolve`

**Files:**
- Modify: `resources/lib/alldebrid.py` (add `STALL_TIMEOUT` constant; add stall tracking in `resolve`'s poll loop, around lines 74-142)
- Test: `test_alldebrid.py` (new `StallDetectionTests` class after `FindFileLinkTests`)

**Interfaces:**
- Consumes: `magnet_info.get("downloaded")` from AllDebrid API status response (bytes downloaded so far). Field may be absent — handle gracefully.
- Produces: `resolve` raises `AllDebridError("Magnet stalled — no download progress in {}s")` if `downloaded` doesn't increase for `STALL_TIMEOUT` (10) seconds during "Downloading" status. Does NOT trigger during "Processing" status. Does NOT trigger if `downloaded` field is absent.

- [ ] **Step 1: Write the failing test**

Add to `test_alldebrid.py` after `FindFileLinkTests` (at the end of the file):

```python
class _FakeResponse:
    """Minimal mock of requests.Response for AllDebrid API calls."""
    def __init__(self, data):
        self._data = data
    def raise_for_status(self):
        pass
    def json(self):
        return self._data


class StallDetectionTests(unittest.TestCase):
    """Test that resolve() detects dead magnets by tracking download progress."""

    def _upload_response(self, magnet_id=123):
        return _FakeResponse({
            "status": "success",
            "data": {"magnets": [{"id": magnet_id}]},
        })

    def _status_response(self, magnet_id=123, status="Downloading",
                         status_code=1, downloaded=0, size=1000000):
        return _FakeResponse({
            "status": "success",
            "data": {"magnets": [{"id": magnet_id, "status": status,
                                  "statusCode": status_code,
                                  "downloaded": downloaded, "size": size}]},
        })

    @patch('resources.lib.alldebrid.requests')
    def test_raises_on_stalled_download(self, mock_requests):
        """Magnet stuck in Downloading with no progress for 10s → AllDebridError."""
        from resources.lib import alldebrid

        mock_requests.post.return_value = self._upload_response()
        mock_requests.get.return_value = self._status_response(downloaded=0)

        current_time = [0.0]
        def mock_time():
            return current_time[0]
        def mock_sleep(seconds):
            current_time[0] += seconds

        with patch.object(alldebrid.time, 'time', mock_time), \
             patch.object(alldebrid.time, 'sleep', mock_sleep):
            with self.assertRaises(alldebrid.AllDebridError) as ctx:
                alldebrid.resolve('magnet:?fake', 'fake_api_key', timeout=0)
            self.assertIn('stalled', str(ctx.exception).lower())

    @patch('resources.lib.alldebrid.requests')
    def test_progress_resets_stall_timer(self, mock_requests):
        """If downloaded increases, stall timer resets — no false positive.
        Progress keeps resetting the 10s stall window, so the function
        eventually times out (not stalls) when the timeout is shorter
        than 10s after the last progress."""
        from resources.lib import alldebrid

        # Alternating: no progress, then progress, then no progress
        responses = [
            self._status_response(downloaded=0),      # poll 1: init
            self._status_response(downloaded=0),      # poll 2: no progress
            self._status_response(downloaded=500000), # poll 3: progress! reset
            self._status_response(downloaded=500000), # poll 4: no progress
            self._status_response(downloaded=500000), # poll 5: no progress
            self._status_response(downloaded=900000), # poll 6: progress! reset
            self._status_response(downloaded=900000), # poll 7: no progress
            self._status_response(downloaded=900000), # poll 8: no progress
        ]
        mock_requests.post.return_value = self._upload_response()
        mock_requests.get.side_effect = responses

        current_time = [0.0]
        def mock_time():
            return current_time[0]
        def mock_sleep(seconds):
            current_time[0] += seconds

        with patch.object(alldebrid.time, 'time', mock_time), \
             patch.object(alldebrid.time, 'sleep', mock_sleep):
            with self.assertRaises(alldebrid.AllDebridError) as ctx:
                alldebrid.resolve('magnet:?fake', 'fake_api_key', timeout=8)
            # Should time out, NOT stall — progress kept resetting the timer
            self.assertIn('timed out', str(ctx.exception).lower())
            self.assertNotIn('stalled', str(ctx.exception).lower())

    @patch('resources.lib.alldebrid.requests')
    def test_no_stall_during_processing_status(self, mock_requests):
        """Processing status (code 0) should not trigger stall detection."""
        from resources.lib import alldebrid

        # All responses are Processing — should NOT raise stall error
        # (will eventually time out instead, but we use a short timeout)
        mock_requests.post.return_value = self._upload_response()
        mock_requests.get.return_value = self._status_response(
            status="Processing", status_code=0, downloaded=0)

        current_time = [0.0]
        def mock_time():
            return current_time[0]
        def mock_sleep(seconds):
            current_time[0] += seconds

        with patch.object(alldebrid.time, 'time', mock_time), \
             patch.object(alldebrid.time, 'sleep', mock_sleep):
            with self.assertRaises(alldebrid.AllDebridError) as ctx:
                alldebrid.resolve('magnet:?fake', 'fake_api_key', timeout=5)
            # Should be a timeout error, not a stall error
            self.assertIn('timed out', str(ctx.exception).lower())
            self.assertNotIn('stalled', str(ctx.exception).lower())

    @patch('resources.lib.alldebrid.requests')
    def test_missing_downloaded_field_no_false_positive(self, mock_requests):
        """If API response lacks 'downloaded' field, no stall false positive."""
        from resources.lib import alldebrid

        mock_requests.post.return_value = self._upload_response()
        # Status response without 'downloaded' key
        mock_requests.get.return_value = _FakeResponse({
            "status": "success",
            "data": {"magnets": [{"id": 123, "status": "Downloading",
                                  "statusCode": 1}]},
        })

        current_time = [0.0]
        def mock_time():
            return current_time[0]
        def mock_sleep(seconds):
            current_time[0] += seconds

        with patch.object(alldebrid.time, 'time', mock_time), \
             patch.object(alldebrid.time, 'sleep', mock_sleep):
            with self.assertRaises(alldebrid.AllDebridError) as ctx:
                alldebrid.resolve('magnet:?fake', 'fake_api_key', timeout=5)
            # Should time out, not stall
            self.assertIn('timed out', str(ctx.exception).lower())
            self.assertNotIn('stalled', str(ctx.exception).lower())
```

Also add `from unittest.mock import patch` to the imports at the top of `test_alldebrid.py` if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test_alldebrid.StallDetectionTests -v`
Expected: FAIL — `test_raises_on_stalled_download` times out or hangs (no stall detection exists yet)

- [ ] **Step 3: Add `STALL_TIMEOUT` constant**

In `resources/lib/alldebrid.py`, after the `API` constant (line 12), add:

```python
STALL_TIMEOUT = 10  # seconds without download progress before declaring magnet dead
```

- [ ] **Step 4: Add stall tracking to `resolve`**

In `resources/lib/alldebrid.py`, inside `resolve`, find the poll loop initialization (around line 76-77):

```python
        last_status = ""
        poll_count = 0
```

Add after it:

```python
        last_downloaded = None
        last_progress_time = None
```

Then find the status-check block (after `magnet_status` and `status_code` are determined, around line 113-119). After the `last_status` update block:

```python
            if magnet_status != last_status:
                _log("magnet[{}] status={} code={} elapsed={}s".format(magnet_id, magnet_status, status_code, elapsed))
                last_status = magnet_status
```

Add after it (before the `if magnet_status in ("Ready", "4")` check):

```python
            # Stall detection: track download progress during Downloading status
            if status_code == 1 or magnet_status == "Downloading":
                current_downloaded = magnet_info.get("downloaded") if isinstance(magnet_info, dict) else None
                if current_downloaded is not None:
                    if last_downloaded is None or current_downloaded > last_downloaded:
                        last_downloaded = current_downloaded
                        last_progress_time = time.time()
                    elif last_progress_time is not None and time.time() - last_progress_time >= STALL_TIMEOUT:
                        raise AllDebridError(
                            "Magnet stalled — no download progress in {}s".format(STALL_TIMEOUT))
            else:
                last_downloaded = None
                last_progress_time = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m unittest test_alldebrid.StallDetectionTests -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run full suite to check for regressions**

Run: `python3 -m unittest test_cli test_scraper_runner test_alldebrid test_download_manager`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add resources/lib/alldebrid.py test_alldebrid.py
git commit -m "fix(alldebrid): detect dead magnets by tracking download progress

resolve() now tracks the 'downloaded' field from AllDebrid status
responses. If the magnet is in Downloading status but downloaded
bytes haven't increased in 10 seconds, raises AllDebridError
instead of looping forever (with --no-magnet-timeout) or waiting
the full timeout. Does not trigger during Processing status or
when the downloaded field is absent."
```
