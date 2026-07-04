# plugin.video.baldest_man — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the hello-world Kodi plugin into a multi-site anime video scraper with unified search, show grouping, and episode listing.

**Architecture:** Three Python modules. `scrapers/` holds one file per site, each exposing `SITE_NAME` and `search(query)`. `lib/scraper_runner.py` auto-discovers scrapers and runs them in sequence. `main.py` handles Kodi routing — search dialog → grouped show folders → playable episode items.

**Tech Stack:** Python 3 (Kodi Matrix), `xbmcplugin`, `xbmcgui`, `requests`, `urllib.parse`, `importlib`

## Global Constraints

- `xbmc.python` 3.0.0 minimum (Kodi Matrix built-in)
- `script.module.requests` 2.22.0 (Kodi repo dependency, declared in addon.xml)
- Episode labels: `Ep 01 The Strongest Hero 1080p` (episode number, title, quality)
- Scraper failures: silent skip, no user notification
- No results: show info item "Nothing found for '<query>'"
- Duplicate episodes across sites: keep both
- Malformed scraper results: log via `xbmc.log`, skip, continue

---

### Task 1: Create scraper discovery and example scraper

**Files:**
- Create: `scrapers/__init__.py`
- Create: `scrapers/example.py`

**Interfaces:**
- Produces: `scrapers.get_scrapers() -> list[module]` — returns all discovered scraper modules, each with `.SITE_NAME` (str) and `.search(query: str) -> list[dict]`

- [ ] **Step 1: Write `scrapers/__init__.py` — auto-discovery**

```python
"""Scraper auto-discovery. Drop a .py file here with SITE_NAME and search()."""
import os
import importlib

_scrapers = []

def _discover():
    scraper_dir = os.path.dirname(__file__)
    for f in sorted(os.listdir(scraper_dir)):
        if f.startswith('_') or not f.endswith('.py'):
            continue
        name = f[:-3]
        mod = importlib.import_module('.' + name, __package__)
        if hasattr(mod, 'SITE_NAME') and hasattr(mod, 'search'):
            _scrapers.append(mod)

_discover()

def get_scrapers():
    return _scrapers
```

- [ ] **Step 2: Write `scrapers/example.py` — scraper template**

```python
"""Example scraper — copy this file and fill in the blanks."""
import requests

SITE_NAME = "example"

def search(query):
    """Return list of dicts with show_title, episode, url. Optional: title, quality."""
    # Replace with real HTTP + HTML parsing. Return [] on failure or no results.
    return []
```

- [ ] **Step 3: Verify scraper discovery works**

```bash
cd /home/dog/plugin.video.baldest_man && python3 -c "
import scrapers
mods = scrapers.get_scrapers()
assert len(mods) >= 1, 'expected at least example scraper'
m = mods[0]
assert m.SITE_NAME == 'example'
assert callable(m.search)
print('OK: discovered', len(mods), 'scraper(s)')
"
```

Expected: `OK: discovered 1 scraper(s)`

- [ ] **Step 4: Commit**

```bash
cd /home/dog/plugin.video.baldest_man
git add scrapers/__init__.py scrapers/example.py
git commit -m "feat: add scraper auto-discovery and example template"
```

---

### Task 2: Create scraper runner

**Files:**
- Create: `lib/__init__.py` (empty)
- Create: `lib/scraper_runner.py`

**Interfaces:**
- Consumes: `scrapers.get_scrapers()` from Task 1
- Produces: `scraper_runner.search_all(query: str) -> list[dict]` — flat list of validated result dicts from all scrapers

- [ ] **Step 1: Create empty `lib/__init__.py`**

```bash
touch /home/dog/plugin.video.baldest_man/lib/__init__.py
```

- [ ] **Step 2: Write `lib/scraper_runner.py`**

```python
"""Runs all scrapers against a query, collects and validates results."""
import sys
import traceback
import scrapers

REQUIRED_KEYS = {'show_title', 'episode', 'url'}


def search_all(query):
    """Run every scraper, return merged list of validated result dicts.

    Args:
        query: str — user's search term

    Returns:
        list[dict] — each dict has show_title, episode, url (and optionally title, quality)
    """
    if not query:
        return []

    results = []
    for mod in scrapers.get_scrapers():
        try:
            raw = mod.search(query)
        except Exception:
            # ponytail: bare except — don't let a broken scraper kill the whole search
            log_msg = "scraper_runner: {} crashed\n{}".format(
                mod.SITE_NAME, traceback.format_exc()
            )
            try:
                import xbmc
                xbmc.log(log_msg, level=xbmc.LOGERROR)
            except ImportError:
                print(log_msg, file=sys.stderr)
            continue

        if not isinstance(raw, list):
            continue

        for item in raw:
            if not isinstance(item, dict):
                continue
            if not REQUIRED_KEYS.issubset(item.keys()):
                continue
            item.setdefault('site', mod.SITE_NAME)
            item.setdefault('title', '')
            item.setdefault('quality', '')
            results.append(item)

    return results
```

