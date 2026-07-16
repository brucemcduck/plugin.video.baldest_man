# Inward (Show-Centric) Search History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Search History show the shows/movies the user drilled into (with posters), linking straight to seasons/scrape — no TMDB re-search, no pick-a-match list.

**Architecture:** Single-file change to `main.py`. History schema shifts from query-centric to show/movie-centric. Record point moves inward from `mode=search` to `mode=seasons` (shows) and `mode=scrape` (movies), gated by a `src=search` URL flag. The Search History view renders show/movie folders with posters linking directly to `seasons`/`scrape`.

**Tech Stack:** Python 3, Kodi plugin API (`xbmc`/`xbmcgui`/`xbmcplugin`/`xbmcaddon`), JSON file in temp dir.

## Global Constraints

- Single file modified: `main.py` (at repo root `/home/bryce/kodi-project/plugin.video.baldest_man/main.py`).
- No test framework exists — the plugin runs inside Kodi. The automated gate for every task is `python -m py_compile main.py` (must exit 0). The full manual Kodi verification checklist is in `docs/superpowers/specs/2026-07-16-search-history-inward-design.md`.
- History file path `_SEARCH_HISTORY` (main.py:67) is unchanged — ephemeral temp file; the schema break is acceptable and legacy entries are skipped on render.
- `_MAX_HISTORY` stays 20 (main.py:68).
- Do not add comments to code unless asked.
- Commit after each task with the exact message given.

**Working directory for all commands:** `/home/bryce/kodi-project/plugin.video.baldest_man`

---

### Task 1: Update `_add_search_history` to a record-based schema

**Files:**
- Modify: `main.py:89-99` (the `_add_search_history` function)

**Interfaces:**
- Consumes: `_load_search_history()`, `_save_search_history()`, `_MAX_HISTORY` (all unchanged, main.py:68-86)
- Produces: `_add_search_history(record)` — takes a single dict with keys `kind`, `show_id`, `title`, `year`, `poster_url`, `content_type`; adds `timestamp` internally; dedups by `show_id`; inserts at front; trims to `_MAX_HISTORY`.

- [ ] **Step 1: Replace the function body**

Current code at `main.py:89-99`:

```python
def _add_search_history(query, content_type):
    """Add or update a search entry. Dedupes by query (case-insensitive),
    moves to front, trims to _MAX_HISTORY."""
    history = _load_search_history()
    query_lower = query.lower()
    history = [h for h in history if h.get('query', '').lower() != query_lower]
    history.insert(0, {'query': query, 'content_type': content_type,
                       'timestamp': int(time.time())})
    if len(history) > _MAX_HISTORY:
        history = history[:_MAX_HISTORY]
    _save_search_history(history)
```

Replace with:

```python
def _add_search_history(record):
    """Add or update a history entry. Dedupes by show_id, moves to front,
    trims to _MAX_HISTORY. record is a dict with show_id, kind, title,
    year, poster_url, content_type; timestamp is added here."""
    history = _load_search_history()
    show_id = record.get('show_id')
    history = [h for h in history if h.get('show_id') != show_id]
    record['timestamp'] = int(time.time())
    history.insert(0, record)
    if len(history) > _MAX_HISTORY:
        history = history[:_MAX_HISTORY]
    _save_search_history(history)
```

- [ ] **Step 2: Verify it compiles**

