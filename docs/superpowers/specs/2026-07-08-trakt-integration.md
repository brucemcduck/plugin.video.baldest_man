# Trakt Integration

**Date:** 2026-07-08
**Status:** Design approved

## Problem

Watch data (history, progress, watchlist) is local to a single Kodi instance. No cross-device sync.

## Solution

Integrate Trakt.tv API for scrobbling, watchlist/collection browsing, and episode progress tracking.

## Architecture

```
resources/lib/trakt.py    — Trakt API client (auth, scrobble, sync, progress)
main.py                   — menu items, scrobble on play/stop, browse integration
resources/settings.xml    — Trakt category with auth button and token fields
```

### Auth

Device OAuth flow (Trakt PIN auth):
1. `POST /oauth/device/code` → `device_code`, `user_code`, `verification_url`
2. Dialog: "Go to trakt.tv/activate and enter code: XXXXXX"
3. Poll `POST /oauth/device/token` until authorized or timeout
4. Store `access_token` and `refresh_token` in settings
5. Auto-refresh on 401 via `POST /oauth/token` with `refresh_token`

Settings: `trakt_access_token` (hidden), `trakt_refresh_token` (hidden), "Authorize Device" action button.

### Scrobbling

On playback:
- **Start:** `POST /scrobble/start` with IMDB ID, season, episode, progress 0%
- **Stop:** `POST /scrobble/stop` with progress percentage

Trakt's scrobble endpoint auto-marks as watched past ~80% and syncs progress across devices. No separate "mark watched" call needed.

IMDB ID sourced from `tmdb.get_imdb_id()` — passed through play URL params from scrape handler (or fetched on-demand during play).

### Browse Menus

Three menu items at root when `trakt_access_token` is set:

| Menu | Trakt API | Behavior |
|------|-----------|----------|
| Trakt Watchlist | `/sync/watchlist/shows` + `/movies` | TMDB lookup → seasons → episodes → scrape |
| Trakt Collection | `/sync/collection/shows` + `/movies` | Same flow as watchlist |
| Progress / Up Next | `/sync/watched/shows` + `/shows/:id/progress/watched` | Jump to next unwatched episode |

New mode: `mode=trakt_browse` with `list_type` param. Reuses existing TMDB lookup, season/episode listing, and scrape modes.

### Files

| File | Change |
|------|--------|
| `resources/lib/trakt.py` | New — API client with auth, scrobble, sync, progress |
| `main.py` | Add `mode=trakt_browse` handler, scrobble calls in play handler, root menu items |
| `resources/settings.xml` | Trakt category with auth button and token fields |

### Edge Cases

- **No network:** Scrobble calls fail silently, playback unaffected
- **Token expired:** Auto-refresh before retry
- **No IMDB ID:** Skip scrobble for that item
- **Auth cancelled:** Token fields remain empty, menu items hidden
- **Trakt returns empty list:** "Nothing in watchlist" message
