"""Shared helpers for HTML-based torrent scrapers. Not a scraper itself."""
import re
import requests
import bs4

HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}

QUALITY_RE = re.compile(r'\b(2160p|1080p|720p|480p|4[kK])\b')
SE_RE = re.compile(r'[Ss](\d{1,2})[Ee](\d{1,3})')


def fetch(url):
    """GET a URL, return parsed soup or None."""
    try:
        resp = requests.get(url, timeout=15, headers=HEADERS)
        resp.raise_for_status()
        return bs4.BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None


def get_magnet(detail_url):
    """Fetch detail page and extract first magnet link, or None."""
    soup = fetch(detail_url)
    if not soup:
        return None
    el = soup.select_one("a[href^='magnet:']")
    return el.get("href") if el else None


def parse_torrent(title, magnet):
    """Parse show_title, episode, quality from a torrent title + magnet.
    Returns a result dict ready for scraper_runner.
    """
    quality = None
    qm = QUALITY_RE.search(title)
    if qm:
        quality = qm.group(1)

    episode = None
    show_title = title

    se_m = SE_RE.search(title)
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
