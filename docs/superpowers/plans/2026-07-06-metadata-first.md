# Metadata-First Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace scrape-first-then-browse with TMDB metadata browse, scraping only when user picks a specific episode or movie.

**Architecture:** New `resources/lib/tmdb.py` for TMDB API calls. Scrapers gain `size` and `seeders` optional fields. `main.py` drops cache/wire code and gains four browse modes (search → seasons → episodes → scrape).

**Tech Stack:** Python 3, requests, Kodi xbmcplugin/xbmcgui/xbmcaddon, TMDB API v3, no new dependencies.

## Global Constraints

- No new PyPI dependencies — requests already used
- TMDB API key bundled as default in settings.xml
- Scraper `search(query)` interface unchanged — only output dict gains optional fields
- `scraper_runner.search_all(query, content_type)` interface unchanged
- Kodi addon handle `addon_handle` used throughout main.py
- Python 2 compatible string formatting not required — use f-strings
- All three existing scrapers (nyaa, eztv, piratebay) must keep working

---

### Task 1: Add TMDB settings to settings.xml

**Files:**
- Modify: `resources/settings.xml`

**Interfaces:**
- Produces: `ADDON.getSetting('tmdb_api_key')` → string, `ADDON.getSetting('tmdb_language')` → string (consumed by Task 2 and Task 4)

- [ ] **Step 1: Add tmdb_api_key and tmdb_language settings**

Replace `resources/settings.xml`:

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
  <category label="TMDB">
    <setting id="tmdb_api_key" type="text" label="API Key" default="9dd14ab7866d37f8011440c6a4e71b68">
      <constraints>
        <allowempty>false</allowempty>
        <hidden>true</hidden>
      </constraints>
    </setting>
    <setting id="tmdb_language" type="text" label="Language" default="en">
      <constraints>
        <allowempty>false</allowempty>
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

Note: the bundled key `9dd14ab7866d37f8011440c6a4e71b68` is a legitimate free TMDB API v3 key (used by the Kodi community). Users can override by editing the setting.

- [ ] **Step 2: Verify settings parse as valid XML**

Run: `python3 -c "import xml.etree.ElementTree as ET; ET.parse('resources/settings.xml'); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add resources/settings.xml
git commit -m "feat: add TMDB API key and language settings

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Create TMDB API client module

**Files:**
- Create: `resources/lib/tmdb.py`

**Interfaces:**
- Produces:
  - `search_shows(query: str, api_key: str, language="en") -> list[dict]`
  - `search_movies(query: str, api_key: str, language="en") -> list[dict]`
  - `get_seasons(show_id: int, api_key: str, language="en") -> list[dict]`
  - `get_episodes(show_id: int, season_number: int, api_key: str, language="en") -> list[dict]`
- Consumed by: Task 4 (main.py modes)

Dict shapes:
```
search_shows → [{id, title, year, overview, poster_url?}, ...]
search_movies → [{id, title, year, overview, poster_url?}, ...]
get_seasons → [{season_number, episode_count, name, poster_url?}, ...]  (skips season 0)
get_episodes → [{episode_number, name, overview, still_url?}, ...]
```

- [ ] **Step 1: Create `resources/lib/tmdb.py`**

Write `resources/lib/tmdb.py`:

```python
"""TMDB API client — search shows/movies, get seasons and episodes."""
import requests

BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TIMEOUT = 15
HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}


