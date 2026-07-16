# Search History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Search History" folder to the root menu that shows the last 20 searches, lets users re-run them with one click, and supports per-item delete and clear-all.

**Architecture:** A JSON file in the temp directory stores search history. Three helper functions manage load/save/add. A new `mode=search_history` handler displays the list. Two small handlers (`mode=delete_history`, `mode=clear_history`) handle deletion. The existing `mode=search` handler saves each successful search.

**Tech Stack:** Python 3, Kodi Matrix+ (xbmcaddon/xbmcgui/xbmcplugin), JSON file I/O.

## Global Constraints

- `notify(msg)` helper exists at main.py:44 — use it for all user-facing messages
- `build_url(query)` helper exists at main.py:35 — use it for all plugin URLs
- `ADDON` is the global `xbmcaddon.Addon()` instance in main.py
- `addon_handle` is the global plugin handle in main.py
- `tempfile.gettempdir()` is used for cache files (see `_SEARCH_CACHE` at main.py:49)
- `json` and `os` are already imported at the top of main.py
- `xbmcgui.Dialog().notification(title, msg, icon, timeout)` for notifications (existing `notify()` wraps this)
- `xbmcgui.ListItem(label)` for list items
- `xbmcplugin.addDirectoryItem(handle, url, listItem, isFolder)` for directory items
- `xbmcplugin.endOfDirectory(handle, cacheToDisc=False)` to close directory listings
- No automated test framework; verification is `python3 -c "import ast..."` syntax check
- One commit per task

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `main.py` | History helpers (`_load_search_history`, `_save_search_history`, `_add_search_history`) | Task 1 |
| `main.py` | Save searches in `mode=search` | Task 2 |
| `main.py` | `mode=search_history` display handler + root menu item | Task 3 |
| `main.py` | `mode=delete_history` + `mode=clear_history` handlers | Task 4 |

All changes in `main.py` — no new files, no settings changes.

---

### Task 1: Add search history helpers

**Files:**
- Modify: `main.py` — add three functions and two constants after the existing cache path definitions (around line 50, after `_SCRAPE_CACHE`)

**Interfaces:**
- Consumes: `os`, `json`, `tempfile` (already imported)
- Produces:
  - `_SEARCH_HISTORY` (str) — path to history JSON file
  - `_MAX_HISTORY = 20` (int) — max entries
  - `_load_search_history() -> list` — returns list of `{"query": str, "content_type": str, "timestamp": int}` dicts, `[]` on missing/corrupt file
  - `_save_search_history(history) -> None` — writes list to JSON, silently ignores errors
  - `_add_search_history(query, content_type) -> None` — dedupes by query (case-insensitive), moves to front, trims to `_MAX_HISTORY`

- [ ] **Step 1: Add constants and helpers**

Add after the `_SCRAPE_CACHE` line (around main.py:50), before `_save_search_cache`:

```python
_SEARCH_HISTORY = os.path.join(tempfile.gettempdir(), "baldman_search_history.json")
_MAX_HISTORY = 20


def _load_search_history():
    """Load search history list. Returns [] on missing/corrupt file."""
    try:
        with open(_SEARCH_HISTORY) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _save_search_history(history):
    """Write history list to JSON. Silently ignores errors."""
    try:
        with open(_SEARCH_HISTORY, 'w') as f:
            json.dump(history, f)
    except OSError:
        pass


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

- [ ] **Step 2: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verify `time` is imported**

Run: `grep -n "^import time" main.py`
Expected: at least one match (time is already imported for the download handler)

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add search history helpers (load/save/add with dedup and trim)"
```

---

### Task 2: Save searches in mode=search

**Files:**
- Modify: `main.py` — add one line in `mode=search` handler (around line 571, after `_save_search_cache`)

**Interfaces:**
- Consumes: `_add_search_history(query, content_type)` from Task 1
- Produces: searches are saved to history automatically

- [ ] **Step 1: Add the save call**

In `mode=search` (around main.py:571), the current code after a successful search is:

```python
        else:
            shows = tmdb.search_shows(query, key, lang) if content_type in ('shows', 'all') else []
            movies = tmdb.search_movies(query, key, lang) if content_type in ('movies', 'all') else []
            _save_search_cache(content_type, shows, movies, query)
```

Add `_add_search_history` after `_save_search_cache`:

```python
        else:
            shows = tmdb.search_shows(query, key, lang) if content_type in ('shows', 'all') else []
            movies = tmdb.search_movies(query, key, lang) if content_type in ('movies', 'all') else []
            _save_search_cache(content_type, shows, movies, query)
            _add_search_history(query, content_type)
```

This is in the `else` branch (new query, not a cache hit from back-navigation), so history only saves on fresh searches.

- [ ] **Step 2: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: save searches to history in mode=search"
```

---

### Task 3: Add mode=search_history handler + root menu item

**Files:**
- Modify: `main.py` — add `mode=search_history` handler (before `# --- Auth: AllDebrid PIN flow ---`, around line 820)
- Modify: `main.py` — add "Search History" folder item in root menu (after the three search items, around line 483)

**Interfaces:**
- Consumes: `_load_search_history()` from Task 1, `build_url()`, `xbmcgui.ListItem`, `xbmcplugin.addDirectoryItem`
- Produces: `mode=search_history` handler that displays history list

