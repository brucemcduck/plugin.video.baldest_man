"""plugin.video.baldest_man — multi-site anime video scraper with AllDebrid."""
import sys
import urllib.parse
# pyrefly: ignore [missing-import]
import xbmcaddon
# pyrefly: ignore [missing-import]
import xbmcgui
# pyrefly: ignore [missing-import]
import xbmcplugin

from lib import scraper_runner
from lib.alldebrid import resolve as ad_resolve, AllDebridError

ADDON = xbmcaddon.Addon()
base_url = sys.argv[0]
addon_handle = int(sys.argv[1])
args = urllib.parse.parse_qs(sys.argv[2][1:])

xbmcplugin.setContent(addon_handle, 'movies')


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


def notify(msg):
    """Show a brief Kodi notification."""
    xbmcgui.Dialog().notification('bald_man', msg, xbmcgui.NOTIFICATION_INFO, 3000)


def api_key():
    return ADDON.getSetting('alldebrid_api_key')


mode = args.get('mode', None)

# --- Root: show search dialog ---
if mode is None:
    dialog = xbmcgui.Dialog()
    query = dialog.input('Search for anime', type=xbmcgui.INPUT_ALPHANUM)
    if query:
        url = build_url({'mode': 'search', 'q': query})
        xbmcplugin.addDirectoryItem(addon_handle, url,
                                    xbmcgui.ListItem('Search: ' + query),
                                    isFolder=True)
    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Search: run scrapers, group by show ---
elif mode[0] == 'search':
    query = args.get('q', [''])[0]
    results = scraper_runner.search_all(query)

    if not results:
        li = xbmcgui.ListItem("Nothing found for '" + query + "'")
        xbmcplugin.addDirectoryItem(addon_handle, '', li, isFolder=False)
        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

    else:
        shows = {}
        for r in results:
            shows.setdefault(r['show_title'], []).append(r)

        for show_title in sorted(shows.keys()):
            url = build_url({'mode': 'episodes', 'q': query, 'show': show_title})
            li = xbmcgui.ListItem(show_title)
            xbmcplugin.addDirectoryItem(addon_handle, url, li, isFolder=True)

        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

# --- Episodes: list playable items for a show ---
elif mode[0] == 'episodes':
    query = args.get('q', [''])[0]
    show_title = args.get('show', [''])[0]
    results = scraper_runner.search_all(query)

    episodes = [r for r in results if r['show_title'] == show_title]
    episodes.sort(key=lambda r: int(r['episode']) if r['episode'].isdigit() else 0)

    for ep in episodes:
        li = xbmcgui.ListItem(label_episode(ep))
        li.setInfo('video', {'title': label_episode(ep)})
        li.setProperty('IsPlayable', 'true')

        ep_type = ep.get('type', 'direct')
        play_url = build_url({'mode': 'play', 'url': ep['url'], 'type': ep_type})
        xbmcplugin.addDirectoryItem(addon_handle, play_url, li, isFolder=False)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

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
        # Direct URL — hand straight to Kodi
        li = xbmcgui.ListItem(path=url)
        xbmcplugin.setResolvedUrl(addon_handle, True, li)
