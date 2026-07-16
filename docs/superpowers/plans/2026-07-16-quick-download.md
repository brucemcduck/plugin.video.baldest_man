# Quick Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Quick Download" context menu action that auto-scrapes, picks the best source (highest quality, smallest size), and downloads with fallback — plus a season multi-select batch download.

**Architecture:** New `mode=quick_download` handler in `main.py` with two reusable helpers extracted from the existing `mode=scrape` handler: `_scrape_with_early_termination()` (scrape with optional early stop) and `_quality_sort_key()` (quality-desc, size-asc sort). Context menu items added to movie, episode, and season ListItems. One new setting for the early-termination threshold.

**Tech Stack:** Python 3, Kodi Matrix+ (xbmcaddon/xbmcgui/xbmcplugin/xbmcvfs), `requests`, `concurrent.futures.ThreadPoolExecutor`, AllDebrid API v4.

## Global Constraints

- `notify(msg)` helper exists at main.py:44 — use it for all user-facing messages
- `clean_error(e)` helper exists at main.py:49 — use it for exception text in notifications
- `build_url(query)` helper exists at main.py:35 — use it for all plugin URLs
- `ADDON` is the global `xbmcaddon.Addon()` instance in main.py
- `api_key()` at main.py:194 reads `alldebridtoken` setting
- `ad_resolve(url, api_key, timeout=, cancel_check=, progress_callback=)` is the AllDebrid resolve function (alldebrid.py:36)
- `download_manager.download_video(direct_url, dest_path, cancel_check=, progress_callback=, source_id=)` downloads to disk (download_manager.py:137)
- `download_manager.safe_filename(title, season=, episode=)` generates a filename (download_manager.py:116)
- `download_manager.get_download_dir()` returns the download folder (download_manager.py:45)
- `download_manager.has_space(path, required_bytes)` checks disk space (download_manager.py:126)
- `download_manager.add_to_manifest(entry)` adds to the manifest (download_manager.py:90)
- `download_manager.cache_artwork(url, dest_path)` caches poster (download_manager.py:201)
- `download_manager.art_dir()` returns artwork directory (download_manager.py:62)
- `scraper_runner.search_all(query, content_type)` runs all HTML scrapers (scraper_runner.py:14)
- `torrentio.search_imdb(imdb_id, ...)` searches Torrentio (imported in main.py already)
- `tmdb.get_episodes(show_id, season_number, api_key, language)` returns episode list (tmdb.py:124)
- `tmdb.get_imdb_id(show_id, api_key, is_movie=)` returns IMDB ID (tmdb.py:101)
- `tmdb.get_poster(show_id, api_key, is_movie=)` returns poster URL (tmdb.py:112)
- `_parse_size_bytes(size_str)` exists in main.py — parses "1.5 GB" → bytes
- `_seeder_ok(result)` filter exists inline in mode=scrape at main.py:535-542 — will be extracted
- Existing `mode=scrape` sorts largest-first (main.py:547); Quick Download sorts quality-desc/size-asc (opposite intent)
- Settings use Kodi's `<constraints>` XML pattern (see settings.xml)
- No automated test framework; verification is `python3 -c "import ast..."` syntax check
- One commit per task

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `resources/settings.xml` | New `quick_download_max_sources` setting | Task 1 |
| `main.py` | `_seeder_ok()` + `_quality_sort_key()` + `_scrape_with_early_termination()` helpers | Task 2 |
| `main.py` | `_quick_download_one()` helper (scrape→sort→fallback→download single item) | Task 3 |
| `main.py` | `mode=quick_download` handler (single + season multi-select) | Task 4 |
| `main.py` | Context menu items on movie/episode/season ListItems | Task 5 |

---

### Task 1: Add quick_download_max_sources setting

**Files:**
- Modify: `resources/settings.xml` (Offline Downloads category, after `download_path` setting around line 82)

**Interfaces:**
- Consumes: nothing
- Produces: `quick_download_max_sources` setting (integer, default 10, min 2, max 50), readable via `ADDON.getSetting('quick_download_max_sources')`

- [ ] **Step 1: Add the setting**

In `resources/settings.xml`, inside the `<category label="Offline Downloads">` block, after the `download_path` setting (the last setting before `</category>`), add:

```xml
    <setting id="quick_download_max_sources" type="integer" label="Quick Download: max sources to collect" default="10">
      <constraints>
        <minimum>2</minimum>
        <maximum>50</maximum>
      </constraints>
    </setting>
```

- [ ] **Step 2: XML validation**

Run: `python3 -c "import xml.etree.ElementTree as E; E.parse('resources/settings.xml'); print('XML OK')"`
Expected: `XML OK`

