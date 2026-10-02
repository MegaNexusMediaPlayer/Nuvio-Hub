"""MegaNexus Sports screen (6.0.35, GitHub issue #8).

Only sports add-ons (resources.lib.sports). Rows are their catalogs (live and
today first). Resting on an event loads its streams into the glass box under
"Sports" and plays the first one in the small video; another stream can be
chosen in the box; OK on the event (or a stream) goes full screen and Back
returns here. Playback is a preview to the playback service, so sports never
reach Continue Watching or Trakt/Simkl. Header: Home (top of Sports),
Settings, HUB (leave).
"""
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
import xbmc
import xbmcaddon
import xbmcgui
from resources.lib import art_cache, sports
from resources.lib.settings_cache import cached_addon
from resources.lib.theme import folder as theme_folder
from .dialog import Dialog, BACK
from .home_trailers import PreviewPlayer

ROW_BASE = 1000
MAX_ROWS = 20
STREAM_LIST = 700
DWELL = 1.0                  # seconds on an event before its streams load
AUTOPLAY_SETTING = 'nuvio_sport_autoplay'
LOAD_WORKERS = 4
LOAD_SECONDS = 15
POSTERS_PER_ROW = 8


def autoplay_enabled():
    return cached_addon().getSetting(AUTOPLAY_SETTING) != 'false'


