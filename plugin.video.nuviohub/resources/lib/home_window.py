"""Remote-friendly Nuvio-style shelves, with cancellable background catalog loading."""
import threading
import time
import json
from concurrent.futures import ThreadPoolExecutor

import xbmc
import xbmcaddon
import xbmcgui

from . import home_data

ADDON = xbmcaddon.Addon('plugin.video.nuviohub')
BACK = {9, 10, 92, 216, 247, 257, 275, 61448, 61467}
ROW_BASE = 7000
NAV = {101: '', 102: 'movies', 103: 'series', 104: 'anime'}


def launch_command(row):
    """Only addon-owned routes are accepted from cards; provider text is never a builtin."""
    p = home_data._api()
    if row.get('target'):
        path, folder = p._content_click_path(**row['target'])
    else:
        path, folder = row.get('path') or '', bool(row.get('is_folder'))
    if not path.startswith('plugin://') or any(c in path for c in ('\n', '\r', '"')):
        return ''
    return 'ActivateWindow(Videos,"%s",return)' % path if folder else 'RunPlugin("%s")' % path


class HomeWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super(HomeWindow, self).__init__(*args)
        self._shelves = kwargs.get('shelves') or []
        self._bucket = ''
        self._generation = 0
        self._closed = False
        self._pending = ''
        self._lock = threading.RLock()
        self._pool = None
        self._futures = []
        self._last_touch = 0
        self._focus_memory = {}
        self._previews = None

    def onInit(self):
        try:
            saved = json.loads(xbmcgui.Window(10000).getProperty('nuvio.home.focus') or '{}')
            if isinstance(saved, dict):
                self._focus_memory = saved
        except (ValueError, TypeError):
            pass
        self._paint(self._shelves)
        from .home_trailers import Controller
        self._previews = Controller(self)
        self._previews.start()

    def preview_selection(self):
        with self._lock:
            if self._closed: return None
            control_id = self.getFocusId()
            index = control_id - ROW_BASE
            if not 0 <= index < len(self._shelves): return None
            pos = self.getControl(control_id).getSelectedPosition()
            rows = self._shelves[index]['rows']
            if not 0 <= pos < len(rows) or not rows[pos].get('target'): return None
            return (self._generation, index, pos), dict(rows[pos])

    def _paint(self, shelves):
        with self._lock:
            self._generation += 1
            generation = self._generation
            for future in self._futures:
                future.cancel()
            self._futures = []
            self._shelves = shelves
            for i in range(home_data.MAX_ROWS):
                self.setProperty('nuvio.row.%d.visible' % i, '1' if i < len(shelves) else '')
                if i < len(shelves):
                    landscape = shelves[i].get('shape') == 'landscape'
                    self.setProperty('nuvio.row.%d.shape' % i, 'landscape' if landscape else 'poster')
                    self.getControl(6500 + i).setHeight(256 if landscape else 372)
                    self.getControl(ROW_BASE + i).setHeight(214 if landscape else 330)
                    self.setProperty('nuvio.row.%d.title' % i, shelves[i]['title'])
                    self._set_rows(i, shelves[i]['rows'])
            saved = self._focus_memory.get(self._bucket or 'home') or [0, 0]
            row = max(0, min(int(saved[0]), len(shelves) - 1))
            self.setProperty('nuvio.hero_row', str(row))
            self.setProperty('nuvio.tab', self._bucket or 'home')
            self.setFocusId(ROW_BASE + row)
            self.getControl(ROW_BASE + row).selectItem(min(max(0, int(saved[1])), len(shelves[row]['rows']) - 1))
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=2)
            for i, shelf in enumerate(shelves):
                if shelf.get('job') or shelf.get('collection_job'):
                    self._futures.append(self._pool.submit(self._load, i, dict(shelf), generation))
        self._touch()

    def _load(self, index, shelf, generation):
        with self._lock:
            if self._closed or generation != self._generation:
                return
        try:
            rows = home_data.load_catalog(shelf)
        except Exception:
            rows = [home_data.placeholder('Open catalog',
                'This catalog could not load right now. Select to retry in the full browser.', shelf['path'])]
        with self._lock:
            if self._closed or generation != self._generation:
                return
            self._shelves[index]['rows'] = rows
            self._set_rows(index, rows)

    def _set_rows(self, index, rows):
        control = self.getControl(ROW_BASE + index)
        try:
            position = control.getSelectedPosition()
        except Exception:
            position = 0
        items = []
        for row in rows:
            li = xbmcgui.ListItem(label=str(row.get('title') or 'Untitled'), label2=str(row.get('subtitle') or ''))
            li.setArt({key: str(row.get(key) or '') for key in ('poster', 'fanart', 'clearlogo')})
            for key in ('title', 'plot', 'meta_line', 'subtitle', 'resume_label'):
                li.setProperty(key, str(row.get(key) or ''))
            li.setProperty('shape', row.get('shape') or 'poster')
            try:
                percent = min(100, max(0, int(float(row.get('percent_value') or 0))))
            except (ValueError, TypeError, OverflowError):
                percent = 0
            li.setProperty('progress', str(percent))
            li.setProperty('has_progress', '1' if percent else '')
            items.append(li)
        control.reset()
        control.addItems(items)
        if items:
            control.selectItem(min(max(0, position), len(items) - 1))

    def _touch(self):
        now = time.monotonic()
        if now - self._last_touch > 2:
            self._last_touch = now
            xbmcgui.Window(10000).setProperty('nuviohub.interactive_busy', str(time.time()))

    def onFocus(self, control_id):
        self._touch()
        if ROW_BASE <= control_id < ROW_BASE + len(self._shelves):
            self.setProperty('nuvio.hero_row', str(control_id - ROW_BASE))

    def onAction(self, action):
        self._touch()
        if action.getId() in BACK:
            if self._bucket:
                self._bucket = ''
                self._paint(home_data.initial_shelves())
            else:
                self._finish()

    def onClick(self, control_id):
        self._touch()
        if control_id in NAV:
            self._bucket = NAV[control_id]
            self._paint(home_data.initial_shelves(self._bucket))
            return
        p = home_data._api()
        if control_id == 105:
            row = {'path': p.build_url(action='hub_search_menu'), 'is_folder': True}
        elif control_id == 106:
            row = {'path': p.build_url(action='setup_center'), 'is_folder': True}
        elif control_id == 107:
            ADDON.openSettings()
            return
        elif ROW_BASE <= control_id < ROW_BASE + len(self._shelves):
            with self._lock:
                index = control_id - ROW_BASE
                pos = self.getControl(control_id).getSelectedPosition()
                rows = self._shelves[index]['rows']
                if not 0 <= pos < len(rows):
                    return
                row = dict(rows[pos])
                self._focus_memory[self._bucket or 'home'] = [index, pos]
                xbmcgui.Window(10000).setProperty('nuvio.home.focus', json.dumps(self._focus_memory))
        else:
            return
        if row.get('collection_id'):
            from .collections_home import collection_shelves
            self._bucket = 'collection:' + row['collection_id']
            self._paint(collection_shelves(row['collection_id']))
            return
        command = launch_command(row)
        if command:
            self._pending = command
            self._finish()

    def _finish(self):
        if self._previews:
            self._previews.close()
        with self._lock:
            self._closed = True
            self._generation += 1
            if self._pool:
                self._pool.shutdown(wait=False, cancel_futures=True)
        self.close()


def open_home():
    window = HomeWindow('nuvio_home.xml', ADDON.getAddonInfo('path'), 'Default', '1080i',
                        shelves=home_data.initial_shelves())
    try:
        window.doModal()
        pending = window._pending
    finally:
        window._finish()
    if pending:
        xbmc.executebuiltin(pending)
