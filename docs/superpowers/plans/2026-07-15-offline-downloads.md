# Offline Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to download videos to local disk before going offline (e.g. a flight), then play them back with zero network connectivity. AllDebrid resolves the magnet to a direct URL once, the file is streamed to disk, and subsequent playback reads the local file — no links, no AllDebrid, no expiry.

**Architecture:** New `download_manager.py` (download + manifest logic), new `mode=download` and `mode=play_local` handlers in `main.py`, a "My Downloads" root menu entry that reads a JSON manifest, and three new settings for offline quality / size cap / download path. Source selection for offline filters to 720p under a size cap and sorts smallest-viable-first (opposite of streaming's largest-first). Posters and TMDB metadata are cached to disk during download so the offline list renders fully offline.

**Tech Stack:** Python 3, requests (chunked download + HTTP Range for resume), Kodi xbmcgui/xmbcplugin, existing AllDebrid resolver, existing TMDB client

## Global Constraints

- AllDebrid is invoked **exactly once per download** — `ad_resolve()` produces a temporary direct HTTP URL that is streamed to disk immediately in the same session. The URL is not stored or reused.
- After download completes, the saved file is a plain video file on disk; playback uses `file://` path and touches zero network services (no AllDebrid, no TMDB, no Trakt).
- Downloads go to `<kodi_videos>/bald_man_downloads/<safe_filename>` by default (user-configurable via `download_path` setting, e.g. SD card / USB).
- Offline source selection filters to `offline_quality` (default `720p`) and rejects sources over `max_download_size_gb` (default `2`). Sort ascending by `_parse_size_bytes` so the smallest viable source wins.
- A `downloads.json` manifest in the addon data dir tracks every saved video: id, title, show_title, season, episode, file_path, size_bytes, date_added, mediatype, plot, and local paths to cached poster/thumb images.
- Poster and still images are downloaded alongside the video so the "My Downloads" list has artwork offline. Stored next to the manifest in an `art/` subdir.
- Disk-space pre-check via `shutil.disk_usage()` before each download — abort with notification if insufficient.
- Resume support: HTTP `Range` header on the AllDebrid direct URL; if the server returns 206, append to existing partial `.part` file, then rename on completion.
- Context menu ("Download for Offline") is the only entry point — no inline download button, no batch queue UI in this iteration.
- Trakt scrobble for offline plays is best-effort and silently skipped when no network is present (matches existing fire-and-forget pattern).

---

### Task 1: Download Manager Module

**Files:**
- Create: `resources/lib/download_manager.py`

**Interfaces:**
- Produces:
  - `DownloadError(Exception)` — base exception
  - `manifest_path()` — returns path to `downloads.json`
  - `load_manifest() -> list[dict]` — read manifest, return [] on missing/corrupt
  - `save_manifest(items)` — atomic write (tmp + rename)
  - `add_to_manifest(entry)` — append + save
  - `remove_from_manifest(item_id)` — delete entry + delete file + delete cached art
  - `get_download_dir() -> str` — resolves `download_path` setting, ensures dir exists
  - `safe_filename(title, season, episode) -> str` — sanitize title to filesystem-safe name
  - `download_video(direct_url, dest_path, cancel_check=None, progress_callback=None) -> bool` — chunked HTTP GET with Range resume; returns True on completion
  - `cache_artwork(url, dest_path) -> str|None` — download poster/thumb to disk, return local path
  - `has_space(path, required_bytes) -> bool` — disk-space pre-check
  - `_log(msg)` — internal helper (Kodi or stderr)
- Consumes: `requests`, `shutil`, `os`, `xbmcaddon` (for settings)

- [ ] **Step 1: Create download_manager.py with module structure**

```python
"""Offline download manager — saves videos to disk for no-network playback."""
import json
import os
import re
import shutil

import requests

try:
    import xbmcaddon
except ImportError:
    xbmcaddon = None

CHUNK_SIZE = 1024 * 1024  # 1 MB
MANIFEST_NAME = "downloads.json"
ART_SUBDIR = "art"


class DownloadError(Exception):
    pass


def _log(msg):
    try:
        import xbmc
        xbmc.log("bald_man download: " + str(msg), level=xbmc.LOGINFO)
    except ImportError:
        import sys
        print("download: " + str(msg), file=sys.stderr)
```

- [ ] **Step 2: Add settings + path helpers**

```python
def _addon():
    return xbmcaddon.Addon() if xbmcaddon else None


def get_download_dir():
    """Resolve download_path setting, fall back to Kodi special://profile,
    ensure the directory exists. Returns absolute path."""
    addon = _addon()
    path = addon.getSetting('download_path') if addon else ''
    if not path:
        # Default: Kodi videos folder via special protocol
        try:
            import xbmcvfs
            path = xbmcvfs.translatePath('special://userdata/addon_data/plugin.video.baldest_man/downloads')
        except ImportError:
            path = os.path.join(os.path.expanduser('~'), 'bald_man_downloads')
    os.makedirs(path, exist_ok=True)
    return path


def manifest_path():
    try:
        import xbmcvfs
        base = xbmcvfs.translatePath('special://userdata/addon_data/plugin.video.baldest_man')
    except ImportError:
        base = get_download_dir()
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, MANIFEST_NAME)


def art_dir():
    try:
        import xbmcvfs
        base = xbmcvfs.translatePath('special://userdata/addon_data/plugin.video.baldest_man')
    except ImportError:
        base = get_download_dir()
    p = os.path.join(base, ART_SUBDIR)
    os.makedirs(p, exist_ok=True)
    return p
```

- [ ] **Step 3: Add manifest read/write**

```python
def load_manifest():
    try:
        with open(manifest_path()) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return []


def save_manifest(items):
    p = manifest_path()
    tmp = p + '.tmp'
    try:
        with open(tmp, 'w') as f:
            json.dump(items, f, indent=2)
        os.replace(tmp, p)
    except OSError as e:
        raise DownloadError("Failed to save manifest: {}".format(e))


def add_to_manifest(entry):
    items = load_manifest()
    items.append(entry)
    save_manifest(items)


def remove_from_manifest(item_id):
    items = load_manifest()
    kept = []
    for it in items:
        if it.get('id') == item_id:
            # Delete the video file + cached art
            for key in ('file_path', 'poster_path', 'thumb_path'):
                p = it.get(key)
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        else:
            kept.append(it)
    save_manifest(kept)
```

- [ ] **Step 4: Add filename sanitizer + space check**

```python
def safe_filename(title, season=None, episode=None):
    """Build a filesystem-safe filename. Shows get SxxExx suffix."""
    name = re.sub(r'[^\w\s.-]', '', title).strip().replace(' ', '.')
    if season and episode:
        name += f".S{int(season):02d}E{int(episode):02d}"
    # Cap length to avoid filesystem limits
    if len(name) > 180:
        name = name[:180]
    return name + '.mp4'


def has_space(path, required_bytes):
    try:
        usage = shutil.disk_usage(os.path.dirname(path) or '.')
        return usage.free >= required_bytes * 1.05  # 5% headroom
    except OSError:
        return True  # Can't check — allow attempt
```

- [ ] **Step 5: Add chunked download with Range resume**

```python
def download_video(direct_url, dest_path, cancel_check=None, progress_callback=None):
    """Stream direct_url to dest_path in 1MB chunks.
    Supports resume via HTTP Range if a .part file exists.
    Returns True on completion, False if cancelled.
    Raises DownloadError on network failure.
    """
    part_path = dest_path + '.part'
    resume_at = 0
    headers = {}
    if os.path.exists(part_path):
        resume_at = os.path.getsize(part_path)
        headers['Range'] = 'bytes={}-'.format(resume_at)
        _log("resuming at {} bytes".format(resume_at))

    try:
        resp = requests.get(direct_url, headers=headers, stream=True, timeout=30)
        if resume_at and resp.status_code != 206:
            # Server doesn't support range — restart from scratch
            resume_at = 0
            resp = requests.get(direct_url, stream=True, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DownloadError("Download request failed: {}".format(e))

    total = int(resp.headers.get('Content-Length', 0)) + resume_at
    mode = 'ab' if resume_at else 'wb'
    written = resume_at

    try:
        with open(part_path, mode) as f:
            for chunk in resp.iter_content(CHUNK_SIZE):
                if cancel_check and cancel_check():
                    _log("download cancelled by user")
                    return False
                if chunk:
                    f.write(chunk)
                    written += len(chunk)
                    if progress_callback:
                        pct = int(written / total * 100) if total else 0
                        progress_callback(written, total, pct)
        os.replace(part_path, dest_path)
        _log("download complete: {}".format(dest_path))
        return True
    except OSError as e:
        raise DownloadError("File write failed: {}".format(e))
```

- [ ] **Step 6: Add artwork cache helper**

```python
def cache_artwork(url, dest_path):
    """Download an image to dest_path, return dest_path on success or None."""
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        with open(dest_path, 'wb') as f:
            f.write(resp.content)
        return dest_path
    except (requests.RequestException, OSError) as e:
        _log("artwork cache failed: {}".format(e))
        return None
```

- [ ] **Step 7: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('resources/lib/download_manager.py').read()); print('OK')"
```

- [ ] **Step 8: Commit**

```bash
git add resources/lib/download_manager.py
git commit -m "feat: add offline download manager (manifest, chunked download, artwork cache)"
```

---

### Task 2: Offline Settings

**Files:**
- Modify: `resources/settings.xml` — add Offline category

**Interfaces:**
- Produces: `offline_quality`, `max_download_size_gb`, `download_path` settings

- [ ] **Step 1: Add Offline settings category**

In `resources/settings.xml`, after the Trakt category (or at the end), add:

```xml
  <category label="Offline Downloads">
    <setting id="offline_quality" type="text" label="Preferred quality for offline" default="720p">
      <constraints>
        <allowempty>false</allowempty>
      </constraints>
    </setting>
    <setting id="max_download_size_gb" type="integer" label="Max file size (GB)" default="2">
      <constraints>
        <minimum>1</minimum>
        <maximum>20</maximum>
      </constraints>
    </setting>
    <setting id="download_path" type="text" label="Download folder (blank = default)" default="">
      <constraints>
        <allowempty>true</allowempty>
      </constraints>
    </setting>
  </category>
