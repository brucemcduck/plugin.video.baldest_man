# Scraper Content-Type Filtering & Parallel Execution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up searches from ~180s sequential to ~30s parallel by running scrapers concurrently and skipping irrelevant ones based on content type.

**Architecture:** Add a `content_type` parameter to `scraper_runner.search_all()` that filters scrapers by `CONTENT_TYPES` attribute, then runs the survivors in a `ThreadPoolExecutor`. A Kodi setting controls worker count. `main.py` already has `content_type` and just needs to pass it through.

**Tech Stack:** Python stdlib `concurrent.futures.ThreadPoolExecutor`, existing `requests` + `bs4` stack

## Global Constraints

- No new dependencies — ThreadPoolExecutor is stdlib
- Scrapers without `CONTENT_TYPES` default to supporting both movies and shows (backwards compatible)
- `scraper_workers` setting defaults to 6, range 1–20
- Thread safety: each scraper uses its own implicit requests session, no shared state

---

### Task 1: Add CONTENT_TYPES to specialized scrapers

**Files:**
- Modify: `scrapers/yts.py`
- Modify: `scrapers/eztv.py`
- Modify: `scrapers/nyaa.py`

**Interfaces:**
- Produces: `CONTENT_TYPES` module-level list — `["movies"]` or `["shows"]` — consumed by Task 3's filter

- [ ] **Step 1: Add CONTENT_TYPES to yts.py**

Open `scrapers/yts.py`. After `SITE_NAME = "yts"`, add:

```python
CONTENT_TYPES = ["movies"]
```

- [ ] **Step 2: Add CONTENT_TYPES to eztv.py**

Open `scrapers/eztv.py`. After `SITE_NAME = "eztv"`, add:

```python
CONTENT_TYPES = ["shows"]
```

- [ ] **Step 3: Add CONTENT_TYPES to nyaa.py**

Open `scrapers/nyaa.py`. After `SITE_NAME = "nyaa"`, add:

```python
CONTENT_TYPES = ["shows"]
```

- [ ] **Step 4: Verify**

Run: `python3 -c "import scrapers.yts; print(scrapers.yts.CONTENT_TYPES)"`
Expected: `['movies']`

Run: `python3 -c "import scrapers.eztv; print(scrapers.eztv.CONTENT_TYPES)"`
Expected: `['shows']`

Run: `python3 -c "import scrapers.nyaa; print(scrapers.nyaa.CONTENT_TYPES)"`
Expected: `['shows']`

- [ ] **Step 5: Commit**

```bash
git add scrapers/yts.py scrapers/eztv.py scrapers/nyaa.py
git commit -m "feat: add CONTENT_TYPES to specialized scrapers"
```

---

### Task 2: Add scraper_workers Kodi setting

**Files:**
- Modify: `resources/settings.xml`

**Interfaces:**
- Produces: `scraper_workers` setting ID — consumed by Task 3's `_worker_count()`

- [ ] **Step 1: Add scraper_workers setting to settings.xml**

Open `resources/settings.xml`. After the existing `</category>` closing tag, add:

```xml
  <category label="Scrapers">
    <setting id="scraper_workers" type="integer" label="Max concurrent scrapers" default="6">
      <constraints>
        <minimum>1</minimum>
        <maximum>20</maximum>
      </constraints>
    </setting>
  </category>
```

Full file should read:

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<settings>
  <category label="AllDebrid">
    <setting id="alldebrid_api_key" type="text" label="API Key" default="">
      <constraints>
        <allowempty>true</allowempty>
        <hidden>true</hidden>
      </constraints>
    </setting>
  </category>
  <category label="Scrapers">
    <setting id="scraper_workers" type="integer" label="Max concurrent scrapers" default="6">
      <constraints>
        <minimum>1</minimum>
        <maximum>20</maximum>
      </constraints>
    </setting>
  </category>
