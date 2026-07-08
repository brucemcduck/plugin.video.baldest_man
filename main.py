"""plugin.video.baldest_man — multi-site video scraper with AllDebrid + TMDB metadata."""
import json
import os
import re
import sys
import tempfile
import urllib.parse
# pyrefly: ignore [missing-import]
import xbmcaddon
# pyrefly: ignore [missing-import]
import xbmcgui
# pyrefly: ignore [missing-import]
import xbmcplugin

from resources.lib import scraper_runner, tmdb
from resources.lib.alldebrid import resolve as ad_resolve, AllDebridError
from resources.lib.trakt import get_device_code, poll_for_token, scrobble_start, TraktError
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


_SEARCH_CACHE = os.path.join(tempfile.gettempdir(), "baldman_tmdb.json")
_SCRAPE_CACHE = os.path.join(tempfile.gettempdir(), "baldman_scrape.json")


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
    xbmcplugin.addDirectoryItem(addon_handle, play_url, li, isFolder=False)


def api_key():
    return ADDON.getSetting('alldebrid_api_key')


def tmdb_api_key():
    return ADDON.getSetting('tmdb_api_key')


def tmdb_lang():
    return ADDON.getSetting('tmdb_language') or 'en'


mode = args.get('mode', None)

# --- Root: menu ---
if mode is None:
    # Clear stale search cache — fresh entry from root always shows dialog
    try:
        os.remove(_SEARCH_CACHE)
    except OSError:
        pass

    for label, content_type in [
        ('Search Shows', 'shows'),
        ('Search Movies', 'movies'),
        ('Search All', 'all'),
    ]:
        url = build_url({'mode': 'search', 'content_type': content_type})
        xbmcplugin.addDirectoryItem(addon_handle, url,
                                    xbmcgui.ListItem(label), isFolder=True)

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

    # Check cache — skip dialog on back-navigation
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
                                 'show_title': s['title']})
                label = f"{s['title']} ({s.get('year', '')})"
                li = xbmcgui.ListItem(label)
                set_info(li, s, is_folder=True)
                xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        if content_type in ('movies', 'all'):
            for m in movies:
                url = build_url({'mode': 'scrape', 'show_title': m['title'],
                                 'year': m.get('year', ''),
                                 'show_id': str(m['id']),
                                 'content_type': 'movies'})
                label = f"{m['title']} ({m.get('year', '')})"
                li = xbmcgui.ListItem(label)
                set_info(li, m, is_folder=True)
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

        from concurrent.futures import ThreadPoolExecutor, as_completed

        is_movie = content_type == 'movies'

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

                # Future 1: all HTML scrapers
                futures[pool.submit(scraper_runner.search_all, query, content_type)] = "scrapers"
                pending += 1

                # Future 2: IMDB ID lookup
                if show_id:
                    futures[pool.submit(tmdb.get_imdb_id, int(show_id), tmdb_api_key(),
                                        is_movie=is_movie)] = "imdb"
                    pending += 1

                # Future 3: poster
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
                        pdlg.update(int(done / pending * 100),
                                    "{} sources".format(len(all_results)))
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

                # Wait for Torrentio if launched
                if torrentio_future:
                    try:
                        tr = torrentio_future.result()
                        all_results.extend(tr)
                    except Exception:
                        pass
                    done += 1
                    pdlg.update(100, "{} sources".format(len(all_results)))

        finally:
            pdlg.close()

        # Filter by seeder quality: at least 1 seeder per 10GB of file size
        def _seeder_ok(r):
            s = r.get('seeders')
            if s is None:
                return True
            size_bytes = _parse_size_bytes(r.get('size', ''))
            if not size_bytes:
                return True
            return s * 10737418240 >= size_bytes

        all_results = [r for r in all_results if _seeder_ok(r)]

        # Sort by file size descending (largest first)
        all_results.sort(key=lambda r: _parse_size_bytes(r.get('size', '')), reverse=True)

        meta = {'show_title': show_title, 'show_id': show_id,
                'content_type': content_type}
        if imdb_id:
            meta['imdb_id'] = imdb_id
        if season_number:
            meta['season'] = season_number
        if episode_number:
            meta['episode'] = episode_number
        if episode_title:
            meta['episode_title'] = episode_title

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

# --- Auth: Trakt device OAuth ---
elif mode[0] == 'auth_trakt':
    client_id = ADDON.getSetting('trakt_client_id')
    if not client_id:
        notify('Trakt Client ID not set')
    else:
        try:
            data = get_device_code(client_id)
        except TraktError as e:
            notify("Trakt: " + str(e))
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
                notify("Trakt: " + str(e))

    xbmcplugin.endOfDirectory(addon_handle)

# --- Play: resolve if torrent, hand to Kodi ---
elif mode[0] == 'play':
    url = args.get('url', [''])[0]
    ep_type = args.get('type', ['direct'])[0]
    label = args.get('label', [''])[0]

    if ep_type == 'torrent':
        key = api_key()
        if not key:
            notify('AllDebrid API key not set')
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
                                        progress_callback=progress_cb)
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
                notify('AllDebrid: ' + str(e))
                xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
    else:
        li = xbmcgui.ListItem(label, path=url)
        xbmcplugin.setResolvedUrl(addon_handle, True, li)
