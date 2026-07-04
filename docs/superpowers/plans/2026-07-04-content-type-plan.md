# Content Type & Movie Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the root search dialog with a three-choice menu (Shows/Movies/All) and add first-class movie support with `is_movie` field and mixed search results display.

**Architecture:** Two files changed. `scrapers/example.py` documents the new `is_movie` field. `main.py` is rewritten with a new root menu, `content_type` param flowing through modes, and split show/movie display in search results. No backend changes — scraper_runner.py and alldebrid.py are untouched.

**Tech Stack:** Python 3, Kodi Matrix (`xbmcplugin`, `xbmcgui`, `xbmcaddon`)

## Global Constraints

- Episode labels: `Ep 01 The Strongest Hero 1080p`
- Movie labels: `Movie Title 1080p` (show_title + quality, no "Ep" prefix)
- `setProperty('IsPlayable', 'true')` on all playable items
- `cacheToDisc=False` on all `endOfDirectory` calls
- `setInfo('video', ...)` on all playable items
- `setResolvedUrl()` for all play URLs
- Shows sorted alphabetically by `show_title`
- Movies sorted alphabetically by `show_title`
- `is_movie=True` marks standalone movie (no episode field needed)
- `is_movie` absent or `False` means show episode (requires `show_title` + `episode`)
- `content_type` param values: `shows`, `movies`, `all`

---

### Task 1: Update example scraper with `is_movie` field

**Files:**
- Modify: `scrapers/example.py` — replace entire file

**Interfaces:**
- Produces: updated docstring — `is_movie` field documented, movie example shown

- [ ] **Step 1: Write updated `scrapers/example.py`**

```python
"""Example scraper — copy this file and fill in the blanks.

Return types:
  - "type": "torrent"   — magnet/torrent link, resolved via AllDebrid on play
  - "type": "direct" or omitted — direct video URL, played immediately

Content types:
  - Omit "is_movie" or set False — show episode (requires "episode" field)
  - "is_movie": True — standalone movie (no "episode" field needed)
"""
import requests

SITE_NAME = "example"


def search(query):
    """Return list of dicts with show_title, url, and optional fields.

    Show episode fields:
        show_title (str, required)
        episode   (str, required)  — episode number as string, e.g. "01"
        url       (str, required)  — magnet link or direct video URL
        type      (str, optional)  — "torrent" or "direct"; omit for direct
        title     (str, optional)  — episode title
        quality   (str, optional)  — e.g. "1080p", "720p"
        is_movie  (bool, optional) — omit or False for shows

    Movie fields:
        show_title (str, required)
        url        (str, required)
        is_movie   (bool, required) — True
        type       (str, optional)
        quality    (str, optional)
    """
    return [
        # Example show episode:
        # {
        #     "show_title": "One Punch Man",
        #     "episode": "01",
        #     "title": "The Strongest Man",
        #     "url": "magnet:?xt=urn:btih:deadbeefcafe...",
        #     "type": "torrent",
        #     "quality": "1080p",
        # },
        # Example movie:
        # {
        #     "show_title": "Your Name",
        #     "url": "magnet:?xt=urn:btih:beefdead...",
        #     "is_movie": True,
        #     "type": "torrent",
        #     "quality": "1080p",
        # },
    ]
```

- [ ] **Step 2: Verify scraper discovery still works**

```bash
cd /home/dog/plugin.video.baldest_man && python3 -c "
import scrapers
mods = scrapers.get_scrapers()
assert len(mods) >= 1, 'expected at least 1 scraper'
m = mods[0]
assert m.SITE_NAME == 'example'
assert callable(m.search)
print('OK: discovered', len(mods), 'scraper(s)')
"
```

Expected: `OK: discovered 1 scraper(s)`

- [ ] **Step 3: Commit**

```bash
git add scrapers/example.py
git commit -m "docs: add is_movie field and movie example to scraper template"
```

---

### Task 2: Rewrite main.py with root menu, content type, and movie support

**Files:**
- Modify: `main.py` — replace entire file

**Interfaces:**
- Consumes: `lib.scraper_runner.search_all(query)` — existing, unchanged
- Consumes: `lib.alldebrid.resolve(url, api_key)`, `AllDebridError` — existing, unchanged
- Consumes: `xbmcaddon.Addon().getSetting('alldebrid_api_key')` — existing, unchanged
- Produces: five modes — root (menu), search (filtered display), episodes, play (unchanged)

