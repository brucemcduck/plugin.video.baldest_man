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

## Install

### Option A — Direct zip (works now, no Pages setup)

Download this zip on your phone / TV browser / Fire TV Downloader, then in Kodi:
**Add-ons → Install from zip file** → pick the downloaded file.

**Addon (recommended first install):**
```
https://raw.githubusercontent.com/brucemcduck/plugin.video.baldest_man/master/docs/repo/zips/plugin.video.baldest_man/plugin.video.baldest_man-0.1.0.zip
```

**Repository (for later updates via Install from repository):**
```
https://raw.githubusercontent.com/brucemcduck/plugin.video.baldest_man/master/docs/repo/repository.baldest_man-1.0.1.zip
```

### Option B — Paste-a-link source (needs GitHub Pages once)

Pages is **off** until you enable it. The `github.io` link will 404 until this is done.

1. Open [github.com/brucemcduck/plugin.video.baldest_man/settings/pages](https://github.com/brucemcduck/plugin.video.baldest_man/settings/pages)
2. **Build and deployment → Source:** Deploy from a branch
3. **Branch:** `master` · **Folder:** `/docs` (not `/ (root)`)
4. **Save** → wait 1–2 minutes
5. Confirm in a browser: [brucemcduck.github.io/plugin.video.baldest_man/repo/](https://brucemcduck.github.io/plugin.video.baldest_man/repo/)

Then in Kodi:

1. **Settings → File manager → Add source** → paste **exactly** (include trailing `/repo/`):
   ```
   https://brucemcduck.github.io/plugin.video.baldest_man/repo/
   ```
   Do **not** use the GitHub.com page, `raw.githubusercontent.com`, or the site root — those won't list the zips.
2. **Add-ons → Install from zip file** → pick the `bald_man` source → you should see:
   - `repository.baldest_man-1.0.1.zip`
   - `plugin.video.baldest_man-0.1.0.zip`
3. Install the **repository** zip first, then **Add-ons → Install from repository** → **bald_man Repository** → **Video add-ons** → **bald_man**

If the source opens but the list is empty, remove the source and re-add with the exact URL above (trailing slash matters on some devices).

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

## Releasing a new version

Bump `version` in `addon.xml`, then rebuild the hosted repo files:

```bash
python tools/build_repo.py
git add docs/repo/ addon.xml
git commit -m "release: vX.Y.Z"
git push
```

GitHub Pages (branch `master`, folder `/docs`) serves the files after you push. Users with the repository installed get updates via **Install from repository**.

## First-time setup

1. Open **Add-ons → Video add-ons → bald_man → Configure**
2. **AllDebrid** → **Authorize AllDebrid (PIN)** and complete the browser flow
3. **TMDB** → paste your API key from [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api)
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
