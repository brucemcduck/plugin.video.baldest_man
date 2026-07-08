"""AllDebrid PIN-based device authorization."""
import time
import requests

API = "https://api.alldebrid.com/v4"
TIMEOUT = 15
HEADERS = {"User-Agent": "plugin.video.baldest_man/0.1"}


class AuthError(Exception):
    pass


def get_pin():
    """Request a PIN code. Returns (pin, check_token, user_url, expires_in)."""
    try:
        resp = requests.get(API + ".1/pin/get", timeout=TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise AuthError("Failed to get PIN: {}".format(e))
    except ValueError:
        raise AuthError("Invalid response from AllDebrid")

    if data.get("status") != "success":
        raise AuthError(data.get("error", {}).get("message", "Unknown error"))

    pin_data = data.get("data", {})
    return (
        pin_data.get("pin", ""),
        pin_data.get("check", ""),
        pin_data.get("user_url", ""),
        pin_data.get("expires_in", 600),
    )


def poll_for_key(pin, check_token, max_wait=120, cancel_check=None):
    """Poll until user authorizes. Returns API key or raises AuthError.

    If cancel_check is provided, it's called each iteration. Return True to abort.
    """
    deadline = time.time() + min(max_wait, 600)
    params = {"pin": pin, "check": check_token}

    while time.time() < deadline:
        if cancel_check and cancel_check():
            raise AuthError("Cancelled by user")

        try:
            resp = requests.post(API + "/pin/check", data=params,
                                 timeout=TIMEOUT, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            time.sleep(3)
            continue

        if data.get("status") == "success" and data.get("data", {}).get("activated"):
            return data["data"]["apikey"]

        error_code = data.get("error", {}).get("code", "")
        if error_code in ("PIN_EXPIRED", "PIN_INVALID"):
            raise AuthError("PIN expired — try again")

        time.sleep(3)

    raise AuthError("Timed out waiting for authorization")
