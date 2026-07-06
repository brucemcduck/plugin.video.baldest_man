# Metadata-First Search Design

Switch from "scrape all torrent sites, then browse" to "browse TMDB metadata,
scrape only when picking an episode/movie."

## Flow

### Shows
```
Search → TMDB show list → Seasons → Episodes → Scrape → Pick result → Play
```

### Movies
```
Search → TMDB movie list → Scrape → Pick result → Play
```

### Rationale
- Current: search "silicon valley" → scrape 3 sites → results include every
  season/episode mixed together → browse a flat list grouped by show title
- New: search "silicon valley" → TMDB returns the show instantly → browse
  seasons → browse episodes → only THEN scrape, with a precise query like
  "Silicon Valley S01E05"
- Scraping per-episode is faster (fewer results) and more accurate (exact query)

## New Module: `resources/lib/tmdb.py`

Three functions, no classes. Plain REST calls to api.themoviedb.org.

```python
search_shows(query)       -> [{id, title, year, overview, poster_url}]
search_movies(query)      -> [{id, title, year, overview, poster_url}]
get_seasons(show_id)      -> [{season_number, episode_count, poster_url}]
get_episodes(show_id, s#) -> [{episode_number, name, overview, still_url}]
```

- `get_seasons` reads from `/tv/{id}` — seasons come in the show detail response
- `get_episodes` calls `/tv/{id}/season/{n}`
- All return plain lists of dicts
- Rate limit handling: on 429, sleep and retry once
- TMDB API key bundled as addon setting default
- Language param from addon setting, default `en`

## Modified Module: `resources/lib/scraper_runner.py`

Unchanged interface, but consumed differently:
- In the old flow, `search_all(query)` was called once with a broad query
- In the new flow, it's called later with a precise query like
  `"Silicon Valley S01E05"` or `"The Matrix (1999)"`
- The relevance filter `_relevant()` stays — it's cheap insurance
- `REQUIRED_KEYS` stays `{'show_title', 'url'}`
- `size` and `seeders` are optional fields scrapers may include

## Scraper Changes: `size` and `seeders`

Each scraper adds two optional fields to result dicts:

```python
{
    "show_title": "...",
    "url": "magnet:...",
    "type": "torrent",
    "site": "piratebay",
    "episode": "05",
    "title": "...",
    "quality": "1080p",
    "size": "1.2 GB",     # NEW — human-readable, optional
    "seeders": 42,        # NEW — int, optional
}
```

| Scraper | Source of size | Source of seeders |
|---------|---------------|-------------------|
| PirateBay | `item.size` from API | `item.seeders` from API |
| EZTV | format `t.size_bytes` | `t.seeds` from API |
| Nyaa | `td:nth-child(4)` text | `td:nth-child(6)` int |

All three scrapers already parse this data but don't include it in output.

## Display Labels

### Episodes (scrape results)
```
Ep 05 The Cap Table [1080p] ⬆12 · 1.2GB
```
Omit seeders/size suffix if both missing.

### Season/movie list items
```
Silicon Valley (2014)
Matrix, The (1999)
```
Year from TMDB appends in parens to disambiguate remakes/reboots.

## Main.py — Mode Rework

| Mode | Trigger | Action |
|------|---------|--------|
| `None` | Root menu | Search Shows, Search Movies, Search All, AllDebrid ✓ |
| `search` | User picks search type | Dialog input → TMDB search → display show/movie list |
| `seasons` | User picks a show | TMDB get_seasons → display season folders |
| `episodes` | User picks a season | TMDB get_episodes → display episode folders |
| `scrape` | User picks episode/movie | `scraper_runner.search_all("Show S01E05")` → display results |
| `play` | User picks a result | AllDebrid resolve → play (unchanged) |
| `auth` | User picks AllDebrid | PIN flow → save key (unchanged) |

URL params carry forward: `mode`, `show_id`, `show_title`, `season_number`,
`episode_number`, `episode_title`, `content_type`, `year`.

What gets removed:
- `results` mode (back-navigation via cache) — no longer needed
- `_save_cache()` / `_cached_results()` — no longer double-scraping
- `_CACHE_FILE` — no temp file

## Settings (`resources/settings.xml`)

Two new entries:

```xml
<setting id="tmdb_api_key" type="text" default="<bundled-key>" visible="false"/>
<setting label="TMDB Language" id="tmdb_language" type="text" default="en"/>
```

Existing settings stay:
- `alldebrid_api_key` (fix persistence if broken)
- `scraper_workers`

## Edge Cases

- **TMDB search returns nothing**: show "Nothing found" dialog, return to search
- **No torrents found for an episode**: show "No sources found for S01E05"
- **TMDB API down**: show error notification, offer to retry
- **AllDebrid not configured**: on play attempt, show notification directing to auth
- **Show has no season 0** (specials): skip specials by default
- **Scrapers return 0 results** for precise query: display message, not empty list

## What Doesn't Change

- `scrapers/` — all three scraper modules, auto-discovery in `__init__.py`
- `resources/lib/alldebrid.py` — magnet → direct URL resolution
- `resources/lib/alldebrid_auth.py` — PIN-based device authorization
- `check_scrapers.py` — terminal health check tool
