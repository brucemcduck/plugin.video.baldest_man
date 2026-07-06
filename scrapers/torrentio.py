"""Torrentio — aggregates 24+ torrent trackers via a single API."""
import re
import requests

SITE_NAME = "torrentio"

API = "https://torrentio.strem.fun/stream"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:120.0) Gecko/20100101 Firefox/120.0"}
TIMEOUT = 20

_SE_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})')
_QUALITY_RE = re.compile(r'\b(2160p|1080p|720p|480p|4[kK])\b')
_SEEDERS_RE = re.compile(r'👤\s*(\d+)')
_SIZE_RE = re.compile(r'💾\s*([\d.]+)\s*(GB|MB|GiB|MiB)', re.IGNORECASE)


def search(query):
    """Stub — Torrentio is called directly via search_imdb()."""
    return []


def search_imdb(imdb_id, season=None, episode=None, is_movie=False):
    """Query Torrentio by IMDB ID. Returns parsed result dicts."""
    if not imdb_id:
        return []

    if is_movie:
        url = f"{API}/movie/{imdb_id}.json"
    elif season is not None and episode is not None:
        url = f"{API}/series/{imdb_id}:{season}:{episode}.json"
    else:
        return []

    try:
        resp = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for stream in data.get("streams", []):
        title = stream.get("title", "")
        if not title:
            continue

        info_hash = stream.get("infoHash", "")
        if not info_hash:
            continue

        # Title is: "Torrent Name\n👤 42 💾 469 MB ⚙️ SOURCE"
        name_part, stats_part = _split_title(title)

        magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={requests.utils.quote(name_part)}"

        result = {
            "show_title": _show_title(name_part),
            "url": magnet,
            "type": "torrent",
            "site": SITE_NAME,
            "title": name_part,
        }

        # Episode detection
        if not is_movie:
            se_m = _SE_RE.search(name_part)
            if se_m:
                result["episode"] = se_m.group(2)
            else:
                result["is_movie"] = True
        else:
            result["is_movie"] = True

        # Quality
        qm = _QUALITY_RE.search(name_part)
        if qm:
            result["quality"] = qm.group(1)
        else:
            hints = stream.get("behaviorHints", {}) or {}
            group = hints.get("bingeGroup", "")
            for res in ("2160p", "1080p", "720p", "480p"):
                if res in group:
                    result["quality"] = res
                    break

        # Seeders and size from stats
        if stats_part:
            sm = _SEEDERS_RE.search(stats_part)
            if sm:
                result["seeders"] = int(sm.group(1))
            szm = _SIZE_RE.search(stats_part)
            if szm:
                result["size"] = f"{szm.group(1)} {szm.group(2).upper()}"

        # Size fallback from behaviorHints filename
        if "size" not in result:
            hints = stream.get("behaviorHints", {}) or {}
            filename = hints.get("filename", "")
            szm = _SIZE_RE.search(filename)
            if szm:
                result["size"] = f"{szm.group(1)} {szm.group(2).upper()}"

        results.append(result)

    return results


def _split_title(title):
    """Split Torrentio title into (name, stats)."""
    if "\n" in title:
        parts = title.split("\n", 1)
        return parts[0].strip(), parts[1].strip()
    return title.strip(), ""


def _show_title(name):
    """Extract clean show title from torrent name."""
    # Strip year in parens: "Show Name (2014) ..."
    name = re.sub(r'\s*\(\d{4}\)', '', name)

    m = _SE_RE.search(name)
    if m:
        name = name[:m.start()].strip(' .-[]()')
        if '.' in name and ' ' not in name:
            name = name.replace('.', ' ')
    else:
        # Movie or no episode marker — clean up dots/spacing
        if '.' in name and ' ' not in name:
            name = name.replace('.', ' ')

    return re.sub(r'\s+', ' ', name).strip()
