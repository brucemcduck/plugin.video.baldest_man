# AllDebrid Integration — Spec Addendum

**Date:** 2026-07-04
**Status:** approved
**Extends:** 2026-07-04-baldest-man-design.md

## Overview

Add AllDebrid torrent/magnet resolution. Scrapers return torrent/magnet links. When the user clicks an episode, `main.py` resolves the link through AllDebrid's API before handing the direct URL to Kodi for playback.

## New files

```
plugin.video.baldest_man/
├── resources/
│   └── settings.xml       # AllDebrid API key setting
├── lib/
│   └── alldebrid.py       # resolve(url) -> direct_url
├── scrapers/
│   └── example.py          # updated: shows torrent return pattern
```

## Settings

`resources/settings.xml` — single text setting for the AllDebrid API key, hidden by `option="hidden"`.

## AllDebrid module

`lib/alldebrid.py` exposes:

```python
class AllDebridError(Exception):
    pass

def resolve(url, api_key) -> str:
    """
    Takes a magnet link or torrent URL, returns a direct streamable URL.
    Raises AllDebridError on failure (bad key, rate limit, service down).
    """
```

Uses the AllDebrid API v4.1 endpoint. The API key is read from Kodi settings via `xbmcaddon.Addon()`.

## Routing update

New mode in `main.py`:

- **`mode=play`** — receives a torrent/magnet URL from the episode item, calls `alldebrid.resolve()`, then `xbmcplugin.setResolvedUrl()` to hand the direct URL to Kodi's player.

Episode items now build `mode=play` URLs with the magnet/torrent URL as a param.

## Scraper contract update

Result dicts gain an optional `type` field:

```python
{
    "type": "torrent",   # "torrent" for magnet/torrent links, omitted for direct URLs
    "url": "magnet:?xt=urn:btih:...",
    ...
}
```

When `type` is absent or `"direct"`, `main.py` passes the URL straight to Kodi (no resolution). This keeps the design compatible with both torrent and direct-video scrapers.

## Error handling

| Case | Behavior |
|------|----------|
| AllDebrid API key not set | Show notification: "AllDebrid API key not set", return to list |
| resolve() fails | Show notification with error, return to episode list |
| resolve() succeeds | Kodi plays the video normally |
| Scraper returns `"type": "direct"` | Skip resolution, play URL directly |

## Dependencies (no new addon.xml deps)

- `xbmcaddon` — Kodi built-in
- `xbmcgui.Dialog().notification()` — Kodi built-in
- `requests` — already declared