- [ ] **Step 3: Commit**

```bash
git add resources/settings.xml
git commit -m "feat: add quick_download_max_sources setting"
```

---

### Task 2: Extract scrape helpers (_seeder_ok, _quality_sort_key, _scrape_with_early_termination)

**Files:**
- Modify: `main.py` — add three new functions before the mode dispatch (before `if mode is None:` at line 223); refactor `mode=scrape` to use them

**Interfaces:**
- Consumes: `scraper_runner.search_all`, `torrentio.search_imdb`, `tmdb.get_imdb_id`, `tmdb.get_poster`, `_parse_size_bytes`, `ThreadPoolExecutor`, `xbmcgui.DialogProgress`
- Produces:
  - `_seeder_ok(r) -> bool` — extracted from the inline filter at main.py:535-542
  - `_quality_sort_key(r) -> tuple` — returns `(-quality_rank, size)` for quality-desc/size-asc sorting
  - `_scrape_with_early_termination(query, content_type, show_id=None, is_movie=False, season_number=None, episode_number=None, max_sources=None) -> (list, str|None, str|None, dict)` — returns `(results, poster_url, imdb_id, meta)`

- [ ] **Step 1: Add `_seeder_ok()` function**

Add before `if mode is None:` (line 223), after the existing `_parse_size_bytes` function:

```python
def _seeder_ok(r):
    """Check seeder quality: at least 1 seeder per 10GB of file size."""
    s = r.get('seeders')
    if s is None:
        return True
    size_bytes = _parse_size_bytes(r.get('size', ''))
    if not size_bytes:
        return True
    return s * 10737418240 >= size_bytes
```

- [ ] **Step 2: Add `_quality_sort_key()` function**

Add immediately after `_seeder_ok()`:

```python
_QUALITY_RANK = {'4k': 4, '2160p': 4, '1080p': 3, '720p': 2, '480p': 1}


def _quality_sort_key(r):
    """Sort key: quality descending, then size ascending within each tier."""
    q = (r.get('quality') or '').lower()
    rank = _QUALITY_RANK.get(q, 0)
    size = _parse_size_bytes(r.get('size', '')) or 0
    return (-rank, size)
```

- [ ] **Step 3: Add `_scrape_with_early_termination()` function**

Add immediately after `_quality_sort_key()`:

```python
def _scrape_with_early_termination(query, content_type, show_id=None,
                                    is_movie=False, season_number=None,
                                    episode_number=None, max_sources=None):
    """Scrape sources with optional early termination.
    Returns (results, poster_url, imdb_id, meta).
    If max_sources is set, stops collecting once that many viable results
    (passing _seeder_ok) are found. If None, waits for all scrapers."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    pdlg = xbmcgui.DialogProgress()
    pdlg.create("Searching for sources...", "Starting...")

    all_results = []
    poster_url = None
    imdb_id = None
    pending = 0
    done = 0

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}

            futures[pool.submit(scraper_runner.search_all, query, content_type)] = "scrapers"
            pending += 1

            if show_id:
                futures[pool.submit(tmdb.get_imdb_id, int(show_id), tmdb_api_key(),
                                    is_movie=is_movie)] = "imdb"
                pending += 1

            if show_id:
                futures[pool.submit(tmdb.get_poster, int(show_id), tmdb_api_key(),
                                    is_movie=is_movie)] = "poster"
                pending += 1

            torrentio_future = None
            for future in as_completed(futures):
                if pdlg.iscanceled():
                    break
                source = futures[future]
                done += 1
                try:
                    result = future.result()
                except Exception:
                    pdlg.update(int(done / pending * 100), "{} failed".format(source))
                    continue

                if source == "scrapers":
                    all_results.extend(result)
                    viable = [r for r in all_results if _seeder_ok(r)]
                    pdlg.update(int(done / pending * 100),
                                "{} sources".format(len(all_results)))
                    if max_sources and len(viable) >= max_sources:
                        break
                elif source == "imdb" and result:
                    imdb_id = result
                    if is_movie:
                        torrentio_future = pool.submit(torrentio.search_imdb, imdb_id,
                                                       is_movie=True)
                    elif season_number and episode_number:
                        torrentio_future = pool.submit(torrentio.search_imdb, imdb_id,
                                                       int(season_number), int(episode_number))
                    if torrentio_future:
                        pending += 1
                    pdlg.update(int(done / pending * 100),
                                "{} sources".format(len(all_results)))
                elif source == "poster" and result:
                    poster_url = result
                    pdlg.update(int(done / pending * 100),
                                "{} sources".format(len(all_results)))

            if torrentio_future and not pdlg.iscanceled():
                viable = [r for r in all_results if _seeder_ok(r)]
                if not max_sources or len(viable) < max_sources:
                    try:
                        tr = torrentio_future.result()
                        all_results.extend(tr)
                    except Exception:
                        pass
                done += 1
                pdlg.update(100, "{} sources".format(len(all_results)))

    finally:
        pdlg.close()

    all_results = [r for r in all_results if _seeder_ok(r)]

    meta = {'content_type': content_type}
    if show_id:
        meta['show_id'] = show_id
    if imdb_id:
        meta['imdb_id'] = imdb_id
    if season_number:
        meta['season'] = season_number
    if episode_number:
        meta['episode'] = episode_number

    return all_results, poster_url, imdb_id, meta
```

