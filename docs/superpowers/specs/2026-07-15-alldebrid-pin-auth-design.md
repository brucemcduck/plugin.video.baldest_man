# AllDebrid PIN Authentication Design

**Date:** 2026-07-15
**Status:** Approved (design phase)

## Problem

The addon currently requires users to manually copy their AllDebrid API key from alldebrid.com and paste it into a `alldebrid_api_key` text setting. This causes three pain points:

1. **Pasting is painful** — the long API key is error-prone to copy into Kodi's settings UI (especially on TV remotes)
2. **Silent failures** — when the key is wrong, expired, or revoked, the addon fails to scrape/play with no clear message; AllDebrid's error text never reaches the user
3. **No account visibility** — there's no way to check from inside Kodi whether AllDebrid is active, premium, or nearing expiry

## Solution

Adopt AllDebrid's PIN / device-code flow (the same pattern Umbrella, Seren, and Gaia use), add a one-click account-info dialog, and ensure AllDebrid's error messages surface to the user.

## Architecture

**Approach B (approved):** Add module-level functions to the existing `resources/lib/alldebrid.py` alongside `resolve()`, mirroring the Trakt auth pattern (`trakt.get_device_code` / `poll_for_token` + `mode=auth_trakt` handler) already in this repo. No class refactor, no new module.

### Files changed

| File | Change |
|---|---|
| `resources/lib/alldebrid.py` | Add `pin_start()`, `pin_poll()`, `get_user()`, `revoke()`, `validate_key()` |
| `main.py` | Add `mode=ad_authorize`, `ad_revoke`, `ad_account_info` handlers; update `api_key()` to read `alldebridtoken`; add one-time migration from `alldebrid_api_key` |
| `resources/settings.xml` | Replace editable `alldebrid_api_key` with action buttons (Authorize/Revoke/Account Info) + hidden `alldebridtoken` + display-only `alldebridusername` |

### New functions in `alldebrid.py`

- **`pin_start() -> dict`** — `GET /v4.1/pin/get?agent=plugin.video.baldest_man`; returns `{"pin": "1234", "check": "abc...", "expires_in": 600}`
- **`pin_poll(check, pin, cancel_check=None, poll_interval=5) -> str | None`** — polls `POST /v4/pin/check` every 5s with `{agent, check, pin}`; returns `apikey` string when activated, `None` if cancelled, raises `AllDebridError` on PIN expiry
- **`get_user(api_key) -> dict`** — `GET /v4/user?agent=...&apikey=...`; returns the `user` object: `{username, email, isPremium, premiumUntil}`
- **`revoke()`** — clears `alldebridtoken` and `alldebridusername` settings (no server-side revoke; AllDebrid has no revoke endpoint)
- **`validate_key(api_key) -> bool`** — thin wrapper over `get_user`; returns True/False; used at auth completion

The existing `resolve()` and `_check_response()` are unchanged. `_check_response` already raises `AllDebridError` carrying AllDebrid's `error.message` — that's the error-surfacing foundation.

### New mode handlers in `main.py`

Mirroring the existing `mode=auth_trakt` pattern:

- **`mode=ad_authorize`** — runs the PIN flow with a `DialogProgress`, stores the key, validates it, shows success/failure
- **`mode=ad_revoke`** — calls `alldebrid.revoke()`, shows confirmation
- **`mode=ad_account_info`** — calls `get_user()`, shows a dialog with account details

## PIN Flow (ad_authorize)

1. Call `alldebrid.pin_start()` → returns `{pin, check, expires_in}`
2. Open a cancellable `DialogProgress` showing:
   - Line 1: `Go to: alldebrid.com/pin`
   - Line 2: `Enter code: 1234`
3. Poll loop via `pin_poll(check, pin, cancel_check=pdlg.iscanceled)`:
   - **Activated** → response includes `apikey` → return key
   - **PIN expired** (AllDebrid returns error) → raise `AllDebridError("PIN expired")`
   - **User cancelled** → return None
4. On success: `ADDON.setSetting('alldebridtoken', key)`, then `get_user(key)` to validate + fetch username. Store `alldebridusername`. Notify "AllDebrid authorized: \<username\>". Close dialog.
5. On failure: notify with error message, close dialog.

**Timeout:** the poll loop tracks a deadline from AllDebrid's `expires_in` (typically 600s) rather than a hardcoded value. On expiry, exits with "PIN expired".

## Settings Restructure

### Current
```xml
<setting id="alldebrid_api_key" type="text" label="AllDebrid API Key"/>
```

### New
```xml
<category label="AllDebrid">
  <setting id="ad_authorize_btn" type="action"
           label="Authorize AllDebrid (PIN)"
           action="RunPlugin(plugin://plugin.video.baldest_man/?mode=ad_authorize)"/>
  <setting id="ad_revoke_btn" type="action"
           label="Revoke Authorization"
           action="RunPlugin(plugin://plugin.video.baldest_man/?mode=ad_revoke)"/>
  <setting id="ad_account_info_btn" type="action"
           label="Account Info"
           action="RunPlugin(plugin://plugin.video.baldest_man/?mode=ad_account_info)"/>
  <setting id="alldebridusername" type="text" label="Logged in as"
           enable="false"/>
  <setting id="alldebridtoken" type="text" visible="false"/>
</category>
```