class SportsWindow(Dialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.rows = list(kwargs.get('rows') or [])       # [(title, provider, catalog, items)]
        self.outcome = ''
        self.player = PreviewPlayer()
        self.streams = []
        self.selection = None          # (row, pos) under the cursor
        self.changed = time.monotonic()
        self.stream_key = None         # event whose streams are shown/loading
        self.stream_job = None
        self.results = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='NuvioSportStreams')
        self.playing_index = -1
        self.fullscreen_when_ready = False
        self._painted = False

    # ---- painting ------------------------------------------------------
    def onInit(self):
        if not self._painted:
            self._paint()
            self._painted = True
        self.restore_focus()

    def _paint(self):
        shown = [r for r in self.rows if r[3]][:MAX_ROWS]
        self.rows = shown
        for i in range(MAX_ROWS):
            self.setProperty('nuvio.sport.row.%d' % i, shown[i][0] if i < len(shown) else '')
            control = self.getControl(ROW_BASE + i)
            control.reset()
            if i < len(shown):
                control.addItems([self._item(item) for item in shown[i][3]])
        # Explicit vertical navigation (rows are hidden when empty).
        for i in range(len(shown)):
            control = self.getControl(ROW_BASE + i)
            control.controlUp(self.getControl(ROW_BASE + i - 1) if i else self.getControl(STREAM_LIST))
            control.controlDown(self.getControl(ROW_BASE + min(i + 1, len(shown) - 1)))
        if not shown:
            self.setProperty('nuvio.sport.empty', 'No sports add-on is installed. Add one in HUB Settings > Add-ons '
                                                  '(for example a manifest whose catalogs are of type "sport"). '
                                                  'Sports add-ons appear only here, never on the movie and series Home.')
            self.setFocusId(101)
        else:
            self.setProperty('nuvio.sport.empty', '')
            self.setFocusId(ROW_BASE)

    @staticmethod
    def _item(item):
        li = xbmcgui.ListItem(label=item['title'])
        li.setArt(art_cache.art({'thumb': item.get('art') or ''}))
        li.setProperty('live', '1' if item.get('live') else '')
        return li

    def _selected(self):
        cid = self.getFocusId()
        index = cid - ROW_BASE
        if not 0 <= index < len(self.rows):
            return None
        pos = self.getControl(cid).getSelectedPosition()
        items = self.rows[index][3]
        return (index, pos) if 0 <= pos < len(items) else None

    def _event(self, selection):
        index, pos = selection
        return self.rows[index][3][pos]

    # ---- streams -------------------------------------------------------
    def _show_streams(self, rows, status=''):
        control = self.getControl(STREAM_LIST)
        control.reset()
        items = []
        for i, stream in enumerate(rows):
            li = xbmcgui.ListItem(label=stream['label'], label2=stream.get('detail') or '')
            li.setProperty('playing', 'Playing' if i == self.playing_index else '')
            items.append(li)
        control.addItems(items)
        self.setProperty('nuvio.sport.streams_status', status if not rows else '')

    def _request_streams(self, key, event):
        self.stream_key = key
        self.streams = []
        self.playing_index = -1
        self._show_streams([], 'Loading streams…')

        def work():
            try:
                found = sports.streams(event)
            except Exception:
                found = []
            self.results.put((key, found))
        self.stream_job = self.pool.submit(work)

    def _play(self, index, fullscreen=False):
        if not 0 <= index < len(self.streams):
            return
        self._stop_preview()
        stream = self.streams[index]
        token = uuid.uuid4().hex
        self.player = PreviewPlayer()
        self.player.token = token
        item = xbmcgui.ListItem(label=self.getProperty('nuvio.sport.title') or 'Sports')
        item.setProperty('nuvio.preview', token)
        item.setProperty('IsPlayable', 'true')
        home = xbmcgui.Window(10000)
        # A preview to the playback service: no progress, no tracking.
        home.setProperty('nuvio.preview.active', token)
        self.setProperty('nuvio.preview.loading', '1')
        self.setProperty('nuvio.sport.video_status', 'Starting stream…')
        self.player.path = stream['url']
        self.playing_index = index
        self.fullscreen_when_ready = fullscreen
        from resources.lib import refresh_guard
        refresh_guard.suspend()   # small video: no TV mode switch (issue #4)
        self.player.play(stream['url'], item, windowed=True)
        self._show_streams(self.streams)

    def _stop_preview(self):
        from resources.lib import refresh_guard
        refresh_guard.restore()
        self.player.cancel()
        self.player.stop_owned()
        self.player._ended()
        self.setProperty('nuvio.preview', '')
        self.setProperty('nuvio.preview.loading', '')
        self.setProperty('nuvio.sport.video_status', '')
        self.fullscreen_when_ready = False

    # ---- loop ------------------------------------------------------------
    def tick(self):
        now = time.monotonic()
        selection = self._selected()
        if selection is not None and selection != self.selection:
            self.selection = selection
            self.changed = now
            event = self._event(selection)
            self.setProperty('nuvio.sport.title', event['title'])
            self.setProperty('nuvio.sport.info', ' · '.join(x for x in (event.get('info'), self.rows[selection[0]][0]) if x))
            self.setProperty('nuvio.sport.bg', art_cache.url(event.get('background') or event.get('art') or ''))
        if self.selection is not None and self.getFocusId() != STREAM_LIST:
            key = (self.selection, self._event(self.selection)['id'])
            if key != self.stream_key and now - self.changed >= DWELL:
                self._stop_preview()
                self._request_streams(key, self._event(self.selection))
        while not self.results.empty():
            key, found = self.results.get_nowait()
            if key != self.stream_key:
                continue
            self.streams = found
            self._show_streams(found, '' if found else 'No streams for this event right now.')
            if found and (autoplay_enabled() or self.fullscreen_when_ready):
                self._play(0, fullscreen=self.fullscreen_when_ready)
        if self.player.token:
            if self.player.failed:
                self.setProperty('nuvio.sport.video_status', 'This stream did not start. Choose another one.')
                self.setProperty('nuvio.preview.loading', '')
                self.player.token = ''
            elif self.player.owns() and (self.player.ready or self.player.getTime() > .15):
                self.setProperty('nuvio.preview', '1')
                self.setProperty('nuvio.preview.loading', '')
                self.setProperty('nuvio.sport.video_status', '')
                if self.fullscreen_when_ready:
                    self.fullscreen_when_ready = False
                    xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')
            elif self.getProperty('nuvio.preview') == '1' and not self.player.isPlayingVideo():
                self.setProperty('nuvio.preview', '')

    # ---- input -----------------------------------------------------------
    def onClick(self, cid):
        if cid == 108:
            self.outcome = 'hub'
            self.close()
        elif cid == 101:
            self._stop_preview()
            if self.rows:
                self.getControl(ROW_BASE).selectItem(0)
                self.setFocusId(ROW_BASE)
        elif cid == 107:
            self._stop_preview()
            from .settings import run
            self.child(run)
        elif cid == STREAM_LIST:
            index = self.getControl(STREAM_LIST).getSelectedPosition()
            if index == self.playing_index and self.player.owns():
                xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')
            else:
                self._play(index)
        elif ROW_BASE <= cid < ROW_BASE + len(self.rows):
            selection = self._selected()
            if selection is None:
                return
            key = (selection, self._event(selection)['id'])
            if key == self.stream_key and self.player.owns():
                xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')
            elif key == self.stream_key and self.streams:
                self._play(max(0, self.playing_index), fullscreen=True)
            else:
                self.selection = selection
                self._request_streams(key, self._event(selection))
                self.fullscreen_when_ready = True

    def onAction(self, action):
        if action.getId() in BACK:
            self.close()

    def close(self):
        self._stop_preview()
        self.pool.shutdown(wait=False)
        super().close()


