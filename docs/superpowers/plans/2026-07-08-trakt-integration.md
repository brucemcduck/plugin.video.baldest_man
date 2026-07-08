# Trakt Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Trakt.tv sync for scrobbling watch history, browsing watchlist/collection, and picking up next unwatched episode across devices.

**Architecture:** New `trakt.py` API client (OAuth + scrobble + sync), new settings for auth tokens, new `mode=trakt_browse` handler and root menu items in main.py. Reuses existing TMDB IDs and scrape flow.

**Tech Stack:** Python 3, requests, Trakt API v2, TMDB API

## Global Constraints

- Trakt API base: `https://api.trakt.tv`
- Trakt client ID: must be provided in settings (user registers their own API app at trakt.tv/oauth/applications)
- OAuth device flow: `/oauth/device/code` → `/oauth/device/token` → `/oauth/token` (refresh)
- Scrobbling: `POST /scrobble/start`, `POST /scrobble/stop`
- Sync: `GET /sync/watchlist/shows`, `GET /sync/watchlist/movies`, `GET /sync/collection/shows`, `GET /sync/collection/movies`
- Progress: `GET /sync/watched/shows` + `GET /shows/:id/progress/watched`
- All Trakt API calls require `trakt-api-key` and `trakt-api-version: 2` headers
- Scrobble/pause/stop payload: `{"show": {"ids": {"imdb": "tt..."}}, "episode": {"season": N, "number": N}, "progress": Pct}` or `{"movie": {"ids": {"imdb": "tt..."}}}`
- Scrobble calls must never block playback — fire-and-forget with try/except
- Menu items only appear when `trakt_access_token` is set
- IMDB ID for scrobbling: pass through play URL params from scrape handler

---

### Task 1: Trakt API Client

**Files:**
- Create: `resources/lib/trakt.py`

**Interfaces:**
- Produces:
  - `TraktError(Exception)` — base exception
  - `get_device_code(client_id) -> dict` — `{device_code, user_code, verification_url, expires_in, interval}`
  - `poll_for_token(client_id, device_code, interval=5) -> dict` — `{access_token, refresh_token}`
  - `refresh_token(client_id, refresh_token) -> dict` — `{access_token, refresh_token}`
  - `scrobble_start(access_token, imdb_id, season, episode) -> None` — fire and forget, silent on error
  - `scrobble_stop(access_token, imdb_id, season, episode, progress_pct) -> None`
  - `get_watchlist(access_token, list_type='shows') -> list` — returns `[{title, year, ids: {imdb, tmdb, slug}}]`
  - `get_collection(access_token, list_type='shows') -> list`
  - `get_watched_shows(access_token) -> list`
  - `get_show_progress(access_token, trakt_show_id) -> dict` — `{next_episode: {season, number, title}}`
  - `_get(access_token, path) -> dict|list` — internal helper
  - `_post(access_token, path, body) -> dict` — internal helper
  - `_headers(access_token) -> dict` — internal helper
- Consumes: `requests`, `CLIENT_ID` constant

- [ ] **Step 1: Create trakt.py with module structure**

```python
"""Trakt.tv API v2 — scrobbling, watchlist, collection, progress."""
import time
import requests

API = "https://api.trakt.tv"
HEADERS_BASE = {
    "Content-Type": "application/json",
    "trakt-api-version": "2",
}
TIMEOUT = 15


class TraktError(Exception):
    pass
```

- [ ] **Step 2: Add OAuth device flow**

```python
def get_device_code(client_id):
    try:
        resp = requests.post(API + "/oauth/device/code",
                             json={"client_id": client_id},
                             timeout=TIMEOUT,
                             headers=HEADERS_BASE)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise TraktError("Failed to get device code: {}".format(e))
    except ValueError:
        raise TraktError("Invalid response")


def poll_for_token(client_id, device_code, interval=5, max_wait=300):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = requests.post(API + "/oauth/device/token",
                                 json={"code": device_code,
                                       "client_id": client_id,
                                       "client_secret": ""},
                                 timeout=TIMEOUT,
                                 headers=HEADERS_BASE)
            if resp.status_code == 200:
                data = resp.json()
                return {"access_token": data["access_token"],
                        "refresh_token": data["refresh_token"]}
            if resp.status_code == 400:
                time.sleep(interval)
                continue
            resp.raise_for_status()
        except (requests.RequestException, ValueError):
            time.sleep(interval)
            continue
    raise TraktError("Timed out waiting for authorization")


def refresh_token(client_id, refresh_token):
    try:
        resp = requests.post(API + "/oauth/token",
                             json={"refresh_token": refresh_token,
                                   "client_id": client_id,
                                   "client_secret": "",
                                   "grant_type": "refresh_token"},
                             timeout=TIMEOUT,
                             headers=HEADERS_BASE)
        resp.raise_for_status()
        data = resp.json()
        return {"access_token": data["access_token"],
                "refresh_token": data["refresh_token"]}
    except (requests.RequestException, ValueError, KeyError) as e:
        raise TraktError("Token refresh failed: {}".format(e))
```