The caller adds `show_title` and `episode_title` to meta as needed.

- [ ] **Step 4: Refactor `mode=scrape` to use the helpers**

In the `mode=scrape` handler (main.py:448-564), replace the inline scrape logic with calls to the new helpers. Replace the block from line 448 (`if not cache_hit:`) through line 544 (`all_results = [r for r in all_results if _seeder_ok(r)]`) with:

```python
    if not cache_hit:

        if season_number and episode_number:
            query = f"{show_title} S{int(season_number):02d}E{int(episode_number):02d}"
        else:
            query = f"{show_title} {year}".strip() if year else show_title

        is_movie = content_type == 'movies'

        all_results, poster_url, imdb_id, meta = _scrape_with_early_termination(
            query, content_type, show_id=show_id, is_movie=is_movie,
            season_number=season_number, episode_number=episode_number,
            max_sources=None)

        meta['show_title'] = show_title
        if episode_title:
            meta['episode_title'] = episode_title
```

Keep the existing sort (largest-first) and display code that follows (lines 546-564):

```python
        all_results.sort(key=lambda r: _parse_size_bytes(r.get('size', '')), reverse=True)

        for r in all_results:
            if season_number and 'episode' in r and 'season' not in r:
                r['season'] = season_number
            pl = episode_title if episode_number and episode_title else show_title
            add_scrape_result(r, poster_url, play_label=pl, meta=meta)
```

