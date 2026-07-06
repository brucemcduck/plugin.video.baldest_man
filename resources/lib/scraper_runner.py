"""Runs scrapers in parallel against a query, filters by content type."""
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import scrapers

REQUIRED_KEYS = {'show_title', 'url'}
DEFAULT_WORKERS = 6
SCRAPER_TIMEOUT = 15


def search_all(query, content_type="all"):
    """Run relevant scrapers in parallel, return merged validated results.

    Args:
        query: str — user's search term
        content_type: str — "movies", "shows", or "all"

    Returns:
        list[dict]
    """
    if not query:
        return []

    # Filter scrapers by content type
    scrapers_to_run = [
        m for m in scrapers.get_scrapers()
        if content_type == "all"
        or content_type in getattr(m, "CONTENT_TYPES", ["movies", "shows"])
    ]

    if not scrapers_to_run:
        return []

    results = []
    workers = _worker_count()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(m.search, query): m for m in scrapers_to_run}
        for future in as_completed(futures):
            mod = futures[future]
            try:
                raw = future.result(timeout=SCRAPER_TIMEOUT)
            except Exception:
                _log("scraper_runner: {} crashed\n{}".format(
                    mod.SITE_NAME, traceback.format_exc()))
                continue

            if not isinstance(raw, list):
                continue

            passed = 0
            dropped_relevance = 0
            for item in raw:
                if not isinstance(item, dict):
                    continue
                if not REQUIRED_KEYS.issubset(item.keys()):
                    continue
                if 'episode' not in item and not item.get('is_movie'):
                    continue
                if not _relevant(query, item['show_title']):
                    dropped_relevance += 1
                    _log("scraper_runner: {} dropped irrelevant '{}'".format(
                        mod.SITE_NAME, item['show_title']))
                    continue
                item.setdefault('site', mod.SITE_NAME)
                item.setdefault('title', '')
                item.setdefault('quality', '')
                results.append(item)
                passed += 1

            if passed or dropped_relevance:
                _log("scraper_runner: {} → {} results, {} dropped (irrelevant)".format(
                    mod.SITE_NAME, passed, dropped_relevance))

    return results


def _worker_count():
    """Read scraper_workers from Kodi settings, falling back to default."""
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon()
        val = addon.getSetting('scraper_workers')
        return int(val) if val else DEFAULT_WORKERS
    except (ImportError, ValueError):
        return DEFAULT_WORKERS


def _relevant(query, show_title):
    """True if the query appears as a substring of show_title (case-insensitive)."""
    return query.lower() in show_title.lower()


def _log(msg):
    try:
        import xbmc
        xbmc.log(msg, level=xbmc.LOGINFO)
    except ImportError:
        print(msg, file=sys.stderr)
