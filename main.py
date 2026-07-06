"""plugin.video.baldest_man — multi-site anime video scraper with AllDebrid."""
import json
import os
import sys
import tempfile
import urllib.parse
# pyrefly: ignore [missing-import]
import xbmcaddon
# pyrefly: ignore [missing-import]
import xbmcgui
# pyrefly: ignore [missing-import]
import xbmcplugin

from resources.lib import scraper_runner
from resources.lib.alldebrid import resolve as ad_resolve, AllDebridError
from resources.lib.alldebrid_auth import get_pin, poll_for_key, AuthError

ADDON = xbmcaddon.Addon()
base_url = sys.argv[0]
addon_handle = int(sys.argv[1])
args = urllib.parse.parse_qs(sys.argv[2][1:])

xbmcplugin.setContent(addon_handle, 'movies')

_CACHE_FILE = os.path.join(tempfile.gettempdir(), "baldman_search.json")


def build_url(query):
    """Build a plugin URL from a dict of params."""
    return base_url + '?' + urllib.parse.urlencode(query)


def label_episode(item):
    """Format episode label: Ep 01 The Strongest Hero 1080p"""
    parts = ['Ep', item['episode']]
    if item.get('title'):
        parts.append(item['title'])
    if item.get('quality'):
        parts.append(item['quality'])
    return ' '.join(parts)


def label_movie(item):
    """Format movie label: Movie Title 1080p"""
    parts = [item['show_title']]
    if item.get('quality'):
        parts.append(item['quality'])
    return ' '.join(parts)


def add_playable_item(item, handle, label):
    """Add a playable listitem with play URL and IsPlayable set."""
    li = xbmcgui.ListItem(label)
    li.setInfo('video', {'title': label})
    li.setProperty('IsPlayable', 'true')
    ep_type = item.get('type', 'direct')
    play_url = build_url({'mode': 'play', 'url': item['url'], 'type': ep_type})
    xbmcplugin.addDirectoryItem(handle, play_url, li, isFolder=False)
    return li


def notify(msg):
    """Show a brief Kodi notification."""
    xbmcgui.Dialog().notification('bald_man', msg, xbmcgui.NOTIFICATION_INFO, 3000)


def _save_cache(query, results):
    try:
        with open(_CACHE_FILE, 'w') as f:
            json.dump({"query": query, "results": results}, f)
    except (OSError, TypeError):
        pass  # cache write failure is non-fatal


def _display_results(query, content_type, results):
    """Render the search results list (shows as folders, movies as playable)."""
    shows = {}
    movies = []
    for r in results:
        if r.get('is_movie'):
            movies.append(r)
        else:
            shows.setdefault(r['show_title'], []).append(r)

    show_movies = content_type in ('movies', 'all')
    show_shows = content_type in ('shows', 'all')

    if show_shows:
        for show_title in sorted(shows.keys()):
            url = build_url({'mode': 'episodes', 'q': query, 'show': show_title})
            li = xbmcgui.ListItem(show_title)
            xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

    if show_movies:
        movies.sort(key=lambda r: r['show_title'])
        for m in movies:
            li = add_playable_item(m, addon_handle, label_movie(m))

    total = (len(shows) if show_shows else 0) + (len(movies) if show_movies else 0)
    if total == 0:
        li = xbmcgui.ListItem("Nothing found for '" + query + "'")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)


def _cached_results(query):
    """Return cached search results if query matches, else re-scrape."""
    try:
        with open(_CACHE_FILE) as f:
            data = json.load(f)
        if data.get("query") == query:
            return data["results"]
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return scraper_runner.search_all(query, content_type='shows')


def api_key():
    return ADDON.getSetting('alldebrid_api_key')


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

    # AllDebrid authorization
    key = api_key()
    auth_label = "AllDebrid ✓" if key else "Authorize AllDebrid"
    url = build_url({'mode': 'auth'})
    xbmcplugin.addDirectoryItem(addon_handle, url,
                                xbmcgui.ListItem(auth_label), isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Search: dialog, then filtered display ---
elif mode[0] == 'search':
    content_type = args.get('content_type', ['all'])[0]

    dialog = xbmcgui.Dialog()
    query = dialog.input('Search for anime', type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

    else:
        results = scraper_runner.search_all(query, content_type=content_type)
        _save_cache(query, results)
        _display_results(query, content_type, results)

# --- Results: redisplay cached results (back-navigation) ---
elif mode[0] == 'results':
    query = args.get('q', [''])[0]
    content_type = args.get('content_type', ['all'])[0]
    results = _cached_results(query)
    _display_results(query, content_type, results)

# --- Episodes: list playable items for a show ---
elif mode[0] == 'episodes':
    query = args.get('q', [''])[0]
    show_title = args.get('show', [''])[0]
    results = _cached_results(query)

    # Back to search results
    url = build_url({'mode': 'results', 'q': query, 'content_type': 'all'})
    xbmcplugin.addDirectoryItem(addon_handle, url,
                                xbmcgui.ListItem(".."), isFolder=True)

    # ponytail: substring match — scrapers format show_title differently,
    # e.g. nyaa returns "Dragon Ball Daima" but eztv returns "Dragon.Ball.Daima.S01E05"
    episodes = [r for r in results
                if not r.get('is_movie')
                and (r['show_title'] == show_title
                     or show_title.lower() in r['show_title'].lower())]
    episodes.sort(key=lambda r: int(r['episode']) if r['episode'].isdigit() else 0)

    for ep in episodes:
        li = add_playable_item(ep, addon_handle, label_episode(ep))

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

        # Poll with progress indicator
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
