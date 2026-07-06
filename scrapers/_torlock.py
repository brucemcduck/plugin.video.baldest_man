"""TorLock — magnet links on search page, verified torrents."""
import re
import requests
from scrapers._common import fetch, parse_torrent

SITE_NAME = "torlock"

BASE = "https://www.torlock.com"
SEARCH = BASE + "/all/torrents/{}.html"


def search(query):
    if not query:
        return []

    soup = fetch(SEARCH.format(requests.utils.quote(query)))
    if not soup:
        return []

    rows = soup.select("table tbody tr, article.tr, div.tr")
    results = []

    for row in rows:
        title_el = row.select_one("a[href*='/torrent/']")
        magnet_el = row.select_one("a[href^='magnet:']")
        if not (title_el and magnet_el):
            continue

        title = title_el.get_text(strip=True)
        magnet = magnet_el.get("href", "")
        if not title or not magnet:
            continue

        title = re.sub(r'\s*\[VERIFIED\]\s*', '', title, flags=re.IGNORECASE)
        result = parse_torrent(title, magnet)
        result["site"] = SITE_NAME
        results.append(result)

    return results
