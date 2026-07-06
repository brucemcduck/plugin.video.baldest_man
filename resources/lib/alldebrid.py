"""AllDebrid API v4.1 resolver — converts magnet/torrent links to direct URLs."""
import requests
from requests.exceptions import RequestException

API = "https://api.alldebrid.com/v4"


class AllDebridError(Exception):
    pass


def resolve(url, api_key):
    """Resolve a magnet link or torrent URL to a direct streamable URL.

    Args:
        url: str — magnet link (magnet:?xt=urn:btih:...) or torrent URL
        api_key: str — AllDebrid API key

    Returns:
        str — direct downloadable/streamable URL

    Raises:
        AllDebridError — on any failure (bad key, rate limit, service down, no files)
    """
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

        # Step 2: Get the magnet/torrent ID
        magnets = upload_data.get("data", {}).get("magnets", [])
        if not magnets:
            raise AllDebridError("No magnet returned from upload")

        magnet_id = magnets[0].get("id")
        if not magnet_id:
            raise AllDebridError("No magnet ID in response")

        # Step 3: Get status via v4.1 (v4/magnet/status deprecated since 10/2024)
        status_resp = requests.get(
            API + ".1/magnet/status",
            params={"agent": "plugin.video.baldest_man", "apikey": api_key, "id": magnet_id},
            timeout=30,
        )
        status_data = _check_response(status_resp)

        magnets = status_data.get("data", {}).get("magnets", [])
        if not magnets:
            raise AllDebridError("No magnet info in status response")
        magnet_info = magnets[0]
        magnet_status = magnet_info.get("status", "")

        if magnet_status == "Ready":
            # v4.1: files are a nested tree — find first downloadable file
            file_link = _find_file_link(magnet_info.get("files", []))
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

        elif magnet_status == "Downloading" or magnet_status == "Processing":
            raise AllDebridError("Magnet still processing, try again")
        else:
            raise AllDebridError("Unknown magnet status: {}".format(magnet_status))
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