Also remove the now-duplicate `_seeder_ok` inline definition (lines 535-542) and the old `from concurrent.futures import ThreadPoolExecutor, as_completed` import at line 455 (it's now inside the helper).

- [ ] **Step 5: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "refactor: extract _seeder_ok, _quality_sort_key, _scrape_with_early_termination from mode=scrape"
```

---

### Task 3: Add _quick_download_one() helper

**Files:**
- Modify: `main.py` — add function after `_scrape_with_early_termination()` (before `if mode is None:`)

**Interfaces:**
- Consumes: `_scrape_with_early_termination()`, `_quality_sort_key()`, `ad_resolve()`, `download_manager.*`, `api_key()`, `clean_error()`, `notify()`, `xbmcgui.DialogProgress`
- Produces: `_quick_download_one(show_title, show_id, year, season_number, episode_number, episode_title, content_type, pdlg, episode_index=None, episode_total=None) -> bool` — returns True if downloaded, False if failed

- [ ] **Step 1: Add `_quick_download_one()` function**

Add after `_scrape_with_early_termination()`, before `if mode is None:`:

```python
def _quick_download_one(show_title, show_id, year, season_number, episode_number,
                        episode_title, content_type, pdlg,
                        episode_index=None, episode_total=None):
    """Scrape, auto-pick best source, download with fallback.
    Returns True on success, False on failure.
    pdlg is an already-created DialogProgress (caller manages create/close).
    episode_index/episode_total are for season-batch progress display."""
    key = api_key()
    if not key:
        notify("AllDebrid not authorized — use the PIN flow in settings")
        return False

    if season_number and episode_number:
        query = f"{show_title} S{int(season_number):02d}E{int(episode_number):02d}"
    else:
        query = f"{show_title} {year}".strip() if year else show_title

    is_movie = content_type == 'movies'
    max_sources = int(ADDON.getSetting('quick_download_max_sources') or '10')

    pdlg.update(0, "Scraping...")

    results, poster_url, imdb_id, meta = _scrape_with_early_termination(
        query, content_type, show_id=show_id, is_movie=is_movie,
        season_number=season_number, episode_number=episode_number,
        max_sources=max_sources)

    if not results:
        label = episode_title or show_title
        notify("No sources found for {}".format(label))
        return False

    results.sort(key=_quality_sort_key)

    label = episode_title or show_title
    timeout = int(ADDON.getSetting('magnet_timeout') or 120)
    fname = download_manager.safe_filename(show_title, season_number, episode_number)
    dest = os.path.join(download_manager.get_download_dir(), fname)

    for i, r in enumerate(results):
        if pdlg.iscanceled():
            return False

        prefix = ""
        if episode_index and episode_total:
            prefix = "Episode {}/{}: ".format(episode_index, episode_total)

        magnet = r.get('magnet', '')
        if not magnet:
            continue

        pdlg.update(10, "{}Resolving source {}/{}...".format(prefix, i + 1, len(results)))

        try:
            direct_url = ad_resolve(magnet, key, timeout=timeout,
                                    cancel_check=pdlg.iscanceled)
            if pdlg.iscanceled():
                return False

            est = _parse_size_bytes(r.get('size', ''))
            if est and not download_manager.has_space(dest, est):
                notify("Not enough disk space for {}".format(label))
                return False

            pdlg.update(15, "{}Downloading {}...".format(prefix, fname))

            def dl_cb(written, total, pct):
                label_txt = "{} ({} / {} MB)".format(
                    fname, written // 1048576, total // 1048576)
                pdlg.update(15 + pct * 85 // 100, label_txt)

            ok = download_manager.download_video(
                direct_url, dest,
                cancel_check=pdlg.iscanceled,
                progress_callback=dl_cb,
                source_id=magnet)

            if not ok:
                if pdlg.iscanceled():
                    return False
                continue

            poster_local = None
            if poster_url:
                poster_local = download_manager.cache_artwork(
                    poster_url, os.path.join(download_manager.art_dir(),
                                             fname + '.poster.jpg'))

            entry = {
                'id': fname,
                'title': label,
                'show_title': show_title,
                'season': season_number,
                'episode': episode_number,
                'file_path': dest,
                'size_bytes': os.path.getsize(dest),
                'date_added': int(time.time()),
                'mediatype': 'episode' if episode_number else 'movie',
                'plot': '',
                'poster_path': poster_local,
            }
            download_manager.add_to_manifest(entry)
            notify("Downloaded: {}".format(label))
            return True

        except AllDebridError:
            continue

    notify("All {} sources failed for {}".format(len(results), label))
    return False
```

- [ ] **Step 2: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add _quick_download_one() helper (scrape→sort→fallback→download)"
```

---

### Task 4: Add mode=quick_download handler

**Files:**
- Modify: `main.py` — add new handler before `# --- Auth: AllDebrid PIN flow ---` (around line 584)

**Interfaces:**
- Consumes: `_quick_download_one()`, `tmdb.get_episodes()`, `xbmcgui.Dialog().multiselect()`, `xbmcgui.DialogProgress`
- Produces: `mode=quick_download` handler supporting single-item and season-batch download

- [ ] **Step 1: Add the quick_download handler**

Insert before `# --- Auth: AllDebrid PIN flow ---`:

```python
# --- Quick Download: auto-pick best source and download ---
elif mode[0] == 'quick_download':
    show_title = args.get('show_title', [''])[0]
    show_id = args.get('show_id', [None])[0]
    year = args.get('year', [''])[0]
    season_number = args.get('season_number', [None])[0]
    episode_number = args.get('episode_number', [None])[0]
    episode_title = args.get('episode_title', [''])[0]
    content_type = args.get('content_type', ['all'])[0]

    pdlg = xbmcgui.DialogProgress()
    pdlg.create("Quick Download", "Starting...")
    try:
        if season_number and not episode_number:
            # Season batch — show multi-select episode picker
            episodes = tmdb.get_episodes(int(show_id), int(season_number),
                                         tmdb_api_key(), tmdb_lang())
            if not episodes:
                pdlg.close()
                notify("No episodes found for this season")
                xbmcplugin.endOfDirectory(addon_handle)
            else:
                ep_labels = [ep.get('name', 'Episode {}'.format(ep['episode_number']))
                             for ep in episodes]
                selected = xbmcgui.Dialog().multiselect("Select episodes (OK = all)", ep_labels)

                if selected is None:
                    # User cancelled
                    pass
                elif len(selected) == 0:
                    # OK with nothing selected = download all
                    selected = list(range(len(episodes)))
                # else: download only selected indices

                if selected is not None:
                    total = len(selected)
                    for idx, ep_idx in enumerate(selected):
                        if pdlg.iscanceled():
                            break
                        ep = episodes[ep_idx]
                        _quick_download_one(
                            show_title, show_id, year,
                            season_number, str(ep['episode_number']),
                            ep.get('name', ''),
                            content_type, pdlg,
                            episode_index=idx + 1, episode_total=total)
        else:
            # Single item (movie or episode)
            _quick_download_one(
                show_title, show_id, year,
                season_number, episode_number, episode_title,
                content_type, pdlg)
    finally:
        try:
            pdlg.close()
        except Exception:
            pass

    xbmcplugin.endOfDirectory(addon_handle)

```

- [ ] **Step 2: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add mode=quick_download handler (single + season multi-select)"
```

---

### Task 5: Add context menu items to movie/episode/season ListItems

**Files:**
- Modify: `main.py:352` (movie ListItem in `mode=search`) — add context menu
- Modify: `main.py:410` (episode ListItem in `mode=episodes`) — add context menu
- Modify: `main.py:380` (season ListItem in `mode=seasons`) — add context menu

**Interfaces:**
- Consumes: `mode=quick_download` URL params, `build_url()`, existing ListItem creation code
- Produces: "Quick Download" / "Quick Download Season" context menu items

- [ ] **Step 1: Add context menu to movie ListItems**

In `mode=search`, after the movie ListItem is created and before `addDirectoryItem` (around line 352), add the context menu. The current code is:

```python
                label = f"{m['title']} ({m.get('year', '')})"
                li = xbmcgui.ListItem(label)
                set_info(li, m, is_folder=True)
                xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)
```

Change to:

```python
                label = f"{m['title']} ({m.get('year', '')})"
                li = xbmcgui.ListItem(label)
                set_info(li, m, is_folder=True)
                qdl_url = build_url({'mode': 'quick_download', 'show_title': m['title'],
                                     'year': m.get('year', ''),
                                     'show_id': str(m['id']),
                                     'content_type': 'movies'})
                li.addContextMenuItems([('Quick Download', 'RunPlugin({})'.format(qdl_url))])
                xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)
```

- [ ] **Step 2: Add context menu to episode ListItems**

In `mode=episodes`, after each episode ListItem is created and before `addDirectoryItem` (around line 410), add the context menu. The current code is:

```python
        li.setInfo('video', info)
        xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)
