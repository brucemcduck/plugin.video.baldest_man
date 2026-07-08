# Magnet Resolution Progress Dialog

**Date:** 2026-07-07
**Status:** Design approved

## Problem

When playing a torrent result, `ad_resolve()` is called synchronously. Kodi shows only a generic busy spinner. The user has no visibility into what's happening or how long it will take, and no way to cancel.

## Solution

Add a foreground `DialogProgress` during magnet resolution showing status text, a pseudo-progress bar, and an ETA. The dialog's cancel button already works (wired up in prior work).

## Architecture

```
main.py (play handler)
  └─ DialogProgress created
     └─ cancel_check=pdlg.iscanceled (existing)
     └─ progress_callback=closure → updates dialog
        └─ resolve(url, key, timeout, cancel_check, progress_callback)
           └─ alldebrid.py
```

The callback pattern keeps `alldebrid.py` Kodi-free. UI logic stays in `main.py`.

## Callback signature

`progress_callback(state: str, pct: int, eta_seconds: int)`

| State | Pct | ETA |
|-------|-----|-----|
| `"uploading"` | 0 | timeout |
| `"downloading"` | `elapsed/timeout * 100` (max 98) | `timeout - elapsed` |
| `"ready"` | 100 | 0 |

## When the callback fires

1. **Upload phase** — immediately after entering the polling loop, before any status checks. Shows `"Uploading magnet..."` with 0%.
2. **Download phase** — each polling iteration. Shows pseudo-progress based on elapsed time vs configured timeout. Capped at 98% since we don't know real download progress.
3. **Ready phase** — when magnet status flips to `Ready`/`4`. Shows 100%, then dialog closes.

## Dialog display

- **Title:** `"Resolving magnet..."`
- **Line 1:** State message: `"Uploading magnet..."` / `"Downloading — ~45s remaining"` / `"Ready!"`
- **Line 2:** `"ETA: ~1m 30s"` (only shown during downloading)
- **Progress bar:** 0–100%, driven by `pct` from callback
- **Cancel button:** Already wired via `cancel_check=pdlg.iscanceled` (raises `AllDebridError("Cancelled by user")`)

## Files changed

| File | Change |
|------|--------|
| `resources/lib/alldebrid.py` | Add `progress_callback` parameter to `resolve()`. Call it at upload, each poll, and on ready. |
| `main.py` | In `play` handler (torrent branch): create `DialogProgress`, pass `progress_callback` closure to `resolve()`, close dialog on completion/error. |

## Edge cases

- **Error during upload:** Dialog closes, error notification shown. No progress shown since it failed immediately.
- **Magnet already ready on first poll:** Upload→0%, then immediately Ready→100%. Dialog shows briefly then closes.
- **Cancel:** Dialog closes, `"Cancelled by user"` notification shown.
- **Timeout:** Dialog closes, timeout notification shown.
- **Cancel check timing:** `cancel_check` is called before each sleep, so cancel response is within `poll_interval` (1s).
- **Poll interval:** Reduced from 2s to 1s for smoother progress updates and faster cancel response.
