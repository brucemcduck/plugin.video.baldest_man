# AllDebrid PIN Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual API-key pasting with AllDebrid's PIN/device-code flow, add account-info dialog, and surface AllDebrid error messages to the user.

**Architecture:** Approach B — add module-level functions (`pin_start`, `pin_poll`, `get_user`, `revoke`, `validate_key`) to the existing `resources/lib/alldebrid.py` alongside `resolve()`, mirroring the Trakt auth pattern (`trakt.get_device_code`/`poll_for_token` + `mode=auth_trakt`). Three new mode handlers in `main.py` (`ad_authorize`, `ad_revoke`, `ad_account_info`). Settings restructured: `alldebrid_api_key` replaced by hidden `alldebridtoken` + action buttons.

**Tech Stack:** Python 3, Kodi Matrix+ (xbmcaddon/xbmcgui/xbmcplugin), `requests` library, AllDebrid API v4/v4.1.

## Global Constraints

- AllDebrid API base URLs: `https://api.alldebrid.com/v4` (pin/check, user) and `https://api.alldebrid.com/v4.1` (pin/get)
- All requests include `agent=plugin.video.baldest_man`
- AllDebrid v4 response envelope: `{"status":"success","data":{...}}` or `{"status":"error","error":{"code":N,"message":"..."}}`
- `_check_response()` in alldebrid.py already parses this envelope and raises `AllDebridError(message)` — reuse it, do not duplicate
- Settings use Kodi's `<constraints><hidden>true</hidden></constraints>` for hidden fields (see existing `alldebrid_api_key` at settings.xml:10-15 and `trakt_access_token` at settings.xml:50-55 for the exact pattern)
- `notify(msg)` helper exists at main.py:40 — use it for all user-facing messages
- `build_url(query)` helper exists at main.py:35 — use it for all plugin URLs
- `ADDON` is the global `xbmcaddon.Addon()` instance in main.py
- `api_key()` at main.py:189 currently reads `alldebrid_api_key` — Task 2 changes it to read `alldebridtoken`
- No automated test framework in this repo (Kodi addon); verification is syntax-check (`python3 -c "import ast..."`) + manual test checklist
- One commit per task

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `resources/lib/alldebrid.py` | AllDebrid API client — existing `resolve()` + new auth functions | Task 1 |
| `resources/settings.xml` | Kodi settings definitions — AllDebrid category restructure | Task 2 |
| `main.py` | Plugin router — `api_key()` migration + three new mode handlers | Task 3 |
| `main.py` | Startup migration check for old `alldebrid_api_key` | Task 3 (folded in) |

---

### Task 1: AllDebrid auth functions in alldebrid.py

**Files:**
- Modify: `resources/lib/alldebrid.py` (add functions after `resolve()`, before `_find_file_link`)

**Interfaces:**
- Consumes: existing `_check_response()` at alldebrid.py:152, `AllDebridError` at alldebrid.py:9, `requests`, `time`
- Produces:
  - `pin_start() -> dict` — returns `{"pin": str, "check": str, "expires_in": int}`
  - `pin_poll(check, pin, cancel_check=None, poll_interval=5) -> str | None` — returns apikey string or None (cancelled); raises `AllDebridError` on expiry
  - `get_user(api_key) -> dict` — returns the `user` dict from AllDebrid's `/user` response
  - `revoke()` — clears `alldebridtoken` + `alldebridusername` settings via xbmcaddon
  - `validate_key(api_key) -> bool` — returns True if `get_user` succeeds

- [ ] **Step 1: Add `pin_start()` function**

Add after the `resolve()` function (after line 131, before `_find_file_link` at line 134):

```python
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
```

- [ ] **Step 2: Add `pin_poll()` function**

Add immediately after `pin_start()`:

```python
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
```

- [ ] **Step 3: Add `get_user()` function**

Add immediately after `pin_poll()`:

```python
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
```

- [ ] **Step 4: Add `revoke()` function**

Add immediately after `get_user()`:

```python
def revoke():
    """Clear stored AllDebrid credentials. No server-side revoke (none exists)."""
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon()
        addon.setSetting("alldebridtoken", "")
        addon.setSetting("alldebridusername", "")
    except ImportError:
        pass
```

- [ ] **Step 5: Add `validate_key()` function**

Add immediately after `revoke()`:

```python
def validate_key(api_key):
    """Check if an API key is valid by calling /user. Returns True/False."""
    try:
        get_user(api_key)
        return True
    except AllDebridError:
        return False
```