- [ ] **Step 1: Add "Search History" to root menu**

In the root menu (`if mode is None:`, around main.py:483), after the three search items loop and before "Continue Watching", add:

```python
    url = build_url({'mode': 'search_history'})
    xbmcplugin.addDirectoryItem(addon_handle, url,
                                xbmcgui.ListItem("Search History"), isFolder=True)
```

The current code around line 483 is:

```python
    for label, content_type in [
        ('Search Shows', 'shows'),
        ('Search Movies', 'movies'),
        ('Search All', 'all'),
    ]:
        url = build_url({'mode': 'search', 'content_type': content_type})
        xbmcplugin.addDirectoryItem(addon_handle, url,
                                    xbmcgui.ListItem(label), isFolder=True)

    # Continue Watching — re-scrape last watched TMDB content
```

Change to:

```python
    for label, content_type in [
        ('Search Shows', 'shows'),
        ('Search Movies', 'movies'),
        ('Search All', 'all'),
    ]:
        url = build_url({'mode': 'search', 'content_type': content_type})
        xbmcplugin.addDirectoryItem(addon_handle, url,
                                    xbmcgui.ListItem(label), isFolder=True)

    url = build_url({'mode': 'search_history'})
    xbmcplugin.addDirectoryItem(addon_handle, url,
                                xbmcgui.ListItem("Search History"), isFolder=True)

    # Continue Watching — re-scrape last watched TMDB content
```

- [ ] **Step 2: Add the search_history handler**

Insert before `# --- Auth: AllDebrid PIN flow ---` (around line 820):

```python
# --- Search History: show recent searches ---
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

Note: The `url` for re-running a search passes `q` as a param. The existing `mode=search` handler reads the query from an input dialog — we need it to accept a `q` param as an alternative. That's handled in Step 3.

- [ ] **Step 3: Make mode=search accept a q param for re-runs**

In `mode=search` (around main.py:556), the current code checks the cache, then shows an input dialog. Add a check for a `q` URL param first — if present, skip the dialog and use it directly:

Current code (around main.py:556):

```python
    # Check cache — skip dialog on back-navigation
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
            _add_search_history(query, content_type)
```

Change to:

```python
    # Check for q param (re-run from history) — skip dialog
    q_param = args.get('q', [None])[0]
    if q_param:
        query = q_param
        shows = tmdb.search_shows(query, key, lang) if content_type in ('shows', 'all') else []
        movies = tmdb.search_movies(query, key, lang) if content_type in ('movies', 'all') else []
        _save_search_cache(content_type, shows, movies, query)
        _add_search_history(query, content_type)
    # Check cache — skip dialog on back-navigation
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

Note: `cached` is still defined before this block — move the `cached = _read_search_cache()` call to after the `q_param` check, or leave it (it's harmless to read the cache even when `q` is present). The simplest approach: leave `cached = _read_search_cache()` where it is and just add the `q_param` check as the first branch.

- [ ] **Step 4: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: add mode=search_history handler + root menu item + q param for re-runs"
```

---

### Task 4: Add delete_history and clear_history handlers

**Files:**
- Modify: `main.py` — add two handlers after the `mode=search_history` handler

**Interfaces:**
- Consumes: `_load_search_history()`, `_save_search_history()` from Task 1
- Produces: `mode=delete_history` (removes one entry by index) and `mode=clear_history` (empties history)

- [ ] **Step 1: Add delete_history and clear_history handlers**

Insert immediately after the `mode=search_history` handler (before `# --- Auth: AllDebrid PIN flow ---`):

```python
# --- Delete single history entry ---
elif mode[0] == 'delete_history':
    idx = int(args.get('index', ['-1'])[0])
    history = _load_search_history()
    if 0 <= idx < len(history):
        history.pop(idx)
        _save_search_history(history)
        notify("Search history entry deleted")
    xbmcplugin.endOfDirectory(addon_handle)

# --- Clear all search history ---
elif mode[0] == 'clear_history':
    _save_search_history([])
    notify("Search history cleared")
    xbmcplugin.endOfDirectory(addon_handle)

```

- [ ] **Step 2: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add delete_history and clear_history handlers"
```

---

## Manual Test Checklist (post-implementation)

1. **Search saves to history** — search a show → open Search History → entry appears
2. **Re-run from history** — click a history entry → search runs, results appear
3. **Deduplication** — search "Breaking Bad" twice → only one entry, at top
4. **Case-insensitive dedup** — search "breaking bad" then "Breaking Bad" → one entry
5. **Content type label** — search under Shows vs Movies → labels show `[Shows]` and `[Movies]`
6. **Auto-trim** — search 21+ different terms → only 20 entries, oldest dropped
7. **Delete single entry** — long-press a history item → Delete → item removed, list refreshes
8. **Clear all** — long-press → Clear All → history empty, shows "No search history yet"
9. **Empty state** — fresh install / cleared history → "No search history yet" shown
10. **Corrupt file recovery** — put garbage in the JSON file → history loads as empty, no crash
11. **Back-navigation** — search something → back to root → Search History → click entry → back → returns to Search History (not root)
