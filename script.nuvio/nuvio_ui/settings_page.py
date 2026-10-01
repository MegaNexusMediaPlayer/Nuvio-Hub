"""Persistent settings pages: update a value without closing or losing focus."""
from .dialog import Dialog
import xbmcaddon
import xbmcgui
from resources.lib import settings_cache
from resources.lib.theme import folder as theme_folder

DONE='nuvio:settings_done'
_STACK=[]
BACK={9,10,92,216,247,257,275,61448,61467}


def item(label,value='',enabled=None):
    row={'label':label,'value':str(value)}
    if enabled is not None:row.update(kind='toggle',enabled=bool(enabled),value='On' if enabled else 'Off')
    return row


class SettingsPage(Dialog):
    def __init__(self,*args,**kwargs):
        super().__init__(*args)
        self.title=kwargs['title'];self.rows=kwargs['rows'];self.choose=kwargs['choose']
        self.back_result=kwargs.get('back_result');self.result=None;self._busy=False;self._position=0
        self._rendered_rows=[];self._refresh_version=0

    def onInit(self):
        self.refresh(self._position);self.setFocusId(500)

    def refresh(self,position):
        settings_cache.invalidate()
        self.setProperty('nuvio.settings.title',self.title() if callable(self.title) else self.title)
        rows=self.rows();items=[]
        self._rendered_rows=rows;self._refresh_version+=1
        for row in rows:
            li=xbmcgui.ListItem(label=row['label'],label2=row.get('value',''))
            li.setProperty('kind',row.get('kind',''))
            li.setProperty('enabled','1' if row.get('enabled') else '')
            items.append(li)
        control=self.getControl(500);control.reset();control.addItems(items)
        if items:control.selectItem(max(0,min(position,len(items)-1)))

    def onClick(self,cid):
        if cid!=500 or self._busy:return
        position=self.getControl(500).getSelectedPosition()
        if not 0<=position<len(self._rendered_rows):return
        self._position=position
        revision=self._refresh_version
        self._busy=True
        def act():
            try:return self.choose(position)
            except Exception as exc:
                xbmcgui.Dialog().ok('HUB Settings',str(exc) if isinstance(exc,ValueError) else 'Could not save this change. Check the configuration and try again.')
                return None
        try:
            # A plain On/Off switch changes in place. Any other row may open Kodi
            # dialogs (select, keyboard, add-on install/settings); this page is
            # hidden meanwhile, so such a dialog can never end up BEHIND it -
            # that looked like a frozen screen until OK was pressed.
            row=self._rendered_rows[position]
            if row.get('kind')=='toggle' or row.get('label') in ('Back','Done'):command=act()
            else:command=self.child(act)
            if isinstance(command,str) and command:
                self.result=None if command==DONE else command;self.close();return
        finally:self._busy=False
        if revision==self._refresh_version:self.refresh(position)

    def onAction(self,action):
        if action.getId() in BACK and not self._busy:
            self.result=self.back_result;self.close()


def show(title,rows,choose,back_result=None):
    window=SettingsPage('nuvio_settings.xml',xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),
        theme_folder(),'1080i',title=title,rows=rows,choose=choose,back_result=back_result)
    parent=_STACK[-1] if _STACK else None
    _STACK.append(window)
    try:
        # The parent is already hidden while it runs a row action (see onClick).
        if parent and not parent._child_active:parent.child(window.doModal)
        else:window.doModal()
        return window.result
    finally:
        _STACK.pop();window.close()