**Conditional visibility:** Authorize button shows when token is empty; Revoke/Account Info show when token is set. Uses Kodi's standard position-based `visible` conditions (e.g., `visible="eq(-2,)"` for "token setting is empty"). Exact syntax verified against Kodi Matrix/Nexus settings schema at implementation time.

**Setting migration:** at addon startup (root menu render), if `alldebrid_api_key` is non-empty and `alldebridtoken` is empty, copy the old key to the new setting. This is a one-time silent migration — existing users keep working without re-authorizing.

**`api_key()` update:** changes from `ADDON.getSetting('alldebrid_api_key')` to `ADDON.getSetting('alldebridtoken')`.

## Error Surfacing & Validation

The goal: no more silent failures. When a key is bad/expired/revoked, the user sees AllDebrid's actual error message.

1. **`_check_response()` (existing)** already parses `{"status":"error","error":{"message":"..."}}` and raises `AllDebridError(message)`. No change.

2. **Play/download handlers (existing)** already catch `AllDebridError` and call `notify(str(e))`. The message now carries AllDebrid's real error text (e.g., "Invalid apikey") instead of a generic string. Message text updated from "AllDebrid API key not set" to "AllDebrid not authorized — use the PIN flow in settings".

3. **`validate_key()` at auth completion** — after the PIN flow stores the key, `get_user()` is called. If it returns an error, the auth handler shows "Authorization failed: \<message\>" and clears the stored token.

4. **No startup API call** — on addon entry, if `alldebridtoken` is set, no extra network call is made. Keeps startup fast. Per-call error handling in `resolve()` already surfaces problems when the user tries to play something.

5. **Empty-key guard** — `api_key()` returns `''` when no token; existing `if not key:` guards in play/download handlers cover this with the updated message.

No new wrapper layer or centralized `_get`/`_post` refactor — `_check_response` + per-handler notify already does the job.

## Account Info Dialog (ad_account_info)

1. Read `alldebridtoken`. If empty → notify "Not authorized" and return.
2. Call `alldebrid.get_user(key)`. If it raises `AllDebridError` → notify with the error message and return (this is the manual "is my key valid?" probe).
3. On success, format and show via `xbmcgui.Dialog().ok()`:
   ```
   AllDebrid Account
   ─────────────────
   Username: bryce
   Status:   Premium
   Expires:  2025-12-31
   Days remaining: 23
   ```
   - Date from `datetime.fromtimestamp(premiumUntil).strftime('%Y-%m-%d')`
   - Days remaining = `(expires - datetime.today()).days`
   - If `isPremium` is false: status shows "Free / Not Premium", expiry/days lines omitted

One-shot dialog, dismissed with OK. No persistent UI.

## AllDebrid API Endpoints Used

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/v4.1/pin/get?agent=...` | GET | none | Start PIN flow; returns `{pin, check, expires_in}` |
| `/v4/pin/check` | POST `{agent, check, pin}` | none | Poll; when activated returns `{apikey}` |
| `/v4/user?agent=...&apikey=...` | GET | apikey | Validate key + fetch account (username, isPremium, premiumUntil) |
| `/v4/magnet/upload`, `/magnet/status`, `/link/unlock` | GET/POST | apikey | Existing resolve flow (unchanged) |

All requests include `agent=plugin.video.baldest_man`.

## Out of Scope

- **No premium-expiry warning on launch** — Umbrella's `alldebridexpirynotice` feature (notify when subscription expires within N days) is deferred. The manual Account Info dialog covers the "check my status" need for now.
- **No Trakt-style token refresh** — AllDebrid keys from the PIN flow are long-lived (don't expire unless revoked); no refresh endpoint exists.
- **No batch re-auth** — single-account only, as today.
- **No server-side revoke** — AllDebrid has no revoke endpoint; `revoke()` only clears local settings.
- **No paste-key fallback** — PIN flow fully replaces manual key entry, per user decision.

## Testing

Manual test checklist (no automated test framework in this repo):

1. **Fresh authorize** — open settings → Authorize → see PIN → enter at alldebrid.com/pin → key stored automatically → "Authorized: \<username\>" notification → Account Info shows correct details
2. **Cancel mid-PIN** — start authorize → cancel dialog → no token stored, no crash
3. **PIN expiry** — start authorize → don't enter PIN → wait 10 min → "PIN expired" notification
4. **Revoke** — with token set → Revoke → token cleared → Authorize button reappears, Revoke/Account Info disappear
5. **Account info with bad key** — manually corrupt `alldebridtoken` in settings → Account Info → error notification with AllDebrid's message
6. **Migration** — set `alldebrid_api_key` in settings, leave `alldebridtoken` empty → open addon → old key migrated → play works without re-authorizing
7. **Play with no auth** — clear token → attempt to play a torrent → "AllDebrid not authorized" notification
8. **Play with expired key** — revoke on AllDebrid website → play → error notification carries AllDebrid's message