```

- [ ] **Step 2: Syntax check (xml well-formed)**

```bash
python3 -c "import xml.etree.ElementTree as E; E.parse('resources/settings.xml'); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add resources/settings.xml
git commit -m "feat: add offline download settings (quality, size cap, path)"
```

---

### Task 3: Download Mode + Context Menu

**Files:**
- Modify: `main.py` — add `mode=download` handler, context menu on scrape results, import download_manager

**Interfaces:**
- Consumes: `download_manager.*` from Task 1; `ad_resolve()` from alldebrid; `_parse_size_bytes()`; offline settings from Task 2; cached scrape results from `_SCRAPE_CACHE`
- Produces: `mode=download` handler that resolves → downloads → caches art → writes manifest entry

- [ ] **Step 1: Add import at top of main.py**

```python
from resources.lib import download_manager
```

- [ ] **Step 2: Add offline source filtering helper**

Near the other helpers (after `_parse_size_bytes`):

```python
def _pick_offline_source(results):
    """Filter scrape results to offline_quality under size cap, smallest first.
    Returns the best result dict or None."""
    want_q = (ADDON.getSetting('offline_quality') or '720p').lower()
    max_gb = int(ADDON.getSetting('max_download_size_gb') or '2')
    max_bytes = max_gb * 1073741824

    def _ok(r):
        q = (r.get('quality') or '').lower()
        sz = _parse_size_bytes(r.get('size', ''))
        if q and q != want_q:
            return False
        if sz and sz > max_bytes:
            return False
        return True

    candidates = [r for r in results if _ok(r)]
    if not candidates:
        # Fall back to any source under the size cap
        candidates = [r for r in results
                      if _parse_size_bytes(r.get('size', '')) <= max_bytes]
    if not candidates:
        return None
    candidates.sort(key=lambda r: _parse_size_bytes(r.get('size', '')) or 0)
    return candidates[0]
