"""TorrentDownloads — magnet on detail page, 16M+ torrents."""
import requests
from scrapers._common import fetch, get_magnet, parse_torrent

SITE_NAME = "torrentdownloads"

BASE = "https://torrentdownloads.info"
SEARCH = BASE + "/search/{}/"


def search(query):
    if not query:
        return []

    soup = fetch(SEARCH.format(requests.utils.quote(query)))
    if not soup:
        return []

    rows = soup.select("table tbody tr, .torrent_item, div.search_result")
    results = []

    for row in rows[:15]:
        title_el = row.select_one("a[href*='/torrent/'], a[href*='/download/']")
        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        detail_url = title_el.get("href", "")
        if not title or not detail_url:
            continue
        if not detail_url.startswith("http"):
            detail_url = BASE + detail_url

        magnet = get_magnet(detail_url)
        if not magnet:
            continue

        result = parse_torrent(title, magnet)
        result["site"] = SITE_NAME
        results.append(result)

    return results