- [ ] **Step 6: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('resources/lib/alldebrid.py').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add resources/lib/alldebrid.py
git commit -m "feat: add AllDebrid PIN auth functions (pin_start, pin_poll, get_user, revoke, validate_key)"
```

---

### Task 2: Settings restructure

**Files:**
- Modify: `resources/settings.xml` (lines 3-22, the AllDebrid category)

**Interfaces:**
- Consumes: nothing (settings definitions are standalone XML)
- Produces: new settings `alldebridtoken` (hidden), `alldebridusername` (display-only), and three action buttons `ad_authorize_btn`/`ad_revoke_btn`/`ad_account_info_btn`; removes `alldebrid_api_key`

- [ ] **Step 1: Replace the AllDebrid category**

Replace the entire `<category label="AllDebrid">...</category>` block (lines 3-22) with:

```xml
  <category label="AllDebrid">
    <setting id="magnet_timeout" type="integer" label="Magnet download timeout (seconds)" default="120">
      <constraints>
        <minimum>30</minimum>
        <maximum>600</maximum>
      </constraints>
    </setting>
    <setting label="Authorize AllDebrid (PIN)" type="action"
             action="RunPlugin(plugin://plugin.video.baldest_man/?mode=ad_authorize)"/>
    <setting label="Revoke Authorization" type="action"
             action="RunPlugin(plugin://plugin.video.baldest_man/?mode=ad_revoke)"/>
    <setting label="Account Info" type="action"
             action="RunPlugin(plugin://plugin.video.baldest_man/?mode=ad_account_info)"/>
    <setting id="alldebridusername" type="text" label="Logged in as" default="">
      <constraints>
        <allowempty>true</allowempty>
      </constraints>
    </setting>
    <setting id="alldebridtoken" type="text" default="">
      <constraints>
        <allowempty>true</allowempty>
        <hidden>true</hidden>
      </constraints>
    </setting>
    <setting id="last_played" type="text" default="">
      <constraints>
        <allowempty>true</allowempty>
        <hidden>true</hidden>
      </constraints>
    </setting>
  </category>
```

This keeps `magnet_timeout` and `last_played` in place (they're not auth-related) and replaces `alldebrid_api_key` with the button-driven flow. The `alldebridtoken` setting uses the same `<hidden>true</hidden>` pattern as the old `alldebrid_api_key` (settings.xml:13) and `trakt_access_token` (settings.xml:53).

Note: Kodi conditional visibility (`visible="eq(-N,)"`) is intentionally omitted here — Kodi shows action buttons unconditionally by default, and the handlers themselves guard against missing tokens (revoke/account-info notify "Not authorized" if no token). Adding conditional visibility is a UI polish that can be done later if the user finds the buttons cluttered.

- [ ] **Step 2: XML validation**

Run: `python3 -c "import xml.etree.ElementTree as E; E.parse('resources/settings.xml'); print('XML OK')"`
Expected: `XML OK`

- [ ] **Step 3: Commit**

```bash
git add resources/settings.xml
git commit -m "feat: replace alldebrid_api_key with PIN auth action buttons + hidden token setting"
```

---

### Task 3: Mode handlers + api_key() migration

**Files:**
- Modify: `main.py:189` — change `api_key()` to read `alldebridtoken`
- Modify: `main.py:16` — add imports from `alldebrid` (pin_start, pin_poll, get_user, revoke, validate_key)
- Modify: `main.py` root menu — add one-time migration from `alldebrid_api_key` to `alldebridtoken`
- Modify: `main.py` — add three new mode handlers before the Trakt auth handler (before `# --- Auth: Trakt device OAuth ---`)

**Interfaces:**
- Consumes: `pin_start()`, `pin_poll()`, `get_user()`, `revoke()`, `validate_key()` from Task 1; `alldebridtoken`/`alldebridusername` settings from Task 2
- Produces: working `mode=ad_authorize`, `mode=ad_revoke`, `mode=ad_account_info` handlers; `api_key()` returns `alldebridtoken` value

- [ ] **Step 1: Update imports**

At main.py:16, change the alldebrid import line from:

```python
from resources.lib.alldebrid import resolve as ad_resolve, AllDebridError
```

to:

```python
from resources.lib.alldebrid import (resolve as ad_resolve, AllDebridError,
                                      pin_start as ad_pin_start,
                                      pin_poll as ad_pin_poll,
                                      get_user as ad_get_user,
                                      revoke as ad_revoke_auth,
                                      validate_key as ad_validate_key)
```

- [ ] **Step 2: Update `api_key()` to read the new setting**

At main.py:189, change:

```python
def api_key():
    return ADDON.getSetting('alldebrid_api_key')
```

to:

```python
def api_key():
    return ADDON.getSetting('alldebridtoken')
```

- [ ] **Step 3: Add one-time migration check in root menu**

Find the root menu section — it starts with `if mode is None:` (around main.py:210). After the opening of that block, before any directory items are added, insert this migration check:

```python
    # One-time migration: copy old alldebrid_api_key to alldebridtoken
    old_key = ADDON.getSetting('alldebrid_api_key')
    new_key = ADDON.getSetting('alldebridtoken')
    if old_key and not new_key:
        ADDON.setSetting('alldebridtoken', old_key)
```

- [ ] **Step 4: Add `mode=ad_authorize` handler**

Insert before the line `# --- Auth: Trakt device OAuth ---` (main.py:559):

