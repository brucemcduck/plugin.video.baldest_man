"""YTS — HD movie torrents via API. Movies only."""
import requests

SITE_NAME = "yts"
CONTENT_TYPES = ["movies"]

API = "https://yts.mx/api/v2/list_movies.json"
HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}


def search(query):
    if not query:
        return []

    try:
        resp = requests.get(API, params={"query_term": query, "limit": 20},
                            timeout=15, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    if data.get("status") != "ok":
        return []

    results = []
    for movie in data.get("data", {}).get("movies", []):
        show_title = movie.get("title", "").strip()
        year = movie.get("year", "")
        if year:
            show_title = f"{show_title} ({year})"

        for torrent in movie.get("torrents", []):
            magnet = (f"magnet:?xt=urn:btih:{torrent.get('hash', '')}"
                      f"&dn={requests.utils.quote(show_title)}")
            quality = torrent.get("quality", "")
            seeds = torrent.get("seeds", 0)

            if not show_title or not torrent.get("hash"):
                continue

            results.append({
                "show_title": show_title,
                "url": magnet,
                "type": "torrent",
                "is_movie": True,
                "quality": quality,
                "site": SITE_NAME,
            })

    return results
