"""A person, not a mixed catalog: portrait, Movies, then Series."""
import xbmcaddon
import xbmcgui
from .dialog import Dialog
from resources.lib import art_cache
from resources.lib.display_text import clean


class Person(Dialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.page = kwargs['page']
        self.outcome = ''
        self.positions = {500: 0, 501: 0}

    def onInit(self):
        person = self.page['person']
        self.setProperty('nuvio.person.name', clean(person.get('name')))
        self.setProperty('nuvio.person.photo', art_cache.url(person.get('photo') or 'special://home/addons/script.nuvio/resources/media/person.png'))
        self.setProperty('nuvio.person.role', clean(person.get('role') or 'Filmography'))
        for cid, kind in ((500, 'movies'), (501, 'series')):
            rows = self.page[kind]
            self.setProperty('nuvio.person.' + kind, str(len(rows)))
            self.getControl(cid).reset()
            items = []
            for row in rows[:24]:
                item = xbmcgui.ListItem(label=clean(row.get('title')), label2=clean(row.get('subtitle')))
                item.setArt(art_cache.art({'poster': row.get('poster') or row.get('fanart') or ''}))
                items.append(item)
            if not items:
                items = [xbmcgui.ListItem(label='No %s returned' % kind)]
            self.getControl(cid).addItems(items)
            self.getControl(cid).selectItem(min(self.positions[cid], len(items)-1))
        self.setFocusId(500 if self.page['movies'] else 501 if self.page['series'] else 510)
        self.restore_focus()

    def onClick(self, cid):
        if cid == 510:
            self.close()
            return
        if cid in (502, 503):
            from .catalog import open_catalog
            kind = 'movies' if cid == 502 else 'series'
            rows = self.page[kind]
            if not rows:
                return
            self.outcome = self.child(open_catalog, {'label': clean(self.page['person'].get('name')) + ' · ' + kind.title(), 'rows': rows})
        elif cid in (500, 501):
            from .details import open_context
            rows = self.page['movies' if cid == 500 else 'series']
            self.positions[cid] = self.getControl(cid).getSelectedPosition()
            if not rows or self.positions[cid] >= len(rows):
                return
            row = rows[self.positions[cid]]
            self.outcome = self.child(open_context, row['target'], row=row)
        if self.outcome == 'playing' or isinstance(self.outcome, dict):
            self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 92, 216):
            self.close()


def open_page(page):
    win = Person('nuvio_person.xml', xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),
                 'Default', '1080i', page=page)
    try:
        win.doModal()
        return win.outcome
    finally:
        win.close()
