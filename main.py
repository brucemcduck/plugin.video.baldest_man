import sys
import urllib.parse
# pyrefly: ignore [missing-import]
import xbmcgui
# pyrefly: ignore [missing-import]
import xbmcplugin

base_url = sys.argv[0]
addon_handle = int(sys.argv[1])
args = urllib.parse.parse_qs(sys.argv[2][1:])

xbmcplugin.setContent(addon_handle, 'movies')

def build_url(query):
    return base_url + '?' + urllib.parse.urlencode(query)

mode = args.get('mode', None)

if mode is None:
    url = build_url({'mode':'folder','foldername': 'Folder One'})
    li = xbmcgui.ListItem('Folder One')
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=url, listitem=li,
     isFolder = True)

    url = build_url({'mode': 'folder', 'foldername': 'Folder Two'})
    li = xbmcgui.ListItem('Folder Two')
    xbmcplugin.addDirectoryItem(handle=addon_handle,url=url,listitem=li,isFolder=True)

    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)


elif mode[0] == 'folder':
    foldername = args['foldername'][0]
    url = 'http://localhost/some_video.mkv'
    li = xbmcgui.ListItem(foldername + ' Video')
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=url,listitem=li)
    xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

