"""EZTV — TV show torrents via API (eztv.re)."""
import re
import requests

SITE_NAME = "eztv"
CONTENT_TYPES = ["shows"]

API = "https://eztv.re/api/get-torrents"
HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}

_SE_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})')


def search(query):
    """Fetch recent torrents and filter client-side by title match.
    The API has no search param — returns everything, we filter locally.
    """
    if not query:
        return []

    try:
        resp = requests.get(API, params={"limit": 100},
                            timeout=15, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    qlower = query.lower()
    results = []

    for t in data.get("torrents", []):
        title = t.get("title", "").strip()
        if not title or qlower not in title.lower():
            continue

        magnet = t.get("magnet_url") or f"magnet:?xt=urn:btih:{t.get('hash', '')}"
        if not magnet:
            continue

        season = int(t.get("season", 0))
        episode = int(t.get("episode", 0))
        size_bytes = int(t.get("size_bytes", 0))

        result = {
            "show_title": _show_title(title),
            "url": magnet,
            "type": "torrent",
            "site": SITE_NAME,
        }

        if episode > 0:
            result["episode"] = str(episode)
            result["title"] = t.get("filename", "")
        elif season > 0:
            result["is_movie"] = True  # season pack
        else:
            result["is_movie"] = True  # standalone / movie

        # Quality from title (API provides explicit quality hints in title)
        for res in ("2160p", "1080p", "720p", "480p"):
            if res in title:
                result["quality"] = res
                break

        if "quality" not in result and size_bytes > 0:
            gb = size_bytes / (1024 ** 3)
            if gb > 2.5:
                result["quality"] = "1080p"
            elif gb > 1.0:
                result["quality"] = "720p"
            elif gb > 0.3:
                result["quality"] = "480p"

        results.append(result)

    return results


def _show_title(title):
    """Extract show name from torrent title. 'Show.Name.S01E05...' → 'Show Name'."""
    m = _SE_RE.search(title)
    if m:
        name = title[:m.start()].strip(' .-[]()')
        # Replace dots with spaces: "Show.Name" → "Show Name"
        if '.' in name and ' ' not in name:
            name = name.replace('.', ' ')
    else:
        name = title
    return re.sub(r'\s+', ' ', name)
