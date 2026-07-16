"""AllDebrid API v4.1 resolver — converts magnet/torrent links to direct URLs."""
import time
import requests
from requests.exceptions import RequestException

API = "https://api.alldebrid.com/v4"


class AllDebridError(Exception):
    pass


def _log(msg):
    """Log to Kodi or stderr for debugging."""
    try:
        import xbmc
        xbmc.log("bald_man alldebrid: " + str(msg), level=xbmc.LOGINFO)
    except ImportError:
        import sys
        print("alldebrid: " + str(msg), file=sys.stderr)


def _fire_progress(cb, state, timeout, elapsed):
    if not cb:
        return
    if state == "uploading":
        cb(state, 0, timeout)
    elif state == "ready":
        cb(state, 100, 0)
    else:
        pct = min(98, int(elapsed / timeout * 100))
        eta = max(0, int(timeout - elapsed))
        cb(state, pct, eta)


def resolve(url, api_key, timeout=120, poll_interval=1, cancel_check=None, progress_callback=None):
    """Resolve a magnet link or torrent URL to a direct streamable URL.

    Polls AllDebrid until the magnet is ready, timing out after `timeout` seconds.
    If cancel_check is provided, it's called each iteration — return True to abort.
    If progress_callback is provided, it's called as progress_callback(state, pct, eta).
    """
    if not api_key:
        raise AllDebridError("API key not set")

    try:
        upload_resp = requests.post(
            API + "/magnet/upload",
            data={"agent": "plugin.video.baldest_man", "apikey": api_key, "magnets[]": url},
            timeout=30,
        )
        upload_data = _check_response(upload_resp)
        _log("upload response: " + str(upload_data.get("data", {}).get("magnets", "?"))[:500])

        magnets = upload_data.get("data", {}).get("magnets", [])
        magnet_id = _extract_id(magnets)
        if not magnet_id:
            raise AllDebridError("No magnet ID in upload response")
        _log("magnet_id=" + str(magnet_id))
        _fire_progress(progress_callback, "uploading", timeout, 0)

        deadline = time.time() + timeout
        start_time = deadline - timeout
        last_status = ""
        poll_count = 0

        while time.time() < deadline:
            if cancel_check and cancel_check():
                raise AllDebridError("Cancelled by user")
            time.sleep(poll_interval)
            poll_count += 1
            if poll_count == 5:
                poll_interval = 2
            elif poll_count == 10:
                poll_interval = 4
            elif poll_count == 15:
                poll_interval = 8

            status_resp = requests.get(
                API + ".1/magnet/status",
                params={"agent": "plugin.video.baldest_man", "apikey": api_key, "id": magnet_id},
                timeout=30,
            )
            status_data = _check_response(status_resp)
            magnets = status_data.get("data", {}).get("magnets", [])
            if not magnets:
                raise AllDebridError("No magnet info in status response")

            if isinstance(magnets, dict) and "status" in magnets:
                magnet_info = magnets
            else:
                magnet_info = _first_item(magnets)

            if isinstance(magnet_info, dict):
                magnet_status = magnet_info.get("status", "")
                status_code = magnet_info.get("statusCode", -1)
            elif isinstance(magnet_info, (int, str)):
                magnet_status = str(magnet_info)
                status_code = int(magnet_info) if str(magnet_info).isdigit() else -1
            else:
                raise AllDebridError("Unexpected magnet status format: {}".format(type(magnet_info).__name__))

            elapsed = int(time.time() - start_time)
            _fire_progress(progress_callback, "downloading", timeout, elapsed)
            if magnet_status != last_status:
                _log("magnet[{}] status={} code={} elapsed={}s".format(magnet_id, magnet_status, status_code, elapsed))
                last_status = magnet_status

            if magnet_status in ("Ready", "4") or status_code == 4:
                _fire_progress(progress_callback, "ready", timeout, 0)
                file_link = _find_file_link(magnet_info.get("files", []))
                if not file_link:
                    raise AllDebridError("Magnet ready but no files returned")

                unlock_resp = requests.get(
                    API + "/link/unlock",
                    params={"agent": "plugin.video.baldest_man", "apikey": api_key, "link": file_link},
                    timeout=30,
                )
                unlock_data = _check_response(unlock_resp)
                direct_url = unlock_data.get("data", {}).get("link", "")
                if not direct_url:
                    raise AllDebridError("Failed to unlock link")
                return direct_url

            elif magnet_status not in ("Downloading", "Processing", "0", "1") and status_code not in (0, 1):
                raise AllDebridError("Magnet failed — status: {} code: {}".format(magnet_status, status_code))

        raise AllDebridError("Magnet download timed out after {}s".format(timeout))
    except RequestException as e:
        raise AllDebridError("API request failed: {}".format(str(e)))


