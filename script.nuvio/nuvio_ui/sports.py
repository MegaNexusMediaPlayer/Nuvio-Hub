"""MegaNexus Sports screen (6.0.35, GitHub issue #8).

Only sports add-ons (resources.lib.sports). Rows are their catalogs (live and
today first). Resting on an event loads its streams into the glass box under
"Sports" and plays the first one in the small video; another stream can be
chosen in the box; OK on the event (or a stream) goes full screen and Back
returns here. Playback is a preview to the playback service, so sports never
reach Continue Watching or Trakt/Simkl. Header: Home (top of Sports),
Settings, HUB (leave).

Only LIVE events look for streams, after the cursor rests DWELL seconds;
upcoming events never do (not even on OK). Small player (default): OK
enlarges the video inside this window (OK there = live channels panel, Back =
small again); hold OK opens Kodi's own full-screen player. Big player: Kodi's
player opens by itself after DWELL. A stream that cuts out reconnects. Back /
Esc never leave Sports - only the HUB button does.
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
FULL_BUTTON = 950            # covers the enlarged video (OK = live channels, Back = small)
CHANNEL_LIST = 960           # live channels panel over the enlarged video
DWELL = 5.0                  # seconds on a LIVE event before its streams load and play
AUTOPLAY_SETTING = 'nuvio_sport_autoplay'
PLAYER_SETTING = 'nuvio_sport_player'      # 'small' (default) | 'big'
PLAYER_LABELS = {'small': 'Small player · enlarge with OK, hold OK for Kodi\'s player',
                 'big': 'Big player · Kodi\'s full-screen player after 5 seconds'}
RECONNECT_DELAYS = (2, 3, 5, 8, 10, 10)    # seconds between reconnect attempts
HEALTHY_SECONDS = 30                       # playing this long resets the attempts
LOAD_WORKERS = 4
LOAD_SECONDS = 15
POSTERS_PER_ROW = 8
CONTEXT = (117, 101, 1009)                 # hold OK / menu


def autoplay_enabled():
    return cached_addon().getSetting(AUTOPLAY_SETTING) != 'false'


def player_mode():
    return 'big' if cached_addon().getSetting(PLAYER_SETTING) == 'big' else 'small'


def _hls_item(item, url):
    """Live HLS through inputstream.adaptive when installed: it rides out
    stalls instead of failing at the first gap. Returns the URL to play."""
    base, _, headers = url.partition('|')
    if '.m3u8' not in base.lower() or not xbmc.getCondVisibility('System.HasAddon(inputstream.adaptive)'):
        return url
    item.setProperty('inputstream', 'inputstream.adaptive')
    try:
        major = int(xbmc.getInfoLabel('System.BuildVersion').split('.')[0])
    except ValueError:
        major = 21
    if major < 21:
        item.setProperty('inputstream.adaptive.manifest_type', 'hls')
    if headers:
        item.setProperty('inputstream.adaptive.manifest_headers', headers)
        item.setProperty('inputstream.adaptive.stream_headers', headers)
    item.setMimeType('application/vnd.apple.mpegurl')
    item.setContentLookup(False)
    return base


class SportsPlayer(PreviewPlayer):
    """Ownership by the ListItem token: live HLS streams report another file
    path than the URL that was played. ``dropped`` = playback ended or failed
    without being asked to (buffer underrun, stream cut) - reconnect."""
    def __init__(self):
        super().__init__()
        self.dropped = False

    def owns(self):
        try:
            if not self.token or not self.isPlayingVideo():
                return False
            if xbmcgui.Window(10000).getProperty('nuvio.preview.active') != self.token:
                return False
            return self.getPlayingItem().getProperty('nuvio.preview') == self.token
        except Exception:
            return False

    def onAVStarted(self):
        self.ready = self.owns()
        if self.cancelled:
            self.stop_owned()

    def onPlayBackStopped(self):
        if not self.cancelled:
            self.dropped = True
        self._ended()

    def onPlayBackEnded(self):
        if not self.cancelled:
            self.dropped = True
        self._ended()

    def onPlayBackError(self):
        self.failed = True
        if not self.cancelled:
            self.dropped = True
        self._ended()


class SportsWindow(Dialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.rows = list(kwargs.get('rows') or [])       # [(title, provider, catalog, items)]
        self.outcome = ''
        self.player = SportsPlayer()
        self.streams = []
        self.selection = None          # (row, pos) under the cursor
        self.changed = time.monotonic()
        self.stream_key = None         # event whose streams are shown/loading
        self.stream_job = None
        self.results = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='NuvioSportStreams')
        self.playing_index = -1
        self.after_ready = ''          # '' | 'full' | 'native' once the stream shows
        self.reconnect_at = 0.0
        self.attempts = 0
        self.started_at = 0.0
        self.use_ia = True
        self.channels = []
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

    def _describe(self, selection):
        event = self._event(selection)
        self.setProperty('nuvio.sport.title', event['title'])
        self.setProperty('nuvio.sport.info', ' · '.join(x for x in (event.get('info'), self.rows[selection[0]][0]) if x))
        self.setProperty('nuvio.sport.bg', art_cache.url(event.get('background') or event.get('art') or ''))

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

    def _request_streams(self, key, event, after=''):
        self.stream_key = key
        self.streams = []
        self.playing_index = -1
        self.after_ready = after
        self._show_streams([], 'Loading streams…')

        def work():
            try:
                found = sports.streams(event)
            except Exception:
                found = []
            self.results.put((key, found))
        self.stream_job = self.pool.submit(work)

    def _play(self, index, after='', keep_view=False, reconnect=False):
        if not 0 <= index < len(self.streams):
            return
        self._stop_preview(keep_view=keep_view)
        stream = self.streams[index]
        token = uuid.uuid4().hex
        self.player = SportsPlayer()
        self.player.token = token
        item = xbmcgui.ListItem(label=self.getProperty('nuvio.sport.title') or 'Sports')
        item.setProperty('nuvio.preview', token)
        item.setProperty('IsPlayable', 'true')
        url = _hls_item(item, stream['url']) if self.use_ia else stream['url']
        home = xbmcgui.Window(10000)
        # A preview to the playback service: no progress, no tracking.
        home.setProperty('nuvio.preview.active', token)
        self.setProperty('nuvio.preview.loading', '1')
        self.setProperty('nuvio.sport.video_status', 'Reconnecting… (%d)' % self.attempts if reconnect else 'Starting stream…')
        self.player.path = url
        if not reconnect:
            self.attempts = 0
            self.use_ia = True
        self.playing_index = index
        self.after_ready = after
        self.reconnect_at = 0.0
        self.started_at = 0.0
        from resources.lib import refresh_guard
        refresh_guard.suspend()   # no TV mode switch (issue #4)
        self.player.play(url, item, windowed=True)
        self._show_streams(self.streams)

    def _stop_preview(self, keep_view=False):
        if not keep_view:
            self._small()
        from resources.lib import refresh_guard
        if not keep_view:
            refresh_guard.restore()
        self.player.cancel()
        self.player.stop_owned()
        self.player._ended()
        self.setProperty('nuvio.preview', '')
        self.setProperty('nuvio.preview.loading', '')
        self.setProperty('nuvio.sport.video_status', '')
        self.after_ready = ''
        self.reconnect_at = 0.0

    def _reconnect(self, now):
        """A live stream cut out (buffering, provider gap): play it again
        instead of stopping with an error, a few times with growing pauses."""
        if self.playing_index < 0 or self.attempts >= len(RECONNECT_DELAYS):
            self.setProperty('nuvio.sport.video_status', 'The stream stopped. Choose it again or another stream.')
            self.player.token = ''
            return
        if not self.reconnect_at:
            if self.player.failed and self.use_ia and not self.started_at:
                self.use_ia = False      # this stream may not like inputstream.adaptive
            self.reconnect_at = now + RECONNECT_DELAYS[self.attempts]
            self.setProperty('nuvio.preview', '')
            self.setProperty('nuvio.sport.video_status', 'Reconnecting…')
            return
        if now >= self.reconnect_at:
            self.attempts += 1
            self._play(self.playing_index, after=self.after_ready, keep_view=True, reconnect=True)

    # ---- loop ------------------------------------------------------------
    def tick(self):
        now = time.monotonic()
        selection = self._selected()
        if selection is not None and selection != self.selection:
            self.selection = selection
            self.changed = now
            event = self._event(selection)
            self._describe(selection)
            if not event.get('live'):
                self.setProperty('nuvio.sport.streams_status', 'Not live yet. Streams appear when the event starts.')
            elif (selection, event['id']) != self.stream_key:
                self.setProperty('nuvio.sport.streams_status', 'Live · streams load in a moment…')
        if self.selection is not None and self.getFocusId() != STREAM_LIST and self.getProperty('nuvio.sport.full') != '1':
            event = self._event(self.selection)
            key = (self.selection, event['id'])
            # Only live events, and only after the cursor rested DWELL seconds.
            if event.get('live') and key != self.stream_key and now - self.changed >= DWELL:
                self._stop_preview()
                self._request_streams(key, event, 'native' if player_mode() == 'big' else '')
        while not self.results.empty():
            key, found = self.results.get_nowait()
            if key != self.stream_key:
                continue
            self.streams = found
            self._show_streams(found, '' if found else 'No streams for this event right now.')
            if found and (autoplay_enabled() or self.after_ready):
                self._play(0, after=self.after_ready, keep_view=self.getProperty('nuvio.sport.full') == '1')
        if not self.player.token:
            return
        if self.player.dropped or (self.player.failed and not self.player.owns()):
            self._reconnect(now)
        elif self.player.owns() and (self.player.ready or self.player.getTime() > .15):
            if not self.started_at:
                self.started_at = now
            elif now - self.started_at > HEALTHY_SECONDS:
                self.attempts = 0
            self.setProperty('nuvio.preview', '1')
            self.setProperty('nuvio.preview.loading', '')
            self.setProperty('nuvio.sport.video_status', '')
            after, self.after_ready = self.after_ready, ''
            if after == 'full':
                self._fullscreen()
            elif after == 'native':
                self._native()

    # ---- views -------------------------------------------------------------
    def _fullscreen(self):
        """The same player, enlarged inside this window: seamless, no new
        playback and no TV mode switch."""
        if self.getProperty('nuvio.sport.full') == '1':
            return
        self._return_focus = self.getFocusId()
        self.setProperty('nuvio.sport.full', '1')
        self.setFocusId(FULL_BUTTON)

    def _small(self):
        self._hide_channels()
        if self.getProperty('nuvio.sport.full') != '1':
            return
        self.setProperty('nuvio.sport.full', '')
        try:
            self.setFocusId(getattr(self, '_return_focus', 0) or ROW_BASE)
        except Exception:
            self.setFocusId(ROW_BASE)

    def _native(self):
        """Kodi's own full-screen player for the stream that plays (hold OK, or
        the Big player). This window steps aside - Kodi's player would open
        under it - and comes back when the player is left."""
        if not self.player.owns():
            return
        monitor = xbmc.Monitor()
        self._child_active = True
        try:
            xbmcgui.WindowXMLDialog.close(self)
            xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')
            seen, start = False, time.monotonic()
            while not monitor.abortRequested():
                full = xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)')
                seen = seen or full
                if (seen and not full) or (not seen and time.monotonic() - start > 5):
                    break
                if monitor.waitForAbort(.1):
                    break
        finally:
            if not self.player.owns():
                # Stopped in Kodi's player on purpose: no reconnect.
                self.player.cancelled = True
                self.player.dropped = False
                self.player.token = ''
                self.setProperty('nuvio.preview', '')
                self.setProperty('nuvio.preview.loading', '')
            if not self._dialog_closed and not monitor.abortRequested():
                self.show_ready()
            self._child_active = False

    # ---- live channels over the enlarged video ---------------------------
    def _live_channels(self):
        seen, result = set(), []
        for index, row in enumerate(self.rows):
            for pos, item in enumerate(row[3]):
                if item.get('live') and item['id'] not in seen:
                    seen.add(item['id'])
                    result.append(((index, pos), item, row[0]))
        return result

    def _show_channels(self):
        self.channels = self._live_channels()
        control = self.getControl(CHANNEL_LIST)
        control.reset()
        items = []
        current = self._event(self.selection)['id'] if self.selection else ''
        for _, item, row_title in self.channels:
            li = xbmcgui.ListItem(label=item['title'], label2=row_title)
            li.setArt(art_cache.art({'thumb': item.get('art') or ''}))
            li.setProperty('playing', 'Playing' if item['id'] == current else '')
            items.append(li)
        control.addItems(items)
        playing = next((i for i, c in enumerate(self.channels) if c[1]['id'] == current), 0)
        if items:
            control.selectItem(playing)
        self.setProperty('nuvio.sport.channels', '1')
        self.setFocusId(CHANNEL_LIST)

    def _hide_channels(self):
        if self.getProperty('nuvio.sport.channels') == '1':
            self.setProperty('nuvio.sport.channels', '')
            if self.getProperty('nuvio.sport.full') == '1':
                self.setFocusId(FULL_BUTTON)

    def _switch_channel(self):
        pos = self.getControl(CHANNEL_LIST).getSelectedPosition()
        if not 0 <= pos < len(self.channels):
            return
        selection, event, _ = self.channels[pos]
        self._hide_channels()
        self.selection = selection
        self._describe(selection)
        try:
            self.getControl(ROW_BASE + selection[0]).selectItem(selection[1])
            self._return_focus = ROW_BASE + selection[0]
        except Exception:
            pass
        key = (selection, event['id'])
        if key != self.stream_key:
            self._stop_preview(keep_view=True)
            self._request_streams(key, event, '')

    # ---- input -----------------------------------------------------------
    def _open_event(self, native=False):
        selection = self._selected()
        if selection is None:
            return
        event = self._event(selection)
        if not event.get('live'):
            xbmcgui.Dialog().notification('Sports', 'Not live yet. Streams appear when the event starts.', time=3000)
            return
        key = (selection, event['id'])
        target = 'native' if native else 'full'
        if key == self.stream_key and self.player.owns():
            self._native() if native else self._fullscreen()
        elif key == self.stream_key and self.player.token and not self.player.dropped:
            self.after_ready = target
        elif key == self.stream_key and self.streams:
            self._play(max(0, self.playing_index), after=target)
        else:
            self.selection = selection
            self._request_streams(key, event, target)

    def onClick(self, cid):
        if cid == FULL_BUTTON:
            self._show_channels()     # OK on the enlarged video: live channels
            return
        if cid == CHANNEL_LIST:
            self._switch_channel()
            return
        if cid == 108:
            self.outcome = 'hub'      # the only way out of Sports
            self.close()
        elif cid == 101:
            self._stop_preview()
            if self.rows:
                self.getControl(ROW_BASE).selectItem(0)
                self.setFocusId(ROW_BASE)
        elif cid == 107:
            self._stop_preview()
            from .settings import run
            self.over(run)   # Sports stays visible behind the glass settings
        elif cid == STREAM_LIST:
            index = self.getControl(STREAM_LIST).getSelectedPosition()
            if index == self.playing_index and self.player.owns():
                self._fullscreen()     # OK on the stream that plays: enlarge
            elif index == self.playing_index and self.player.token and not self.player.dropped:
                self.after_ready = 'full'
            else:
                self._play(index)
        elif ROW_BASE <= cid < ROW_BASE + len(self.rows):
            self._open_event()

    def onAction(self, action):
        aid = action.getId()
        if aid in BACK:
            # Back / Esc never leave Sports: channels -> enlarged -> small -> HUB button.
            if self.getProperty('nuvio.sport.channels') == '1':
                self._hide_channels()
            elif self.getProperty('nuvio.sport.full') == '1':
                self._small()
            else:
                self.setFocusId(108)
            return
        if aid in CONTEXT:
            # Hold OK: Kodi's own full-screen player.
            cid = self.getFocusId()
            if cid in (FULL_BUTTON, CHANNEL_LIST, STREAM_LIST):
                self._native()
            elif ROW_BASE <= cid < ROW_BASE + len(self.rows):
                self._open_event(native=True)

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
    try:
        sports.ensure_enabled()
    except Exception:
        xbmc.log('[MegaNexus] Sports add-on switches not checked.', xbmc.LOGWARNING)
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