Run: `python -m py_compile main.py`
Expected: exits 0, no output.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "refactor: _add_search_history takes a record dict, dedups by show_id"
```

---

### Task 2: Stop recording history in `mode=search`; enrich folder URLs with `src=search` + poster/year

**Files:**
- Modify: `main.py:586-621` (the `mode=search` handler up to the `if query:` block) and the show-folder URL at `main.py:627` and movie-folder URL at `main.py:636`.

**Interfaces:**
- Consumes: Task 1's new `_add_search_history(record)` (no longer called here — this task *removes* the calls).
- Produces: show-folder URLs carry `year`, `poster_url`, `src=search`; movie-folder URLs carry `poster_url`, `src=search`. These params are consumed by Task 3 (`mode=seasons`) and Task 4 (`mode=scrape`).

- [ ] **Step 1: Remove the dead `q_param` re-run path and both history calls**

Current code at `main.py:594-621`:

```python
    # Check for q param (re-run from history) — use cache if available, skip dialog
    q_param = args.get('q', [None])[0]
    cached = _read_search_cache()
    if q_param:
        query = q_param
        if cached and cached.get('content_type') == content_type and cached.get('query', '') == query:
            shows = cached.get('shows', [])
            movies = cached.get('movies', [])
        else:
            shows = tmdb.search_shows(query, key, lang) if content_type in ('shows', 'all') else []
            movies = tmdb.search_movies(query, key, lang) if content_type in ('movies', 'all') else []
            _save_search_cache(content_type, shows, movies, query)
        _add_search_history(query, content_type)
    elif cached and cached.get('content_type') == content_type:
        shows = cached.get('shows', [])
        movies = cached.get('movies', [])
        query = cached.get('query', '')
    else:
        dialog = xbmcgui.Dialog()
        query = dialog.input(f'Search {content_type.capitalize()}',
                             type=xbmcgui.INPUT_ALPHANUM)
        if not query:
            xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
        else:
            shows = tmdb.search_shows(query, key, lang) if content_type in ('shows', 'all') else []
            movies = tmdb.search_movies(query, key, lang) if content_type in ('movies', 'all') else []
            _save_search_cache(content_type, shows, movies, query)
            _add_search_history(query, content_type)
```

Replace with (the `q_param` branch is deleted entirely; the cache-hit and dialog branches remain, minus the history call):

```python
    cached = _read_search_cache()
    if cached and cached.get('content_type') == content_type:
        shows = cached.get('shows', [])
        movies = cached.get('movies', [])
        query = cached.get('query', '')
    else:
        dialog = xbmcgui.Dialog()
        query = dialog.input(f'Search {content_type.capitalize()}',
                             type=xbmcgui.INPUT_ALPHANUM)
        if not query:
            xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
        else:
            shows = tmdb.search_shows(query, key, lang) if content_type in ('shows', 'all') else []
            movies = tmdb.search_movies(query, key, lang) if content_type in ('movies', 'all') else []
            _save_search_cache(content_type, shows, movies, query)
```

- [ ] **Step 2: Enrich the show-folder URL with year/poster/src**

Current code at `main.py:627` (line numbers will have shifted up by ~13 after step 1; locate by the `mode=seasons` build_url inside the `for s in shows:` loop):

```python
            for s in shows:
                url = build_url({'mode': 'seasons', 'show_id': str(s['id']),
                                 'show_title': s['title']})
                label = f"{s['title']} ({s.get('year', '')})"
```

Replace the `url = build_url(...)` line with:

```python
            for s in shows:
                url = build_url({'mode': 'seasons', 'show_id': str(s['id']),
                                 'show_title': s['title'], 'year': s.get('year', ''),
                                 'poster_url': s.get('poster_url', ''), 'src': 'search'})
                label = f"{s['title']} ({s.get('year', '')})"
```

- [ ] **Step 3: Enrich the movie-folder URL with poster/src**

Current code at the `for m in movies:` loop (the `mode=scrape` build_url):

```python
            for m in movies:
                url = build_url({'mode': 'scrape', 'show_title': m['title'],
                                 'year': m.get('year', ''),
                                 'show_id': str(m['id']),
                                 'content_type': 'movies'})
```

Replace the `url = build_url(...)` with:

```python
            for m in movies:
                url = build_url({'mode': 'scrape', 'show_title': m['title'],
                                 'year': m.get('year', ''),
                                 'show_id': str(m['id']),
                                 'poster_url': m.get('poster_url', ''),
                                 'content_type': 'movies', 'src': 'search'})
```

- [ ] **Step 4: Verify it compiles**

Run: `python -m py_compile main.py`
Expected: exits 0, no output.

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "refactor: mode=search no longer records history; folder URLs carry src=search + poster/year"
```