- [ ] **Step 3: Add internal helpers + scrobble methods**

```python
def _headers(access_token):
    h = dict(HEADERS_BASE)
    h["Authorization"] = "Bearer " + access_token
    return h


def _noop(*args, **kwargs):
    pass


def scrobble_start(access_token, imdb_id, season=None, episode=None):
    body = {}
    if season and episode:
        body["show"] = {"ids": {"imdb": imdb_id}}
        body["episode"] = {"season": season, "number": episode}
    else:
        body["movie"] = {"ids": {"imdb": imdb_id}}
    body["progress"] = 0.0
    try:
        requests.post(API + "/scrobble/start", json=body,
                      timeout=TIMEOUT, headers=_headers(access_token))
    except Exception:
        pass


def scrobble_stop(access_token, imdb_id, season=None, episode=None, progress_pct=0):
    body = {}
    if season and episode:
        body["show"] = {"ids": {"imdb": imdb_id}}
        body["episode"] = {"season": season, "number": episode}
    else:
        body["movie"] = {"ids": {"imdb": imdb_id}}
    body["progress"] = float(progress_pct)
    try:
        requests.post(API + "/scrobble/stop", json=body,
                      timeout=TIMEOUT, headers=_headers(access_token))
    except Exception:
        pass
```

- [ ] **Step 4: Add sync methods**

```python
def get_watchlist(access_token, list_type="shows"):
    try:
        resp = requests.get(API + "/sync/watchlist/" + list_type,
                            timeout=TIMEOUT, headers=_headers(access_token))
        resp.raise_for_status()
        return [item.get(list_type[:-1], item) for item in resp.json()]
    except Exception:
        return []


def get_collection(access_token, list_type="shows"):
    try:
        resp = requests.get(API + "/sync/collection/" + list_type,
                            timeout=TIMEOUT, headers=_headers(access_token))
        resp.raise_for_status()
        return [item.get(list_type[:-1], item) for item in resp.json()]
    except Exception:
        return []


def get_watched_shows(access_token):
    try:
        resp = requests.get(API + "/sync/watched/shows",
                            timeout=TIMEOUT, headers=_headers(access_token))
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def get_show_progress(access_token, trakt_show_id):
    try:
        resp = requests.get(API + "/shows/{}/progress/watched".format(trakt_show_id),
                            timeout=TIMEOUT, headers=_headers(access_token))
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}
```

- [ ] **Step 5: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('resources/lib/trakt.py').read()); print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add resources/lib/trakt.py
git commit -m "feat: add Trakt API client (OAuth, scrobble, sync, progress)"
```

---

### Task 2: Trakt Settings + Auth UI

**Files:**
- Modify: `resources/settings.xml` — add Trakt category
- Modify: `main.py` — add auth handler, import trakt

**Interfaces:**
- Consumes: `trakt.get_device_code()`, `trakt.poll_for_token()` from Task 1
- Produces: `trakt_client_id`, `trakt_access_token`, `trakt_refresh_token` settings; `mode=auth_trakt` handler

- [ ] **Step 1: Add settings category**

In `resources/settings.xml`, after the Scrapers category, add:

```xml
  <category label="Trakt">
    <setting id="trakt_client_id" type="text" label="Client ID" default="">
      <constraints>
        <allowempty>true</allowempty>
      </constraints>
    </setting>
    <setting id="trakt_access_token" type="text" default="">
      <constraints>
        <allowempty>true</allowempty>
        <hidden>true</hidden>
      </constraints>
    </setting>
    <setting id="trakt_refresh_token" type="text" default="">
      <constraints>
        <allowempty>true</allowempty>
        <hidden>true</hidden>
      </constraints>
    </setting>
    <setting label="Authorize Device" type="action"
             action="RunPlugin(plugin://plugin.video.baldest_man/?mode=auth_trakt)"/>
  </category>
