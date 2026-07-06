"""nyaa.si anime scraper — searches English-translated anime category."""
import re
import requests
import bs4

SITE_NAME = "nyaa"
CONTENT_TYPES = ["shows"]

BASE = "https://nyaa.si"
SEARCH_URL = BASE + "/?f=0&c=1_0&q={}&s=seeders&o=desc"

_EP_PATTERNS = [
    re.compile(r'[-\s]#?(\d{2,3})(?:\s|$|v\d|[\[\(])'),   # " - 01 " or " 01 " or "#01" or "01v2"
    re.compile(r'[Ee][Pp](\d{2,3})'),                       # "EP01"
    re.compile(r'[Ss]\d+[Ee](\d+)'),                         # "S01E01"
]
_QUALITY_RE = re.compile(r'(?:\(|\[|\s)(\d{3,4}p|4[kK])(?:\)|\]|\s|$)', re.IGNORECASE)
_STRIP_TAGS_RE = re.compile(r'\[.*?\]|\(.*?\)')


def search(query):
    """Search nyaa.si for anime torrents, return parsed results."""
    if not query:
        return []

    try:
        resp = requests.get(
            SEARCH_URL.format(requests.utils.quote(query)),
            timeout=15,
            headers={"User-Agent": "plugin.video.baldest_man/0.1"},
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    soup = bs4.BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("table.torrent-list tbody tr")

    results = []
    for row in rows:
        name_cell = row.select_one("td:nth-child(2)")
        magnet_cell = row.select_one("td:nth-child(3)")
        size_cell = row.select_one("td:nth-child(4)")
        seeders_cell = row.select_one("td:nth-child(6)")

        if not (name_cell and magnet_cell):
            continue

        # Get the first magnet link
        magnet_link = magnet_cell.select_one("a[href^='magnet:']")
        if not magnet_link:
            continue

        title_text = name_cell.get_text(strip=True)
        magnet_url = magnet_link.get("href")
        seeders = int(seeders_cell.get_text(strip=True)) if seeders_cell else 0

        # Parse episode, quality, show_title from the title
        show_title, episode, parsed_quality = _parse_title(title_text)

        # Quality from title takes priority, fallback to size-based guess
        quality = parsed_quality or _guess_quality(size_cell)

        if not show_title:
            continue

        result = {
            "show_title": show_title,
            "url": magnet_url,
            "type": "torrent",
            "site": SITE_NAME,
        }

        if episode:
            result["episode"] = episode
            result["title"] = _clean_name(title_text)
        else:
            # No episode number — treat as movie
            result["is_movie"] = True

        if quality:
            result["quality"] = quality

        if size_cell:
            size_text = size_cell.get_text(strip=True)
            if size_text:
                result["size"] = size_text
        if seeders:
            result["seeders"] = seeders

        results.append(result)

    return results


def _parse_title(raw):
    """Extract show_title, episode, and quality from a nyaa torrent title.

    Returns (show_title, episode_or_None, quality_or_None).
    """
    # Try to pull quality first so we can strip it before episode matching
    quality = None
    qm = _QUALITY_RE.search(raw)
    if qm:
        quality = qm.group(1)

    # Remove bracketed/parenthesized tags for cleaner matching
    cleaned = _STRIP_TAGS_RE.sub(' ', raw)

    episode = None
    for pattern in _EP_PATTERNS:
        m = pattern.search(cleaned)
        if m:
            episode = m.group(1)
            break

    # Build show_title: everything before the episode marker
    if episode:
        for pattern in _EP_PATTERNS:
            m = pattern.search(cleaned)
            if m:
                show_title = cleaned[:m.start()].strip()
                break
        else:
            show_title = cleaned.strip()
    else:
        show_title = cleaned.strip()

    # Normalize show_title: replace multiple spaces, strip trailing dashes
    show_title = re.sub(r'\s+', ' ', show_title).rstrip(' -')

    return show_title, episode, quality


def _guess_quality(size_cell):
    """Guess quality from file size if title didn't have one."""
    if not size_cell:
        return None
    try:
        text = size_cell.get_text(strip=True)
        if "GiB" in text:
            gb = float(text.replace("GiB", "").strip())
            if gb > 2.5:
                return "1080p"
            elif gb > 1.0:
                return "720p"
            elif gb > 0.3:
                return "480p"
        elif "MiB" in text:
            mb = float(text.replace("MiB", "").strip())
            if mb > 800:
                return "720p"
            elif mb > 300:
                return "480p"
    except (ValueError, AttributeError):
        pass
    return None


def _clean_name(raw):
    """Clean up the raw title for display as episode title."""
    name = _STRIP_TAGS_RE.sub('', raw)
    name = re.sub(r'\s+', ' ', name).strip(' -')
    # Trim known suffixes
    name = re.sub(r'\s*\d{3,4}p\s*$', '', name, flags=re.IGNORECASE).strip()
    return name
