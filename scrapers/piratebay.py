"""The Pirate Bay — via apibay.org JSON API."""
import re
import requests

SITE_NAME = "piratebay"

API = "https://apibay.org/q.php"
HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}

# Video categories only: 2xx = movies/TV
_VIDEO_CATS = {"201", "202", "203", "204", "205", "206", "207", "208", "209", "210", "211", "212"}

_SE_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})')
_QUALITY_RE = re.compile(r'\b(2160p|1080p|720p|480p|4[kK])\b')


def search(query):
    if not query:
        return []

    try:
        resp = requests.get(API, params={"q": query, "cat": 0},
                            timeout=15, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    if not isinstance(data, list) or not data:
        return []

    # First item is sometimes an error message
    first = data[0]
    if isinstance(first, dict) and first.get("name") == "No results returned":
        return []

    results = []
    for item in data:
        if not isinstance(item, dict):
            continue

        # Video categories only
        cat = str(item.get("category", ""))
        if cat and cat not in _VIDEO_CATS:
            continue

        name = item.get("name", "").strip()
        info_hash = item.get("info_hash", "")
        if not name or not info_hash:
            continue

        magnet = (f"magnet:?xt=urn:btih:{info_hash}"
                  f"&dn={requests.utils.quote(name)}")

        result = _parse(name, magnet)
        result["site"] = SITE_NAME
        results.append(result)

    return results


def _parse(title, magnet):
    quality = None
    qm = _QUALITY_RE.search(title)
    if qm:
        quality = qm.group(1)

    episode = None
    show_title = title

    se_m = _SE_RE.search(title)
    if se_m:
        episode = se_m.group(2)
        show_title = title[:se_m.start()].strip()

    show_title = re.sub(r'\s+', ' ', show_title).rstrip(' -.[]()')

    result = {
        "show_title": show_title or title,
        "url": magnet,
        "type": "torrent",
    }

    if episode:
        result["episode"] = episode
        result["title"] = title
    else:
        result["is_movie"] = True

    if quality:
        result["quality"] = quality

    return result
