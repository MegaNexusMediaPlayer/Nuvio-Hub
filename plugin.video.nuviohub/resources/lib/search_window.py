# -*- coding: utf-8 -*-
"""Cinematic, local-only renderer for Nuvio Hub search results.

The network search is completed by plugin.py before this window opens.  This
module only paints the prepared rows and therefore never starts metadata or
artwork requests while the user moves through the result rail.
"""
import xbmc
import xbmcaddon
import xbmcgui
import time

from .i18n import tr
from . import skin_theme


ADDON = xbmcaddon.Addon('plugin.video.nuviohub')
ADDON_PATH = ADDON.getAddonInfo('path')

LIST_RESULTS = 3000
BTN_ALL = 3101
BTN_MOVIES = 3102
BTN_SERIES = 3103
BTN_ANIME = 3104
BTN_SEARCH = 3200

ACTION_BACK = {9, 10, 92, 216, 247, 257, 275, 61448, 61467}


def _clean(value):
    return str(value or '').strip()


def _joined(value, limit=3):
    if isinstance(value, (list, tuple)):
        return ' / '.join(_clean(part) for part in value[:limit] if _clean(part))
    return _clean(value)


class SearchResultsWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super(SearchResultsWindow, self).__init__(*args)
        self._query = _clean(kwargs.get('query'))
        self._all_rows = [dict(row) for row in (kwargs.get('rows') or []) if isinstance(row, dict)]
        self._visible_rows = []
        self._active_filter = 'all'
        self._pending_builtin = ''
        self._closing = False
        self._last_busy_touch = 0.0

    def _touch_interactive(self):
        now = time.monotonic()
        if (now - self._last_busy_touch) < 2.0:
            return
        self._last_busy_touch = now
        try:
            xbmcgui.Window(10000).setProperty(
                'dexhub.interactive_busy', '%.3f' % time.time())
        except Exception:
            pass

    def onInit(self):
        self._touch_interactive()
        try:
            skin_theme.publish_theme(window=self)
        except Exception:
            pass
        self.setProperty('dexhub.search.query', self._query)
        self.setProperty('dexhub.search.title', tr('البحث'))
        self.setProperty('dexhub.search.all_label', tr('الكل'))
        self.setProperty('dexhub.search.movies_label', tr('الأفلام'))
        self.setProperty('dexhub.search.series_label', tr('المسلسلات'))
        self.setProperty('dexhub.search.anime_label', tr('الأنمي'))
        self.setProperty('dexhub.search.search_label', tr('بحث جديد'))
        self.setProperty('dexhub.search.result_label', tr('نتيجة'))
        self._apply_filter('all')
        try:
            self.setFocusId(LIST_RESULTS)
        except Exception:
            pass

    def _matches(self, row, name):
        media_type = _clean(row.get('media_type')).lower()
        if name == 'movies':
            return media_type == 'movie'
        if name == 'series':
            return media_type in ('series', 'tv', 'show', 'tvshow') and not bool(row.get('is_anime'))
        if name == 'anime':
            return bool(row.get('is_anime'))
        return True

    def _apply_filter(self, name):
        self._active_filter = name or 'all'
        self._visible_rows = [row for row in self._all_rows if self._matches(row, self._active_filter)]
        # An empty optional filter should not strand the user on a blank rail.
        if not self._visible_rows and self._active_filter != 'all':
            self._active_filter = 'all'
            self._visible_rows = list(self._all_rows)
        self.setProperty('dexhub.search.active_filter', self._active_filter)
        self.setProperty('dexhub.search.count', str(len(self._visible_rows)))
        try:
            control = self.getControl(LIST_RESULTS)
            control.reset()
        except Exception:
            control = None
        items = []
        for row in self._visible_rows:
            title = _clean(row.get('title'))
            year = _clean(row.get('year'))
            media_type = _clean(row.get('media_type')).lower()
            li = xbmcgui.ListItem(label=title, label2=year)
            li.setArt({
                'poster': _clean(row.get('poster')),
                'thumb': _clean(row.get('poster')),
                'fanart': _clean(row.get('fanart')),
                'landscape': _clean(row.get('landscape') or row.get('fanart')),
                'clearlogo': _clean(row.get('clearlogo')),
            })
            for key in ('title', 'year', 'media_type', 'plot', 'rating', 'genre',
                        'runtime', 'poster', 'fanart', 'landscape', 'clearlogo',
                        'path', 'is_folder', 'source_label'):
                li.setProperty(key, _clean(row.get(key)))
            li.setProperty('genre', _joined(row.get('genre')))
            li.setProperty(
                'kind', tr('فيلم') if media_type == 'movie' else tr('مسلسل'))
            items.append(li)
        if control is not None:
            try:
                control.addItems(items)
                if items:
                    control.selectItem(0)
            except Exception:
                pass
        # Hero fields bind directly to Container(3000).ListItem in the XML.
        # No Python callback or sleep is needed while the remote moves.

    def _selected_row(self):
        try:
            pos = int(self.getControl(LIST_RESULTS).getSelectedPosition())
        except Exception:
            pos = -1
        if 0 <= pos < len(self._visible_rows):
            return self._visible_rows[pos]
        return self._visible_rows[0] if self._visible_rows else {}

    def _open_selected(self):
        row = self._selected_row()
        path = _clean(row.get('path'))
        if not path:
            return
        is_folder = _clean(row.get('is_folder')).lower() in ('1', 'true', 'yes')
        if is_folder:
            self._pending_builtin = 'ActivateWindow(Videos,%s,return)' % path
        else:
            self._pending_builtin = 'RunPlugin(%s)' % path
        self._closing = True
        self.close()

    def onFocus(self, control_id):
        return

    def onClick(self, control_id):
        self._touch_interactive()
        if self._closing:
            return
        if control_id == LIST_RESULTS:
            self._open_selected()
        elif control_id == BTN_ALL:
            self._apply_filter('all')
            self.setFocusId(LIST_RESULTS)
        elif control_id == BTN_MOVIES:
            self._apply_filter('movies')
            self.setFocusId(LIST_RESULTS)
        elif control_id == BTN_SERIES:
            self._apply_filter('series')
            self.setFocusId(LIST_RESULTS)
        elif control_id == BTN_ANIME:
            self._apply_filter('anime')
            self.setFocusId(LIST_RESULTS)
        elif control_id == BTN_SEARCH:
            self._pending_builtin = 'RunPlugin(plugin://plugin.video.nuviohub/?action=hub_search_menu)'
            self._closing = True
            self.close()

    def onAction(self, action):
        self._touch_interactive()
        if self._closing:
            return
        action_id = action.getId()
        if action_id in ACTION_BACK:
            self._closing = True
            self.close()
            return

    def consume_pending_builtin(self):
        value, self._pending_builtin = self._pending_builtin, ''
        return value


def open_search_results(query, rows):
    window = SearchResultsWindow(
        'search_results.xml', ADDON_PATH, 'Default', '1080i',
        query=query, rows=rows,
    )
    window.doModal()
    builtin = window.consume_pending_builtin()
    del window
    if builtin:
        xbmc.executebuiltin(builtin)
