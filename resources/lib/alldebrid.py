"""AllDebrid API v4.1 resolver — converts magnet/torrent links to direct URLs."""
import re
import time
import requests
from requests.exceptions import RequestException

VIDEO_EXTENSIONS = (
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts", ".vob", ".iso",
)

API = "https://api.alldebrid.com/v4"
STALL_TIMEOUT = 10  # seconds without download progress before declaring magnet dead


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
    elif not timeout:
        # No timeout configured — report elapsed time, no ETA.
        cb(state, 0, 0)
    else:
        pct = min(98, int(elapsed / timeout * 100))
        eta = max(0, int(timeout - elapsed))
        cb(state, pct, eta)


def resolve(url, api_key, timeout=120, poll_interval=1, cancel_check=None,
            progress_callback=None, season=None, episode=None):
    """Resolve a magnet link or torrent URL to a direct streamable URL.

    Polls AllDebrid until the magnet is ready, timing out after `timeout` seconds.
    If cancel_check is provided, it's called each iteration — return True to abort.
    If progress_callback is provided, it's called as progress_callback(state, pct, eta).
    If season and episode are provided, prefer the file matching S{season}E{episode};
    otherwise the largest video file in the magnet is selected.
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

        deadline = time.time() + timeout if timeout else None
        start_time = time.time()
        last_status = ""
        poll_count = 0
        last_downloaded = None
        last_progress_time = None

        while deadline is None or time.time() < deadline:
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

            # Stall detection: track download progress during Downloading status
            if status_code == 1 or magnet_status == "Downloading":
                current_downloaded = magnet_info.get("downloaded") if isinstance(magnet_info, dict) else None
                if current_downloaded is not None:
                    if last_downloaded is None or current_downloaded > last_downloaded:
                        last_downloaded = current_downloaded
                        last_progress_time = time.time()
                    elif last_progress_time is not None and time.time() - last_progress_time >= STALL_TIMEOUT:
                        raise AllDebridError(
                            "Magnet stalled — no download progress in {}s".format(STALL_TIMEOUT))
            else:
                last_downloaded = None
                last_progress_time = None

            if magnet_status in ("Ready", "4") or status_code == 4:
                _fire_progress(progress_callback, "ready", timeout, 0)
                file_link = _find_file_link(magnet_info.get("files", []),
                                            season=season, episode=episode)
                if not file_link:
                    raise AllDebridError("Magnet ready but no video files returned")

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


def _find_file_link(files, season=None, episode=None):
    """Find the best downloadable file link in AllDebrid's v4.1 nested file tree.

    Tree nodes: {"n": name, "s": size, "l": link} for files,
    {"n": name, "e": [...]} or {"n": name, "files": [...]} for folders.

    Selection order:
    1. If season and episode are given, prefer the video file whose name matches
       S{season}E{episode} (zero-padded or not, any separator).
    2. Otherwise (or if no episode match), return the largest video file by size.
    3. Non-video files (.txt, .nfo, .jpg, ...) are never selected.

    Returns the link string, or None if no video file is found.
    """
    videos = _collect_video_files(files)
    if not videos:
        return None

    if season is not None and episode is not None:
        pattern = _episode_pattern(season, episode)
        for name, _size, link in videos:
            if pattern.search(name):
                return link

    # Fallback: largest video file (sorted ascending, take last)
    videos.sort(key=lambda v: v[1] or 0)
    return videos[-1][2]


def _collect_video_files(files, out=None):
    """Walk the v4.1 file tree and return a flat list of (name, size, link) tuples
    for nodes whose name ends in a known video extension. Folder nodes are
    traversed via 'e' or 'files' keys."""
    if out is None:
        out = []
    if isinstance(files, list):
        for f in files:
            if not isinstance(f, dict):
                continue
            name = f.get("n", "")
            link = f.get("l")
            if link and _is_video(name):
                out.append((name, f.get("s", 0) or 0, link))
                continue
            for child_key in ("e", "files"):
                if child_key in f:
                    _collect_video_files(f[child_key], out)
    return out


def _is_video(name):
    return name.lower().endswith(VIDEO_EXTENSIONS)


def _episode_pattern(season, episode):
    """Regex matching S{season}E{episode} in a filename, tolerant of zero-padding
    and separators. Negative lookahead prevents S01E1 from matching S01E10."""
    s = int(season)
    e = int(episode)
    return re.compile(
        r"[._ -]s0*{}e0*{}(?![0-9])".format(s, e),
        re.IGNORECASE,
    )


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
