"""Trakt.tv API v2 — scrobbling, watchlist, collection, progress."""
import time
import requests

API = "https://api.trakt.tv"
HEADERS_BASE = {
    "Content-Type": "application/json",
    "trakt-api-version": "2",
}
TIMEOUT = 15


class TraktError(Exception):
    pass


def get_device_code(client_id):
    try:
        resp = requests.post(API + "/oauth/device/code",
                             json={"client_id": client_id},
                             timeout=TIMEOUT,
                             headers=HEADERS_BASE)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise TraktError("Failed to get device code: {}".format(e))
    except ValueError:
        raise TraktError("Invalid response")


def poll_for_token(client_id, device_code, interval=5, max_wait=300):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = requests.post(API + "/oauth/device/token",
                                 json={"code": device_code,
                                       "client_id": client_id,
                                       "client_secret": ""},
                                 timeout=TIMEOUT,
                                 headers=HEADERS_BASE)
            if resp.status_code == 200:
                data = resp.json()
                return {"access_token": data["access_token"],
                        "refresh_token": data["refresh_token"]}
            if resp.status_code == 400:
                time.sleep(interval)
                continue
            resp.raise_for_status()
        except (requests.RequestException, ValueError):
            time.sleep(interval)
            continue
    raise TraktError("Timed out waiting for authorization")


def refresh_token(client_id, refresh_token):
    try:
        resp = requests.post(API + "/oauth/token",
                             json={"refresh_token": refresh_token,
                                   "client_id": client_id,
                                   "client_secret": "",
                                   "grant_type": "refresh_token"},
                             timeout=TIMEOUT,
                             headers=HEADERS_BASE)
        resp.raise_for_status()
        data = resp.json()
        return {"access_token": data["access_token"],
                "refresh_token": data["refresh_token"]}
    except (requests.RequestException, ValueError, KeyError) as e:
        raise TraktError("Token refresh failed: {}".format(e))


def _headers(access_token):
    h = dict(HEADERS_BASE)
    h["Authorization"] = "Bearer " + access_token
    return h


def _noop(*args, **kwargs):
    pass


def scrobble_start(access_token, imdb_id, season=None, episode=None):
    body = {}
    if season and episode:
        body["show"] = {"ids": {"imdb": imdb_id}}
        body["episode"] = {"season": season, "number": episode}
    else:
        body["movie"] = {"ids": {"imdb": imdb_id}}
    body["progress"] = 0.0
    try:
        requests.post(API + "/scrobble/start", json=body,
                      timeout=TIMEOUT, headers=_headers(access_token))
    except Exception:
        pass


def scrobble_stop(access_token, imdb_id, season=None, episode=None, progress_pct=0):
    body = {}
    if season and episode:
        body["show"] = {"ids": {"imdb": imdb_id}}
        body["episode"] = {"season": season, "number": episode}
    else:
        body["movie"] = {"ids": {"imdb": imdb_id}}
    body["progress"] = float(progress_pct)
    try:
        requests.post(API + "/scrobble/stop", json=body,
                      timeout=TIMEOUT, headers=_headers(access_token))
    except Exception:
        pass


def get_watchlist(access_token, list_type="shows"):
    try:
        resp = requests.get(API + "/sync/watchlist/" + list_type,
                            timeout=TIMEOUT, headers=_headers(access_token))
        resp.raise_for_status()
        return [item.get(list_type[:-1], item) for item in resp.json()]
    except Exception:
        return []


def get_collection(access_token, list_type="shows"):
    try:
        resp = requests.get(API + "/sync/collection/" + list_type,
                            timeout=TIMEOUT, headers=_headers(access_token))
        resp.raise_for_status()
        return [item.get(list_type[:-1], item) for item in resp.json()]
    except Exception:
        return []


def get_watched_shows(access_token):
    try:
        resp = requests.get(API + "/sync/watched/shows",
                            timeout=TIMEOUT, headers=_headers(access_token))
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def get_show_progress(access_token, trakt_show_id):
    try:
        resp = requests.get(API + "/shows/{}/progress/watched".format(trakt_show_id),
                            timeout=TIMEOUT, headers=_headers(access_token))
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}
