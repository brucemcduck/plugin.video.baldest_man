"""Trakt.tv API v2 — scrobbling, watchlist, collection, progress."""
import os
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


def _addon():
    try:
        import xbmcaddon
        return xbmcaddon.Addon()
    except ImportError:
        return None


def _client_id():
    addon = _addon()
    return addon.getSetting('trakt_client_id') if addon else ''


def _save_tokens(access_token, refresh_tok):
    addon = _addon()
    if not addon:
        return
    addon.setSetting('trakt_access_token', access_token or '')
    addon.setSetting('trakt_refresh_token', refresh_tok or '')


def _headers(access_token=None, client_id=None):
    h = dict(HEADERS_BASE)
    cid = client_id or _client_id()
    if cid:
        h["trakt-api-key"] = cid
    if access_token:
        h["Authorization"] = "Bearer " + access_token
    return h


def get_device_code(client_id):
    try:
        resp = requests.post(API + "/oauth/device/code",
                             json={"client_id": client_id},
                             timeout=TIMEOUT,
                             headers=_headers(client_id=client_id))
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
                                 headers=_headers(client_id=client_id))
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


def refresh_token(client_id, refresh_tok):
    try:
        resp = requests.post(API + "/oauth/token",
                             json={"refresh_token": refresh_tok,
                                   "client_id": client_id,
                                   "client_secret": "",
                                   "grant_type": "refresh_token",
                                   "redirect_uri": "urn:ietf:wg:oauth:2.0:oob"},
                             timeout=TIMEOUT,
                             headers=_headers(client_id=client_id))
        resp.raise_for_status()
        data = resp.json()
        return {"access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_tok)}
    except (requests.RequestException, ValueError, KeyError) as e:
        raise TraktError("Token refresh failed: {}".format(e))


def _request(method, path, access_token, json_body=None, client_id=None,
             retry=True):
    """Authenticated Trakt request. On 401, refresh once and retry."""
    cid = client_id or _client_id()
    url = API + path
    try:
        resp = requests.request(
            method, url, json=json_body, timeout=TIMEOUT,
            headers=_headers(access_token, cid))
    except requests.RequestException as e:
        raise TraktError("Request failed: {}".format(e))

    if resp.status_code == 401 and retry:
        addon = _addon()
        refresh_tok = addon.getSetting('trakt_refresh_token') if addon else ''
        if not cid or not refresh_tok:
            raise TraktError("Unauthorized — re-authorize Trakt in settings")
        tokens = refresh_token(cid, refresh_tok)
        _save_tokens(tokens["access_token"], tokens["refresh_token"])
        return _request(method, path, tokens["access_token"], json_body,
                        client_id=cid, retry=False)

    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", resp.text)
        except ValueError:
            err = resp.text
        raise TraktError("Trakt error {}: {}".format(resp.status_code, err))

    if resp.status_code == 204 or not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        raise TraktError("Invalid JSON response")


def get_user(access_token, client_id=None):
    """Return /users/me user object."""
    data = _request("GET", "/users/me", access_token, client_id=client_id)
    if not data:
        raise TraktError("No user info in response")
    return data


def revoke():
    """Clear stored Trakt credentials."""
    addon = _addon()
    if not addon:
        return
    addon.setSetting("trakt_access_token", "")
    addon.setSetting("trakt_refresh_token", "")
    addon.setSetting("traktusername", "")


def now_playing_path():
    """Path to JSON handoff file for the scrobble service."""
    try:
        import xbmcvfs
        base = xbmcvfs.translatePath(
            'special://userdata/addon_data/plugin.video.baldest_man')
    except ImportError:
        base = os.path.join(os.path.expanduser('~'), '.bald_man')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'trakt_now_playing.json')


def write_now_playing(payload):
    """Write now-playing metadata for service.py to scrobble."""
    import json
    path = now_playing_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
    except OSError:
        pass


def clear_now_playing():
    try:
        os.remove(now_playing_path())
    except OSError:
        pass


def read_now_playing():
    import json
    try:
        with open(now_playing_path(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _scrobble_body(imdb_id, season=None, episode=None, progress_pct=0):
    body = {}
    if season is not None and episode is not None:
        body["show"] = {"ids": {"imdb": imdb_id}}
        body["episode"] = {"season": int(season), "number": int(episode)}
    else:
        body["movie"] = {"ids": {"imdb": imdb_id}}
    body["progress"] = float(progress_pct)
    return body


def scrobble_start(access_token, imdb_id, season=None, episode=None,
                   progress_pct=0):
    try:
        _request("POST", "/scrobble/start", access_token,
                 json_body=_scrobble_body(imdb_id, season, episode, progress_pct))
    except Exception:
        pass


def scrobble_pause(access_token, imdb_id, season=None, episode=None,
                   progress_pct=0):
    try:
        _request("POST", "/scrobble/pause", access_token,
                 json_body=_scrobble_body(imdb_id, season, episode, progress_pct))
    except Exception:
        pass


def scrobble_stop(access_token, imdb_id, season=None, episode=None,
                  progress_pct=0):
    try:
        _request("POST", "/scrobble/stop", access_token,
                 json_body=_scrobble_body(imdb_id, season, episode, progress_pct))
    except Exception:
        pass


def get_watchlist(access_token, list_type="shows"):
    """Return raw sync/watchlist items (each has a nested show/movie dict)."""
    try:
        return _request("GET", "/sync/watchlist/" + list_type, access_token) or []
    except Exception:
        return []


def get_collection(access_token, list_type="shows"):
    """Return raw sync/collection items (each has a nested show/movie dict)."""
    try:
        return _request("GET", "/sync/collection/" + list_type, access_token) or []
    except Exception:
        return []


def get_watched_shows(access_token):
    try:
        data = _request("GET", "/sync/watched/shows", access_token)
        return data or []
    except Exception:
        return []


def get_show_progress(access_token, trakt_show_id):
    try:
        data = _request(
            "GET",
            "/shows/{}/progress/watched".format(trakt_show_id),
            access_token)
        return data or {}
    except Exception:
        return {}
