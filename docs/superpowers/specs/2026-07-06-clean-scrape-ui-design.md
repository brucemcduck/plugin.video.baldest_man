# Clean Scrape Results UI

Replace the single-blob text label on scrape results with structured Kodi
ListItem metadata + show/movie artwork, so Kodi's native views (List, Media
Info, Wide) render it clean — same approach Seren/Umbrella use.

## Current vs Target

```
Current label:
  Silicon.Valley.S01E01.Minimum.Viable.Product.1080p.BluRay.x265-RARBG [1080p] ⬆42 · 469 MB

Target label (List view):
  S01E01 · Minimum Viable Product

Target info panel (Media Info / dialog):
  ⬆42 seeders · 469 MB · 1080p
  source: torrentio
```

## Changes

### `resources/lib/tmdb.py` — new helper

```python
def get_poster(show_id, api_key, is_movie=False):
    """Return poster URL for a show/movie, or None."""
    media_type = "movie" if is_movie else "tv"
    try:
        data = _tmdb_get(f"{BASE}/{media_type}/{show_id}",
                         {"api_key": api_key})
        path = data.get("poster_path")
        return IMAGE_BASE + path if path else None
    except Exception:
        return None
```

### `main.py` — `label_result()` rewrite

Clean, short label. Two formats:

```
S01E05 · Episode Name     (episodes)
The Matrix (1999)          (movies)
```

No quality/seeders/size — those move to the info panel.

### `main.py` — `add_scrape_result()` rewrite

```python
def add_scrape_result(item, poster_url=None):
    label = label_result(item)
    li = xbmcgui.ListItem(label)
    li.setProperty('IsPlayable', 'true')

    # Structured metadata for Kodi's native views
    info = {'title': label, 'mediatype': 'episode' if item.get('episode') else 'movie'}

    # Plot: stats shown in Media Info view and dialog
    plot_parts = []
    if item.get('quality'):
        plot_parts.append(item['quality'])
    if item.get('seeders'):
        plot_parts.append(f"⬆{item['seeders']} seeders")
    if item.get('size'):
        plot_parts.append(item['size'])
    plot_parts.append(f"source: {item.get('site', '?')}")
    info['plot'] = ' · '.join(plot_parts)

    # Size in bytes if parseable (Kodi auto-formats)
    size_str = item.get('size', '')
    if size_str:
        info['size'] = _parse_size_bytes(size_str)

    li.setInfo('video', info)

    # Artwork — TMDB poster from parent show/movie
    if poster_url:
        li.setArt({'poster': poster_url, 'thumb': poster_url})

    play_url = build_url({'mode': 'play', 'url': item['url'],
                          'type': item.get('type', 'direct')})
    xbmcplugin.addDirectoryItem(addon_handle, play_url, li, isFolder=False)
```

### `main.py` — scrape mode: get poster, pass to add_scrape_result

After the existing Torrentio merge block, before the `for r in results` loop,
add poster lookup:

```python
    # Get TMDB poster for artwork
    poster_url = None
    if show_id:
        try:
            poster_url = tmdb.get_poster(int(show_id), tmdb_api_key(),
                                         is_movie=(content_type == 'movies'))
        except Exception:
            pass
```

Then change `add_scrape_result(r)` → `add_scrape_result(r, poster_url)`.

### `main.py` — new helper: `_parse_size_bytes()`

```python
def _parse_size_bytes(size_str):
    """Parse human-readable size string to bytes for Kodi. Returns int or 0."""
    import re
    m = re.match(r'([\d.]+)\s*(GB|MB|GiB|MiB|KB|B)', size_str, re.IGNORECASE)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit in ('GB', 'GIB'):
        return int(val * 1024 ** 3)
    if unit in ('MB', 'MIB'):
        return int(val * 1024 ** 2)
    if unit in ('KB'):
        return int(val * 1024)
    return int(val)
```

## What Doesn't Change

- Scraper modules — no changes
- `scraper_runner.py` — no changes
- Browse modes (search, seasons, episodes) — no changes, already set artwork properly
- Auth and play modes — no changes
- Torrentio integration — no changes
