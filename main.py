"""plugin.video.baldest_man — multi-site video scraper with AllDebrid + TMDB metadata."""
import sys
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
    """Format scrape result: Ep 05 Title [1080p] ⬆12 · 1.2GB"""
    if item.get('episode') and item.get('title'):
        parts = [f"Ep {item['episode']}", item['title']]
    elif item.get('is_movie'):
        parts = [item['show_title']]
    else:
        parts = [item.get('title', item['show_title'])]

    if item.get('quality'):
        parts.append(f"[{item['quality']}]")

    extras = []
    if item.get('seeders'):
        extras.append(f"⬆{item['seeders']}")
    if item.get('size'):
        extras.append(item['size'])
    if extras:
        parts.append(' · '.join(extras))

    return ' '.join(parts)


def add_scrape_result(item):
    """Add a playable scrape result to the directory listing."""
    label = label_result(item)
    li = xbmcgui.ListItem(label)
    li.setInfo('video', {'title': label})
    li.setProperty('IsPlayable', 'true')
    play_url = build_url({'mode': 'play', 'url': item['url'],
                          'type': item.get('type', 'direct')})
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
    for label, content_type in [
        ('Search Shows', 'shows'),
        ('Search Movies', 'movies'),
        ('Search All', 'all'),
    ]:
        url = build_url({'mode': 'search', 'content_type': content_type})
        xbmcplugin.addDirectoryItem(addon_handle, url,
                                    xbmcgui.ListItem(label), isFolder=True)

    key = api_key()
    auth_label = "AllDebrid ✓" if key else "Authorize AllDebrid"
    url = build_url({'mode': 'auth'})
    xbmcplugin.addDirectoryItem(addon_handle, url,
                                xbmcgui.ListItem(auth_label), isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Search: TMDB lookup ---
elif mode[0] == 'search':
    content_type = args.get('content_type', ['all'])[0]

    dialog = xbmcgui.Dialog()
    query = dialog.input(f'Search {content_type.capitalize()}',
                         type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

    else:
        key = tmdb_api_key()
        lang = tmdb_lang()
        shows = []
        movies = []

        if content_type in ('shows', 'all'):
            shows = tmdb.search_shows(query, key, lang)
            for s in shows:
                url = build_url({'mode': 'seasons', 'show_id': str(s['id']),
                                 'show_title': s['title']})
                label = f"{s['title']} ({s.get('year', '')})"
                li = xbmcgui.ListItem(label)
                set_info(li, s, is_folder=True)
                xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        if content_type in ('movies', 'all'):
            movies = tmdb.search_movies(query, key, lang)
            for m in movies:
                url = build_url({'mode': 'scrape', 'show_title': m['title'],
                                 'year': m.get('year', ''),
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
    year = args.get('year', [''])[0]
    season_number = args.get('season_number', [None])[0]
    episode_number = args.get('episode_number', [None])[0]
    content_type = args.get('content_type', ['all'])[0]

    if season_number and episode_number:
        query = f"{show_title} S{int(season_number):02d}E{int(episode_number):02d}"
    else:
        query = f"{show_title} {year}".strip() if year else show_title

    results = scraper_runner.search_all(query, content_type=content_type)

    for r in results:
        add_scrape_result(r)

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
                li = xbmcgui.ListItem(path=direct_url)
                xbmcplugin.setResolvedUrl(addon_handle, True, li)
            except AllDebridError as e:
                notify('AllDebrid: ' + str(e))
                xbmcplugin.setResolvedUrl(addon_handle, False, xbmcgui.ListItem())
    else:
        li = xbmcgui.ListItem(path=url)
        xbmcplugin.setResolvedUrl(addon_handle, True, li)