# ---- opening ---------------------------------------------------------------

def _load(window, monitor):
    """Catalog pages (cached at once, missing/stale ones from the add-ons) and
    the first posters into the image RAM. Back skips."""
    from concurrent.futures import ThreadPoolExecutor as Pool
    pairs = sports.catalogs()
    rows, todo = [], []
    for provider, catalog in pairs:
        metas, fresh = sports.cached_page(provider, catalog)
        rows.append([str(catalog.get('name') or catalog['id']), provider, catalog, metas or []])
        if metas is None or not fresh:
            todo.append(len(rows) - 1)
    if todo:
        pool = Pool(max_workers=LOAD_WORKERS, thread_name_prefix='NuvioSportsLoad')
        futures = {pool.submit(sports.load_page, rows[i][1], rows[i][2]): i for i in todo}
        deadline = time.monotonic() + LOAD_SECONDS
        try:
            while futures and not window.cancelled and time.monotonic() < deadline:
                for future in [f for f in futures if f.done()]:
                    index = futures.pop(future)
                    try:
                        rows[index][3] = future.result()
                    except Exception:
                        pass
                window.setProperty('nuvio.loading', 'Preparing sports · %d / %d · Back to skip' % (len(pairs) - len(futures), len(pairs)))
                if monitor.waitForAbort(.05):
                    break
        finally:
            for future in futures:
                future.cancel()
            pool.shutdown(wait=False)
    result = []
    for title, provider, catalog, metas in rows:
        items = []
        for meta in metas:
            try:
                items.append(sports.card(provider, catalog, meta))
            except Exception:
                continue
        result.append((title, provider, catalog, items))
    base = xbmcgui.Window(10000).getProperty('nuvio.art_cache.base')
    if base.startswith('http://127.0.0.1:') and not window.cancelled:
        _warm(window, monitor, base, sports.poster_urls([r[3] for r in result], POSTERS_PER_ROW))
    return result


def _warm(window, monitor, base, urls):
    """Sports posters go into the same image RAM as Home's posters."""
    from urllib.parse import quote
    from urllib.request import Request, urlopen
    from concurrent.futures import ThreadPoolExecutor as Pool

    def head(url):
        with urlopen(Request(base + '/image?url=' + quote(url, safe=''), method='HEAD'), timeout=4) as response:
            response.read(0)
    if not urls:
        return
    pool = Pool(max_workers=6, thread_name_prefix='NuvioSportPosters')
    futures = [pool.submit(head, url) for url in urls]
    deadline = time.monotonic() + 20
    try:
        while not window.cancelled and time.monotonic() < deadline:
            done = sum(1 for f in futures if f.done())
            window.setProperty('nuvio.loading', 'Loading sports posters · %d / %d · Back to skip' % (done, len(urls)))
            if done == len(futures) or monitor.waitForAbort(.05):
                break
    finally:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=False)


def open_sports():
    from .playback import Loading, ROOT
    monitor = xbmc.Monitor()
    loading = Loading('nuvio_loading.xml', ROOT, theme_folder(), '1080i', label='Preparing sports', full=True)
    loading.show()
    try:
        rows = _load(loading, monitor)
    finally:
        loading.close()
    win = SportsWindow('nuvio_sports.xml', xbmcaddon.Addon('script.nuvio').getAddonInfo('path'), theme_folder(), '1080i', rows=rows)
    try:
        win.doModal()
        return win.outcome
    finally:
        win.close()
