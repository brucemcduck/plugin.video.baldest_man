# Clean Scrape Results UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-blob text labels on scrape results with structured Kodi ListItem metadata + TMDB poster artwork.

**Architecture:** Add `get_poster()` to tmdb.py for poster lookup. Rewrite `label_result()`, `add_scrape_result()` in main.py to set proper `setInfo()` fields (title, plot, mediatype, size) and `setArt()` (poster). Scrape mode fetches poster once and passes it to each result.

**Tech Stack:** Python 3, Kodi xbmcplugin/xbmcgui, requests, TMDB API.

## Global Constraints

- No new PyPI dependencies
- Scraper modules untouched
- `scraper_runner.search_all()` interface unchanged
- Browse modes (search, seasons, episodes) keep existing `set_info()` helper
- Auth and play modes unchanged
- TMDB API key bundled in settings.xml

---

### Task 1: Add `get_poster()` to tmdb.py

**Files:**
- Modify: `resources/lib/tmdb.py`

**Interfaces:**
- Produces: `get_poster(show_id: int, api_key: str, is_movie=False) -> str | None`
- Consumed by: Task 2 (main.py scrape mode)

- [ ] **Step 1: Add `get_poster()` function**

In `resources/lib/tmdb.py`, after `get_imdb_id()` and before `get_episodes()`, insert:

```python
def get_poster(show_id, api_key, is_movie=False):
    """Return poster URL for a show/movie, or None on failure."""
    media_type = "movie" if is_movie else "tv"
    try:
        data = _tmdb_get(f"{BASE}/{media_type}/{show_id}",
                         {"api_key": api_key})
        path = data.get("poster_path")
        return IMAGE_BASE + path if path else None
    except Exception:
        return None
```

- [ ] **Step 2: Smoke test from terminal**

Run:
```bash
python3 -c "
from resources.lib import tmdb
key = 'f090bb54758cabf231fb605d3e3e0468'
# TV show
poster = tmdb.get_poster(63351, key, is_movie=False)
assert poster and poster.startswith('https://image.tmdb.org/t/p/w500/'), f'Bad poster: {poster}'
print(f'TV poster: {poster[:60]}...')
# Movie
poster = tmdb.get_poster(603, key, is_movie=True)
assert poster and poster.startswith('https://image.tmdb.org/t/p/w500/'), f'Bad poster: {poster}'
print(f'Movie poster: {poster[:60]}...')
# Bad ID
bad = tmdb.get_poster(99999999, key, is_movie=False)
assert bad is None
print('Bad ID: None (correct)')
print('All OK')
"
```
Expected: `All OK`

- [ ] **Step 3: Commit**

```bash
git add resources/lib/tmdb.py
git commit -m "feat: add get_poster() to tmdb.py

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Rewrite scrape result display in main.py

**Files:**
- Modify: `main.py`

**Interfaces:**
- Consumes: `tmdb.get_poster()` (Task 1), existing scrape result dicts
- Produces: Kodi ListItems with structured metadata + artwork

- [ ] **Step 1: Add `import re` to main.py imports**

In `main.py`, change the imports block (currently `import sys` / `import urllib.parse`):

```python
"""plugin.video.baldest_man — multi-site video scraper with AllDebrid + TMDB metadata."""
import re
import sys
import urllib.parse
```

All existing imports stay below these.

- [ ] **Step 2: Replace `label_result()` with clean version**

Replace the current `label_result` function (lines 48-68) with:

```python
def label_result(item):
    """Format scrape result label: S01E05 · Episode Name  or  Movie Title (1999)."""
    if item.get('episode'):
        parts = [f"S{int(item.get('season', '01')):02d}E{int(item['episode']):02d}"]
        if item.get('title'):
            parts.append(item['title'])
    elif item.get('is_movie'):
        parts = [item['show_title']]
    else:
        parts = [item.get('title', item['show_title'])]
    return ' · '.join(parts)
```

Note: `item.get('season', '01')` — scrapers don't currently set `season` in result dicts. The `SxxEyy` format needs season number. We'll derive it: if `episode` is present, pull season from the scrape URL params... actually, simpler: just pass `season` through the item dict or use `01` as fallback. The Torrentio scraper results have episode but no season in the dict. The scrape mode has `season_number` as a local variable.

Simplest fix: in scrape mode, add `season_number` to each item dict before passing to `add_scrape_result`:

```python
    for r in results:
        if season_number and 'episode' in r and 'season' not in r:
            r['season'] = season_number
        add_scrape_result(r, poster_url)
