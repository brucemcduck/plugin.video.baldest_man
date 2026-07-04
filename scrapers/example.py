"""Example scraper — copy this file and fill in the blanks.

Return types:
  - "type": "torrent"  — magnet/torrent link, resolved via AllDebrid on play
  - "type": "direct" or omitted — direct video URL, played immediately
"""
import requests

SITE_NAME = "example"


def search(query):
    """Return list of dicts with show_title, episode, url, type.

    Fields:
        show_title (str, required)
        episode   (str, required)  — episode number as string, e.g. "01"
        url       (str, required)  — magnet link or direct video URL
        type      (str, optional)  — "torrent" or "direct"; omit for direct
        title     (str, optional)  — episode title
        quality   (str, optional)  — e.g. "1080p", "720p"
    """
    return [
        # Example torrent result:
        # {
        #     "show_title": "One Punch Man",
        #     "episode": "01",
        #     "title": "The Strongest Man",
        #     "url": "magnet:?xt=urn:btih:deadbeefcafe...",
        #     "type": "torrent",
        #     "quality": "1080p",
        # },
    ]
