"""TorrentGalaxy — magnet on detail page."""
import requests
from scrapers._common import fetch, get_magnet, parse_torrent

SITE_NAME = "torrentgalaxy"

BASE = "https://torrentgalaxy.to"
SEARCH = BASE + "/torrents.php?search={}&sort=seeders&order=desc"


def search(query):
    if not query:
        return []

    soup = fetch(SEARCH.format(requests.utils.quote(query)))
    if not soup:
        return []

    rows = soup.select("div.tgxtablerow, div.tgxtable.row, div.searchitem")
    results = []

    for row in rows[:15]:
        link_el = row.select_one("a[href*='/torrent/']")
        if not link_el:
            continue

        title = link_el.get_text(strip=True)
        detail_url = link_el.get("href", "")
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
