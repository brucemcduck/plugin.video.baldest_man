"""AllDebrid API v4.1 resolver — converts magnet/torrent links to direct URLs."""
import requests
from requests.exceptions import RequestException

API_BASE = "https://api.alldebrid.com/v4/"


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
            API_BASE + "magnet/upload",
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

        # Step 3: Get status — AllDebrid may need time to process
        status_resp = requests.get(
            API_BASE + "magnet/status",
            params={"agent": "plugin.video.baldest_man", "apikey": api_key, "id": magnet_id},
            timeout=30,
        )
        status_data = _check_response(status_resp)

        magnets = status_data.get("data", {}).get("magnets", [])
        if not magnets:
            raise AllDebridError("No magnet info in status response")
        magnet_info = magnets[0]
        status = magnet_info.get("status", "")

        if status == "Ready":
            links = magnet_info.get("links", [])
            if not links:
                raise AllDebridError("Magnet ready but no links returned")
            # Return the first link's streamable URL — unlock it
            first_link = links[0].get("link", "")
            if not first_link:
                raise AllDebridError("Link entry missing URL")

            # Unlock the link to get the final direct URL
            unlock_resp = requests.get(
                API_BASE + "link/unlock",
                params={"agent": "plugin.video.baldest_man", "apikey": api_key, "link": first_link},
                timeout=30,
            )
            unlock_data = _check_response(unlock_resp)
            direct_url = unlock_data.get("data", {}).get("link", "")
            if not direct_url:
                raise AllDebridError("Failed to unlock link")
            return direct_url

        elif status == "Downloading" or status == "Processing":
            # ponytail: no polling loop — magnet just uploaded, give it a moment
            # If real scrapers hit this, add a retry with backoff
            raise AllDebridError("Magnet still processing, try again")
        else:
            raise AllDebridError("Unknown magnet status: {}".format(status))
    except RequestException as e:
        raise AllDebridError("API request failed: {}".format(str(e)))


def _check_response(resp):
    """Validate AllDebrid API response, raise AllDebridError on failure."""
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status", "")
    error_msg = data.get("error", {}).get("message", "")

    if status == "error":
        raise AllDebridError(error_msg or "Unknown API error")

    return data
