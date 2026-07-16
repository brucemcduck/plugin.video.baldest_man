# Search History Design

**Date:** 2026-07-16
**Status:** Approved (design phase)

## Problem

Every time the user searches, they start from a blank text input dialog. There's no way to quickly re-run a previous search. For a frequent user, typing the same show/movie titles repeatedly is tedious — especially on a TV where text input is slow.

## Solution

Add a "Search History" folder to the root menu that shows the last 20 searches. Clicking a history entry re-runs that search immediately. Every successful search is saved to history automatically. Long-press offers per-item delete and "Clear All".

## Architecture

**Approach:** A JSON file in the temp directory stores search history (same pattern as the existing `_SEARCH_CACHE` and `_SCRAPE_CACHE` at main.py:49-50). Three helper functions manage load/save/add. A new `mode=search_history` handler displays the list. The existing `mode=search` handler saves each successful search to history.

### Files changed

| File | Change |
|---|---|
| `main.py` | Add `_load_search_history()`, `_save_search_history()`, `_add_search_history()` helpers; add `mode=search_history` handler; add "Search History" folder item to root menu; add history save call in `mode=search` |

No new files. No settings changes.

## Storage

**File:** `tempfile.gettempdir()/baldman_search_history.json`

**Format:** JSON list of search dicts:
```json
[
  {"query": "Breaking Bad", "content_type": "shows", "timestamp": 1721136400},
  {"query": "Inception", "content_type": "movies", "timestamp": 1721136200}
]
```

**Deduplication:** By query string, case-insensitive. Re-searching the same term moves it to the top of the list with an updated timestamp (most-recent-first ordering).

**Auto-trim:** Max 20 entries. When exceeded, the oldest entry (last in the list) is dropped.

**Error handling:** If the file is missing or corrupt, history starts empty — no crash. `_load_search_history()` returns `[]` on `OSError`/`json.JSONDecodeError`. `_save_search_history()` silently ignores write failures.

## Helpers

```python
_SEARCH_HISTORY = os.path.join(tempfile.gettempdir(), "baldman_search_history.json")
_MAX_HISTORY = 20

def _load_search_history():
    """Load search history list. Returns [] on missing/corrupt file."""

def _save_search_history(history):
    """Write history list to JSON. Silently ignores errors."""

def _add_search_history(query, content_type):
    """Add or update a search entry. Dedupes by query (case-insensitive),
    moves to front, trims to _MAX_HISTORY."""
```

## UI

### Root menu

A new "Search History" folder item is added to the root menu (`mode=None`), after the three "Search Shows/Movies/All" items and before "Continue Watching":

```python
url = build_url({'mode': 'search_history'})
xbmcplugin.addDirectoryItem(addon_handle, url,
                            xbmcgui.ListItem("Search History"), isFolder=True)
```

### mode=search_history handler

1. Load history JSON
2. For each entry, create a ListItem labeled `"[Shows] Breaking Bad"` (content type capitalized + query)
3. URL points to `mode=search` with the saved `query` and `content_type` — clicking re-runs the search immediately, bypassing the text input dialog
4. Context menu (long-press) on each item: "Delete" (removes that entry) and "Clear All" (empties history)
5. If history is empty, show "No search history yet" as a non-folder item

**Label format:** `[{content_type}] {query}` — e.g. `"[Shows] Breaking Bad"`, `"[Movies] Inception"`, `"[All] Marvel"`

**Delete/Clear All** are implemented as separate modes:
- `mode=delete_history` with `index` param — removes one entry, reloads the history list
- `mode=clear_history` — empties the file, reloads the history list

Both call `xbmcplugin.endOfDirectory` to refresh the view.

### Saving in mode=search

In the existing `mode=search` handler (main.py:548), after a successful search (query is non-empty and the TMDB search runs), call `_add_search_history(query, content_type)` before displaying results. This is in the `else` branch at line 568 — only when a new query is entered (not on cache hits from back-navigation).

## Data Flow

```
User types "Breaking Bad" in Search Shows
  → mode=search runs TMDB search
  → _add_search_history("Breaking Bad", "shows") saves to JSON
  → results displayed

User opens Search History from root menu
  → mode=search_history loads JSON
  → list displayed with [Shows] Breaking Bad

User clicks [Shows] Breaking Bad
  → mode=search with query="Breaking Bad", content_type="shows"
  → cache hit (still in _SEARCH_CACHE) → results displayed immediately
  → _add_search_history moves it to front (already deduped)
```

## Testing

Manual test checklist:

1. **Search saves to history** — search a show → open Search History → entry appears
2. **Re-run from history** — click a history entry → search runs, results appear
3. **Deduplication** — search "Breaking Bad" twice → only one entry, at top
4. **Case-insensitive dedup** — search "breaking bad" then "Breaking Bad" → one entry
5. **Content type label** — search under Shows vs Movies → labels show `[Shows]` and `[Movies]`
6. **Auto-trim** — search 21+ different terms → only 20 entries, oldest dropped
7. **Delete single entry** — long-press a history item → Delete → item removed
8. **Clear all** — long-press → Clear All → history empty, shows "No search history yet"
9. **Empty state** — fresh install / cleared history → "No search history yet" shown
10. **Corrupt file recovery** — put garbage in the JSON file → history loads as empty, no crash
11. **Back-navigation** — search something → back to root → Search History → click entry → back → returns to Search History (not root)
