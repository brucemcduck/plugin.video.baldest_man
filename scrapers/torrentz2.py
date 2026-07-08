"""Torrentz2 — metasearch engine aggregating dozens of trackers."""
import re
import requests
import bs4

SITE_NAME = "torrentz2"
BASE = "https://torrentz2.nz"
HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}
TIMEOUT = 15

_SE_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})')
_QUALITY_RE = re.compile(r'\b(2160p|1080p|720p|480p|4[kK])\b')


def search(query):
    if not query:
        return []

    soup = _fetch(BASE + "/search", params={"q": query})
    if not soup:
        return []

    results = []
    for dl in soup.select("div.results dl"):
        dt = dl.find("dt")
        if not dt:
            continue
        a = dt.find("a")
        if not a:
            continue
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not title or not href.startswith("/torrent/"):
            continue

        size, seeders = "", 0
        dd = dl.find("dd")
        if dd:
            s_el = dd.select_one("span.s")
            if s_el:
                size = s_el.get_text(strip=True)
            u_el = dd.select_one("span.u")
            if u_el:
                try:
                    seeders = int(u_el.get_text(strip=True))
                except ValueError:
                    pass

        result = _parse(title, size, seeders)
        if not result:
            continue
        result["site"] = SITE_NAME
        result["_detail_url"] = BASE + href
        results.append(result)

    # Fetch magnet links from detail pages (limit to 10 to avoid hammering)
    for r in results[:10]:
        detail = _fetch(r["_detail_url"])
        if not detail:
            continue
        magnet = _extract_magnet(detail)
        if magnet:
            r["url"] = magnet
        del r["_detail_url"]

    return [r for r in results if "url" in r and r.get("url")]


def _parse(title, size, seeders):
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
    if '.' in show_title and ' ' not in show_title:
        show_title = show_title.replace('.', ' ')

    result = {
        "show_title": show_title or title,
        "type": "torrent",
    }

    if episode:
        result["episode"] = episode
        result["title"] = title
    else:
        result["is_movie"] = True

    if quality:
        result["quality"] = quality
    if size:
        result["size"] = size
    if seeders:
        result["seeders"] = seeders

    return result


def _extract_magnet(soup):
    a = soup.select_one("a[href^='magnet:']")
    if a:
        return a.get("href")
    return None


def _fetch(url, params=None):
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        return bs4.BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None
