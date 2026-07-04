# AllDebrid Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AllDebrid torrent/magnet resolution so scrapers can return torrent links that get resolved to direct streamable URLs on playback.

**Architecture:** Three new/modified files. `resources/settings.xml` stores the API key. `lib/alldebrid.py` wraps the AllDebrid API v4.1. `main.py` gains a `mode=play` that invokes resolution then hands the direct URL to Kodi. `scrapers/example.py` is updated to show the torrent pattern.

**Tech Stack:** Python 3, AllDebrid API v4.1, Kodi `xbmcaddon`, `xbmcplugin.setResolvedUrl()`

## Global Constraints

- AllDebrid API v4.1 endpoint: `https://api.alldebrid.com/v4/`
- API key stored in Kodi settings via `xbmcaddon.Addon()`
- Resolution is lazy: only called when user clicks play
- Scrapers set `"type": "torrent"` for magnet/torrent URLs
- Scrapers omit `type` or set `"direct"` for direct URLs (no resolution needed)
- `setResolvedUrl()` used for direct URLs in play mode
- Error notifications via `xbmcgui.Dialog().notification()`
- Already-declared deps only: `requests`, `xbmcaddon`, `xbmcgui`

---

### Task 1: Create AllDebrid API key setting

**Files:**
- Create: `resources/`
- Create: `resources/settings.xml`

**Interfaces:**
- Produces: `xbmcaddon.Addon().getSetting('alldebrid_api_key') -> str` — the API key, empty string if unset

- [ ] **Step 1: Write `resources/settings.xml`**

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
</settings>
```

- [ ] **Step 2: Register settings.xml in addon.xml**

Add this extension point after the existing `xbmc.python.pluginsource` extension:

```xml
  <extension point="xbmc.addon.metadata">
    ...
    <summary lang="en_GB">Scrapes videos from websites</summary>
    ...
  </extension>
```

No change needed — the `xbmc.python.pluginsource` extension already supports settings implicitly. The settings file is auto-detected by Kodi at `resources/settings.xml`.

Wait — actually we do need to check. In Kodi, for a plugin to have settings, we don't need an explicit extension point in addon.xml. The `resources/settings.xml` file is discovered automatically when the addon is installed. So Step 2 is just verifying no addon.xml changes are needed.

- [ ] **Step 3: Commit**

```bash
git add resources/settings.xml
git commit -m "feat: add AllDebrid API key setting"
```

---

### Task 2: Create AllDebrid resolver module

**Files:**
- Create: `lib/alldebrid.py`

**Interfaces:**
- Consumes: `xbmcaddon.Addon().getSetting('alldebrid_api_key')` from Task 1
- Produces: `alldebrid.resolve(url: str, api_key: str) -> str` — direct streamable URL
- Produces: `alldebrid.AllDebridError` — raised on any failure

- [ ] **Step 1: Write `lib/alldebrid.py`**

```python
"""AllDebrid API v4.1 resolver — converts magnet/torrent links to direct URLs."""
import requests

API_BASE = "https://api.alldebrid.com/v4/"


class AllDebridError(Exception):
    pass


def resolve(url, api_key):
    """Resolve a magnet link or torrent URL to a direct streamable URL.

    Args:
        url: str — magnet link (magnet:?xt=urn:btih:...) or torrent URL
        api_key: str — AllDebrid API key

    Returns:
        str — direct downloadable/streamable URL

    Raises:
        AllDebridError — on any failure (bad key, rate limit, service down, no files)
    """
    if not api_key:
        raise AllDebridError("API key not set")

    # Step 1: Upload magnet/torrent to AllDebrid
    upload_resp = requests.get(
        API_BASE + "magnet/upload",
        params={"agent": "plugin.video.baldest_man", "apikey": api_key, "magnets[]": url},
        timeout=30,
    )
    upload_data = _check_response(upload_resp)

    # Step 2: Get the magnet/torrent ID
    magnets = upload_data.get("data", {}).get("magnets", [])
    if not magnets:
        raise AllDebridError("No magnet returned from upload")

    magnet_id = magnets[0].get("id")
    if not magnet_id:
        raise AllDebridError("No magnet ID in response")

    # Step 3: Get status — AllDebrid may need time to process
    status_resp = requests.get(
        API_BASE + "magnet/status",
        params={"agent": "plugin.video.baldest_man", "apikey": api_key, "id": magnet_id},
        timeout=30,
    )
    status_data = _check_response(status_resp)

    magnet_info = status_data.get("data", {}).get("magnets", {})
    status = magnet_info.get("status", "")

    if status == "Ready":
        links = magnet_info.get("links", [])
        if not links:
            raise AllDebridError("Magnet ready but no links returned")
        # Return the first link's streamable URL — unlock it
        first_link = links[0].get("link", "")
        if not first_link:
            raise AllDebridError("Link entry missing URL")

        # Unlock the link to get the final direct URL
        unlock_resp = requests.get(
            API_BASE + "link/unlock",
            params={"agent": "plugin.video.baldest_man", "apikey": api_key, "link": first_link},
            timeout=30,
        )
        unlock_data = _check_response(unlock_resp)
        direct_url = unlock_data.get("data", {}).get("link", "")
        if not direct_url:
            raise AllDebridError("Failed to unlock link")
        return direct_url

    elif status == "Downloading" or status == "Processing":
        # ponytail: no polling loop — magnet just uploaded, give it a moment
        # If real scrapers hit this, add a retry with backoff
        raise AllDebridError("Magnet still processing, try again")
    else:
        raise AllDebridError("Unknown magnet status: {}".format(status))


