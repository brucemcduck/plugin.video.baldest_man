"""Example scraper — copy this file and fill in the blanks.

Return types:
  - "type": "torrent"   — magnet/torrent link, resolved via AllDebrid on play
  - "type": "direct" or omitted — direct video URL, played immediately

Content types:
  - Omit "is_movie" or set False — show episode (requires "episode" field)
  - "is_movie": True — standalone movie (no "episode" field needed)
"""
import requests

SITE_NAME = "example"


def search(query):
    """Return list of dicts with show_title, url, and optional fields.

    Show episode fields:
        show_title (str, required)
        episode   (str, required)  — episode number as string, e.g. "01"
        url       (str, required)  — magnet link or direct video URL
        type      (str, optional)  — "torrent" or "direct"; omit for direct
        title     (str, optional)  — episode title
        quality   (str, optional)  — e.g. "1080p", "720p"
        is_movie  (bool, optional) — omit or False for shows

    Movie fields:
        show_title (str, required)
        url        (str, required)
        is_movie   (bool, required) — True
        type       (str, optional)
        quality    (str, optional)
    """
    return [
        # Example show episode:
        # {
        #     "show_title": "One Punch Man",
        #     "episode": "01",
        #     "title": "The Strongest Man",
        #     "url": "magnet:?xt=urn:btih:deadbeefcafe...",
        #     "type": "torrent",
        #     "quality": "1080p",
        # },
        # Example movie:
        # {
        #     "show_title": "Your Name",
        #     "url": "magnet:?xt=urn:btih:beefdead...",
        #     "is_movie": True,
        #     "type": "torrent",
        #     "quality": "1080p",
        # },
    ]
