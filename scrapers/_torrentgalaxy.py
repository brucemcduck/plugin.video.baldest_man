"""TorrentGalaxy — magnet links on search page."""
import re
import requests
import bs4

SITE_NAME = "torrentgalaxy"

BASE = "https://torrentgalaxy.to"
SEARCH = BASE + "/torrents.php?search={}&sort=seeders&order=desc"
HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}

_SE_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})')
_QUALITY_RE = re.compile(r'\b(2160p|1080p|720p|480p|4[kK])\b')


def search(query):
    if not query:
        return []

    try:
        resp = requests.get(
            SEARCH.format(requests.utils.quote(query)),
            timeout=15, headers=HEADERS,
        )
        resp.raise_for_status()
        soup = bs4.BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return []

    rows = soup.select("div.tgxtablerow")
    results = []

    for row in rows:
        # Title from a.txlight
        title_el = row.select_one("a.txlight")
        if not title_el:
            continue
        title = title_el.get("title", "").strip()

        # Magnet from a[role="button"]
        magnet_el = row.select_one("a[role='button']")
        magnet = magnet_el.get("href", "") if magnet_el else ""
        if not magnet or not magnet.startswith("magnet:"):
            continue

        if not title:
            continue

        result = _parse(title, magnet)
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