</settings>
```

- [ ] **Step 2: Verify XML is well-formed**

Run: `python3 -c "import xml.etree.ElementTree as ET; ET.parse('resources/settings.xml'); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add resources/settings.xml
git commit -m "feat: add scraper_workers setting (1-20, default 6)"
```

---

### Task 3: Rewrite scraper_runner with filter and thread pool

**Files:**
- Modify: `resources/lib/scraper_runner.py` (entire file)

**Interfaces:**
- Consumes: `CONTENT_TYPES` from scraper modules (Task 1), `scraper_workers` setting (Task 2)
- Produces: `search_all(query, content_type="all")` → `list[dict]` — consumed by `main.py` (Task 4)

- [ ] **Step 1: Write a local smoke test**

Create a test script to verify the new runner works outside Kodi:

File: `test_runner.py` (temporary, delete after testing)

```python
"""Quick smoke test for parallel scraper runner."""
import sys
sys.path.insert(0, '.')
from resources.lib import scraper_runner

# Test 1: content_type filter — "movies" should skip eztv and nyaa
results = scraper_runner.search_all("test", content_type="movies")
print(f"movies search: {len(results)} results")

# Test 2: content_type filter — "shows" should skip yts
results = scraper_runner.search_all("test", content_type="shows")
print(f"shows search: {len(results)} results")

# Test 3: "all" runs everything
results = scraper_runner.search_all("test", content_type="all")
print(f"all search: {len(results)} results")
```

- [ ] **Step 2: Run smoke test to see it fail**

Run: `python3 test_runner.py`
Expected: `TypeError: search_all() got an unexpected keyword argument 'content_type'`

- [ ] **Step 3: Rewrite scraper_runner.py**

Replace the entire file:

```python
"""Runs scrapers in parallel against a query, filters by content type."""
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import scrapers

REQUIRED_KEYS = {'show_title', 'url'}
DEFAULT_WORKERS = 6
SCRAPER_TIMEOUT = 15


def search_all(query, content_type="all"):
    """Run relevant scrapers in parallel, return merged validated results.

    Args:
        query: str — user's search term
        content_type: str — "movies", "shows", or "all"

    Returns:
        list[dict]
    """
    if not query:
        return []

    # Filter scrapers by content type
    scrapers_to_run = [
        m for m in scrapers.get_scrapers()
        if content_type == "all"
        or content_type in getattr(m, "CONTENT_TYPES", ["movies", "shows"])
    ]

    if not scrapers_to_run:
        return []

    results = []
    workers = _worker_count()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(m.search, query): m for m in scrapers_to_run}
        for future in as_completed(futures):
            mod = futures[future]
            try:
                raw = future.result(timeout=SCRAPER_TIMEOUT)
            except Exception:
                _log("scraper_runner: {} crashed\n{}".format(
                    mod.SITE_NAME, traceback.format_exc()))
                continue

            if not isinstance(raw, list):
                continue

            passed = 0
            dropped_relevance = 0
            for item in raw:
                if not isinstance(item, dict):
                    continue
                if not REQUIRED_KEYS.issubset(item.keys()):
                    continue
                if 'episode' not in item and not item.get('is_movie'):
                    continue
                if not _relevant(query, item['show_title']):
                    dropped_relevance += 1
                    _log("scraper_runner: {} dropped irrelevant '{}'".format(
                        mod.SITE_NAME, item['show_title']))
                    continue
                item.setdefault('site', mod.SITE_NAME)
                item.setdefault('title', '')
                item.setdefault('quality', '')
                results.append(item)
                passed += 1

            if passed or dropped_relevance:
                _log("scraper_runner: {} → {} results, {} dropped (irrelevant)".format(
                    mod.SITE_NAME, passed, dropped_relevance))

    return results


def _worker_count():
    """Read scraper_workers from Kodi settings, falling back to default."""
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon()
        val = addon.getSetting('scraper_workers')
        return int(val) if val else DEFAULT_WORKERS
    except (ImportError, ValueError):
        return DEFAULT_WORKERS