- [ ] **Step 3: Verify runner with a self-check**

```bash
cd /home/dog/plugin.video.baldest_man && python3 -c "
from lib import scraper_runner

# Empty query returns empty list
assert scraper_runner.search_all('') == []
assert scraper_runner.search_all(None) == []

# Example scraper returns empty list, so any query returns empty
results = scraper_runner.search_all('naruto')
assert results == []
print('OK: runner handles empty query and empty scraper')
"
```

Expected: `OK: runner handles empty query and empty scraper`

- [ ] **Step 4: Commit**

```bash
cd /home/dog/plugin.video.baldest_man
git add lib/__init__.py lib/scraper_runner.py
git commit -m "feat: add scraper runner with validation and error handling"
```

---

### Task 3: Rewrite main.py for search-driven plugin

**Files:**
- Modify: `main.py` — replace entire file

**Interfaces:**
- Consumes: `lib.scraper_runner.search_all(query)` from Task 2
- Produces: Kodi plugin modes — root (search dialog), search (grouped show folders), episodes (playable items)

**URL param design:**
- `mode=None` — root, show search dialog
- `mode=search&q=<query>` — run scrapers, group by show, display folders
- `mode=episodes&q=<query>&show=<show_title>` — re-run search, filter by show, display playable episodes

- [ ] **Step 1: Write the new `main.py`**

```python
"""plugin.video.baldest_man — multi-site anime video scraper."""
import sys
import urllib.parse
# pyrefly: ignore [missing-import]
import xbmcgui
# pyrefly: ignore [missing-import]
import xbmcplugin

from lib import scraper_runner

base_url = sys.argv[0]
addon_handle = int(sys.argv[1])
args = urllib.parse.parse_qs(sys.argv[2][1:])

xbmcplugin.setContent(addon_handle, 'movies')


def build_url(query):
    """Build a plugin URL from a dict of params."""
    return base_url + '?' + urllib.parse.urlencode(query)


def label_episode(item):
    """Format episode label: Ep 01 The Strongest Hero 1080p"""
    parts = ['Ep', item['episode']]
    if item.get('title'):
        parts.append(item['title'])
    if item.get('quality'):
        parts.append(item['quality'])
    return ' '.join(parts)


mode = args.get('mode', None)

# --- Root: show search dialog ---
if mode is None:
    dialog = xbmcgui.Dialog()
    query = dialog.input('Search for anime', type=xbmcgui.INPUT_ALPHANUM)
    if query:
        url = build_url({'mode': 'search', 'q': query})
        xbmcplugin.addDirectoryItem(addon_handle, url,
                                    xbmcgui.ListItem('Search: ' + query),
                                    isFolder=True)
    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Search: run scrapers, group by show ---
elif mode[0] == 'search':
    query = args.get('q', [''])[0]
    results = scraper_runner.search_all(query)

    if not results:
        li = xbmcgui.ListItem("Nothing found for '" + query + "'")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)
        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

    else:
        # Group by show_title
        shows = {}
        for r in results:
            shows.setdefault(r['show_title'], []).append(r)

        for show_title in sorted(shows.keys()):
            url = build_url({'mode': 'episodes', 'q': query, 'show': show_title})
            li = xbmcgui.ListItem(show_title)
            xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Episodes: list playable items for a show ---
elif mode[0] == 'episodes':
    query = args.get('q', [''])[0]
    show_title = args.get('show', [''])[0]
    results = scraper_runner.search_all(query)

    episodes = [r for r in results if r['show_title'] == show_title]
    # Sort by episode number as integer
    episodes.sort(key=lambda r: int(r['episode']) if r['episode'].isdigit() else 0)

    for ep in episodes:
        li = xbmcgui.ListItem(label_episode(ep))
        li.setInfo('video', {'title': label_episode(ep)})
        li.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(addon_handle, ep['url'], li, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
```

- [ ] **Step 2: Verify Python syntax**

```bash
python3 -c "import py_compile; py_compile.compile('/home/dog/plugin.video.baldest_man/main.py', doraise=True); print('OK: syntax valid')"
```

Expected: `OK: syntax valid`

- [ ] **Step 3: Test in Kodi**

Install the addon and verify:
1. Open the addon → search dialog appears
2. Type a query → (empty results since example scraper returns [])
3. Test with a real scraper: drop a scraper file in `scrapers/`, re-open, search, browse shows, play an episode

- [ ] **Step 4: Commit**

```bash
cd /home/dog/plugin.video.baldest_man
git add main.py
git commit -m "feat: rewrite main.py with search, grouping, and episode listing"
```
