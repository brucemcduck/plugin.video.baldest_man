# plugin.video.baldest_man — Design Spec

**Date:** 2026-07-04
**Status:** approved

## Overview

A Kodi video plugin that searches across multiple anime websites simultaneously, groups results by show, and lets the user browse episodes and play them. New sites are added by dropping a Python file in the `scrapers/` folder.

## File structure

```
plugin.video.baldest_man/
├── addon.xml
├── main.py              # plugin entry: routing, search flow, display
├── lib/
│   └── scraper_runner.py  # imports all scrapers, runs searches, merges results
└── scrapers/
    ├── __init__.py
    └── example.py         # template/stub scraper
```

## Routing & modes

`main.py` handles three modes via the Kodi plugin URL params:

- **`mode=None`** (root) — show a search dialog, user types a query
- **`mode=search`** — fire all scrapers with the query, group results by show, display show folders
- **`mode=episodes`** — show episodes for a selected show as playable video items

## Scraper contract

Each `.py` file in `scrapers/` must expose:

```python
SITE_NAME = "example"

def search(query: str) -> list[dict]:
    ...
```

Result dicts:
```python
{
    "show_title": "One Punch Man",
    "episode": "01",
    "title": "The Strongest Man",       # optional
    "url": "https://stream.example.com/video.mp4",
    "quality": "720p",                   # optional
}
```

`scraper_runner.py` discovers all scrapers at import time, calls each in sequence, collects results. Each scraper is expected to handle its own HTTP/HTML — `requests` is available as a Kodi dependency.

## Display

Search results are grouped by `show_title`. Each show renders as a folder. Clicking enters `mode=episodes`, listing that show's episodes.

Episode labels: `Ep 01 The Strongest Hero 1080p`

Each video item uses `setProperty('IsPlayable', 'true')` so Kodi knows it's playable.

## Error handling

| Case | Behavior |
|------|----------|
| Site down / timeout | Silently skip, show results from working sites |
| No results from any site | Show info item: "Nothing found for '<query>'" |
| Duplicate episodes across sites | Keep both, user picks preferred source/quality |
| Scraper returns malformed dict | Log it, skip result, continue |

## Dependencies

- `xbmc.python` 3.0.0 (Kodi Matrix built-in)
- `script.module.requests` 2.22.0 (Kodi repo)
- `urllib.parse` (stdlib, Python 3)
