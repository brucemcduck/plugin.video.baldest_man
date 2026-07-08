# Magnet Resolution Progress Dialog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a foreground DialogProgress during magnet resolution with status text, pseudo-progress bar, and ETA.

**Architecture:** Extend the existing `cancel_check` callback pattern in `resolve()` with a `progress_callback(state, pct, eta)`. `main.py` creates a `DialogProgress` and passes a closure that updates it. Library stays Kodi-free.

**Tech Stack:** Python 3, Kodi xbmcgui.DialogProgress, AllDebrid API v4.1

## Global Constraints

- Poll interval reduced to 1s for smoother progress
- Pseudo-progress capped at 98% during download, jumps to 100% on ready
- Cancel button must remain functional (already wired via `cancel_check`)

---

### Task 1: Add progress_callback to alldebrid.py resolve()

**Files:**
- Modify: `resources/lib/alldebrid.py:23` (resolve function signature and body)

**Interfaces:**
- Consumes: (none new)
- Produces: `resolve(url, api_key, timeout=120, poll_interval=1, cancel_check=None, progress_callback=None)` — calls `progress_callback(state, pct, eta_seconds)` during upload, each poll, and on ready

- [ ] **Step 1: Change default poll_interval and add progress_callback parameter**

```python
def resolve(url, api_key, timeout=120, poll_interval=1, cancel_check=None, progress_callback=None):
    """Resolve a magnet link or torrent URL to a direct streamable URL.

    Polls AllDebrid until the magnet is ready, timing out after `timeout` seconds.
    If cancel_check is provided, it's called each iteration — return True to abort.
    If progress_callback is provided, it's called as progress_callback(state, pct, eta).
    """
```

- [ ] **Step 2: Add helper to call progress callback**

Add after `_log` function, before `resolve`:

```python
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
```

- [ ] **Step 3: Fire upload callback after getting magnet_id, before loop**

Insert after `_log("magnet_id=" + str(magnet_id))` line:

```python
        _fire_progress(progress_callback, "uploading", timeout, 0)
```

- [ ] **Step 4: Fire download callback each polling iteration, after status parse**

Add `_fire_progress` call right before the existing status-change block (after the `elapsed` computation):

```python
            elapsed = int(time.time() + poll_interval - deadline + timeout)
            _fire_progress(progress_callback, "downloading", timeout, elapsed)
            if magnet_status != last_status:
                _log("magnet[{}] status={} code={} elapsed={}s".format(magnet_id, magnet_status, status_code, elapsed))
                last_status = magnet_status
```

- [ ] **Step 5: Fire ready callback before unlocking**

Insert before the unlock HTTP request:

```python
            if magnet_status in ("Ready", "4") or status_code == 4:
                _fire_progress(progress_callback, "ready", timeout, 0)
                file_link = _find_file_link(magnet_info.get("files", []))
```

---

### Task 2: Add DialogProgress to main.py play handler

**Files:**
- Modify: `main.py:408-419` (play handler torrent branch)

**Interfaces:**
- Consumes: `resolve()` with new `progress_callback` parameter
- Produces: DialogProgress shown during magnet resolution, closed on completion/error

- [ ] **Step 1: Create DialogProgress and pass callbacks**

Replace lines 409-419:

Old:
```python
            try:
                timeout = int(ADDON.getSetting('magnet_timeout') or 120)
                direct_url = ad_resolve(url, key, timeout=timeout)
                # Save for Continue Watching
                label = args.get('label', [''])[0]
                ADDON.setSetting('last_played', json.dumps({'url': url, 'label': label}))
                li = xbmcgui.ListItem(path=direct_url)
                xbmcplugin.setResolvedUrl(addon_handle, True, li)
            except AllDebridError as e:
                notify('AllDebrid: ' + str(e))
                xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
```

New:
```python
            try:
                timeout = int(ADDON.getSetting('magnet_timeout') or 120)
                pdlg = xbmcgui.DialogProgress()
                pdlg.create("Resolving magnet...", "Uploading magnet...")

                def progress_cb(state, pct, eta):
                    if state == "uploading":
                        pdlg.update(0, "Uploading magnet...")
                    elif state == "ready":
                        pdlg.update(100, "Ready!")
                    else:
                        msg = "Downloading — ~{}s remaining".format(eta)
                        pdlg.update(pct, msg)

                direct_url = ad_resolve(url, key, timeout=timeout,
                                        cancel_check=pdlg.iscanceled,
                                        progress_callback=progress_cb)
                pdlg.close()
                label = args.get('label', [''])[0]
                ADDON.setSetting('last_played', json.dumps({'url': url, 'label': label}))
                li = xbmcgui.ListItem(path=direct_url)
                xbmcplugin.setResolvedUrl(addon_handle, True, li)
            except AllDebridError as e:
                try:
                    pdlg.close()
                except Exception:
                    pass
                notify('AllDebrid: ' + str(e))
                xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
```

- [ ] **Step 2: Run syntax check**

```bash
python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"
python3 -c "import ast; ast.parse(open('resources/lib/alldebrid.py').read()); print('OK')"
```
Expected: OK for both.

- [ ] **Step 3: Copy to Kodi and test**

```bash
cp main.py /home/bryce/.kodi/addons/plugin.video.baldest_man/
cp resources/lib/alldebrid.py /home/bryce/.kodi/addons/plugin.video.baldest_man/resources/lib/
```
Restart Kodi and play a torrent result. Verify:
- Dialog appears with "Uploading magnet..."
- Transitions to "Downloading — ~Xs remaining" with climbing percentage
- Jumps to "Ready!" at 100% then closes
- Cancel button stops the process