```

- [ ] **Step 3: Add context menu to scrape result items**

In `add_scrape_result`, after `li.setProperty('IsPlayable', 'true')`, add a context menu item that triggers download. Build the download URL from the same params used for play, plus the cached scrape key so the download handler can re-read candidates:

```python
    # Context menu: Download for Offline
    dl_params = dict(params) if 'params' in dir() else {
        'mode': 'download',
        'url': item['url'],
        'type': item.get('type', 'direct'),
        'label': play_label if play_label else label,
    }
    dl_params['mode'] = 'download'
    dl_url = build_url(dl_params)
    commands = [('Download for Offline', 'RunPlugin({})'.format(dl_url))]
```

Note: the full `meta` dict is already spread into `params` earlier in the function — reuse it. Attach via:

```python
    li.addContextMenuItems(commands)
```

Place this right before `xbmcplugin.addDirectoryItem(...)` in `add_scrape_result`.

- [ ] **Step 4: Add mode=download handler**

Before the play handler:

```python
# --- Download: resolve + save to disk for offline playback ---
elif mode[0] == 'download':
    url = args.get('url', [''])[0]
    ep_type = args.get('type', ['direct'])[0]
    label = args.get('label', [''])[0]

    if ep_type != 'torrent':
        notify('Only torrent sources can be downloaded for offline')
        xbmcplugin.endOfDirectory(addon_handle)
    else:
        key = api_key()
        if not key:
            notify('AllDebrid API key not set')
            xbmcplugin.endOfDirectory(addon_handle)
        else:
            pdlg = xbmcgui.DialogProgress()
            pdlg.create("Downloading for Offline", "Resolving magnet...")

            try:
                timeout = int(ADDON.getSetting('magnet_timeout') or 120)

                def prog_cb(state, pct, eta):
                    if state == "uploading":
                        pdlg.update(0, "Uploading magnet...")
                    elif state == "ready":
                        pdlg.update(5, "Resolved — starting download...")
                    else:
                        pdlg.update(pct // 5, "Resolving... ~{}s".format(eta))

                direct_url = ad_resolve(url, key, timeout=timeout,
                                        cancel_check=pdlg.iscanceled,
                                        progress_callback=prog_cb)
                if pdlg.iscanceled():
                    pdlg.close()
                    xbmcplugin.endOfDirectory(addon_handle)
                    raise AllDebridError("Cancelled")

                # Pick filename + paths
                show_title = args.get('show_title', [''])[0]
                season = args.get('season', [None])[0]
                episode = args.get('episode', [None])[0]
                fname = download_manager.safe_filename(show_title or label, season, episode)
                dest = os.path.join(download_manager.get_download_dir(), fname)

                # Space check — estimate from scrape size if present
                est = _parse_size_bytes(args.get('size', [''])[0])
                if est and not download_manager.has_space(dest, est):
                    pdlg.close()
                    notify("Not enough disk space for this download")
                    xbmcplugin.endOfDirectory(addon_handle)
                    raise AllDebridError("Insufficient space")

                pdlg.update(6, "Downloading {}...".format(fname))

                def dl_cb(written, total, pct):
                    label_txt = "{} ({} / {} MB)".format(
                        fname, written // 1048576, total // 1048576)
                    pdlg.update(6 + pct * 94 // 100, label_txt)

                ok = download_manager.download_video(
                    direct_url, dest,
                    cancel_check=pdlg.iscanceled,
                    progress_callback=dl_cb)
                pdlg.close()

                if not ok:
                    notify("Download cancelled")
                else:
                    # Cache artwork + write manifest entry
                    poster_url = args.get('poster_url', [None])[0]
                    poster_local = None
                    if poster_url:
                        poster_local = download_manager.cache_artwork(
                            poster_url, os.path.join(download_manager.art_dir(),
                                                     fname + '.poster.jpg'))

                    entry = {
                        'id': fname,
                        'title': label,
                        'show_title': show_title,
                        'season': season,
                        'episode': episode,
                        'file_path': dest,
                        'size_bytes': os.path.getsize(dest),
                        'date_added': int(__import__('time').time()),
                        'mediatype': 'episode' if episode else 'movie',
                        'plot': args.get('plot', [''])[0],
                        'poster_path': poster_local,
                    }
                    download_manager.add_to_manifest(entry)
                    notify("Downloaded: {}".format(label))

            except AllDebridError as e:
                try:
                    pdlg.close()
                except Exception:
                    pass
                notify('Download failed: ' + str(e))

            xbmcplugin.endOfDirectory(addon_handle)
```

- [ ] **Step 5: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('main.py').read()); print('main OK')"
```

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: add offline download mode + context menu on scrape results"
```

---

### Task 4: My Downloads Menu + Local Playback

**Files:**
- Modify: `main.py` — add "My Downloads" root entry, `mode=my_downloads` handler, `mode=play_local` handler

**Interfaces:**
- Consumes: `download_manager.load_manifest()` from Task 1
- Produces: offline-browsable list of saved videos; local file playback with no network

- [ ] **Step 1: Add "My Downloads" root menu item**

In the root menu handler (`if mode is None:`), after the Trakt menus block and before `endOfDirectory`:

```python
    # My Downloads — offline library
    dl_count = len(download_manager.load_manifest())
    dl_label = "My Downloads ({})".format(dl_count) if dl_count else "My Downloads"
    url = build_url({'mode': 'my_downloads'})
    xbmcplugin.addDirectoryItem(addon_handle, url,
                                xbmcgui.ListItem(dl_label), isFolder=True)
```

- [ ] **Step 2: Add mode=my_downloads handler**

Before the download handler:

```python
# --- My Downloads: offline library (no network needed) ---
elif mode[0] == 'my_downloads':
    items = download_manager.load_manifest()
    if not items:
        li = xbmcgui.ListItem("No downloads yet — use context menu on a source")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)
    else:
        for it in items:
            label = it.get('title', it.get('show_title', 'Unknown'))
            if it.get('season') and it.get('episode'):
                label = "{} S{:02d}E{:02d}".format(
                    it.get('show_title', label),
                    int(it['season']), int(it['episode']))
            li = xbmcgui.ListItem(label)
            li.setProperty('IsPlayable', 'true')
            info = {'title': label, 'mediatype': it.get('mediatype', 'movie')}
            if it.get('plot'):
                info['plot'] = it['plot']
            sz = it.get('size_bytes', 0)
            if sz:
                info['size'] = sz
            li.setInfo('video', info)
            poster = it.get('poster_path')
            if poster and os.path.exists(poster):
                li.setArt({'poster': poster, 'thumb': poster})
            play_url = build_url({'mode': 'play_local', 'id': it.get('id', '')})
            xbmcplugin.addDirectoryItem(addon_handle, play_url, li, isFolder=False)
    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
```

- [ ] **Step 3: Add mode=play_local handler**

Before the download handler:

```python
# --- Play Local: file:// playback, zero network ---
elif mode[0] == 'play_local':
    item_id = args.get('id', [''])[0]
    target = None
    for it in download_manager.load_manifest():
        if it.get('id') == item_id:
            target = it
            break
    if target and os.path.exists(target.get('file_path', '')):
        li = xbmcgui.ListItem(target.get('title', ''), path=target['file_path'])
        xbmcplugin.setResolvedUrl(addon_handle, True, li)
    else:
        notify("File not found — it may have been deleted")
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
```

- [ ] **Step 4: Add delete option via context menu on download items**

In the `my_downloads` handler, when building each list item, add a context menu to delete:

```python
            del_url = build_url({'mode': 'delete_download', 'id': it.get('id', '')})
            li.addContextMenuItems([('Delete Download', 'RunPlugin({})'.format(del_url))])
```

Add a small handler for deletion:

```python
# --- Delete Download: remove file + manifest entry ---
elif mode[0] == 'delete_download':
    item_id = args.get('id', [''])[0]
    download_manager.remove_from_manifest(item_id)
    notify("Download deleted")
    xbmc.executebuiltin('Container.Refresh')
    xbmcplugin.endOfDirectory(addon_handle)
```

(Requires `import xbmc` — add at top alongside the other xbmc imports, guarded by the existing pyrefly ignore pattern.)

- [ ] **Step 5: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('main.py').read()); print('main OK')"
```

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat: add My Downloads menu, local playback, and delete option"
```

---

### Task 5: End-to-End Manual Test Checklist

**Files:** none (verification only)

- [ ] **Step 1: Pre-flight setup (with network)**
  - Open addon settings → set `offline_quality` = `720p`, `max_download_size_gb` = `2`
  - Search for a short TV episode (smallest test case)
  - Open context menu on a 720p scrape result → "Download for Offline"
  - Verify progress dialog shows resolve → download phases
  - Verify file appears in `<kodi_videos>/bald_man_downloads/`
  - Verify `downloads.json` contains the entry with correct metadata
  - Verify poster image cached in `art/` subdir

- [ ] **Step 2: Offline playback (no network)**
  - Disable network on the device
  - Open addon → "My Downloads" appears at root with count
  - Enter it → downloaded item shows with poster + metadata
  - Select it → plays from local file, no spinner/resolution step
  - Verify playback controls (seek, pause) work normally

- [ ] **Step 3: Edge cases**
  - Start a download, cancel mid-way → `.part` file remains, no manifest entry
  - Re-download same item → resume appends to `.part`, completes, renames
  - Delete a download via context menu → file + manifest entry removed, list refreshes
  - Download a movie with no poster → list item renders without artwork, no crash
  - Source list has no 720p under cap → falls back to next-best under cap with notification

- [ ] **Step 4: Final commit (if any fixups)**

```bash
git add -A
git commit -m "fix: offline downloads edge-case adjustments from manual testing"
```

---

## Notes & Risks

- **AllDebrid URL TTL:** The resolved direct URL is temporary. The download handler resolves and downloads in one atomic session — the URL is never persisted. If a download is interrupted, the next attempt re-resolves from the magnet (the `.part` file resume only helps if the same URL is reused within its validity window; otherwise it restarts from scratch with a fresh resolve). This is acceptable: downloads happen before the flight, while online.
- **No transcode in this iteration:** 720p + 2GB cap targets ~1GB/movie and ~500MB/episode, which fits 60+ items on a 64GB device. If more compression is needed later, an ffmpeg-based post-process step can be added as a future task.
- **No batch queue UI:** Single download via context menu only. A multi-select batch mode with total-size summary is a natural follow-up but out of scope here to keep the change small.
- **Kodi videos folder default:** The default `download_path` resolves to the addon's userdata dir (writable, always exists). Users with SD cards / USB sticks set `download_path` explicitly in settings. The setting accepts a plain filesystem path.