def pin_start():
    """Start AllDebrid PIN flow. Returns dict with 'pin', 'check', 'expires_in'.
    Raises AllDebridError on failure."""
    try:
        resp = requests.get(
            API + ".1/pin/get",
            params={"agent": "plugin.video.baldest_man"},
            timeout=30,
        )
        data = _check_response(resp)
        pin_data = data.get("data", {})
        if not pin_data.get("pin") or not pin_data.get("check"):
            raise AllDebridError("No PIN in response")
        return {
            "pin": pin_data["pin"],
            "check": pin_data["check"],
            "expires_in": pin_data.get("expires_in", 600),
        }
    except RequestException as e:
        raise AllDebridError("PIN request failed: {}".format(e))


def pin_poll(check, pin, cancel_check=None, poll_interval=5, expires_in=600):
    """Poll AllDebrid until the PIN is activated. Returns the apikey string.
    Returns None if cancelled via cancel_check. Raises AllDebridError on expiry.
    """
    deadline = time.time() + expires_in
    while time.time() < deadline:
        if cancel_check and cancel_check():
            return None
        time.sleep(poll_interval)
        try:
            resp = requests.post(
                API + "/pin/check",
                data={"agent": "plugin.video.baldest_man",
                      "check": check, "pin": pin},
                timeout=30,
            )
            data = _check_response(resp)
            pin_data = data.get("data", {})
            if pin_data.get("activated"):
                apikey = pin_data.get("apikey", "")
                if apikey:
                    return str(apikey)
                raise AllDebridError("PIN activated but no apikey returned")
        except AllDebridError:
            raise
        except RequestException as e:
            raise AllDebridError("PIN check failed: {}".format(e))
    raise AllDebridError("PIN expired")


def get_user(api_key):
    """Fetch account info via /user endpoint. Returns the 'user' dict.
    Raises AllDebridError on failure (invalid key, network error)."""
    try:
        resp = requests.get(
            API + "/user",
            params={"agent": "plugin.video.baldest_man", "apikey": api_key},
            timeout=30,
        )
        data = _check_response(resp)
        user = data.get("data", {}).get("user", {})
        if not user:
            raise AllDebridError("No user info in response")
        return user
    except RequestException as e:
        raise AllDebridError("User request failed: {}".format(e))


def revoke():
    """Clear stored AllDebrid credentials. No server-side revoke (none exists)."""
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon()
        addon.setSetting("alldebridtoken", "")
        addon.setSetting("alldebridusername", "")
    except ImportError:
        pass


def validate_key(api_key):
    """Check if an API key is valid by calling /user. Returns True/False."""
    try:
        get_user(api_key)
        return True
    except AllDebridError:
        return False


def _find_file_link(files):
    """Find first downloadable file link in AllDebrid's v4.1 nested file tree.
    Tree nodes: {"n": name, "s": size, "l": link} for files,
    {"n": name, "e": [...]} or {"n": name, "files": [...]} for folders.
    """
    if isinstance(files, list):
        for f in files:
            if isinstance(f, dict):
                if "l" in f and f["l"]:
                    return f["l"]
                for child_key in ("e", "files"):
                    if child_key in f:
                        result = _find_file_link(f[child_key])
                        if result:
                            return result
    return None


def _check_response(resp):
    """Validate AllDebrid API response, raise AllDebridError on failure."""
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError as e:
        raise AllDebridError("Invalid API response: {}".format(str(e)))
    status = data.get("status", "")
    error_msg = data.get("error", {}).get("message", "")

    if status == "error":
        raise AllDebridError(error_msg or "Unknown API error")

    return data


def _first_item(collection):
    """Get first item from a list or dict value. Handles v4.1 format variations."""
    if isinstance(collection, dict):
        return next(iter(collection.values()), None)
    if isinstance(collection, list) and collection:
        return collection[0]
    return None


def _extract_id(collection):
    """Extract magnet ID from upload response. v4.1 may return:
    - list of dicts: [{"id": 123, ...}]
    - dict of dicts: {"hash": {"id": 123, ...}}
    - dict of ints: {"hash": 123}  (value IS the id)
    """
    item = _first_item(collection)
    if isinstance(item, dict):
        return item.get("id")
    return item  # int or string ID directly