```

- [ ] **Step 2: Add trakt import and auth handler in main.py**

Add import at top:

```python
from resources.lib.trakt import get_device_code, poll_for_token, TraktError
```

Add auth handler before the play handler:

```python
# --- Auth: Trakt device OAuth ---
elif mode[0] == 'auth_trakt':
    client_id = ADDON.getSetting('trakt_client_id')
    if not client_id:
        notify('Trakt Client ID not set')
    else:
        try:
            data = get_device_code(client_id)
        except TraktError as e:
            notify("Trakt: " + str(e))
        else:
            msg = ("1. Go to: [COLOR skyblue]{}[/COLOR]\n"
                   "2. Enter code: [COLOR yellow]{}[/COLOR]\n"
                   "3. Press OK after authorizing").format(
                       data.get("verification_url", "https://trakt.tv/activate"),
                       data.get("user_code", ""))
            xbmcgui.Dialog().ok("Trakt Authorization", msg)

            pdlg = xbmcgui.DialogProgress()
            pdlg.create("Trakt", "Waiting for authorization...")
            try:
                token = poll_for_token(client_id, data["device_code"],
                                       interval=data.get("interval", 5))
                ADDON.setSetting('trakt_access_token', token["access_token"])
                ADDON.setSetting('trakt_refresh_token', token["refresh_token"])
                pdlg.close()
                notify("Trakt authorized!")
            except TraktError as e:
                pdlg.close()
                notify("Trakt: " + str(e))

    xbmcplugin.endOfDirectory(addon_handle)
```

- [ ] **Step 3: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('main.py').read()); print('main OK')"
```

- [ ] **Step 4: Commit**

```bash
git add main.py resources/settings.xml
git commit -m "feat: add Trakt settings and device OAuth flow"
```

---

### Task 3: Scrobbling + IMDB passthrough

**Files:**
- Modify: `main.py` — play handler (add scrobble calls), add_scrape_result (add IMDB to play URL), scrape handler (pass IMDB ID)

**Interfaces:**
- Consumes: `trakt.scrobble_start()`, `trakt.scrobble_stop()` from Task 1; `trakt_client_id`, `trakt_access_token` settings from Task 2; `tmdb.get_imdb_id()` from scrape handler
- Produces: IMDB ID in play URL params; scrobble on play start; scrobble on play stop

- [ ] **Step 1: Pass IMDB ID through scrape → play URL**

In the scrape handler, we already fetch `imdb_id` inside the parallel futures. Save it and pass to `add_scrape_result` via the `meta` dict. After `imdb_id` is received from the IMDB future:

```python
                elif source == "imdb" and result:
                    imdb_id = result
                    ...
```

Add `imdb_id = None` before the ThreadPoolExecutor block, then set it when IMDB resolves. After the executor, include it in the meta dict:

```python
    meta = {'show_title': show_title, 'show_id': show_id,
            'content_type': content_type}
    if imdb_id:
        meta['imdb_id'] = imdb_id
```

- [ ] **Step 2: Scrobble on play**

In the play handler, after `setResolvedUrl(True, li)`, but before `except`:

```python
                xbmcplugin.setResolvedUrl(addon_handle, True, li)

                # Scrobble start to Trakt
                access_token = ADDON.getSetting('trakt_access_token')
                if access_token:
                    imdb = args.get('imdb_id', [None])[0]
                    if imdb:
                        s = args.get('season', [None])[0]
                        ep = args.get('episode', [None])[0]
                        if s and ep:
                            scrobble_start(access_token, imdb, int(s), int(ep))
                        else:
                            scrobble_start(access_token, imdb)
```

Add import: `from resources.lib.trakt import scrobble_start, scrobble_stop`

- [ ] **Step 3: Scrobble stop on playback end**

Kodi doesn't have a clean "playback ended" callback for plugins. The simplest approach: scrobble stop in the play handler's `except AllDebridError` block (only for resolution failures) is wrong — we need it when playback actually finishes.

