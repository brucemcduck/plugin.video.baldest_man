"""plugin.video.baldest_man — multi-site video scraper with AllDebrid + TMDB metadata."""
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
# pyrefly: ignore [missing-import]
import xbmc
# pyrefly: ignore [missing-import]
import xbmcaddon
# pyrefly: ignore [missing-import]
import xbmcgui
# pyrefly: ignore [missing-import]
import xbmcplugin

from resources.lib import scraper_runner, tmdb, download_manager
from resources.lib.alldebrid import (resolve as ad_resolve, AllDebridError,
                                      pin_start as ad_pin_start,
                                      pin_poll as ad_pin_poll,
                                      get_user as ad_get_user,
                                      revoke as ad_revoke_auth)
from resources.lib.download_manager import DownloadError
from resources.lib.trakt import (get_device_code, poll_for_token, scrobble_start,
                                  get_watchlist, get_collection,
                                  get_watched_shows, get_show_progress,
                                  TraktError)
from scrapers import torrentio

ADDON = xbmcaddon.Addon()
base_url = sys.argv[0]
addon_handle = int(sys.argv[1])
args = urllib.parse.parse_qs(sys.argv[2][1:])

xbmcplugin.setContent(addon_handle, 'movies')


def build_url(query):
    """Build a plugin URL from a dict of params."""
    return base_url + '?' + urllib.parse.urlencode(query)


def notify(msg):
    """Show a brief Kodi notification."""
    xbmcgui.Dialog().notification('bald_man', msg, xbmcgui.NOTIFICATION_INFO, 3000)


def clean_error(msg):
    """Map raw exception text to short, human-readable messages for notifications."""
    s = str(msg)
    lower = s.lower()
    if 'max retries exceeded' in lower or 'ssl' in lower or 'handshake' in lower:
        return 'Network error: can\'t reach service (check your connection)'
    if 'connection refused' in lower or 'connection timed out' in lower or 'timeout' in lower:
        return 'Network error: connection failed (check your connection)'
    if 'invalid apikey' in lower or 'unauthorized' in lower:
        return 'AllDebrid: invalid or expired key — re-authorize in settings'
    if 'name or service not known' in lower or 'getaddrinfo' in lower:
        return 'Network error: can\'t resolve host (check your connection)'
    return s.replace('\n', ' ')[:80]


_SEARCH_CACHE = os.path.join(tempfile.gettempdir(), "baldman_tmdb.json")
_SCRAPE_CACHE = os.path.join(tempfile.gettempdir(), "baldman_scrape.json")

_SEARCH_HISTORY = os.path.join(tempfile.gettempdir(), "baldman_search_history.json")
_MAX_HISTORY = 20


def _load_search_history():
    """Load search history list. Returns [] on missing/corrupt file."""
    try:
        with open(_SEARCH_HISTORY) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _save_search_history(history):
    """Write history list to JSON. Silently ignores errors."""
    try:
        with open(_SEARCH_HISTORY, 'w') as f:
            json.dump(history, f)
    except OSError:
        pass


def _add_search_history(record):
    """Add or update a history entry. Dedupes by (show_id, kind), moves to front,
    trims to _MAX_HISTORY. record is a dict with show_id, kind, title,
    year, poster_url, content_type; timestamp is added here."""
    history = _load_search_history()
    history = [h for h in history if h.get('show_id')]
    show_id = record.get('show_id')
    history = [h for h in history
               if (h.get('show_id'), h.get('kind')) != (show_id, record.get('kind'))]
    record['timestamp'] = int(time.time())
    history.insert(0, record)
    if len(history) > _MAX_HISTORY:
        history = history[:_MAX_HISTORY]
    _save_search_history(history)


def _save_search_cache(content_type, shows, movies, query):
    """Save TMDB search results so back-navigation avoids re-dialog."""
    try:
        with open(_SEARCH_CACHE, 'w') as f:
            json.dump({"content_type": content_type, "shows": shows,
                        "movies": movies, "query": query}, f)
    except (OSError, TypeError):
        pass


