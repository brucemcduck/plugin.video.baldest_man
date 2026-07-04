# Content Type & Movie Support — Spec Addendum

**Date:** 2026-07-04
**Status:** approved
**Extends:** 2026-07-04-baldest-man-design.md, 2026-07-04-alldebrid-design.md

## Overview

Improve search UX with three content type filters at the root level and first-class movie support. Users pick "Search Shows", "Search Movies", or "Search All" before typing a query. Results are filtered and displayed accordingly.

## Root menu

Instead of jumping straight to the search dialog, the addon root shows three folders:

```
📁 Search Shows
📁 Search Movies
📁 Search All
```

Each passes `content_type` (`shows`, `movies`, `all`) through the plugin URL.

## Scraper contract update

New optional field:

```python
{
    "is_movie": True,   # optional — marks standalone movie (no episode, no folder)
    ...
}
```

When `is_movie=True`, the result is treated as a playable movie. When absent or `False`, it's treated as a show episode and grouped by `show_title`.

## Routing update

- **Root** (`mode=None`) — displays the three folder items, each linking to mode=search with the appropriate `content_type`
- **Search** (`mode=search`) — unchanged flow (dialog → scrapers → display), but results are filtered by `content_type`:
  - `shows` → only non-movie results, grouped by `show_title` as folders
  - `movies` → only `is_movie=True` results, flat list of playable items
  - `all` → shows as folders (grouped) + movies as flat playable items, mixed
- **Episodes** (`mode=episodes`) — unchanged
- **Play** (`mode=play`) — unchanged

## Display

Show folders use the label `show_title` (unchanged).

Movie items use the label format: `"Movie Title 1080p"` — show title + quality, no "Ep" prefix.

Movie items are playable directly from the search results (no intermediate folder). They use `setProperty('IsPlayable', 'true')` and link to `mode=play`.

## Ordering

Within each section, items are sorted alphabetically by title:
- Shows: sorted by `show_title`
- Movies: sorted by `show_title`
