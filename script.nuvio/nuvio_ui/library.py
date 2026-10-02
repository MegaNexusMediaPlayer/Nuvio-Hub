"""MegaNexus Library screen (6.0.35).

Tabs: Local, the connected tracking services (named: "Trakt · Simkl"...) and
Calendar (everything by the month it was added; month and year only). Each
card has a small badge with its source (Local / Trakt / Simkl...). Opens on
the tracking tab when a service is connected, else on Local. The tracking
watchlists are refreshed in the background.
"""
import xbmcaddon
import xbmcgui
from resources.lib import art_cache, library
from resources.lib.theme import folder as theme_folder
from .dialog import Dialog, BACK

TABS = {201: 'local', 202: 'tracking', 203: 'calendar'}
ROW_BASE = 500
MAX_ROWS = 14


class LibraryWindow(Dialog):
    TOUCH_ROWS = True   # vertical drags over poster rows move between rows (touch only)
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.tab = 'tracking' if library.tracking_connected() else 'local'
        self.rows = []          # [(title, cards)]
        self.outcome = ''
        self._refresh = None
        self._refreshed = False

    def onInit(self):
        self._show()
        if self.rows:
            self.restore_focus()
        else:
            self.setFocusId({v: k for k, v in TABS.items()}[self.tab])

    def _rows_for(self, tab):
        if tab == 'calendar':
            return library.calendar(MAX_ROWS)
        movies, series = library.rows(library.LOCAL if tab == 'local' else library.TRACKING)
        return [(title, cards) for title, cards in (('Movies', movies), ('Series', series)) if cards]

    def _show(self):
        self.setProperty('nuvio.library.tab', self.tab)
        self.setProperty('nuvio.library.tracking_label', library.tracking_label())
        self.rows = self._rows_for(self.tab)[:MAX_ROWS]
        for i in range(MAX_ROWS):
            control = self.getControl(ROW_BASE + i)
            control.reset()
            self.setProperty('nuvio.library.row.%d' % i, self.rows[i][0] if i < len(self.rows) else '')
            if i < len(self.rows):
                items = []
                for card in self.rows[i][1]:
                    item = xbmcgui.ListItem(label=card['title'])
                    item.setArt(art_cache.art({'poster': card.get('poster') or ''}))
                    badges = card.get('badges') or []
                    for n in range(3):   # small pills, one under the other
                        item.setProperty('badge.%d' % n, badges[n] if n < len(badges) else '')
                    items.append(item)
                control.addItems(items)
        for i in range(len(self.rows)):
            control = self.getControl(ROW_BASE + i)
            control.controlUp(self.getControl(ROW_BASE + i - 1) if i else self.getControl(201))
            control.controlDown(self.getControl(ROW_BASE + min(i + 1, len(self.rows) - 1)))
        status = ''
        if self.tab == 'tracking' and not library.tracking_connected():
            status = 'Connect Trakt or Simkl: HUB Settings > Accounts & tracking services'
        elif self.tab in ('tracking', 'calendar') and library.tracking_connected() and not self._refreshed:
            status = 'Updating from %s…' % library.tracking_label()
            self._start_refresh()
        elif not self.rows:
            status = 'Nothing here yet. Use Title options or Details > Add to Library.'
        self.setProperty('nuvio.library.status', status)

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
        if self.tab in ('tracking', 'calendar'):
            self._show()

    def _row(self, cid):
        index = cid - ROW_BASE
        if not 0 <= index < len(self.rows):
            return None
        cards = self.rows[index][1]
        pos = self.getControl(cid).getSelectedPosition()
        return cards[pos] if 0 <= pos < len(cards) else None

    def onClick(self, cid):
        if cid in TABS:
            if TABS[cid] != self.tab:
                self.tab = TABS[cid]
                self._show()
            return
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
        row = self._row(self.getFocusId())
        if not row or aid not in (117, 101, 1009, 11):
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
