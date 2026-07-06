"""1337x — search page, magnet on detail page. Selectors from py1337x."""
import re
import requests
import bs4

SITE_NAME = "1337x"

BASE = "https://1337x.to"
SEARCH = BASE + "/search/{}/{}/"
HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}

_MAX_DETAIL = 15  # max detail-page fetches for magnets

_SE_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})')
_QUALITY_RE = re.compile(r'\b(2160p|1080p|720p|480p|4[kK])\b')


def search(query):
    if not query:
        return []

    soup = _get(SEARCH.format(requests.utils.quote(query), 1))
    if not soup:
        return []

    # py1337x approach: flat lists by index, no row dependency
    links = [a for a in soup.select("a[href*='/torrent/']")
             if '/torrent/' in a.get("href", "")]
    seeders = soup.select("td.coll-2")
    sizes = soup.select("td.coll-4")

    results = []
    for i, link_el in enumerate(links[:_MAX_DETAIL]):
        title = link_el.get_text(strip=True)
        detail_url = link_el.get("href", "")
        if not title or not detail_url:
            continue
        if not detail_url.startswith("http"):
            detail_url = BASE + detail_url

        # Get magnet from detail page
        magnet = _get_magnet(detail_url)
        if not magnet:
            continue

        result = _parse(title, magnet)
        result["site"] = SITE_NAME
        results.append(result)

    return results


def _get(url):
    try:
        resp = requests.get(url, timeout=15, headers=HEADERS)
        resp.raise_for_status()
        return bs4.BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None


def _get_magnet(detail_url):
    soup = _get(detail_url)
    if not soup:
        return None
    el = soup.select_one("a[href^='magnet']")
    return el.get("href") if el else None


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
