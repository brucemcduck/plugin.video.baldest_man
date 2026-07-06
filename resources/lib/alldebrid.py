"""AllDebrid API v4.1 resolver — converts magnet/torrent links to direct URLs."""
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


def resolve(url, api_key):
    """Resolve a magnet link or torrent URL to a direct streamable URL."""
    if not api_key:
        raise AllDebridError("API key not set")

    try:
        # Step 1: Upload magnet/torrent to AllDebrid
        upload_resp = requests.post(
            API + "/magnet/upload",
            data={"agent": "plugin.video.baldest_man", "apikey": api_key, "magnets[]": url},
            timeout=30,
        )
        upload_data = _check_response(upload_resp)
        _log("upload response: " + str(upload_data.get("data", {}).get("magnets", "?"))[:500])

        # Step 2: Get the magnet/torrent ID
        magnets = upload_data.get("data", {}).get("magnets", [])
        magnet_id = _extract_id(magnets)
        if not magnet_id:
            raise AllDebridError("No magnet ID in upload response")
        _log("magnet_id=" + str(magnet_id))

        # Step 3: Get status via v4.1
        status_resp = requests.get(
            API + ".1/magnet/status",
            params={"agent": "plugin.video.baldest_man", "apikey": api_key, "id": magnet_id},
            timeout=30,
        )
        status_data = _check_response(status_resp)
        _log("status response: " + str(status_data.get("data", {}))[:500])

        magnets = status_data.get("data", {}).get("magnets", [])
        if not magnets:
            raise AllDebridError("No magnet info in status response")
        _log("status magnets type=" + type(magnets).__name__ + " value=" + str(magnets)[:500])
        magnet_info = _first_item(magnets)
        _log("magnet_info type=" + type(magnet_info).__name__ + " value=" + str(magnet_info)[:500])

        # v4.1 status: int code (4=Ready) or string, or full dict
        if isinstance(magnet_info, dict):
            magnet_status = magnet_info.get("status", "")
            status_code = magnet_info.get("statusCode", -1)
        elif isinstance(magnet_info, (int, str)):
            magnet_status = str(magnet_info)
            status_code = int(magnet_info) if str(magnet_info).isdigit() else -1
        else:
            raise AllDebridError("Unexpected magnet status format: {}".format(type(magnet_info).__name__))

        _log("magnet_status=" + magnet_status + " status_code=" + str(status_code))

        if magnet_status in ("Ready", "4") or status_code == 4:
            # Step 4: Get files
            files_resp = requests.get(
                API + "/magnet/files",
                params={"agent": "plugin.video.baldest_man", "apikey": api_key, "id": magnet_id},
                timeout=30,
            )
            files_data = _check_response(files_resp)
            file_tree = files_data.get("data", {}).get("files", [])
            _log("files response: " + str(file_tree)[:500])

            file_link = _find_file_link(file_tree)
            if not file_link:
                raise AllDebridError("Magnet ready but no files returned")

            # Unlock the link to get the final direct URL
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

        elif magnet_status in ("Downloading", "Processing", "0", "1") or status_code in (0, 1):
            raise AllDebridError("Magnet still processing, try again")
        else:
            raise AllDebridError("Magnet failed — status: {} code: {}".format(magnet_status, status_code))
    except RequestException as e:
        raise AllDebridError("API request failed: {}".format(str(e)))


def _find_file_link(files):
    """Find first downloadable file link in AllDebrid's v4.1 nested file tree."""
    if isinstance(files, list):
        for f in files:
            if isinstance(f, dict):
                # Direct file: {"n": "name", "s": size, "l": "url"}
                if "l" in f and f["l"]:
                    return f["l"]
                # Nested folder: {"n": "folder", "files": [...]}
                if "files" in f:
                    result = _find_file_link(f["files"])
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
