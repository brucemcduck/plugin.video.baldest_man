# bald_man — Kodi Video Addon

Search shows and movies via TMDB, scrape torrent sources, resolve through AllDebrid, and play or download offline.

Works on any device that runs **Kodi** (Windows, Mac, Linux, Android TV, Fire TV, phones, tablets).

## Requirements

- [Kodi](https://kodi.tv/download) 20+ (Python 3)
- [AllDebrid](https://alldebrid.com/) account (PIN auth built in)
- Free [TMDB API key](https://www.themoviedb.org/settings/api) (v3 auth)

### Kodi dependencies (auto-installed from official repos)

- `script.module.requests`
- `script.module.beautifulsoup4`

Enable **Settings → Add-ons → Unknown sources** before installing third-party addons.

## Install on any device

### Option A — Download ZIP (easiest)

1. Open [github.com/brucemcduck/plugin.video.baldest_man](https://github.com/brucemcduck/plugin.video.baldest_man)
2. Click **Code → Download ZIP**
3. In Kodi: **Settings → Add-ons → Install from zip file** → pick the ZIP
4. **Important:** rename the extracted folder to `plugin.video.baldest_man` if GitHub added a suffix like `-master`

### Option B — Git clone (PC / Mac / Linux)

```bash
git clone https://github.com/brucemcduck/plugin.video.baldest_man.git
```

Copy or symlink into your Kodi addons folder:

| Platform | Addons folder |
|----------|---------------|
| Windows | `%APPDATA%\Kodi\addons\` |
| Linux | `~/.kodi/addons/` |
| macOS | `~/Library/Application Support/Kodi/addons/` |
| Android / Fire TV | Use **Install from zip** or a file manager + Kodi file picker |

Restart Kodi after copying.

### Option C — Android TV / Fire TV / phone / tablet

1. Download the ZIP on your device (or transfer via USB/cloud)
2. Kodi → **Add-ons → Install from zip file** → browse to the ZIP
3. Configure settings (see below)

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
