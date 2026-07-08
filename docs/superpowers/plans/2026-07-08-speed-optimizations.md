# Speed Optimizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut perceived scrape time by ~50% and reduce magnet polling HTTP calls by ~80%.

**Architecture:** Three independent changes: Torrentz2 parallel detail fetches (scraper only), AllDebrid exponential backoff (resolver only), and parallel scrape + progress dialog (main.py scrape handler). Tasks 1 and 2 touch unrelated files and can run in parallel.

**Tech Stack:** Python 3, ThreadPoolExecutor, xbmcgui.DialogProgress, AllDebrid API v4.1

## Global Constraints

- No new files created — modify existing scraper, resolver, and main handler
- Existing result dict format unchanged — scrapers still return `{"show_title", "url", "type", ...}`
- Cancel behavior preserved — progress dialog cancel returns partial results
- Progress callback API unchanged — `progress_callback(state, pct, eta)` still works

---

### Task 1: Torrentz2 Parallel Detail Fetches

**Files:**
- Modify: `scrapers/torrentz2.py:56-64`

**Interfaces:**
- Consumes: (none)
- Produces: `search(query)` returns list of result dicts — same format, now fetches detail pages in parallel

- [ ] **Step 1: Replace sequential detail fetches with ThreadPoolExecutor**

Replace the current block:

```python
    # Fetch magnet links from detail pages (limit to 10 to avoid hammering)
    for r in results[:10]:
        detail = _fetch(r["_detail_url"])
        if not detail:
            continue
        magnet = _extract_magnet(detail)
        if magnet:
            r["url"] = magnet
        del r["_detail_url"]

    return [r for r in results if "url" in r and r.get("url")]
```

With:

```python
    # Fetch magnet links from detail pages in parallel (limit 10)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_magnet(r):
        detail = _fetch(r["_detail_url"])
        if detail:
            magnet = _extract_magnet(detail)
            if magnet:
                r["url"] = magnet
        del r["_detail_url"]
        return r

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch_magnet, r): r for r in results[:10]}
        for future in as_completed(futures):
            pass

    return [r for r in results if "url" in r and r.get("url")]
```

- [ ] **Step 2: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('scrapers/torrentz2.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add scrapers/torrentz2.py
git commit -m "perf: parallel torrentz2 detail page fetches (5 workers)"
```

---

### Task 2: AllDebrid Exponential Backoff

**Files:**
- Modify: `resources/lib/alldebrid.py:69` — polling loop sleep interval

**Interfaces:**
- Consumes: `resolve(url, api_key, timeout=120, poll_interval=1, cancel_check=None, progress_callback=None)` — current signature
- Produces: Same signature, now uses exponential backoff for poll intervals

- [ ] **Step 1: Add backoff logic to polling loop**

In the `resolve()` function, after `time.sleep(poll_interval)`, replace the fixed `poll_interval` variable with a dynamic backoff:

Replace:
```python
        while time.time() < deadline:
            if cancel_check and cancel_check():
                raise AllDebridError("Cancelled by user")
            time.sleep(poll_interval)
```

With:
```python
        poll_count = 0
        while time.time() < deadline:
            if cancel_check and cancel_check():
                raise AllDebridError("Cancelled by user")
            time.sleep(poll_interval)
            poll_count += 1
            if poll_count == 5:
                poll_interval = 2
            elif poll_count == 10:
                poll_interval = 4
            elif poll_count == 15:
                poll_interval = 8
```

- [ ] **Step 2: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('resources/lib/alldebrid.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add resources/lib/alldebrid.py
git commit -m "perf: exponential backoff for AllDebrid magnet polling"
```

---

### Task 3: Parallel Scrape + Progress Dialog

**Files:**
- Modify: `main.py:314-370` — scrape handler

**Interfaces:**
- Consumes: `scraper_runner.search_all()`, `tmdb.get_imdb_id()`, `tmdb.get_poster()`, `torrentio.search_imdb()`, `add_scrape_result()`, `build_url()`, `xbmcgui.DialogProgress`
- Produces: Scrape results rendered via `xbmcplugin.addDirectoryItem()` with progress dialog

- [ ] **Step 1: Replace serial scrape handler with parallel futures + progress dialog**

Replace the entire scrape handler block from the mode check to `endOfDirectory`:

Lines to replace (approximately lines 314-370):

Old:
```python
    results = scraper_runner.search_all(query, content_type=content_type)

    # Torrentio via IMDB ID — covers 24+ trackers in one call
    if show_id:
        try:
            is_movie = content_type == 'movies'
            imdb_id = tmdb.get_imdb_id(int(show_id), tmdb_api_key(), is_movie=is_movie)
            if imdb_id:
                if is_movie:
                    tr = torrentio.search_imdb(imdb_id, is_movie=True)
                elif season_number and episode_number:
                    tr = torrentio.search_imdb(imdb_id, int(season_number), int(episode_number))
                else:
                    tr = []
                results.extend(tr)
        except Exception:
            pass

    # TMDB poster for artwork on every result
    poster_url = None
    if show_id:
        try:
            poster_url = tmdb.get_poster(int(show_id), tmdb_api_key(),
                                         is_movie=(content_type == 'movies'))
        except Exception:
            pass

    # Sort by file size descending (largest first)
    results.sort(key=lambda r: _parse_size_bytes(r.get('size', '')), reverse=True)

    for r in results:
        if season_number and 'episode' in r and 'season' not in r:
            r['season'] = season_number
        pl = episode_title if episode_number and episode_title else show_title
        add_scrape_result(r, poster_url, play_label=pl)

    if not results:
        label = "No sources found"
        if episode_number:
            label += f" for S{int(season_number):02d}E{int(episode_number):02d}"
        li = xbmcgui.ListItem(label)
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
```

New:
```python
    from concurrent.futures import ThreadPoolExecutor, as_completed

    is_movie = content_type == 'movies'

    pdlg = xbmcgui.DialogProgress()
    pdlg.create("Searching for sources...", "Starting...")

    all_results = []
    poster_url = None
    pending = 0
    done = 0

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}

            # Future 1: all HTML scrapers
            futures[pool.submit(scraper_runner.search_all, query, content_type)] = "scrapers"
            pending += 1

            # Future 2: IMDB ID lookup
            if show_id:
                futures[pool.submit(tmdb.get_imdb_id, int(show_id), tmdb_api_key(),
                                    is_movie=is_movie)] = "imdb"
                pending += 1

            # Future 3: poster
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
                    pdlg.update(int(done / pending * 100),
                                "{} sources".format(len(all_results)))
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

            # Wait for Torrentio if launched
            if torrentio_future:
                try:
                    tr = torrentio_future.result()
                    all_results.extend(tr)
                except Exception:
                    pass
                done += 1
                pdlg.update(100, "{} sources".format(len(all_results)))

    finally:
        pdlg.close()
```

- [ ] **Step 2: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "perf: parallel scrape with progress dialog"
```
