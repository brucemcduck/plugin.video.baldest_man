"""LimeTorrents — magnet on detail page."""
import requests
from scrapers._common import fetch, get_magnet, parse_torrent

SITE_NAME = "limetorrents"

BASE = "https://limetorrents.lol"
SEARCH = BASE + "/search/all/{}/"


def search(query):
    if not query:
        return []

    soup = fetch(SEARCH.format(requests.utils.quote(query)))
    if not soup:
        return []

    rows = soup.select("table.table2 tbody tr")
    results = []

    for row in rows[:15]:
        name_el = row.select_one("td.tdleft a, td:nth-child(1) a")
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
