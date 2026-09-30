"""Persistent settings pages: update a value without closing or losing focus."""
from .dialog import Dialog
import xbmcaddon
import xbmcgui
from resources.lib import settings_cache

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
        try:
            command=self.choose(position)
            if isinstance(command,str) and command:
                self.result=None if command==DONE else command;self.close();return
        except Exception as exc:
            xbmcgui.Dialog().ok('Nuvio Settings',str(exc) if isinstance(exc,ValueError) else 'Could not save this change. Check the configuration and try again.')
        finally:self._busy=False
        if revision==self._refresh_version:self.refresh(position)

    def onAction(self,action):
        if action.getId() in BACK and not self._busy:
            self.result=self.back_result;self.close()


def show(title,rows,choose,back_result=None):
    window=SettingsPage('nuvio_settings.xml',xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),
        'Default','1080i',title=title,rows=rows,choose=choose,back_result=back_result)
    parent=_STACK[-1] if _STACK else None
    _STACK.append(window)
    try:
        if parent:parent.child(window.doModal)
        else:window.doModal()
        return window.result
    finally:
        _STACK.pop();window.close()
