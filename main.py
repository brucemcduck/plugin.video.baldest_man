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
from resources.lib.alldebrid_auth import get_pin, poll_for_key, AuthError
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
    """Format scrape result label: S01E05 · Episode Name  or  Movie Title (1999)."""
    if item.get('episode'):
        parts = [f"S{int(item.get('season', '01')):02d}E{int(item['episode']):02d}"]
        if item.get('title'):
            parts.append(item['title'])
    elif item.get('is_movie'):
        parts = [item['show_title']]
    else:
        parts = [item.get('title', item['show_title'])]
    return ' · '.join(parts)


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


def add_scrape_result(item, poster_url=None):
    """Add a playable scrape result with structured metadata and artwork."""
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

    play_url = build_url({'mode': 'play', 'url': item['url'],
                          'type': item.get('type', 'direct'),
                          'label': label})
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

    # Continue Watching — last played torrent
    last = ADDON.getSetting('last_played')
    if last:
        try:
            last_data = json.loads(last)
            if last_data.get('url'):
                url = build_url({'mode': 'continue_watching'})
                xbmcplugin.addDirectoryItem(addon_handle, url,
                                            xbmcgui.ListItem("Continue Watching"), isFolder=True)
        except (json.JSONDecodeError, KeyError):
            pass

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Continue Watching: show last played item ---
elif mode[0] == 'continue_watching':
    last = ADDON.getSetting('last_played')
    if last:
        try:
            item = json.loads(last)
            label = item.get('label', 'Last Played') or 'Last Played'
            li = xbmcgui.ListItem(label)
            li.setProperty('IsPlayable', 'true')
            play_url = build_url({'mode': 'play', 'url': item['url'], 'type': 'torrent',
                                  'label': label})
            xbmcplugin.addDirectoryItem(addon_handle, play_url, li, isFolder=False)
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
        label = f"{ep['episode_number']}. {ep.get('name', '')}"
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
    content_type = args.get('content_type', ['all'])[0]

    if season_number and episode_number:
        query = f"{show_title} S{int(season_number):02d}E{int(episode_number):02d}"
    else:
        query = f"{show_title} {year}".strip() if year else show_title

    results = scraper_runner.search_all(query, content_type=content_type)

    # Torrentio via IMDB ID — covers 24+ trackers in one call
    if show_id:
        try:
            is_movie = content_type == 'movies'
            imdb_id = tmdb.get_imdb_id(int(show_id), tmdb_api_key(), is_movie=is_movie)
            if imdb_id:
                if is_movie:
                    tr = torrentio.search_imdb(imdb_id, is_movie=True)
                elif season_number and episode_number:
                    tr = torrentio.search_imdb(imdb_id, int(season_number), int(episode_number))
                else:
                    tr = []
                results.extend(tr)
        except Exception:
            pass

    # TMDB poster for artwork on every result
    poster_url = None
    if show_id:
        try:
            poster_url = tmdb.get_poster(int(show_id), tmdb_api_key(),
                                         is_movie=(content_type == 'movies'))
        except Exception:
            pass

    # Sort by file size descending (largest first)
    results.sort(key=lambda r: _parse_size_bytes(r.get('size', '')), reverse=True)

    for r in results:
        if season_number and 'episode' in r and 'season' not in r:
            r['season'] = season_number
        add_scrape_result(r, poster_url)

    if not results:
        label = "No sources found"
        if episode_number:
            label += f" for S{int(season_number):02d}E{int(episode_number):02d}"
        li = xbmcgui.ListItem(label)
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Auth: AllDebrid PIN-based device authorization ---
elif mode[0] == 'auth':
    try:
        pin, check_token, user_url, expires = get_pin()
    except AuthError as e:
        notify("AllDebrid: " + str(e))
    else:
        msg = ("1. Go to: [COLOR skyblue]{}[/COLOR]\n"
               "2. Enter code: [COLOR yellow]{}[/COLOR]\n"
               "3. Press OK after authorizing").format(
                   user_url or "https://alldebrid.com/pin/", pin)
        xbmcgui.Dialog().ok("AllDebrid Authorization", msg)

        pdlg = xbmcgui.DialogProgress()
        pdlg.create("AllDebrid", "Waiting for authorization...")
        try:
            apikey = poll_for_key(pin, check_token)
            ADDON.setSetting('alldebrid_api_key', apikey)
            pdlg.close()
            notify("AllDebrid authorized!")
        except AuthError as e:
            pdlg.close()
            notify("AllDebrid: " + str(e))

    xbmcplugin.endOfDirectory(addon_handle)

# --- Play: resolve if torrent, hand to Kodi ---
elif mode[0] == 'play':
    url = args.get('url', [''])[0]
    ep_type = args.get('type', ['direct'])[0]

    if ep_type == 'torrent':
        key = api_key()
        if not key:
            notify('AllDebrid API key not set')
            xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
        else:
            try:
                direct_url = ad_resolve(url, key)
                # Save for Continue Watching
                label = args.get('label', [''])[0]
                ADDON.setSetting('last_played', json.dumps({'url': url, 'label': label}))
                li = xbmcgui.ListItem(path=direct_url)
                xbmcplugin.setResolvedUrl(addon_handle, True, li)
            except AllDebridError as e:
                notify('AllDebrid: ' + str(e))
                xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
    else:
        li = xbmcgui.ListItem(path=url)
        xbmcplugin.setResolvedUrl(addon_handle, True, li)
