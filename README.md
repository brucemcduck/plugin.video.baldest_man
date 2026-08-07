# bald_man — Kodi Video Addon

Search shows and movies via TMDB, scrape torrent sources, resolve through AllDebrid, and play or download offline.

This is a **personal project** built mainly for my own use across my devices. It’s public so I can install and update it easily on TVs and phones, but it isn’t a supported product — no guarantees, no issue triage, use at your own risk.

Works on any device that runs **Kodi** (Windows, Mac, Linux, Android TV, Fire TV, phones, tablets).

## Requirements

- [Kodi](https://kodi.tv/download) 20+ (Python 3)
- [AllDebrid](https://alldebrid.com/) account (PIN auth built in)
- Free [TMDB API key](https://www.themoviedb.org/settings/api) (v3 auth)

### Kodi dependencies (auto-installed from official repos)

- `script.module.requests`
- `script.module.beautifulsoup4`

Enable **Settings → Add-ons → Unknown sources** before installing third-party addons.

## Install (recommended — enables auto-updates)

Kodi will auto-update bald_man when you bump the version and push a new repo build — **if** you install through the repository (not by sideloading the plugin zip alone).

### 1. Enable GitHub Pages (once)

1. [Settings → Pages](https://github.com/brucemcduck/plugin.video.baldest_man/settings/pages)
2. **Source:** Deploy from a branch · **Branch:** `master` · **Folder:** `/docs`
3. Confirm: [brucemcduck.github.io/plugin.video.baldest_man/repo/](https://brucemcduck.github.io/plugin.video.baldest_man/repo/)

### 2. Install the repository, then the addon

1. **Settings → File manager → Add source** → paste:
   ```
   https://brucemcduck.github.io/plugin.video.baldest_man/repo/
   ```
2. **Add-ons → Install from zip file** → that source → **`repository.baldest_man-1.0.1.zip`** only  
   (Do **not** install `plugin.video.baldest_man-*.zip` here if you want clean repo updates.)
3. **Add-ons → Install from repository** → **bald_man Repository** → **Video add-ons** → **bald_man** → Install

### 3. Turn on Kodi auto-updates (once per device)

**Settings → System → Add-ons:**

- **Updates:** Install updates automatically
- **Update official add-ons from:** Any repositories (needed for third-party repos)

Kodi checks repos about once a day (and often on startup). After you publish a higher `version` in `addon.xml` + rebuild/push the repo, devices pick it up on the next check — no re-downloading zips by hand.

Force a check anytime: **Add-ons → (left menu) → Check for updates**.

### Fallback — direct plugin zip (no auto-update)

If you only want a one-shot install without the repo:

```
https://raw.githubusercontent.com/brucemcduck/plugin.video.baldest_man/master/docs/repo/zips/plugin.video.baldest_man/plugin.video.baldest_man-0.1.2.zip
```

Or install `repository.baldest_man-1.0.1.zip` the same way from:
```
https://raw.githubusercontent.com/brucemcduck/plugin.video.baldest_man/master/docs/repo/repository.baldest_man-1.0.1.zip
```

## Other install methods

### Git clone (developers)

```bash
git clone https://github.com/brucemcduck/plugin.video.baldest_man.git
```

Copy or symlink into your Kodi addons folder:

| Platform | Addons folder |
|----------|---------------|
| Windows | `%APPDATA%\Kodi\addons\` |
| Linux | `~/.kodi/addons/` |
| macOS | `~/Library/Application Support/Kodi/addons/` |

Restart Kodi after copying.

## Releasing a new version (triggers auto-update)

1. Bump `version` in `addon.xml` (must be higher than the last release — e.g. `0.1.1` → `0.1.2`)
2. Rebuild and push:

```bash
python tools/build_repo.py
git add docs/repo/ addon.xml
git commit -m "release: vX.Y.Z"
git push
```

Devices with **repository.baldest_man** installed + auto-updates on will install the new zip from Pages on the next update check. No version bump = no update (Kodi ignores identical versions).

## First-time setup

1. Open **Add-ons → Video add-ons → bald_man → Configure**
2. **AllDebrid** → **Authorize AllDebrid (PIN)** and complete the browser flow
3. **TMDB** — a default API key is bundled; override in settings only if you want your own from [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api)
4. (Optional) **Trakt** → add Client ID and authorize for watchlist/sync

## CLI (download without Kodi UI)

For headless downloads on a PC or server:

```bash
pip install -r requirements.txt
python cli.py [--dry-run] [--segments N] [--max-size-gb N]
```

The CLI reads credentials from the same Kodi `settings.xml` as the addon:

- **Windows:** `%APPDATA%\Kodi\userdata\addon_data\plugin.video.baldest_man\settings.xml`
- **Linux / macOS:** `~/.kodi/userdata/addon_data/plugin.video.baldest_man/settings.xml`

Configure the addon in Kodi once; the CLI picks up those settings.

## Features

- TMDB search (shows, movies, seasons, episodes)
- Multi-scraper parallel search (Pirate Bay, EZTV, Nyaa, Torrentio, etc.)
- AllDebrid magnet resolution with stall detection
- Offline downloads with multi-segment parallel fetch
- Trakt watchlist, collection, and scrobble
- Quick download and search history

## Development

```bash
pip install -r requirements.txt
python -m unittest test_cli test_scraper_runner test_alldebrid test_download_manager
python check_scrapers.py "Breaking Bad S01E01"
```

## Security notes

- **Never commit API keys.** AllDebrid tokens and TMDB keys live in Kodi userdata only.
- If you previously used a bundled TMDB key from an old build, rotate it at TMDB and use your own.
- This addon resolves third-party torrent links; use only content you have rights to access.

## License

MIT