---

### Task 3: Record show history in `mode=seasons`

**Files:**
- Modify: `main.py` — the `mode=seasons` handler (starts at `elif mode[0] == 'seasons':`, currently main.py:660).

**Interfaces:**
- Consumes: Task 1's `_add_search_history(record)`; the `src`, `year`, `poster_url` URL params produced by Task 2.
- Produces: a `show` history record whenever a user drills into a show from search (or re-enters from Search History, which also carries `src=search`).

- [ ] **Step 1: Add the history-record block at the top of the handler**

Current code (start of the `mode=seasons` handler):

```python
elif mode[0] == 'seasons':
    show_id = int(args.get('show_id', ['0'])[0])
    show_title = args.get('show_title', [''])[0]

    seasons = tmdb.get_seasons(show_id, tmdb_api_key(), tmdb_lang())
```

Replace with:

```python
elif mode[0] == 'seasons':
    show_id = int(args.get('show_id', ['0'])[0])
    show_title = args.get('show_title', [''])[0]

    src = args.get('src', [''])[0]
    if src == 'search':
        _add_search_history({
            'kind': 'show',
            'show_id': show_id,
            'title': show_title,
            'year': args.get('year', [''])[0],
            'poster_url': args.get('poster_url', [''])[0],
            'content_type': 'shows',
        })

    seasons = tmdb.get_seasons(show_id, tmdb_api_key(), tmdb_lang())
```

Note: `_add_search_history` adds the `timestamp` key itself (Task 1), so it is omitted from the record here.

- [ ] **Step 2: Verify it compiles**

