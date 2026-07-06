"""YourBittorrent — TV/anime specialist, magnet on row or detail page."""
import requests
from scrapers._common import fetch, get_magnet, parse_torrent

SITE_NAME = "yourbittorrent"

BASE = "https://yourbittorrent.com"
SEARCH = BASE + "/?q={}"


def search(query):
    if not query:
        return []

    soup = fetch(SEARCH.format(requests.utils.quote(query)))
    if not soup:
        return []

    rows = soup.select("table tbody tr, div.list-item, .torrent-item")
    results = []

    for row in rows[:15]:
        title_el = row.select_one("a[href*='/torrent/'], a[href*='/download/']")
        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        detail_url = title_el.get("href", "")
        if not title:
            continue
        if detail_url and not detail_url.startswith("http"):
            detail_url = BASE + detail_url

        magnet_el = row.select_one("a[href^='magnet:']")
        magnet = (magnet_el.get("href") if magnet_el
                  else get_magnet(detail_url) if detail_url
                  else None)
        if not magnet:
            continue

        result = parse_torrent(title, magnet)
        result["site"] = SITE_NAME
        results.append(result)

    return results