- [ ] **Step 1: Write new `main.py`**

```python
"""plugin.video.baldest_man — multi-site anime video scraper with AllDebrid."""
import sys
import urllib.parse
# pyrefly: ignore [missing-import]
import xbmcaddon
# pyrefly: ignore [missing-import]
import xbmcgui
# pyrefly: ignore [missing-import]
import xbmcplugin

from lib import scraper_runner
from lib.alldebrid import resolve as ad_resolve, AllDebridError

ADDON = xbmcaddon.Addon()
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


def label_movie(item):
    """Format movie label: Movie Title 1080p"""
    parts = [item['show_title']]
    if item.get('quality'):
        parts.append(item['quality'])
    return ' '.join(parts)


def add_playable_item(item, handle):
    """Add a playable listitem with play URL and IsPlayable set."""
    li = xbmcgui.ListItem()
    li.setInfo('video', {})
    li.setProperty('IsPlayable', 'true')
    ep_type = item.get('type', 'direct')
    play_url = build_url({'mode': 'play', 'url': item['url'], 'type': ep_type})
    xbmcplugin.addDirectoryItem(handle, play_url, li, isFolder=False)
    return li


def notify(msg):
    """Show a brief Kodi notification."""
    xbmcgui.Dialog().notification('bald_man', msg, xbmcgui.NOTIFICATION_INFO, 3000)


def api_key():
    return ADDON.getSetting('alldebrid_api_key')


mode = args.get('mode', None)

# --- Root: three-choice menu ---
if mode is None:
    for label, content_type in [
        ('Search Shows', 'shows'),
        ('Search Movies', 'movies'),
        ('Search All', 'all'),
    ]:
        url = build_url({'mode': 'search', 'content_type': content_type})
        xbmcplugin.addDirectoryItem(addon_handle, url,
                                    xbmcgui.ListItem(label), isFolder=True)
    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Search: dialog, then filtered display ---
elif mode[0] == 'search':
    content_type = args.get('content_type', ['all'])[0]

    dialog = xbmcgui.Dialog()
    query = dialog.input('Search for anime', type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

    else:
        results = scraper_runner.search_all(query)

        # Split results into shows and movies
        shows = {}
        movies = []
        for r in results:
            if r.get('is_movie'):
                movies.append(r)
            else:
                shows.setdefault(r['show_title'], []).append(r)

        # Filter by content_type
        show_movies = content_type in ('movies', 'all')
        show_shows = content_type in ('shows', 'all')

        if show_shows:
            for show_title in sorted(shows.keys()):
                url = build_url({'mode': 'episodes', 'q': query, 'show': show_title})
                li = xbmcgui.ListItem(show_title)
                xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        if show_movies:
            movies.sort(key=lambda r: r['show_title'])
            for m in movies:
                li = add_playable_item(m, addon_handle)
                li.setLabel(label_movie(m))
                li.setInfo('video', {'title': label_movie(m)})

        # Show "nothing found" if filtered results are empty
        total = (len(shows) if show_shows else 0) + (len(movies) if show_movies else 0)
        if total == 0:
            li = xbmcgui.ListItem("Nothing found for '" + query + "'")
            xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Episodes: list playable items for a show ---
elif mode[0] == 'episodes':
    query = args.get('q', [''])[0]
    show_title = args.get('show', [''])[0]
    results = scraper_runner.search_all(query)

    episodes = [r for r in results
                if r['show_title'] == show_title and not r.get('is_movie')]
    episodes.sort(key=lambda r: int(r['episode']) if r['episode'].isdigit() else 0)

    for ep in episodes:
        li = add_playable_item(ep, addon_handle)
        li.setLabel(label_episode(ep))
        li.setInfo('video', {'title': label_episode(ep)})

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

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

- [ ] **Step 2: Verify Python syntax**

```bash
python3 -c "import py_compile; py_compile.compile('/home/dog/plugin.video.baldest_man/main.py', doraise=True); print('OK: syntax valid')"
```

Expected: `OK: syntax valid`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add content type menu, is_movie support, mixed search display"
```