```python
# --- Auth: AllDebrid PIN flow ---
elif mode[0] == 'ad_authorize':
    try:
        pin_data = ad_pin_start()
    except AllDebridError as e:
        notify("AllDebrid: " + str(e))
        xbmcplugin.endOfDirectory(addon_handle)
    else:
        msg = ("1. Go to: [COLOR skyblue]https://alldebrid.com/pin[/COLOR]\n"
               "2. Enter code: [COLOR yellow]{}[/COLOR]\n"
               "3. Wait while we check...").format(pin_data["pin"])
        xbmcgui.Dialog().ok("AllDebrid Authorization", msg)

        pdlg = xbmcgui.DialogProgress()
        pdlg.create("AllDebrid", "Waiting for authorization...")
        try:
            apikey = ad_pin_poll(
                pin_data["check"], pin_data["pin"],
                cancel_check=pdlg.iscanceled,
                expires_in=pin_data["expires_in"])
            if not apikey:
                pdlg.close()
                notify("Authorization cancelled")
            else:
                ADDON.setSetting('alldebridtoken', apikey)
                try:
                    user = ad_get_user(apikey)
                    username = user.get("username", "")
                    if username:
                        ADDON.setSetting('alldebridusername', username)
                    pdlg.close()
                    notify("AllDebrid authorized: " + (username or "success"))
                except AllDebridError as e:
                    pdlg.close()
                    ADDON.setSetting('alldebridtoken', "")
                    notify("Authorization failed: " + str(e))
        except AllDebridError as e:
            pdlg.close()
            notify("AllDebrid: " + str(e))

        xbmcplugin.endOfDirectory(addon_handle)

# --- Auth: AllDebrid revoke ---
elif mode[0] == 'ad_revoke':
    ad_revoke_auth()
    notify("AllDebrid authorization revoked")
    xbmcplugin.endOfDirectory(addon_handle)

# --- Auth: AllDebrid account info ---
elif mode[0] == 'ad_account_info':
    key = ADDON.getSetting('alldebridtoken')
    if not key:
        notify("AllDebrid not authorized — use the PIN flow in settings")
        xbmcplugin.endOfDirectory(addon_handle)
    else:
        try:
            user = ad_get_user(key)
        except AllDebridError as e:
            notify("AllDebrid: " + str(e))
            xbmcplugin.endOfDirectory(addon_handle)
        else:
            from datetime import datetime
            username = user.get("username", "?")
            is_premium = user.get("isPremium", False)
            lines = ["AllDebrid Account", "─────────────────",
                     "Username: {}".format(username)]
            if is_premium:
                premium_until = user.get("premiumUntil", 0)
                if premium_until:
                    expires = datetime.fromtimestamp(premium_until)
                    days = (expires - datetime.today()).days
                    lines.append("Status:   Premium")
                    lines.append("Expires:  " + expires.strftime("%Y-%m-%d"))
                    lines.append("Days remaining: {}".format(max(0, days)))
                else:
                    lines.append("Status:   Premium")
            else:
                lines.append("Status:   Free / Not Premium")
            xbmcgui.Dialog().ok("AllDebrid Account", "\n".join(lines))
            xbmcplugin.endOfDirectory(addon_handle)

```

- [ ] **Step 5: Update "not authorized" messages in play + download handlers**

Find the two places in main.py that say `'AllDebrid API key not set'` (in the `mode=play` and `mode=download` handlers) and change both to:

```python
            notify('AllDebrid not authorized — use the PIN flow in settings')
```

Use `replaceAll: true` if the edit tool supports it, otherwise edit each occurrence.

- [ ] **Step 6: Syntax check**

Run: `python3 -c "import ast; ast.parse(open('main.py').read()); print('main OK')"`
Expected: `main OK`

- [ ] **Step 7: Commit**

```bash
git add main.py
git commit -m "feat: add AllDebrid PIN auth handlers + migrate api_key() to alldebridtoken"
```

---

## Manual Test Checklist (post-implementation)

Run these in Kodi after all three tasks are complete:

1. **Fresh authorize** — open settings → "Authorize AllDebrid (PIN)" → see PIN dialog → enter PIN at alldebrid.com/pin → "Authorized: \<username\>" notification → "Logged in as" setting shows username
2. **Cancel mid-PIN** — start authorize → cancel the progress dialog → "Authorization cancelled" notification, no token stored
3. **PIN expiry** — start authorize → don't enter PIN → wait 10 min → "PIN expired" notification
4. **Account info** — with token set → "Account Info" button → dialog shows username, Premium status, expiry, days remaining
5. **Account info with bad key** — manually corrupt `alldebridtoken` in settings → Account Info → error notification with AllDebrid's message
6. **Revoke** — with token set → "Revoke Authorization" → "authorization revoked" notification → token cleared, "Logged in as" empty
7. **Migration** — set `alldebrid_api_key` in settings (simulating old install), leave `alldebridtoken` empty → open addon root menu → old key silently copied → play a torrent without re-authorizing
8. **Play with no auth** — clear `alldebridtoken` → attempt to play a torrent → "AllDebrid not authorized — use the PIN flow in settings"
9. **Play after auth** — authorize via PIN → play a torrent → resolves and plays normally