```

Change to:

```python
        li.setInfo('video', info)
        qdl_url = build_url({'mode': 'quick_download', 'show_title': show_title,
                             'show_id': str(show_id),
                             'season_number': str(season_number),
                             'episode_number': str(ep['episode_number']),
                             'episode_title': ep.get('name', ''),
                             'content_type': 'shows'})
        li.addContextMenuItems([('Quick Download', 'RunPlugin({})'.format(qdl_url))])
        xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)
```

- [ ] **Step 3: Add context menu to season ListItems**

In `mode=seasons`, after each season ListItem is created and before `addDirectoryItem` (around line 380), add the context menu. The current code is:

```python
        li = xbmcgui.ListItem(label)
        poster = s.get('poster_url')
        if poster:
            li.setArt({'poster': poster})
        xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)
```

Change to:

```python
        li = xbmcgui.ListItem(label)
        poster = s.get('poster_url')
        if poster:
            li.setArt({'poster': poster})
        qdl_url = build_url({'mode': 'quick_download', 'show_title': show_title,
                             'show_id': str(show_id),
                             'season_number': str(s['season_number']),
                             'content_type': 'shows'})
        li.addContextMenuItems([('Quick Download Season', 'RunPlugin({})'.format(qdl_url))])
        xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)
```

- [ ] **Step 4: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: add Quick Download context menu items to movie/episode/season ListItems"
```

---

## Manual Test Checklist (post-implementation)

Run these in Kodi after all five tasks are complete:

1. **Movie quick download** — search a movie → long-press → Quick Download → progress dialog shows scrape/resolve/download → file appears in My Downloads
2. **Episode quick download** — browse show → season → episode → long-press → Quick Download → same flow
3. **Season quick download (all)** — browse show → season → long-press → Quick Download Season → multiselect dialog → OK with nothing selected → all episodes download sequentially
4. **Season quick download (selective)** — same flow → select 3 episodes → only those 3 download
5. **Season quick download (cancel)** — same flow → back button → nothing happens
6. **Source fallback** — find a title where the first source fails to resolve (bad magnet) → verify it tries the next source automatically
7. **Early termination** — set `quick_download_max_sources` to 2 → verify scraping stops after 2 viable results
8. **All sources fail** — search a nonexistent title → "No sources found" notification
9. **Episode failure in season** — if one episode has no sources → notify + continue to next episode
10. **Cancel mid-season-batch** — cancel during a season batch → already-downloaded episodes remain in manifest
11. **Existing scrape still works** — browse to a movie normally → click (not long-press) → source list appears as before (largest-first sort, all scrapers, no early termination)