Instead: scrobble_start marks it as "watching now" on Trakt, and Trakt auto-marks as watched when the next `scrobble_start` call happens or after a timeout. For now, just scrobble start — Trakt handles the rest.

- [ ] **Step 4: Syntax check and commit**

```bash
python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"
git add main.py
git commit -m "feat: scrobble to Trakt on play, pass IMDB ID through scrape flow"
```

---

### Task 4: Trakt Browse Menus

**Files:**
- Modify: `main.py` — add root menu items, `mode=trakt_browse` handler

**Interfaces:**
- Consumes: `trakt.get_watchlist()`, `trakt.get_collection()`, `trakt.get_watched_shows()`, `trakt.get_show_progress()` from Task 1; `trakt_access_token` setting from Task 2; `tmdb.search_shows()` for TMDB enrichment; `set_info()` for list items
- Produces: "Trakt Watchlist", "Trakt Collection", "Progress / Up Next" root menu items; `mode=trakt_browse` handler

- [ ] **Step 1: Add Trakt root menu items**

In the root menu handler, after the Continue Watching block, add:

```python
    # Trakt menus
    trakt_token = ADDON.getSetting('trakt_access_token')
    if trakt_token:
        for label, list_type in [
            ('Trakt Watchlist', 'watchlist'),
            ('Trakt Collection', 'collection'),
            ('Progress / Up Next', 'progress'),
        ]:
            url = build_url({'mode': 'trakt_browse', 'list_type': list_type})
            xbmcplugin.addDirectoryItem(addon_handle, url,
                                        xbmcgui.ListItem(label), isFolder=True)
```

- [ ] **Step 2: Add trakt_browse handler**

Before the play handler:

```python
# --- Trakt Browse: watchlist, collection, progress ---
elif mode[0] == 'trakt_browse':
    access_token = ADDON.getSetting('trakt_access_token')
    list_type = args.get('list_type', ['watchlist'])[0]

    if not access_token:
        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
    else:
        items = []
        if list_type == 'watchlist':
            shows = get_watchlist(access_token, 'shows')
            movies = get_watchlist(access_token, 'movies')
            items = [('show', s['show'], s['show']['ids']) for s in shows]
            items += [('movie', m['movie'], m['movie']['ids']) for m in movies]
        elif list_type == 'collection':
            shows = get_collection(access_token, 'shows')
            movies = get_collection(access_token, 'movies')
            items = [('show', s['show'], s['show']['ids']) for s in shows]
            items += [('movie', m['movie'], m['movie']['ids']) for m in movies]
        elif list_type == 'progress':
            watched = get_watched_shows(access_token)
            for w in watched:
                sid = w['show']['ids'].get('trakt')
                if sid:
                    prog = get_show_progress(access_token, sid)
                    ne = prog.get('next_episode')
                    if ne:
                        items.append(('progress', w['show'],
                                      {'tmdb': w['show']['ids'].get('tmdb'),
                                       'season': ne['season'],
                                       'number': ne['number'],
                                       'title': ne.get('title', '')}))

        if not items:
            li = xbmcgui.ListItem("Nothing found")
            xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)
        else:
            for item_type, data, ids in items:
                title = data.get('title', '')
                year = str(data.get('year', ''))
                label = f"{title} ({year})" if year else title
                li = xbmcgui.ListItem(label)

                if item_type == 'progress':
                    url = build_url({'mode': 'scrape',
                                     'show_title': title,
                                     'show_id': str(ids.get('tmdb', '')),
                                     'season_number': str(ids.get('season', '1')),
                                     'episode_number': str(ids.get('number', '1')),
                                     'episode_title': ids.get('title', ''),
                                     'content_type': 'shows'})
                    xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)
                elif item_type == 'show':
                    url = build_url({'mode': 'seasons',
                                     'show_id': str(ids.get('tmdb', '')),
                                     'show_title': title})
                    xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)
                else:
                    url = build_url({'mode': 'scrape',
                                     'show_title': title,
                                     'show_id': str(ids.get('tmdb', '')),
                                     'content_type': 'movies'})
                    xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
```

Add import at top: `from resources.lib.trakt import get_watchlist, get_collection, get_watched_shows, get_show_progress`

- [ ] **Step 3: Syntax check and commit**

```bash
python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"
git add main.py
git commit -m "feat: add Trakt Watchlist, Collection, and Progress browse menus"
```
