"""1337x — search page, magnet on detail page."""
import requests
from scrapers._common import fetch, get_magnet, parse_torrent

SITE_NAME = "1337x"

BASE = "https://1337x.to"
SEARCH = BASE + "/search/{}/{}/"


def search(query):
    if not query:
        return []

    soup = fetch(SEARCH.format(requests.utils.quote(query), 1))
    if not soup:
        return []

    rows = soup.select("table.table-list tbody tr")
    results = []

    for row in rows[:15]:
        name_el = row.select_one("td.name a:nth-child(1)")
        if not name_el:
            continue

        title = name_el.get_text(strip=True)
        detail_url = name_el.get("href", "")
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
