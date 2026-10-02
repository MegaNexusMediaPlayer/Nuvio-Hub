"""MegaNexus Library screen (6.0.35): Local / Tracking services, Movies and Series.

Opens on Tracking services when Trakt or Simkl is connected, else on Local.
The tracking tab shows the stored watchlist mirror at once and refreshes it
in the background.
"""
import xbmcaddon
import xbmcgui
from resources.lib import art_cache, library
from resources.lib.theme import folder as theme_folder
from .dialog import Dialog, BACK

TABS = {201: 'local', 202: 'tracking'}
LISTS = (500, 501)


class LibraryWindow(Dialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.tab = 'tracking' if library.tracking_connected() else 'local'
        self.rows = {500: [], 501: []}
        self.outcome = ''
        self._refresh = None
        self._refreshed = False

    def onInit(self):
        self._show()
        if not self.rows[500] and not self.rows[501]:
            self.setFocusId(201 if self.tab == 'local' else 202)
        else:
            self.restore_focus()

    def _show(self):
        self.setProperty('nuvio.library.tab', self.tab)
        source = library.LOCAL if self.tab == 'local' else library.TRACKING
        movies, series = library.rows(source)
        self.rows = {500: movies, 501: series}
        for cid, rows in self.rows.items():
            control = self.getControl(cid)
            control.reset()
            items = []
            for row in rows:
                item = xbmcgui.ListItem(label=row['title'])
                item.setArt(art_cache.art({'poster': row.get('poster') or ''}))
                items.append(item)
            control.addItems(items)
        local = self.tab == 'local'
        self.setProperty('nuvio.library.movies_empty', '' if movies else (
            'No movies yet. Use Title options or Details > Add to Library.' if local else 'No movies on your watchlists.'))
        self.setProperty('nuvio.library.series_empty', '' if series else (
            'No series yet.' if local else 'No series on your watchlists.'))
        if not local and not library.tracking_connected():
            self.setProperty('nuvio.library.status', 'Connect Trakt or Simkl: HUB Settings > Accounts & tracking services')
        elif not local and not self._refreshed:
            self.setProperty('nuvio.library.status', 'Updating from Trakt / Simkl…')
            self._start_refresh()
        else:
            self.setProperty('nuvio.library.status', '')

    def _start_refresh(self):
        if self._refresh is not None:
            return
        from .playback import _CATALOG
        self._refresh = _CATALOG.submit(library.refresh_tracking)

    def tick(self):
        if self._refresh is None or not self._refresh.done():
            return
        future, self._refresh = self._refresh, None
        self._refreshed = True
        try:
            future.result()
        except Exception:
            pass
        if self.tab == 'tracking':
            self._show()

    def _row(self, cid):
        rows = self.rows.get(cid) or []
        pos = self.getControl(cid).getSelectedPosition()
        return rows[pos] if 0 <= pos < len(rows) else None

    def onClick(self, cid):
        if cid in TABS:
            if TABS[cid] != self.tab:
                self.tab = TABS[cid]
                self._show()
            return
        if cid in LISTS:
            row = self._row(cid)
            if not row:
                return
            from .details import open_context
            self.outcome = self.child(open_context, row['target'], row=row)
            if self.outcome == 'playing' or isinstance(self.outcome, dict):
                self.close()
            else:
                self._show()

    def onAction(self, action):
        aid = action.getId()
        if aid in BACK:
            self.close()
            return
        cid = self.getFocusId()
        if cid in LISTS and aid in (117, 101, 1009, 11):
            row = self._row(cid)
            if not row:
                return
            from .details import context_choice, quick_choice, run_choice
            choice = 'info' if aid == 11 else context_choice(row['target'], row)
            if not choice:
                return
            if quick_choice(choice, row['target'], row):
                self._show()
                return
            self.outcome = self.child(run_choice, row['target'], choice, row)
            if self.outcome == 'playing' or isinstance(self.outcome, dict):
                self.close()


def open_library():
    win = LibraryWindow('nuvio_library.xml', xbmcaddon.Addon('script.nuvio').getAddonInfo('path'), theme_folder(), '1080i')
    try:
        win.doModal()
        return win.outcome
    finally:
        win.close()