Run: `python -m py_compile main.py`
Expected: exits 0, no output.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: record show history on drill-in via mode=seasons (src=search gate)"
```

---

### Task 4: Record movie history in `mode=scrape`

**Files:**
- Modify: `main.py` — the `mode=scrape` handler (starts at `elif mode[0] == 'scrape':`, currently main.py:726).

**Interfaces:**
- Consumes: Task 1's `_add_search_history(record)`; the `src`, `poster_url` URL params produced by Task 2; existing `show_title`, `year`, `show_id`, `content_type` params.
- Produces: a `movie` history record whenever a user scrapes a movie from search (gated by `src=search` AND `content_type='movies'`, so show-episode scrapes are excluded).

- [ ] **Step 1: Add the history-record block after the param reads**

Current code (start of the `mode=scrape` handler):

```python
elif mode[0] == 'scrape':
    show_title = args.get('show_title', [''])[0]
    show_id = args.get('show_id', [None])[0]
    year = args.get('year', [''])[0]
    season_number = args.get('season_number', [None])[0]
    episode_number = args.get('episode_number', [None])[0]
    episode_title = args.get('episode_title', [''])[0]
    content_type = args.get('content_type', ['all'])[0]

    cache_key = json.dumps({'show_title': show_title, 'show_id': show_id,
```

Replace with (insert the `src` read and record block before `cache_key`):

```python
elif mode[0] == 'scrape':
    show_title = args.get('show_title', [''])[0]
    show_id = args.get('show_id', [None])[0]
    year = args.get('year', [''])[0]
    season_number = args.get('season_number', [None])[0]
    episode_number = args.get('episode_number', [None])[0]
    episode_title = args.get('episode_title', [''])[0]
    content_type = args.get('content_type', ['all'])[0]

    src = args.get('src', [''])[0]
    if src == 'search' and content_type == 'movies':
        _add_search_history({
            'kind': 'movie',
            'show_id': int(show_id) if show_id else 0,
            'title': show_title,
            'year': year,
            'poster_url': args.get('poster_url', [''])[0],
            'content_type': 'movies',
        })

    cache_key = json.dumps({'show_title': show_title, 'show_id': show_id,
```

Note: `show_id` from URL params is a string or `None`; coerce to `int` for the record (matching the schema). The `0` fallback only occurs for malformed URLs and won't dedup-collide with real IDs in practice.

- [ ] **Step 2: Verify it compiles**

Run: `python -m py_compile main.py`
Expected: exits 0, no output.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: record movie history on scrape via mode=scrape (src=search + movies gate)"
```

---

### Task 5: Rewrite `mode=search_history` to render show/movie folders with posters

**Files:**
- Modify: `main.py` — the `mode=search_history` handler (starts at `elif mode[0] == 'search_history':`, currently main.py:861).

**Interfaces:**
- Consumes: `_load_search_history()`; the existing `set_info(li, item, is_folder)` helper (main.py:121); `build_url()`. History records have `kind`, `show_id`, `title`, `year`, `poster_url`, `content_type`, `timestamp`.
- Produces: a directory of show/movie ListItems with posters, each linking directly to `mode=seasons` (shows) or `mode=scrape` (movies), both carrying `src=search` so re-entry re-bumps the record.

- [ ] **Step 1: Replace the render loop**

Current code (the full `mode=search_history` handler):

```python
elif mode[0] == 'search_history':
    history = _load_search_history()

    if not history:
        li = xbmcgui.ListItem("No search history yet")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)
    else:
        for idx, h in enumerate(history):
            ct = h.get('content_type', 'all')
            ct_label = ct.capitalize()
            query = h.get('query', '')
            label = "[{}] {}".format(ct_label, query)

            url = build_url({'mode': 'search', 'content_type': ct,
                             'q': query})
            li = xbmcgui.ListItem(label)

            del_url = build_url({'mode': 'delete_history', 'index': str(idx)})
            clear_url = build_url({'mode': 'clear_history'})
            li.addContextMenuItems([
                ('Delete', 'RunPlugin({})'.format(del_url)),
                ('Clear All', 'RunPlugin({})'.format(clear_url)),
            ])

            xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
```

Replace with:

```python
elif mode[0] == 'search_history':
    history = _load_search_history()

    if not history:
        li = xbmcgui.ListItem("No search history yet")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)
    else:
        for idx, h in enumerate(history):
            if not h.get('show_id') or not h.get('kind'):
                continue
            kind = h.get('kind')
            title = h.get('title', '')
            year = h.get('year', '')
            poster_url = h.get('poster_url', '')
            label = f"{title} ({year})" if year else title

            if kind == 'show':
                url = build_url({'mode': 'seasons',
                                 'show_id': str(h['show_id']),
                                 'show_title': title, 'year': year,
                                 'poster_url': poster_url, 'src': 'search'})
            else:
                url = build_url({'mode': 'scrape', 'show_title': title,
                                 'year': year, 'show_id': str(h['show_id']),
                                 'poster_url': poster_url,
                                 'content_type': 'movies', 'src': 'search'})

            li = xbmcgui.ListItem(label)
            set_info(li, {'title': title, 'poster_url': poster_url},
                     is_folder=True)

            del_url = build_url({'mode': 'delete_history', 'index': str(idx)})
            clear_url = build_url({'mode': 'clear_history'})
            li.addContextMenuItems([
                ('Delete', 'RunPlugin({})'.format(del_url)),
                ('Clear All', 'RunPlugin({})'.format(clear_url)),
            ])

            xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
```

Key points: legacy entries (no `show_id`/`kind`) are skipped via `continue` — index-based delete still works for the remaining entries because `idx` is the position in the loaded list (delete_history pops by that same index, see `main.py:890`). `set_info` guards on `poster_url`/`overview` presence (main.py:121-132), so passing no `overview` is safe.

- [ ] **Step 2: Verify it compiles**

Run: `python -m py_compile main.py`
Expected: exits 0, no output.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: Search History renders show/movie folders with posters, links to seasons/scrape"
```

---

## Post-implementation

All five tasks land the full feature. The manual Kodi verification checklist (10 items) is in `docs/superpowers/specs/2026-07-16-search-history-inward-design.md` under "Verification" — run through it in Kodi after deploying the plugin. No automated tests exist for this codebase.
