"""EZTV — TV show torrents via API."""
import requests

SITE_NAME = "eztv"
CONTENT_TYPES = ["shows"]

API = "https://eztvx.to/api/get-torrents"
HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}


def search(query):
    if not query:
        return []

    try:
        resp = requests.get(API, params={"query": query, "limit": 50},
                            timeout=15, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for t in data.get("torrents", []):
        magnet = t.get("magnet_url") or f"magnet:?xt=urn:btih:{t.get('hash', '')}"
        show_title = t.get("title", "").strip()
        season = str(t.get("season", ""))
        episode = str(t.get("episode", ""))
        seeds = t.get("seeds", 0)
        size_bytes = int(t.get("size_bytes", 0))

        if not show_title or not magnet:
            continue

        # Clean up season/episode — some entries have "0" meaning unknown
        has_episode = episode and episode != "0"
        has_season = season and season != "0"

        result = {
            "show_title": show_title,
            "url": magnet,
            "type": "torrent",
            "site": SITE_NAME,
        }

        if has_episode:
            result["episode"] = episode
            result["title"] = t.get("filename", "")
        elif has_season:
            # Full season pack — treat as movie/show with no specific episode
            result["is_movie"] = True
        else:
            result["is_movie"] = True

        # Guess quality from size
        if size_bytes > 0:
            gb = size_bytes / (1024 ** 3)
            if gb > 2.5:
                result["quality"] = "1080p"
            elif gb > 1.0:
                result["quality"] = "720p"
            elif gb > 0.3:
                result["quality"] = "480p"

        results.append(result)

    return results
