"""TMDB API client — search shows/movies, get seasons and episodes."""
import requests

BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TIMEOUT = 15
HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}


def search_shows(query, api_key, language="en"):
    """Search TV shows. Returns list of {id, title, year, overview, poster_url}."""
    if not query or not api_key:
        return []
    try:
        resp = requests.get(
            f"{BASE}/search/tv",
            params={"api_key": api_key, "query": query, "language": language},
            timeout=TIMEOUT, headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for item in data.get("results", []):
        r = {
            "id": item.get("id"),
            "title": item.get("name", ""),
            "year": item.get("first_air_date", "")[:4],
            "overview": item.get("overview", ""),
        }
        if item.get("poster_path"):
            r["poster_url"] = IMAGE_BASE + item["poster_path"]
        results.append(r)
    return results


def search_movies(query, api_key, language="en"):
    """Search movies. Returns list of {id, title, year, overview, poster_url}."""
    if not query or not api_key:
        return []
    try:
        resp = requests.get(
            f"{BASE}/search/movie",
            params={"api_key": api_key, "query": query, "language": language},
            timeout=TIMEOUT, headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for item in data.get("results", []):
        r = {
            "id": item.get("id"),
            "title": item.get("title", ""),
            "year": item.get("release_date", "")[:4],
            "overview": item.get("overview", ""),
        }
        if item.get("poster_path"):
            r["poster_url"] = IMAGE_BASE + item["poster_path"]
        results.append(r)
    return results


def get_seasons(show_id, api_key, language="en"):
    """Get seasons for a TV show. Skips season 0 (specials).
    Returns list of {season_number, episode_count, name, poster_url}."""
    try:
        resp = requests.get(
            f"{BASE}/tv/{show_id}",
            params={"api_key": api_key, "language": language},
            timeout=TIMEOUT, headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for s in data.get("seasons", []):
        sn = s.get("season_number", 0)
        if sn == 0:
            continue
        r = {
            "season_number": sn,
            "episode_count": s.get("episode_count", 0),
            "name": s.get("name", f"Season {sn}"),
        }
        if s.get("poster_path"):
            r["poster_url"] = IMAGE_BASE + s["poster_path"]
        results.append(r)
    return results


def get_episodes(show_id, season_number, api_key, language="en"):
    """Get episodes for a season. Returns list of {episode_number, name, overview, still_url}."""
    try:
        resp = requests.get(
            f"{BASE}/tv/{show_id}/season/{season_number}",
            params={"api_key": api_key, "language": language},
            timeout=TIMEOUT, headers=HEADERS,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    results = []
    for ep in data.get("episodes", []):
        r = {
            "episode_number": ep.get("episode_number", 0),
            "name": ep.get("name", ""),
            "overview": ep.get("overview", ""),
        }
        if ep.get("still_path"):
            r["still_url"] = IMAGE_BASE + ep["still_path"]
        results.append(r)
    return results
