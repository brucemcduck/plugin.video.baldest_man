"""Kickass Torrents — magnet links on search page."""
import requests
from scrapers._common import fetch, parse_torrent

SITE_NAME = "kickass"

URLS = [
    "https://kickasstorrents.to/usearch/{}/",
    "https://katcr.to/search/{}/",
]


def search(query):
    if not query:
        return []

    soup = _fetch_search(query)
    if not soup:
        return []

    rows = soup.select("tr.odd, tr.even, tr[id^='torrent_'], table.data tbody tr")
    results = []

    for row in rows:
        title_el = (row.select_one("a.cellMainLink, a.torrentname, td:nth-child(1) a")
                    or row.select_one("a[href*='/torrent/']"))
        magnet_el = row.select_one("a[href^='magnet:']")
        if not (title_el and magnet_el):
            continue

        title = title_el.get_text(strip=True)
        magnet = magnet_el.get("href", "")
        if not title or not magnet:
            continue

        result = parse_torrent(title, magnet)
        result["site"] = SITE_NAME
        results.append(result)

    return results


def _fetch_search(query):
    for url_tpl in URLS:
        soup = fetch(url_tpl.format(requests.utils.quote(query)))
        if soup:
            return soup
    return None