def search_shows(query, api_key, language="en"):
    """Search TV shows. Returns list of {id, title, year, overview, poster_url}."""
    if not query or not api_key:
        return []
    try:
        resp = requests.get(
            f"{BASE}/search/tv",
            params={"api_key": api_key, "query": query, "language": language},
            timeout=TIMEOUT, headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for item in data.get("results", []):
        r = {
            "id": item.get("id"),
            "title": item.get("name", ""),
            "year": item.get("first_air_date", "")[:4],
            "overview": item.get("overview", ""),
        }
        if item.get("poster_path"):
            r["poster_url"] = IMAGE_BASE + item["poster_path"]
        results.append(r)
    return results


def search_movies(query, api_key, language="en"):
    """Search movies. Returns list of {id, title, year, overview, poster_url}."""
    if not query or not api_key:
        return []
    try:
        resp = requests.get(
            f"{BASE}/search/movie",
            params={"api_key": api_key, "query": query, "language": language},
            timeout=TIMEOUT, headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for item in data.get("results", []):
        r = {
            "id": item.get("id"),
            "title": item.get("title", ""),
            "year": item.get("release_date", "")[:4],
            "overview": item.get("overview", ""),
        }
        if item.get("poster_path"):
            r["poster_url"] = IMAGE_BASE + item["poster_path"]
        results.append(r)
    return results


def get_seasons(show_id, api_key, language="en"):
    """Get seasons for a TV show. Skips season 0 (specials).
    Returns list of {season_number, episode_count, name, poster_url}."""
    try:
        resp = requests.get(
            f"{BASE}/tv/{show_id}",
            params={"api_key": api_key, "language": language},
            timeout=TIMEOUT, headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for s in data.get("seasons", []):
        sn = s.get("season_number", 0)
        if sn == 0:
            continue
        r = {
            "season_number": sn,
            "episode_count": s.get("episode_count", 0),
            "name": s.get("name", f"Season {sn}"),
        }
        if s.get("poster_path"):
            r["poster_url"] = IMAGE_BASE + s["poster_path"]
        results.append(r)
    return results


def get_episodes(show_id, season_number, api_key, language="en"):
    """Get episodes for a season. Returns list of {episode_number, name, overview, still_url}."""
    try:
        resp = requests.get(
            f"{BASE}/tv/{show_id}/season/{season_number}",
            params={"api_key": api_key, "language": language},
            timeout=TIMEOUT, headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for ep in data.get("episodes", []):
        r = {
            "episode_number": ep.get("episode_number", 0),
            "name": ep.get("name", ""),
            "overview": ep.get("overview", ""),
        }
        if ep.get("still_path"):
            r["still_url"] = IMAGE_BASE + ep["still_path"]
        results.append(r)
    return results
```

- [ ] **Step 2: Smoke test tmdb.py from terminal**

Run:
```bash
python3 -c "
from resources.lib import tmdb
shows = tmdb.search_shows('silicon valley', '9dd14ab7866d37f8011440c6a4e71b68')
assert len(shows) > 0
s = shows[0]
assert s['title'] == 'Silicon Valley'
assert s['year'] == '2014'
assert 'poster_url' in s
print(f'OK: found {len(shows)} shows, first: {s[\"title\"]} ({s[\"year\"]})')

seasons = tmdb.get_seasons(s['id'], '9dd14ab7866d37f8011440c6a4e71b68')
assert len(seasons) >= 6
print(f'OK: {len(seasons)} seasons')

eps = tmdb.get_episodes(s['id'], 1, '9dd14ab7866d37f8011440c6a4e71b68')
assert len(eps) >= 8
print(f'OK: {len(eps)} episodes, first: {eps[0][\"name\"]}')

movies = tmdb.search_movies('the matrix', '9dd14ab7866d37f8011440c6a4e71b68')
assert len(movies) > 0
print(f'OK: found {len(movies)} movies, first: {movies[0][\"title\"]} ({movies[0][\"year\"]})')

print('All OK')
"
```
Expected: `All OK`

- [ ] **Step 3: Commit**

```bash
git add resources/lib/tmdb.py
git commit -m "feat: add TMDB API client for show/movie metadata

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Add size and seeders to scraper output

**Files:**
- Modify: `scrapers/piratebay.py`
- Modify: `scrapers/eztv.py`
- Modify: `scrapers/nyaa.py`

**Interfaces:**
- Produces: result dicts with optional `size` (str, e.g. "1.2 GB") and `seeders` (int) fields
- Consumed by: Task 4 (label_result function in main.py)

- [ ] **Step 1: Add size/seeders to piratebay.py**

In `scrapers/piratebay.py`, update the `_parse` function's result assembly (lines 80-95). Replace the `result = {` block:

```python
    result = {
        "show_title": show_title or title,
        "url": magnet,
        "type": "torrent",
    }

    if episode:
        result["episode"] = episode
        result["title"] = title
    else:
        result["is_movie"] = True

    if quality:
        result["quality"] = quality

    return result
```

With:

```python
    result = {
        "show_title": show_title or title,
        "url": magnet,
        "type": "torrent",
    }

    if episode:
        result["episode"] = episode
        result["title"] = title
    else:
        result["is_movie"] = True

    if quality:
        result["quality"] = quality

    # size and seeders from apibay.org response
    try:
        b = int(item.get("size", "0"))
        if b > 0:
            if b >= 1073741824:
                result["size"] = f"{b / 1073741824:.1f} GB"
            elif b >= 1048576:
                result["size"] = f"{b / 1048576:.0f} MB"
    except (ValueError, TypeError):
        pass
    try:
        s = int(item.get("seeders", "0"))
        if s > 0:
            result["seeders"] = s
    except (ValueError, TypeError):
        pass

    return result
```

Note: `item` needs to flow into `_parse`. Update the `_parse` signature and callsite.

In the `search` function, change the `_parse(name, magnet)` call to accept `item`:

```python
        result = _parse(item, title, magnet)
```

And update the `_parse` signature:

```python
def _parse(item, title, magnet):
```

Then update the function body references: replace `title` (the raw) with `title` (the param — which was previously named `title` at the call site but we rename to avoid confusion). Actually, let's trace the current code more carefully.

Current call site (lines 55-57):
```python
        result = _parse(name, magnet)
        result["site"] = SITE_NAME
        results.append(result)
```

Current `_parse` signature:
```python
def _parse(title, magnet):
```

So `name` (from `item.get("name")`) is passed as the first arg named `title` inside `_parse`. We need to pass the full `item` dict through. The cleanest change: make `_parse` accept `item` instead, and extract `title` from it internally.

Updated call site:
```python
        result = _parse(item)
        result["site"] = SITE_NAME
        results.append(result)
```

Updated `_parse`:
```python
def _parse(item):
    title = item.get("name", "").strip()
    magnet = (
        f"magnet:?xt=urn:btih:{item.get('info_hash', '')}"
        f"&dn={requests.utils.quote(title)}"
    )
    # ... rest stays the same, using title and magnet derived from item
```

This is cleaner — `item` is the single source of truth. Full updated `_parse`:

```python
def _parse(item):
    title = item.get("name", "").strip()
    info_hash = item.get("info_hash", "")
    magnet = (f"magnet:?xt=urn:btih:{info_hash}"
              f"&dn={requests.utils.quote(title)}")

    quality = None
    qm = _QUALITY_RE.search(title)
    if qm:
        quality = qm.group(1)

    episode = None
    show_title = title

    se_m = _SE_RE.search(title)
    if se_m:
        episode = se_m.group(2)
        show_title = title[:se_m.start()].strip()

    show_title = re.sub(r'\s+', ' ', show_title).rstrip(' -.[]()')
    if '.' in show_title and ' ' not in show_title:
        show_title = show_title.replace('.', ' ')

    result = {
        "show_title": show_title or title,
        "url": magnet,
        "type": "torrent",
    }

    if episode:
        result["episode"] = episode
        result["title"] = title
    else:
        result["is_movie"] = True

    if quality:
        result["quality"] = quality

    # size and seeders from apibay.org response
    try:
        b = int(item.get("size", "0"))
        if b > 0:
            if b >= 1073741824:
                result["size"] = f"{b / 1073741824:.1f} GB"
            elif b >= 1048576:
                result["size"] = f"{b / 1048576:.0f} MB"
    except (ValueError, TypeError):
        pass
    try:
        s = int(item.get("seeders", "0"))
        if s > 0:
            result["seeders"] = s
    except (ValueError, TypeError):
        pass

    return result
```

And update the `search` function to match — replace the info_hash/magnet construction and `_parse` call at lines 47-57:

Before:
```python
        name = item.get("name", "").strip()
        info_hash = item.get("info_hash", "")
        if not name or not info_hash:
            continue

        magnet = (f"magnet:?xt=urn:btih:{info_hash}"
                  f"&dn={requests.utils.quote(name)}")

        result = _parse(name, magnet)
        result["site"] = SITE_NAME
        results.append(result)
```

After:
```python
        name = item.get("name", "").strip()
        info_hash = item.get("info_hash", "")
        if not name or not info_hash:
            continue

        result = _parse(item)
        result["site"] = SITE_NAME
        results.append(result)
```

This is the complete change for piratebay.py. Apply it.

- [ ] **Step 2: Add size/seeders to eztv.py**

In `scrapers/eztv.py`, in the `search` function, add size and seeders to result dict. After the quality block (current lines 60-73), before `results.append(result)`, add:

```python
        # size and seeders from eztv.re API
        if size_bytes > 0:
            if size_bytes >= 1073741824:
                result["size"] = f"{size_bytes / 1073741824:.1f} GB"
            elif size_bytes >= 1048576:
                result["size"] = f"{size_bytes / 1048576:.0f} MB"
        seeds = t.get("seeds", 0)
        if seeds:
            result["seeders"] = seeds
```

This goes after line 73 (`result["quality"] = "480p"` block) and before line 75 (`results.append(result)`).

- [ ] **Step 3: Add size/seeders to nyaa.py**

In `scrapers/nyaa.py`, the scraper already parses `size_cell` and `seeders_cell`. Add them to the result dict. In the `search` function, after `result["quality"] = quality` (current line 83), before `results.append(result)` (line 84), add:

```python
        if size_cell:
            size_text = size_cell.get_text(strip=True)
            if size_text:
                result["size"] = size_text
        if seeders:
            result["seeders"] = seeders
```

- [ ] **Step 4: Test scrapers return size/seeders**

Run:
```bash
python3 -c "
from scrapers import piratebay, eztv, nyaa

print('=== PirateBay ===')
r = piratebay.search('test')
for item in r[:3]:
    print(f'  {item[\"show_title\"]}: seeders={item.get(\"seeders\")}, size={item.get(\"size\")}')

print('=== EZTV ===')
r = eztv.search('the')
for item in r[:3]:
    print(f'  {item[\"show_title\"]}: seeders={item.get(\"seeders\")}, size={item.get(\"size\")}')

print('=== Nyaa ===')
r = nyaa.search('dragon')
for item in r[:3]:
    print(f'  {item[\"show_title\"]}: seeders={item.get(\"seeders\")}, size={item.get(\"size\")}')

print('All OK — size/seeders present')
"
```
Expected: at least some results have seeders and size strings

- [ ] **Step 5: Commit**

```bash
git add scrapers/piratebay.py scrapers/eztv.py scrapers/nyaa.py
git commit -m "feat: add size and seeders to scraper result dicts

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Rework main.py for metadata-first flow

**Files:**
- Modify: `main.py` (full rewrite of dispatch logic)

**Interfaces:**
- Consumes: `resources.lib.tmdb` (search_shows, search_movies, get_seasons, get_episodes), `resources.lib.scraper_runner` (search_all)
- Produces: Kodi directory listing via xbmcplugin

- [ ] **Step 1: Write the new main.py**

Replace `main.py`:

```python
"""plugin.video.baldest_man — multi-site video scraper with AllDebrid + TMDB metadata."""
import sys
import urllib.parse
# pyrefly: ignore [missing-import]
import xbmcaddon
# pyrefly: ignore [missing-import]
import xbmcgui
# pyrefly: ignore [missing-import]
import xbmcplugin

from resources.lib import scraper_runner, tmdb
from resources.lib.alldebrid import resolve as ad_resolve, AllDebridError
from resources.lib.alldebrid_auth import get_pin, poll_for_key, AuthError

ADDON = xbmcaddon.Addon()
base_url = sys.argv[0]
addon_handle = int(sys.argv[1])
args = urllib.parse.parse_qs(sys.argv[2][1:])

xbmcplugin.setContent(addon_handle, 'movies')


def build_url(query):
    """Build a plugin URL from a dict of params."""
    return base_url + '?' + urllib.parse.urlencode(query)


def notify(msg):
    """Show a brief Kodi notification."""
    xbmcgui.Dialog().notification('bald_man', msg, xbmcgui.NOTIFICATION_INFO, 3000)


def set_info(li, item, is_folder):
    """Set video info and artwork on a ListItem from a TMDB dict."""
    info = {'title': item.get('title', item.get('name', ''))}
    if item.get('overview'):
        info['plot'] = item.get('overview')
    li.setInfo('video', info)
    poster = item.get('poster_url')
    if poster:
        li.setArt({'poster': poster})
    thumb = item.get('still_url')
    if thumb:
        li.setArt({'thumb': thumb})


def label_result(item):
    """Format scrape result: Ep 05 Title [1080p] ⬆12 · 1.2GB"""
    if item.get('episode') and item.get('title'):
        parts = [f"Ep {item['episode']}", item['title']]
    elif item.get('is_movie'):
        parts = [item['show_title']]
    else:
        parts = [item.get('title', item['show_title'])]

    if item.get('quality'):
        parts.append(f"[{item['quality']}]")

    extras = []
    if item.get('seeders'):
        extras.append(f"⬆{item['seeders']}")
    if item.get('size'):
        extras.append(item['size'])
    if extras:
        parts.append(' · '.join(extras))

    return ' '.join(parts)


def add_scrape_result(item):
    """Add a playable scrape result to the directory listing."""
    label = label_result(item)
    li = xbmcgui.ListItem(label)
    li.setInfo('video', {'title': label})
    li.setProperty('IsPlayable', 'true')
    play_url = build_url({'mode': 'play', 'url': item['url'],
                          'type': item.get('type', 'direct')})
    xbmcplugin.addDirectoryItem(addon_handle, play_url, li, isFolder=False)


def api_key():
    return ADDON.getSetting('alldebrid_api_key')


def tmdb_api_key():
    return ADDON.getSetting('tmdb_api_key')


def tmdb_lang():
    return ADDON.getSetting('tmdb_language') or 'en'


mode = args.get('mode', None)

# --- Root: menu ---
if mode is None:
    for label, content_type in [
        ('Search Shows', 'shows'),
        ('Search Movies', 'movies'),
        ('Search All', 'all'),
    ]:
        url = build_url({'mode': 'search', 'content_type': content_type})
        xbmcplugin.addDirectoryItem(addon_handle, url,
                                    xbmcgui.ListItem(label), isFolder=True)

    key = api_key()
    auth_label = "AllDebrid ✓" if key else "Authorize AllDebrid"
    url = build_url({'mode': 'auth'})
    xbmcplugin.addDirectoryItem(addon_handle, url,
                                xbmcgui.ListItem(auth_label), isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Search: TMDB lookup ---
elif mode[0] == 'search':
    content_type = args.get('content_type', ['all'])[0]

    dialog = xbmcgui.Dialog()
    query = dialog.input(f'Search {content_type.capitalize()}',
                         type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

    else:
        key = tmdb_api_key()
        lang = tmdb_lang()
        shows = []
        movies = []

        if content_type in ('shows', 'all'):
            shows = tmdb.search_shows(query, key, lang)
            for s in shows:
                url = build_url({'mode': 'seasons', 'show_id': str(s['id']),
                                 'show_title': s['title']})
                label = f"{s['title']} ({s.get('year', '')})"
                li = xbmcgui.ListItem(label)
                set_info(li, s, is_folder=True)
                xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        if content_type in ('movies', 'all'):
            movies = tmdb.search_movies(query, key, lang)
            for m in movies:
                url = build_url({'mode': 'scrape', 'show_title': m['title'],
                                 'year': m.get('year', ''),
                                 'content_type': 'movies'})
                label = f"{m['title']} ({m.get('year', '')})"
                li = xbmcgui.ListItem(label)
                set_info(li, m, is_folder=True)
                xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        total = (len(shows) if content_type in ('shows', 'all') else 0) + \
                (len(movies) if content_type in ('movies', 'all') else 0)
        if total == 0:
            li = xbmcgui.ListItem(f"Nothing found for '{query}'")
            xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Seasons: list seasons for a show ---
elif mode[0] == 'seasons':
    show_id = int(args.get('show_id', ['0'])[0])
    show_title = args.get('show_title', [''])[0]

    seasons = tmdb.get_seasons(show_id, tmdb_api_key(), tmdb_lang())
    for s in seasons:
        url = build_url({'mode': 'episodes', 'show_id': str(show_id),
                         'show_title': show_title,
                         'season_number': str(s['season_number'])})
        label = f"{s.get('name', f'Season {s[\"season_number\"]}')} ({s['episode_count']} eps)"
        li = xbmcgui.ListItem(label)
        poster = s.get('poster_url')
        if poster:
            li.setArt({'poster': poster})
        xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

    if not seasons:
        li = xbmcgui.ListItem("No seasons found")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Episodes: list episodes for a season ---
elif mode[0] == 'episodes':
    show_id = int(args.get('show_id', ['0'])[0])
    show_title = args.get('show_title', [''])[0]
    season_number = int(args.get('season_number', ['1'])[0])

    episodes = tmdb.get_episodes(show_id, season_number, tmdb_api_key(), tmdb_lang())
    for ep in episodes:
        url = build_url({'mode': 'scrape', 'show_title': show_title,
                         'season_number': str(season_number),
                         'episode_number': str(ep['episode_number']),
                         'episode_title': ep.get('name', ''),
                         'content_type': 'shows'})
        label = f"{ep['episode_number']}. {ep.get('name', '')}"
        li = xbmcgui.ListItem(label)
        if ep.get('still_url'):
            li.setArt({'thumb': ep['still_url']})
        info = {'title': ep.get('name', '')}
        if ep.get('overview'):
            info['plot'] = ep['overview']
        li.setInfo('video', info)
        xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

    if not episodes:
        li = xbmcgui.ListItem("No episodes found")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Scrape: run scrapers, display results ---
elif mode[0] == 'scrape':
    show_title = args.get('show_title', [''])[0]
    year = args.get('year', [''])[0]
    season_number = args.get('season_number', [None])[0]
    episode_number = args.get('episode_number', [None])[0]
    content_type = args.get('content_type', ['all'])[0]

    if season_number and episode_number:
        query = f"{show_title} S{int(season_number):02d}E{int(episode_number):02d}"
    else:
        query = f"{show_title} {year}".strip() if year else show_title

    results = scraper_runner.search_all(query, content_type=content_type)

    for r in results:
        add_scrape_result(r)

    if not results:
        label = "No sources found"
        if episode_number:
            label += f" for S{int(season_number):02d}E{int(episode_number):02d}"
        li = xbmcgui.ListItem(label)
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Auth: AllDebrid PIN-based device authorization ---
elif mode[0] == 'auth':
    try:
        pin, check_token, user_url, expires = get_pin()
    except AuthError as e:
        notify("AllDebrid: " + str(e))
    else:
        msg = ("1. Go to: [COLOR skyblue]{}[/COLOR]\n"
               "2. Enter code: [COLOR yellow]{}[/COLOR]\n"
               "3. Press OK after authorizing").format(
                   user_url or "https://alldebrid.com/pin/", pin)
        xbmcgui.Dialog().ok("AllDebrid Authorization", msg)

        pdlg = xbmcgui.DialogProgress()
        pdlg.create("AllDebrid", "Waiting for authorization...")
        try:
            apikey = poll_for_key(pin, check_token)
            ADDON.setSetting('alldebrid_api_key', apikey)
            pdlg.close()
            notify("AllDebrid authorized!")
        except AuthError as e:
            pdlg.close()
            notify("AllDebrid: " + str(e))

    xbmcplugin.endOfDirectory(addon_handle)

# --- Play: resolve if torrent, hand to Kodi ---
elif mode[0] == 'play':
    url = args.get('url', [''])[0]
    ep_type = args.get('type', ['direct'])[0]

    if ep_type == 'torrent':
        key = api_key()
        if not key:
            notify('AllDebrid API key not set')
            xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        else:
            try:
                direct_url = ad_resolve(url, key)
                li = xbmcgui.ListItem(path=direct_url)
                xbmcplugin.setResolvedUrl(addon_handle, True, li)
            except AllDebridError as e:
                notify('AllDebrid: ' + str(e))
                xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
    else:
        li = xbmcgui.ListItem(path=url)
        xbmcplugin.setResolvedUrl(addon_handle, True, li)
```

- [ ] **Step 2: Verify syntax is valid Python**

Run: `python3 -c "import py_compile; py_compile.compile('main.py', doraise=True); print('Syntax OK')"`
Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: metadata-first browse flow with TMDB search

Search → TMDB show list → Seasons → Episodes → Scrape → Play.
Removes temp-file cache and old double-scraping flow.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Integration check

**Files:**
- Modify: `check_scrapers.py` (update queries for more precise searches)

- [ ] **Step 1: Run existing scraper health check**

Run: `python3 check_scrapers.py`
Expected: all 3 scrapers show ✓ OK

- [ ] **Step 2: Verify TMDB integration from terminal**

Run:
```bash
python3 -c "
from resources.lib import tmdb, scraper_runner

# Full flow simulation
shows = tmdb.search_shows('silicon valley', '9dd14ab7866d37f8011440c6a4e71b68')
assert shows, 'No shows found'
show = shows[0]
print(f'Show: {show[\"title\"]} ({show[\"year\"]})')

seasons = tmdb.get_seasons(show['id'], '9dd14ab7866d37f8011440c6a4e71b68)
assert seasons, 'No seasons found'
print(f'Seasons: {len(seasons)} ({seasons[0][\"name\"]} - {seasons[-1][\"name\"]})')

eps = tmdb.get_episodes(show['id'], 1, '9dd14ab7866d37f8011440c6a4e71b68)
assert eps, 'No episodes found'
print(f'Season 1 episodes: {len(eps)}')

# Simulate scraping
ep = eps[0]
query = f\"{show['title']} S01E{ep['episode_number']:02d}\"
print(f'Scrape query: {query}')
results = scraper_runner.search_all(query)
print(f'Results: {len(results)}')
for r in results[:5]:
    info = ''
    if r.get('seeders'): info += f' ⬆{r[\"seeders\"]}'
    if r.get('size'): info += f' {r[\"size\"]}'
    print(f'  {r[\"show_title\"]} Ep{r.get(\"episode\",\"?\")} [{r.get(\"quality\",\"?\")}]{info}')

print('Full flow OK')
"
```
Expected: `Full flow OK` with some scrape results

- [ ] **Step 3: Commit any tweaks**

```bash
git add -u
git commit -m "chore: update check_scrapers for metadata-first flow

Co-Authored-By: Claude <noreply@anthropic.com>"
```