def _relevant(query, show_title):
    """True if the query appears as a substring of show_title (case-insensitive)."""
    return query.lower() in show_title.lower()


def _log(msg):
    try:
        import xbmc
        xbmc.log(msg, level=xbmc.LOGINFO)
    except ImportError:
        print(msg, file=sys.stderr)
```

- [ ] **Step 4: Run smoke test to verify it works**

Run: `python3 test_runner.py`
Expected: Something like (results vary by network):
```
scraper_runner: eztv crashed
...
movies search: N results
shows search: N results
all search: N results
```

- [ ] **Step 5: Verify content_type=movies skips shows-only scrapers**

Run: `python3 -c "
import sys; sys.path.insert(0,'.')
import scrapers
from resources.lib.scraper_runner import search_all
# This should NOT log any activity from eztv or nyaa
search_all('test', content_type='movies')
print('done')
" 2>&1 | grep -c eztv`
Expected: `0` (eztv is shows-only, should be skipped for movies search)

- [ ] **Step 6: Verify content_type=shows skips movies-only scrapers**

Run: `python3 -c "
import sys; sys.path.insert(0,'.')
from resources.lib.scraper_runner import search_all
search_all('test', content_type='shows')
print('done')
" 2>&1 | grep -c yts`
Expected: `0` (yts is movies-only, should be skipped for shows search)

- [ ] **Step 7: Clean up test file**

```bash
rm test_runner.py
```

- [ ] **Step 8: Commit**

```bash
git add resources/lib/scraper_runner.py
git commit -m "feat: parallel scraper execution with content-type filtering"
```

---

### Task 4: Pass content_type from main.py to search_all

**Files:**
- Modify: `main.py:89,127`

**Interfaces:**
- Consumes: `search_all(query, content_type)` from Task 3
- Produces: (no new interfaces — existing play/episode flow unchanged)

- [ ] **Step 1: Pass content_type in search mode**

Open `main.py`. Line 89 currently reads:
```python
results = scraper_runner.search_all(query)
```

Change to:
```python
results = scraper_runner.search_all(query, content_type=content_type)
```

- [ ] **Step 2: Pass content_type in episodes mode**

Open `main.py`. Line 127 currently reads:
```python
results = scraper_runner.search_all(query)
```

Change to:
```python
results = scraper_runner.search_all(query, content_type='shows')
```
(Episodes mode only shows shows, so always pass `'shows'`.)

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile main.py`
Expected: `(no output)` — compiles clean

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: pass content_type through to parallel scraper runner"
```

---

### Task 5: Integration smoke test

**Files:**
- (none — manual verification)

**Interfaces:**
- Consumes: All above tasks

- [ ] **Step 1: Trigger a search via Kodi**

Open Kodi, navigate to the addon, choose "Search All", search for "test".

- [ ] **Step 2: Check Kodi log for parallel execution**

Run: `tail -50 ~/.kodi/temp/kodi.log | grep scraper_runner`

Expected output: Multiple scrapers reporting results in rapid succession (not one every 15 seconds). Lines like:
```
scraper_runner: eztv → 0 results, 0 dropped (irrelevant)
scraper_runner: piratebay → 3 results, 0 dropped (irrelevant)
...
```

- [ ] **Step 3: Check that content-type filtering works**

Run a "Search Movies" instead. The log should NOT show any activity from `eztv` or `nyaa`.

- [ ] **Step 4: Verify the Kodi setting is respected**

In Kodi: Add-ons → plugin.video.baldest_man → Settings → Scrapers → Max concurrent scrapers.
Change to 2, re-run a search. Compare the log timestamps — they should serialize into ~2 groups.

- [ ] **Step 5: Commit (if any tweaks needed)**

```bash
git add -A
git commit -m "chore: integration verification"
```