def _read_search_cache():
    """Return cached TMDB results dict or None."""
    try:
        with open(_SEARCH_CACHE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def set_info(li, item, is_folder):
    """Set video info and artwork on a ListItem from a TMDB dict."""
    info = {'title': item.get('title', item.get('name', ''))}
    if item.get('overview'):
        info['plot'] = item.get('overview')
    li.setInfo('video', info)
    poster = item.get('poster_url')
    if poster:
        li.setArt({'poster': poster})
    thumb = item.get('still_url')
    if thumb:
        li.setArt({'thumb': thumb})


def label_result(item):
    """Format scrape result label: Episode Name  or  Movie Title."""
    if item.get('episode'):
        return item.get('title') or f"S{int(item.get('season', '01')):02d}E{int(item['episode']):02d}"
    elif item.get('is_movie'):
        return item.get('show_title', '')
    else:
        return item.get('title', item.get('show_title', ''))


def _parse_size_bytes(size_str):
    """Parse human-readable size string to bytes for Kodi. Returns int or 0."""
    m = re.match(r'([\d.]+)\s*(GB|MB|GiB|MiB|KB|B)', str(size_str), re.IGNORECASE)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit in ('GB', 'GIB'):
        return int(val * 1073741824)
    if unit in ('MB', 'MIB'):
        return int(val * 1048576)
    if unit == 'KB':
        return int(val * 1024)
    return int(val)


def _pick_offline_source(results):
    """Filter scrape results to offline_quality under size cap, smallest first.
    Returns the best result dict or None."""
    want_q = (ADDON.getSetting('offline_quality') or '720p').lower()
    max_gb = int(ADDON.getSetting('max_download_size_gb') or '2')
    max_bytes = max_gb * 1073741824

    def _ok(r):
        q = (r.get('quality') or '').lower()
        sz = _parse_size_bytes(r.get('size', ''))
        if q and q != want_q:
            return False
        if sz and sz > max_bytes:
            return False
        return True

    candidates = [r for r in results if _ok(r)]
    if not candidates:
        candidates = [r for r in results
                      if _parse_size_bytes(r.get('size', '')) <= max_bytes]
    if not candidates:
        return None
    candidates.sort(key=lambda r: _parse_size_bytes(r.get('size', '')) or 0)
    return candidates[0]


def add_scrape_result(item, poster_url=None, play_label=None, meta=None):
    """Add a playable scrape result with structured metadata and artwork.
    play_label overrides the list label for the player title (e.g. TMDB name).
    meta is a dict of TMDB context saved for Continue Watching."""
    label = label_result(item)
    li = xbmcgui.ListItem(label)
    li.setProperty('IsPlayable', 'true')

    info = {
        'title': label,
        'mediatype': 'episode' if item.get('episode') else 'movie',
    }

    # Plot: stats shown in Media Info view
    plot_parts = []
    if item.get('quality'):
        plot_parts.append(item['quality'])
    if item.get('seeders'):
        plot_parts.append(f"⬆{item['seeders']} seeders")
    if item.get('size'):
        plot_parts.append(item['size'])
    plot_parts.append(f"source: {item.get('site', '?')}")
    info['plot'] = ' · '.join(plot_parts)

    # Size in bytes (Kodi auto-formats in UI)
    size_str = item.get('size', '')
    if size_str:
        info['size'] = _parse_size_bytes(size_str)

    li.setInfo('video', info)

    # Poster from TMDB parent show/movie
    if poster_url:
        li.setArt({'poster': poster_url, 'thumb': poster_url})

    params = {'mode': 'play', 'url': item['url'],
              'type': item.get('type', 'direct'),
              'label': play_label if play_label else label}
    if meta:
        params.update(meta)
    play_url = build_url(params)

    # Context menu: Download for Offline
    dl_params = dict(params)
    dl_params['mode'] = 'download'
    dl_params['size'] = item.get('size', '')
    if poster_url:
        dl_params['poster_url'] = poster_url
    dl_params['plot'] = info.get('plot', '')
    dl_url = build_url(dl_params)
    li.addContextMenuItems([('Download for Offline', 'RunPlugin({})'.format(dl_url))])

    xbmcplugin.addDirectoryItem(addon_handle, play_url, li, isFolder=False)


def api_key():
    return ADDON.getSetting('alldebridtoken')


def tmdb_api_key():
    return ADDON.getSetting('tmdb_api_key')


def tmdb_lang():
    return ADDON.getSetting('tmdb_language') or 'en'


def _seeder_ok(r):
    """Check seeder quality: at least 1 seeder per 10GB of file size."""
    s = r.get('seeders')
    if s is None:
        return True
    size_bytes = _parse_size_bytes(r.get('size', ''))
    if not size_bytes:
        return True
    return s * 10737418240 >= size_bytes


_QUALITY_RANK = {'4k': 4, '2160p': 4, '1080p': 3, '720p': 2, '480p': 1}


def _quality_sort_key(r):
    """Sort key: quality descending, then size ascending within each tier."""
    q = (r.get('quality') or '').lower()
    rank = _QUALITY_RANK.get(q, 0)
    size = _parse_size_bytes(r.get('size', '')) or 0
    return (-rank, size)


def _scrape_with_early_termination(query, content_type, show_id=None,
                                    is_movie=False, season_number=None,
                                    episode_number=None, max_sources=None,
                                    pdlg=None):
    """Scrape sources with optional early termination.
    Returns (results, poster_url, imdb_id, meta).
    If max_sources is set, stops collecting once that many viable results
    (passing _seeder_ok) are found. If None, waits for all scrapers.
    If pdlg is provided, uses that DialogProgress (caller manages lifecycle).
    Otherwise creates and closes its own."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    owns_dialog = pdlg is None
    if owns_dialog:
        pdlg = xbmcgui.DialogProgress()
        pdlg.create("Searching for sources...", "Starting...")

    all_results = []
    poster_url = None
    imdb_id = None
    pending = 0
    done = 0

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {}

            futures[pool.submit(scraper_runner.search_all, query, content_type)] = "scrapers"
            pending += 1

            if show_id:
                futures[pool.submit(tmdb.get_imdb_id, int(show_id), tmdb_api_key(),
                                    is_movie=is_movie)] = "imdb"
                pending += 1

            if show_id:
                futures[pool.submit(tmdb.get_poster, int(show_id), tmdb_api_key(),
                                    is_movie=is_movie)] = "poster"
                pending += 1

            torrentio_future = None
            for future in as_completed(futures):
                if pdlg.iscanceled():
                    break
                source = futures[future]
                done += 1
                try:
                    result = future.result()
                except Exception:
                    pdlg.update(int(done / pending * 100), "{} failed".format(source))
                    continue

                if source == "scrapers":
                    all_results.extend(result)
                    viable = [r for r in all_results if _seeder_ok(r)]
                    pdlg.update(int(done / pending * 100),
                                "{} sources".format(len(all_results)))
                    if max_sources and len(viable) >= max_sources:
                        break
                elif source == "imdb" and result:
                    imdb_id = result
                    if is_movie:
                        torrentio_future = pool.submit(torrentio.search_imdb, imdb_id,
                                                       is_movie=True)
                    elif season_number and episode_number:
                        torrentio_future = pool.submit(torrentio.search_imdb, imdb_id,
                                                       int(season_number), int(episode_number))
                    if torrentio_future:
                        pending += 1
                    pdlg.update(int(done / pending * 100),
                                "{} sources".format(len(all_results)))
                elif source == "poster" and result:
                    poster_url = result
                    pdlg.update(int(done / pending * 100),
                                "{} sources".format(len(all_results)))

            if torrentio_future and not pdlg.iscanceled():
                viable = [r for r in all_results if _seeder_ok(r)]
                if not max_sources or len(viable) < max_sources:
                    try:
                        tr = torrentio_future.result()
                        all_results.extend(tr)
                    except Exception:
                        pass
                done += 1
                pdlg.update(100, "{} sources".format(len(all_results)))

    finally:
        if owns_dialog:
            pdlg.close()

    all_results = [r for r in all_results if _seeder_ok(r)]

    meta = {'content_type': content_type}
    if show_id:
        meta['show_id'] = show_id
    if imdb_id:
        meta['imdb_id'] = imdb_id
    if season_number:
        meta['season'] = season_number
    if episode_number:
        meta['episode'] = episode_number

    return all_results, poster_url, imdb_id, meta


def _quick_download_one(show_title, show_id, year, season_number, episode_number,
                        episode_title, content_type, pdlg,
                        episode_index=None, episode_total=None):
    """Scrape, auto-pick best source, download with fallback.
    Returns True on success, False on failure.
    pdlg is an already-created DialogProgress (caller manages create/close).
    episode_index/episode_total are for season-batch progress display."""
    key = api_key()
    if not key:
        notify("AllDebrid not authorized — use the PIN flow in settings")
        return False

    if season_number and episode_number:
        query = f"{show_title} S{int(season_number):02d}E{int(episode_number):02d}"
    else:
        query = f"{show_title} {year}".strip() if year else show_title

    is_movie = content_type == 'movies'
    max_sources = int(ADDON.getSetting('quick_download_max_sources') or '10')

    pdlg.update(0, "Scraping...")

    results, poster_url, imdb_id, meta = _scrape_with_early_termination(
        query, content_type, show_id=show_id, is_movie=is_movie,
        season_number=season_number, episode_number=episode_number,
        max_sources=max_sources, pdlg=pdlg)

    if not results:
        label = episode_title or show_title
        notify("No sources found for {}".format(label))
        return False

    results.sort(key=_quality_sort_key)

    label = episode_title or show_title
    timeout = int(ADDON.getSetting('magnet_timeout') or 120)
    fname = download_manager.safe_filename(show_title, season_number, episode_number)
    dest = os.path.join(download_manager.get_download_dir(), fname)

    for i, r in enumerate(results):
        if pdlg.iscanceled():
            return False

        prefix = ""
        if episode_index and episode_total:
            prefix = "Episode {}/{}: ".format(episode_index, episode_total)

        magnet = r.get('url', '')
        if not magnet:
            continue

        pdlg.update(10, "{}Resolving source {}/{}...".format(prefix, i + 1, len(results)))

        try:
            direct_url = ad_resolve(magnet, key, timeout=timeout,
                                    cancel_check=pdlg.iscanceled,
                                    season=season_number, episode=episode_number)
            if pdlg.iscanceled():
                return False

            est = _parse_size_bytes(r.get('size', ''))
            if est and not download_manager.has_space(dest, est):
                notify("Not enough disk space for {}".format(label))
                return False

            pdlg.update(15, "{}Downloading {}...".format(prefix, fname))

            def dl_cb(written, total, pct):
                label_txt = "{} ({} / {} MB)".format(
                    fname, written // 1048576, total // 1048576)
                pdlg.update(15 + pct * 85 // 100, label_txt)

            ok = download_manager.download_video(
                direct_url, dest,
                cancel_check=pdlg.iscanceled,
                progress_callback=dl_cb,
                source_id=magnet)

            if not ok:
                if pdlg.iscanceled():
                    return False
                continue

        except (AllDebridError, DownloadError):
            continue

        poster_local = None
        if poster_url:
            poster_local = download_manager.cache_artwork(
                poster_url, os.path.join(download_manager.art_dir(),
                                         fname + '.poster.jpg'))

        entry = {
            'id': fname,
            'title': label,
            'show_title': show_title,
            'season': season_number,
            'episode': episode_number,
            'file_path': dest,
            'size_bytes': os.path.getsize(dest),
            'date_added': int(time.time()),
            'mediatype': 'episode' if episode_number else 'movie',
            'plot': '',
            'poster_path': poster_local,
        }
        download_manager.add_to_manifest(entry)
        notify("Downloaded: {}".format(label))
        return True

    notify("All {} sources failed for {}".format(len(results), label))
    return False


mode = args.get('mode', None)

# --- Root: menu ---
if mode is None:
    # Clear stale search cache — fresh entry from root always shows dialog
    try:
        os.remove(_SEARCH_CACHE)
    except OSError:
        pass

    # One-time migration: copy old alldebrid_api_key to alldebridtoken
    old_key = ADDON.getSetting('alldebrid_api_key')
    new_key = ADDON.getSetting('alldebridtoken')
    if old_key and not new_key:
        ADDON.setSetting('alldebridtoken', old_key)

    for label, content_type in [
        ('Search Shows', 'shows'),
        ('Search Movies', 'movies'),
        ('Search All', 'all'),
    ]:
        url = build_url({'mode': 'search', 'content_type': content_type})
        xbmcplugin.addDirectoryItem(addon_handle, url,
                                    xbmcgui.ListItem(label), isFolder=True)

    url = build_url({'mode': 'search_history'})
    xbmcplugin.addDirectoryItem(addon_handle, url,
                                xbmcgui.ListItem("Search History"), isFolder=True)

    # Continue Watching — re-scrape last watched TMDB content
    last = ADDON.getSetting('last_played')
    if last:
        try:
            last_data = json.loads(last)
            if last_data.get('show_title'):
                cw_label = "Continue Watching"
                if last_data.get('episode_title'):
                    cw_label = "Continue: " + last_data['episode_title']
                elif last_data.get('show_title'):
                    cw_label = "Continue: " + last_data['show_title']
                url = build_url({'mode': 'continue_watching'})
                xbmcplugin.addDirectoryItem(addon_handle, url,
                                            xbmcgui.ListItem(cw_label), isFolder=True)
        except (json.JSONDecodeError, KeyError):
            pass

    # Trakt menus
    trakt_token = ADDON.getSetting('trakt_access_token')
    if trakt_token:
        for label, list_type in [
            ('Trakt Watchlist', 'watchlist'),
            ('Trakt Collection', 'collection'),
            ('Progress / Up Next', 'progress'),
        ]:
            url = build_url({'mode': 'trakt_browse', 'list_type': list_type})
            xbmcplugin.addDirectoryItem(addon_handle, url,
                                        xbmcgui.ListItem(label), isFolder=True)

    # My Downloads — offline library
    dl_count = len(download_manager.load_manifest())
    dl_label = "My Downloads ({})".format(dl_count) if dl_count else "My Downloads"
    url = build_url({'mode': 'my_downloads'})
    xbmcplugin.addDirectoryItem(addon_handle, url,
                                xbmcgui.ListItem(dl_label), isFolder=True)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Continue Watching: re-scrape last watched ---
elif mode[0] == 'continue_watching':
    last = ADDON.getSetting('last_played')
    if last:
        try:
            item = json.loads(last)
            meta = {'mode': 'scrape',
                    'show_title': item.get('show_title', ''),
                    'content_type': item.get('content_type', 'all')}
            if item.get('show_id'):
                meta['show_id'] = item['show_id']
            if item.get('season'):
                meta['season_number'] = item['season']
            if item.get('episode'):
                meta['episode_number'] = item['episode']
            if item.get('episode_title'):
                meta['episode_title'] = item['episode_title']
            url = build_url(meta)
            xbmcplugin.addDirectoryItem(addon_handle, url,
                                        xbmcgui.ListItem("Re-scraping..."), isFolder=True)
        except (json.JSONDecodeError, KeyError):
            pass
    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Search: TMDB lookup ---
elif mode[0] == 'search':
    content_type = args.get('content_type', ['all'])[0]
    key = tmdb_api_key()
    lang = tmdb_lang()
    shows = []
    movies = []
    query = ''

    cached = _read_search_cache()
    if cached and cached.get('content_type') == content_type:
        shows = cached.get('shows', [])
        movies = cached.get('movies', [])
        query = cached.get('query', '')
    else:
        dialog = xbmcgui.Dialog()
        query = dialog.input(f'Search {content_type.capitalize()}',
                             type=xbmcgui.INPUT_ALPHANUM)
        if not query:
            xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
        else:
            shows = tmdb.search_shows(query, key, lang) if content_type in ('shows', 'all') else []
            movies = tmdb.search_movies(query, key, lang) if content_type in ('movies', 'all') else []
            _save_search_cache(content_type, shows, movies, query)

    if query:

        if content_type in ('shows', 'all'):
            for s in shows:
                url = build_url({'mode': 'seasons', 'show_id': str(s['id']),
                                 'show_title': s['title'], 'year': s.get('year', ''),
                                 'poster_url': s.get('poster_url', ''), 'src': 'search'})
                label = f"{s['title']} ({s.get('year', '')})"
                li = xbmcgui.ListItem(label)
                set_info(li, s, is_folder=True)
                xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        if content_type in ('movies', 'all'):
            for m in movies:
                url = build_url({'mode': 'scrape', 'show_title': m['title'],
                                 'year': m.get('year', ''),
                                 'show_id': str(m['id']),
                                 'poster_url': m.get('poster_url', ''),
                                 'content_type': 'movies', 'src': 'search'})
                label = f"{m['title']} ({m.get('year', '')})"
                li = xbmcgui.ListItem(label)
                set_info(li, m, is_folder=True)
                qdl_url = build_url({'mode': 'quick_download', 'show_title': m['title'],
                                     'year': m.get('year', ''),
                                     'show_id': str(m['id']),
                                     'content_type': 'movies'})
                li.addContextMenuItems([('Quick Download', 'RunPlugin({})'.format(qdl_url))])
                xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        total = (len(shows) if content_type in ('shows', 'all') else 0) + \
                (len(movies) if content_type in ('movies', 'all') else 0)
        if total == 0:
            notify("No results from TMDB — check connection")
            li = xbmcgui.ListItem(f"Nothing found for '{query}'")
            xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Seasons: list seasons for a show ---
elif mode[0] == 'seasons':
    show_id = int(args.get('show_id', ['0'])[0])
    show_title = args.get('show_title', [''])[0]

    src = args.get('src', [''])[0]
    if src == 'search':
        _add_search_history({
            'kind': 'show',
            'show_id': show_id,
            'title': show_title,
            'year': args.get('year', [''])[0],
            'poster_url': args.get('poster_url', [''])[0],
            'content_type': 'shows',
        })

    seasons = tmdb.get_seasons(show_id, tmdb_api_key(), tmdb_lang())
    for s in seasons:
        url = build_url({'mode': 'episodes', 'show_id': str(show_id),
                         'show_title': show_title,
                         'season_number': str(s['season_number'])})
        name = s.get('name', f'Season {s["season_number"]}')
        label = f"{name} ({s['episode_count']} eps)"
        li = xbmcgui.ListItem(label)
        poster = s.get('poster_url')
        if poster:
            li.setArt({'poster': poster})
        qdl_url = build_url({'mode': 'quick_download', 'show_title': show_title,
                             'show_id': str(show_id),
                             'season_number': str(s['season_number']),
                             'content_type': 'shows'})
        li.addContextMenuItems([('Quick Download Season', 'RunPlugin({})'.format(qdl_url))])
        xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

    if not seasons:
        li = xbmcgui.ListItem("No seasons found")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Episodes: list episodes for a season ---
elif mode[0] == 'episodes':
    show_id = int(args.get('show_id', ['0'])[0])
    show_title = args.get('show_title', [''])[0]
    season_number = int(args.get('season_number', ['1'])[0])

    episodes = tmdb.get_episodes(show_id, season_number, tmdb_api_key(), tmdb_lang())
    for ep in episodes:
        url = build_url({'mode': 'scrape', 'show_title': show_title,
                         'show_id': str(show_id),
                         'season_number': str(season_number),
                         'episode_number': str(ep['episode_number']),
                         'episode_title': ep.get('name', ''),
                         'content_type': 'shows'})
        label = ep.get('name', '')
        li = xbmcgui.ListItem(label)
        if ep.get('still_url'):
            li.setArt({'thumb': ep['still_url']})
        info = {'title': ep.get('name', '')}
        if ep.get('overview'):
            info['plot'] = ep['overview']
        li.setInfo('video', info)
        qdl_url = build_url({'mode': 'quick_download', 'show_title': show_title,
                             'show_id': str(show_id),
                             'season_number': str(season_number),
                             'episode_number': str(ep['episode_number']),
                             'episode_title': ep.get('name', ''),
                             'content_type': 'shows'})
        li.addContextMenuItems([('Quick Download', 'RunPlugin({})'.format(qdl_url))])
        xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

    if not episodes:
        li = xbmcgui.ListItem("No episodes found")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Scrape: run scrapers, display results ---
elif mode[0] == 'scrape':
    show_title = args.get('show_title', [''])[0]
    show_id = args.get('show_id', [None])[0]
    year = args.get('year', [''])[0]
    season_number = args.get('season_number', [None])[0]
    episode_number = args.get('episode_number', [None])[0]
    episode_title = args.get('episode_title', [''])[0]
    content_type = args.get('content_type', ['all'])[0]

    src = args.get('src', [''])[0]
    if src == 'search' and content_type == 'movies':
        _add_search_history({
            'kind': 'movie',
            'show_id': int(show_id) if show_id else 0,
            'title': show_title,
            'year': year,
            'poster_url': args.get('poster_url', [''])[0],
            'content_type': 'movies',
        })

    cache_key = json.dumps({'show_title': show_title, 'show_id': show_id,
                            'season': season_number, 'episode': episode_number,
                            'content_type': content_type}, sort_keys=True)

    # Check scrape cache — skip re-scrape on back-navigation
    cache_hit = False
    try:
        with open(_SCRAPE_CACHE) as f:
            cached = json.load(f)
            if cached.get('key') == cache_key:
                for r in cached.get('results', []):
                    if season_number and 'episode' in r and 'season' not in r:
                        r['season'] = season_number
                    add_scrape_result(r, cached.get('poster_url'),
                                      meta=cached.get('meta'))
                xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
                cache_hit = True
    except (OSError, json.JSONDecodeError):
        pass

    if not cache_hit:

        if season_number and episode_number:
            query = f"{show_title} S{int(season_number):02d}E{int(episode_number):02d}"
        else:
            query = f"{show_title} {year}".strip() if year else show_title

        is_movie = content_type == 'movies'

        all_results, poster_url, imdb_id, meta = _scrape_with_early_termination(
            query, content_type, show_id=show_id, is_movie=is_movie,
            season_number=season_number, episode_number=episode_number,
            max_sources=None)

        meta['show_title'] = show_title
        if episode_title:
            meta['episode_title'] = episode_title

        # Sort by file size descending (largest first)
        all_results.sort(key=lambda r: _parse_size_bytes(r.get('size', '')), reverse=True)

        for r in all_results:
            if season_number and 'episode' in r and 'season' not in r:
                r['season'] = season_number
            pl = episode_title if episode_number and episode_title else show_title
            add_scrape_result(r, poster_url, play_label=pl, meta=meta)

        if not all_results:
            label = "No sources found"
            if episode_number:
                label += f" for S{int(season_number):02d}E{int(episode_number):02d}"
            li = xbmcgui.ListItem(label)
            xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

        # Save to scrape cache so back-navigation is instant
        try:
            with open(_SCRAPE_CACHE, 'w') as f:
                json.dump({'key': cache_key, 'results': all_results,
                           'poster_url': poster_url,
                           'meta': meta}, f)
        except (OSError, TypeError):
            pass

        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Quick Download: auto-pick best source and download ---
elif mode[0] == 'quick_download':
    show_title = args.get('show_title', [''])[0]
    show_id = args.get('show_id', [None])[0]
    year = args.get('year', [''])[0]
    season_number = args.get('season_number', [None])[0]
    episode_number = args.get('episode_number', [None])[0]
    episode_title = args.get('episode_title', [''])[0]
    content_type = args.get('content_type', ['all'])[0]

    pdlg = xbmcgui.DialogProgress()
    pdlg.create("Quick Download", "Starting...")
    try:
        if season_number and not episode_number:
            # Season batch — show multi-select episode picker
            episodes = tmdb.get_episodes(int(show_id), int(season_number),
                                         tmdb_api_key(), tmdb_lang())
            if not episodes:
                pdlg.close()
                notify("No episodes found for this season")
                xbmcplugin.endOfDirectory(addon_handle)
            else:
                ep_labels = [ep.get('name', 'Episode {}'.format(ep['episode_number']))
                             for ep in episodes]
                selected = xbmcgui.Dialog().multiselect("Select episodes (OK = all)", ep_labels)

                if selected is None:
                    # User cancelled
                    pass
                elif len(selected) == 0:
                    # OK with nothing selected = download all
                    selected = list(range(len(episodes)))
                # else: download only selected indices

                if selected is not None:
                    total = len(selected)
                    for idx, ep_idx in enumerate(selected):
                        if pdlg.iscanceled():
                            break
                        ep = episodes[ep_idx]
                        _quick_download_one(
                            show_title, show_id, year,
                            season_number, str(ep['episode_number']),
                            ep.get('name', ''),
                            content_type, pdlg,
                            episode_index=idx + 1, episode_total=total)
        else:
            # Single item (movie or episode)
            _quick_download_one(
                show_title, show_id, year,
                season_number, episode_number, episode_title,
                content_type, pdlg)
    finally:
        try:
            pdlg.close()
        except Exception:
            pass

    xbmcplugin.endOfDirectory(addon_handle)

elif mode[0] == 'search_history':
    history = _load_search_history()

    if not history:
        li = xbmcgui.ListItem("No search history yet")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)
    else:
        for idx, h in enumerate(history):
            if not h.get('show_id') or not h.get('kind'):
                continue
            kind = h.get('kind')
            title = h.get('title', '')
            year = h.get('year', '')
            poster_url = h.get('poster_url', '')
            label = f"{title} ({year})" if year else title

            if kind == 'show':
                url = build_url({'mode': 'seasons',
                                 'show_id': str(h['show_id']),
                                 'show_title': title, 'year': year,
                                 'poster_url': poster_url, 'src': 'search'})
            else:
                url = build_url({'mode': 'scrape', 'show_title': title,
                                 'year': year, 'show_id': str(h['show_id']),
                                 'poster_url': poster_url,
                                 'content_type': 'movies', 'src': 'search'})

            li = xbmcgui.ListItem(label)
            set_info(li, {'title': title, 'poster_url': poster_url},
                     is_folder=True)

            del_url = build_url({'mode': 'delete_history', 'index': str(idx)})
            clear_url = build_url({'mode': 'clear_history'})
            li.addContextMenuItems([
                ('Delete', 'RunPlugin({})'.format(del_url)),
                ('Clear All', 'RunPlugin({})'.format(clear_url)),
            ])

            xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Delete single history entry ---
elif mode[0] == 'delete_history':
    idx = int(args.get('index', ['-1'])[0])
    history = _load_search_history()
    if 0 <= idx < len(history):
        history.pop(idx)
        _save_search_history(history)
        notify("Search history entry deleted")
    xbmcplugin.endOfDirectory(addon_handle)
    xbmc.executebuiltin('Container.Refresh')

# --- Clear all search history ---
elif mode[0] == 'clear_history':
    _save_search_history([])
    notify("Search history cleared")
    xbmcplugin.endOfDirectory(addon_handle)
    xbmc.executebuiltin('Container.Refresh')

# --- Auth: AllDebrid PIN flow ---
elif mode[0] == 'ad_authorize':
    try:
        pin_data = ad_pin_start()
    except AllDebridError as e:
        notify(clean_error(e))
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
                    notify("Authorization failed: " + clean_error(e))
        except AllDebridError as e:
            pdlg.close()
            notify(clean_error(e))

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
            notify(clean_error(e))
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

# --- Auth: Trakt device OAuth ---
elif mode[0] == 'auth_trakt':
    client_id = ADDON.getSetting('trakt_client_id')
    if not client_id:
        notify('Trakt Client ID not set')
    else:
        try:
            data = get_device_code(client_id)
        except TraktError as e:
            notify("Trakt: " + clean_error(e))
        else:
            msg = ("1. Go to: [COLOR skyblue]{}[/COLOR]\n"
                   "2. Enter code: [COLOR yellow]{}[/COLOR]\n"
                   "3. Press OK after authorizing").format(
                       data.get("verification_url", "https://trakt.tv/activate"),
                       data.get("user_code", ""))
            xbmcgui.Dialog().ok("Trakt Authorization", msg)

            pdlg = xbmcgui.DialogProgress()
            pdlg.create("Trakt", "Waiting for authorization...")
            try:
                token = poll_for_token(client_id, data["device_code"],
                                       interval=data.get("interval", 5))
                ADDON.setSetting('trakt_access_token', token["access_token"])
                ADDON.setSetting('trakt_refresh_token', token["refresh_token"])
                pdlg.close()
                notify("Trakt authorized!")
            except TraktError as e:
                pdlg.close()
                notify("Trakt: " + clean_error(e))

    xbmcplugin.endOfDirectory(addon_handle)

# --- Trakt Browse: watchlist, collection, progress ---
elif mode[0] == 'trakt_browse':
    access_token = ADDON.getSetting('trakt_access_token')
    list_type = args.get('list_type', ['watchlist'])[0]

    if not access_token:
        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)
    else:
        items = []
        try:
            if list_type == 'watchlist':
                shows = get_watchlist(access_token, 'shows')
                movies = get_watchlist(access_token, 'movies')
                items = [('show', s['show'], s['show']['ids']) for s in shows]
                items += [('movie', m['movie'], m['movie']['ids']) for m in movies]
            elif list_type == 'collection':
                shows = get_collection(access_token, 'shows')
                movies = get_collection(access_token, 'movies')
                items = [('show', s['show'], s['show']['ids']) for s in shows]
                items += [('movie', m['movie'], m['movie']['ids']) for m in movies]
            elif list_type == 'progress':
                watched = get_watched_shows(access_token)
                for w in watched:
                    sid = w['show']['ids'].get('trakt')
                    if sid:
                        prog = get_show_progress(access_token, sid)
                        ne = prog.get('next_episode')
                        if ne:
                            items.append(('progress', w['show'],
                                          {'tmdb': w['show']['ids'].get('tmdb'),
                                           'season': ne['season'],
                                           'number': ne['number'],
                                           'title': ne.get('title', '')}))
        except Exception:
            pass

        if not items:
            li = xbmcgui.ListItem("Nothing found")
            xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)
        else:
            for item_type, data, ids in items:
                tmdb_id = ids.get('tmdb')
                if not tmdb_id:
                    continue
                title = data.get('title', '')
                year = str(data.get('year', ''))
                label = f"{title} ({year})" if year else title
                li = xbmcgui.ListItem(label)

                if item_type == 'progress':
                    url = build_url({'mode': 'scrape',
                                     'show_title': title,
                                     'show_id': str(tmdb_id),
                                     'season_number': str(ids.get('season', '')),
                                     'episode_number': str(ids.get('number', '')),
                                     'episode_title': ids.get('title', ''),
                                     'content_type': 'shows'})
                    xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)
                elif item_type == 'show':
                    url = build_url({'mode': 'seasons',
                                     'show_id': str(tmdb_id),
                                     'show_title': title})
                    xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)
                else:
                    url = build_url({'mode': 'scrape',
                                     'show_title': title,
                                     'show_id': str(tmdb_id),
                                     'content_type': 'movies'})
                    xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- My Downloads: offline library (no network needed) ---
elif mode[0] == 'my_downloads':
    items = download_manager.load_manifest()
    if not items:
        li = xbmcgui.ListItem("No downloads yet — use context menu on a source")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)
    else:
        for it in items:
            label = it.get('title', it.get('show_title', 'Unknown'))
            if it.get('season') and it.get('episode'):
                label = "{} S{:02d}E{:02d}".format(
                    it.get('show_title', label),
                    int(it['season']), int(it['episode']))
            li = xbmcgui.ListItem(label)
            li.setProperty('IsPlayable', 'true')
            info = {'title': label, 'mediatype': it.get('mediatype', 'movie')}
            if it.get('plot'):
                info['plot'] = it['plot']
            sz = it.get('size_bytes', 0)
            if sz:
                info['size'] = sz
            li.setInfo('video', info)
            poster = it.get('poster_path')
            if poster and os.path.exists(poster):
                li.setArt({'poster': poster, 'thumb': poster})
            play_url = build_url({'mode': 'play_local', 'id': it.get('id', '')})
            del_url = build_url({'mode': 'delete_download', 'id': it.get('id', '')})
            li.addContextMenuItems([('Delete Download', 'RunPlugin({})'.format(del_url))])
            xbmcplugin.addDirectoryItem(addon_handle, play_url, li, isFolder=False)
    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Play Local: file:// playback, zero network ---
elif mode[0] == 'play_local':
    item_id = args.get('id', [''])[0]
    target = None
    for it in download_manager.load_manifest():
        if it.get('id') == item_id:
            target = it
            break
    if target and os.path.exists(target.get('file_path', '')):
        li = xbmcgui.ListItem(target.get('title', ''), path=target['file_path'])
        xbmcplugin.setResolvedUrl(addon_handle, True, li)
    else:
        notify("File not found — it may have been deleted")
        xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())

# --- Delete Download: remove file + manifest entry ---
elif mode[0] == 'delete_download':
    item_id = args.get('id', [''])[0]
    download_manager.remove_from_manifest(item_id)
    notify("Download deleted")
    try:
        xbmc.executebuiltin('Container.Refresh')
    except Exception:
        pass
    xbmcplugin.endOfDirectory(addon_handle)

# --- Download: resolve + save to disk for offline playback ---
elif mode[0] == 'download':
    url = args.get('url', [''])[0]
    ep_type = args.get('type', ['direct'])[0]
    label = args.get('label', [''])[0]

    if ep_type != 'torrent':
        notify('Only torrent sources can be downloaded for offline')
        xbmcplugin.endOfDirectory(addon_handle)
    else:
        key = api_key()
        if not key:
            notify('AllDebrid not authorized — use the PIN flow in settings')
            xbmcplugin.endOfDirectory(addon_handle)
        else:
            # Enforce max_download_size_gb cap (the setting is otherwise decorative)
            max_gb = int(ADDON.getSetting('max_download_size_gb') or '20')
            max_bytes = max_gb * 1073741824
            est = _parse_size_bytes(args.get('size', [''])[0])
            if est and est > max_bytes:
                notify("Source ({} GB) exceeds your max download size ({} GB)".format(
                    est // 1073741824, max_gb))
                xbmcplugin.endOfDirectory(addon_handle)
            else:
                pdlg = xbmcgui.DialogProgress()
                pdlg.create("Downloading for Offline", "Resolving magnet...")

                try:
                    timeout = int(ADDON.getSetting('magnet_timeout') or 120)

                    def prog_cb(state, pct, eta):
                        if state == "uploading":
                            pdlg.update(0, "Uploading magnet...")
                        elif state == "ready":
                            pdlg.update(5, "Resolved — starting download...")
                        else:
                            # Map resolve progress into 0–5% so the bar never retreats
                            pdlg.update(min(5, pct * 5 // 100),
                                        "Resolving... ~{}s".format(eta))

                    show_title = args.get('show_title', [''])[0]
                    season = args.get('season', [None])[0]
                    episode = args.get('episode', [None])[0]

                    direct_url = ad_resolve(url, key, timeout=timeout,
                                            cancel_check=pdlg.iscanceled,
                                            progress_callback=prog_cb,
                                            season=season, episode=episode)
                    if pdlg.iscanceled():
                        notify("Download cancelled")
                        xbmcplugin.endOfDirectory(addon_handle)
                        raise AllDebridError("Cancelled")

                    fname = download_manager.safe_filename(show_title or label, season, episode)
                    dest = os.path.join(download_manager.get_download_dir(), fname)

                    if est and not download_manager.has_space(dest, est):
                        notify("Not enough disk space for this download")
                        xbmcplugin.endOfDirectory(addon_handle)
                        raise AllDebridError("Insufficient space")

                    pdlg.update(6, "Downloading {}...".format(fname))

                    def dl_cb(written, total, pct):
                        label_txt = "{} ({} / {} MB)".format(
                            fname, written // 1048576, total // 1048576)
                        pdlg.update(6 + pct * 94 // 100, label_txt)

                    ok = download_manager.download_video(
                        direct_url, dest,
                        cancel_check=pdlg.iscanceled,
                        progress_callback=dl_cb,
                        source_id=url)

                    if not ok:
                        notify("Download cancelled")
                    else:
                        poster_url = args.get('poster_url', [None])[0]
                        poster_local = None
                        if poster_url:
                            poster_local = download_manager.cache_artwork(
                                poster_url, os.path.join(download_manager.art_dir(),
                                                         fname + '.poster.jpg'))

                        entry = {
                            'id': fname,
                            'title': label,
                            'show_title': show_title,
                            'season': season,
                            'episode': episode,
                            'file_path': dest,
                            'size_bytes': os.path.getsize(dest),
                            'date_added': int(time.time()),
                            'mediatype': 'episode' if episode else 'movie',
                            'plot': args.get('plot', [''])[0],
                            'poster_path': poster_local,
                        }
                        download_manager.add_to_manifest(entry)
                        notify("Downloaded: {}".format(label))

                except (AllDebridError, DownloadError) as e:
                    notify('Download failed: ' + clean_error(e))
                finally:
                    try:
                        pdlg.close()
                    except Exception:
                        pass

                xbmcplugin.endOfDirectory(addon_handle)

# --- Play: resolve if torrent, hand to Kodi ---
elif mode[0] == 'play':
    url = args.get('url', [''])[0]
    ep_type = args.get('type', ['direct'])[0]
    label = args.get('label', [''])[0]

    if ep_type == 'torrent':
        key = api_key()
        if not key:
            notify('AllDebrid not authorized — use the PIN flow in settings')
            xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        else:
            pdlg = None
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
                        pdlg.update(pct, "Downloading... ~{}s".format(eta))

                direct_url = ad_resolve(url, key, timeout=timeout,
                                        cancel_check=pdlg.iscanceled,
                                        progress_callback=progress_cb,
                                        season=args.get('season', [None])[0],
                                        episode=args.get('episode', [None])[0])
                pdlg.close()
                last = {'show_title': args.get('show_title', [''])[0],
                        'label': label}
                show_id = args.get('show_id', [None])[0]
                if show_id:
                    last['show_id'] = show_id
                ct = args.get('content_type', [''])[0]
                if ct:
                    last['content_type'] = ct
                s = args.get('season', [None])[0]
                if s:
                    last['season'] = s
                ep = args.get('episode', [None])[0]
                if ep:
                    last['episode'] = ep
                et = args.get('episode_title', [''])[0]
                if et:
                    last['episode_title'] = et
                ADDON.setSetting('last_played', json.dumps(last))
                li = xbmcgui.ListItem(label, path=direct_url)
                xbmcplugin.setResolvedUrl(addon_handle, True, li)

                # Scrobble start to Trakt
                access_token = ADDON.getSetting('trakt_access_token')
                if access_token:
                    imdb = args.get('imdb_id', [None])[0]
                    if imdb:
                        try:
                            s = args.get('season', [None])[0]
                            ep = args.get('episode', [None])[0]
                            if s and ep:
                                scrobble_start(access_token, imdb, int(s), int(ep))
                            else:
                                scrobble_start(access_token, imdb)
                        except Exception:
                            pass
            except AllDebridError as e:
                if pdlg is not None:
                    try:
                        pdlg.close()
                    except Exception:
                        pass
                notify(clean_error(e))
                xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
    else:
        li = xbmcgui.ListItem(label, path=url)
        xbmcplugin.setResolvedUrl(addon_handle, True, li)