```

This goes in scrape mode, right before the `for r in results` loop. Include this in Step 4.

- [ ] **Step 3: Add `_parse_size_bytes()` helper**

After `label_result()`, add:

```python
def _parse_size_bytes(size_str):
    """Parse human-readable size string to bytes for Kodi. Returns int or 0."""
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
```

- [ ] **Step 4: Replace `add_scrape_result()` with structured metadata version**

Replace the current `add_scrape_result` function (lines 71-79) with:

```python
def add_scrape_result(item, poster_url=None):
    """Add a playable scrape result with structured metadata and artwork."""
    label = label_result(item)
    li = xbmcgui.ListItem(label)
    li.setProperty('IsPlayable', 'true')

    info = {
        'title': label,
        'mediatype': 'episode' if item.get('episode') else 'movie',
    }

    # Plot: stats shown in Media Info view
    plot_parts = []
    if item.get('quality'):
        plot_parts.append(item['quality'])
    if item.get('seeders'):
        plot_parts.append(f"⬆{item['seeders']} seeders")
    if item.get('size'):
        plot_parts.append(item['size'])
    plot_parts.append(f"source: {item.get('site', '?')}")
    info['plot'] = ' · '.join(plot_parts)

    # Size in bytes (Kodi auto-formats in UI)
    size_str = item.get('size', '')
    if size_str:
        info['size'] = _parse_size_bytes(size_str)

    li.setInfo('video', info)

    # Poster from TMDB parent show/movie
    if poster_url:
        li.setArt({'poster': poster_url, 'thumb': poster_url})

    play_url = build_url({'mode': 'play', 'url': item['url'],
                          'type': item.get('type', 'direct')})
    xbmcplugin.addDirectoryItem(addon_handle, play_url, li, isFolder=False)
```

- [ ] **Step 5: Update scrape mode — add poster fetch + season injection**

In the scrape mode section, after the Torrentio merge block (after `results.extend(tr)` inside the `if show_id:` try-block, and the `except Exception: pass`), and before `for r in results:`, add poster lookup and season injection:

```python
    # TMDB poster for artwork on every result
    poster_url = None
    if show_id:
        try:
            poster_url = tmdb.get_poster(int(show_id), tmdb_api_key(),
                                         is_movie=(content_type == 'movies'))
        except Exception:
            pass

    for r in results:
        if season_number and 'episode' in r and 'season' not in r:
            r['season'] = season_number
        add_scrape_result(r, poster_url)
```

This replaces the existing:
```python
    for r in results:
        add_scrape_result(r)
```

- [ ] **Step 6: Verify syntax**

Run:
```bash
python3 -c "import py_compile; py_compile.compile('main.py', doraise=True); print('Syntax OK')"
```
Expected: `Syntax OK`

- [ ] **Step 7: Terminal smoke test — verify helpers work**

Run:
```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from resources.lib import tmdb

# Test _parse_size_bytes
import re
def _parse_size_bytes(s):
    m = re.match(r'([\d.]+)\s*(GB|MB|GiB|MiB|KB|B)', str(s), re.IGNORECASE)
    if not m: return 0
    val, unit = float(m.group(1)), m.group(2).upper()
    if unit in ('GB', 'GIB'): return int(val * 1073741824)
    if unit in ('MB', 'MIB'): return int(val * 1048576)
    if unit == 'KB': return int(val * 1024)
    return int(val)

assert _parse_size_bytes('1.5 GB') == 1610612736
assert _parse_size_bytes('469 MB') == 491782144
assert _parse_size_bytes('1.2 GiB') == 1288490188
assert _parse_size_bytes('') == 0
print(f'1.5 GB -> {_parse_size_bytes(\"1.5 GB\")} bytes')
print(f'469 MB -> {_parse_size_bytes(\"469 MB\")} bytes')
print('Size parsing OK')

# Test label_result
def label_result(item):
    if item.get('episode'):
        parts = [f\"S{int(item.get('season', '01')):02d}E{int(item['episode']):02d}\"]
        if item.get('title'):
            parts.append(item['title'])
    elif item.get('is_movie'):
        parts = [item['show_title']]
    else:
        parts = [item.get('title', item['show_title'])]
    return ' · '.join(parts)

ep = {'episode': '01', 'season': '01', 'title': 'Minimum Viable Product'}
assert label_result(ep) == 'S01E01 · Minimum Viable Product'
mov = {'show_title': 'The Matrix', 'is_movie': True}
assert label_result(mov) == 'The Matrix'
print(f'Episode label: {label_result(ep)}')
print(f'Movie label: {label_result(mov)}')
print('Labels OK')

# Test poster 
key = 'f090bb54758cabf231fb605d3e3e0468'
poster = tmdb.get_poster(603, key, is_movie=True)
assert poster, 'No poster!'
print(f'Poster URL: {poster[:50]}...')
print('All OK')
"
```
Expected: `All OK`

- [ ] **Step 8: Commit**

```bash
git add main.py
git commit -m "feat: clean scrape results UI with structured metadata and posters

Short labels, Kodi info panel fills from structured metadata,
TMDB poster artwork on every result.

Co-Authored-By: Claude <noreply@anthropic.com>"
```
