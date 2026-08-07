"""Background service — Trakt scrobble start/pause/stop during playback."""
import time

# pyrefly: ignore [missing-import]
import xbmc
# pyrefly: ignore [missing-import]
import xbmcaddon

from resources.lib.trakt import (
    scrobble_start, scrobble_pause, scrobble_stop,
    read_now_playing, clear_now_playing,
)


class TraktPlayer(xbmc.Player):
    def __init__(self):
        super(TraktPlayer, self).__init__()
        self._active = None
        self._started = False

    def _progress_pct(self):
        try:
            total = float(self.getTotalTime())
            if total <= 0:
                return 0.0
            return max(0.0, min(100.0, self.getTime() / total * 100.0))
        except Exception:
            return 0.0

    def _load_handoff(self):
        data = read_now_playing()
        if not data or not data.get('imdb_id'):
            return None
        # Ignore stale handoffs older than 10 minutes
        started = data.get('started') or 0
        if started and time.time() - int(started) > 600:
            clear_now_playing()
            return None
        return data

    def onAVStarted(self):
        self._maybe_start()

    def onPlayBackStarted(self):
        self._maybe_start()

    def _maybe_start(self):
        if self._started:
            return
        addon = xbmcaddon.Addon()
        token = addon.getSetting('trakt_access_token')
        if not token:
            return
        data = self._load_handoff()
        if not data:
            return
        self._active = data
        self._started = True
        scrobble_start(token, data['imdb_id'],
                       data.get('season'), data.get('episode'),
                       progress_pct=self._progress_pct())

    def onPlayBackPaused(self):
        self._scrobble(scrobble_pause)

    def onPlayBackResumed(self):
        self._scrobble(scrobble_start)

    def onPlayBackStopped(self):
        self._finish()

    def onPlayBackEnded(self):
        self._finish(ended=True)

    def _scrobble(self, fn):
        if not self._active:
            return
        addon = xbmcaddon.Addon()
        token = addon.getSetting('trakt_access_token')
        if not token:
            return
        d = self._active
        fn(token, d['imdb_id'], d.get('season'), d.get('episode'),
           progress_pct=self._progress_pct())

    def _finish(self, ended=False):
        if not self._active:
            self._started = False
            return
        pct = 100.0 if ended else self._progress_pct()
        # Trakt watches typically count at >= 80%
        if ended and pct < 80:
            pct = 100.0
        addon = xbmcaddon.Addon()
        token = addon.getSetting('trakt_access_token')
        if token:
            d = self._active
            scrobble_stop(token, d['imdb_id'],
                          d.get('season'), d.get('episode'),
                          progress_pct=pct)
        clear_now_playing()
        self._active = None
        self._started = False


if __name__ == '__main__':
    monitor = xbmc.Monitor()
    player = TraktPlayer()
    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break