def _check_response(resp):
    """Validate AllDebrid API response, raise AllDebridError on failure."""
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status", "")
    error_msg = data.get("error", {}).get("message", "")

    if status == "error":
        raise AllDebridError(error_msg or "Unknown API error")

    return data
```

- [ ] **Step 2: Verify Python syntax and basic import**

```bash
cd /home/dog/plugin.video.baldest_man && python3 -c "
import py_compile
py_compile.compile('lib/alldebrid.py', doraise=True)
import sys
sys.path.insert(0, '.')
from lib.alldebrid import AllDebridError, resolve
# Empty key raises immediately
try:
    resolve('magnet:?xt=urn:btih:deadbeef', '')
    assert False, 'should have raised'
except AllDebridError as e:
    assert 'API key not set' in str(e)
    print('OK: empty key rejected')
# Verify the exception is importable
print('OK: AllDebridError imported')
"
```

Expected: `OK: empty key rejected` and `OK: AllDebridError imported`

- [ ] **Step 3: Commit**

```bash
git add lib/alldebrid.py
git commit -m "feat: add AllDebrid API v4.1 resolver"
```

---

### Task 3: Update main.py with play mode and resolver integration

**Files:**
- Modify: `main.py` — add mode=play, update episode URLs to use play mode

**Interfaces:**
- Consumes: `lib.alldebrid.resolve(url, api_key)` from Task 2
- Consumes: `xbmcaddon.Addon().getSetting('alldebrid_api_key')` from Task 1
- Produces: `mode=play` — resolves magnet/torrent URL, calls `setResolvedUrl()`

- [ ] **Step 1: Update `main.py`**

Replace the entire file with:

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


def notify(msg):
    """Show a brief Kodi notification."""
    xbmcgui.Dialog().notification('bald_man', msg, xbmcgui.NOTIFICATION_INFO, 3000)


def api_key():
    return ADDON.getSetting('alldebrid_api_key')


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
    episodes.sort(key=lambda r: int(r['episode']) if r['episode'].isdigit() else 0)

    for ep in episodes:
        li = xbmcgui.ListItem(label_episode(ep))
        li.setInfo('video', {'title': label_episode(ep)})
        li.setProperty('IsPlayable', 'true')

        ep_type = ep.get('type', 'direct')
        play_url = build_url({'mode': 'play', 'url': ep['url'], 'type': ep_type})
        xbmcplugin.addDirectoryItem(addon_handle, play_url, li, isFolder=False)

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
        # Direct URL — hand straight to Kodi
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
git commit -m "feat: add AllDebrid play mode and resolver integration"
```

---

### Task 4: Update example scraper

**Files:**
- Modify: `scrapers/example.py` — document torrent return pattern

**Interfaces:**
- Updated: `search()` docstring shows `"type": "torrent"` in example results

- [ ] **Step 1: Write updated `scrapers/example.py`**

```python
"""Example scraper — copy this file and fill in the blanks.

Return types:
  - "type": "torrent"  — magnet/torrent link, resolved via AllDebrid on play
  - "type": "direct" or omitted — direct video URL, played immediately
"""
import requests

SITE_NAME = "example"


def search(query):
    """Return list of dicts with show_title, episode, url, type.
    
    Fields:
        show_title (str, required)
        episode   (str, required)  — episode number as string, e.g. "01"
        url       (str, required)  — magnet link or direct video URL
        type      (str, optional)  — "torrent" or "direct"; omit for direct
        title     (str, optional)  — episode title
        quality   (str, optional)  — e.g. "1080p", "720p"
    """
    return [
        # Example torrent result:
        # {
        #     "show_title": "One Punch Man",
        #     "episode": "01",
        #     "title": "The Strongest Man",
        #     "url": "magnet:?xt=urn:btih:deadbeefcafe...",
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
assert len(mods) >= 1
print('OK: discovered', len(mods), 'scraper(s)')
"
```

Expected: `OK: discovered 1 scraper(s)`

- [ ] **Step 3: Commit**

```bash
git add scrapers/example.py
git commit -m "docs: update example scraper with torrent return pattern"
```
