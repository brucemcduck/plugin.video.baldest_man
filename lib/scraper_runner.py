"""Runs all scrapers against a query, collects and validates results."""
import sys
import traceback
import scrapers

REQUIRED_KEYS = {'show_title', 'url'}


def search_all(query):
    """Run every scraper, return merged list of validated result dicts.

    Args:
        query: str — user's search term

    Returns:
        list[dict] — each dict has show_title, url; optionally episode (for shows),
                     is_movie (True for movies), title, quality
    """
    if not query:
        return []

    results = []
    for mod in scrapers.get_scrapers():
        try:
            raw = mod.search(query)
        except Exception:
            # ponytail: bare except — don't let a broken scraper kill the whole search
            log_msg = "scraper_runner: {} crashed\n{}".format(
                mod.SITE_NAME, traceback.format_exc()
            )
            try:
                import xbmc
                xbmc.log(log_msg, level=xbmc.LOGERROR)
            except ImportError:
                print(log_msg, file=sys.stderr)
            continue

        if not isinstance(raw, list):
            continue

        for item in raw:
            if not isinstance(item, dict):
                continue
            if not REQUIRED_KEYS.issubset(item.keys()):
                continue
            if 'episode' not in item and not item.get('is_movie'):
                continue
            item.setdefault('site', mod.SITE_NAME)
            item.setdefault('title', '')
            item.setdefault('quality', '')
            results.append(item)

    return results
