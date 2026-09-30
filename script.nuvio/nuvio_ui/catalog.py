from resources.lib import art_cache
from .dialog import Dialog
import xbmcaddon
import xbmcgui
from resources.lib import catalog_pages
from resources.lib import simkl_watched
from .playback import _CATALOG

class Catalog(Dialog):
    def __init__(self,*args,**kwargs):
        super().__init__(*args);self.params=kwargs['params'];self.rows=[];self.jobs=[];self.outcome='';self._initialized=False;self._selected=0;self._page_job=None;self._alive=True
    def onInit(self):
        self.setProperty('nuvio.title',self.params.get('label') or 'Browse all')
        if self._initialized:
            rows=self.rows;self.rows=[];self.getControl(500).reset();self._append(rows)
            if self.rows:self.getControl(500).selectItem(min(self._selected,len(self.rows)-1))
            self.restore_focus();return
        self._initialized=True
        if 'rows' in self.params:
            self._append(self.params['rows']);self.setFocusId(500 if self.rows else 501);return
        try:self.jobs=catalog_pages.jobs_for(self.params)
        except ValueError as exc:xbmcgui.Dialog().ok('Collections',str(exc));self.close();return
        if self.params.get('initial_rows'):
            self._append(self.params['initial_rows']);self.setFocusId(500)
        self._more()
    def _more(self):
        if self._page_job is not None:return
        if self.jobs and all(j['done'] for j in self.jobs):return
        self.getControl(501).setLabel('Loading titles…')
        self._page_job=_CATALOG.submit(lambda:catalog_pages.fetch_page(self.jobs,stopped=lambda:not self._alive))

    def tick(self):
        if not self._alive or self._page_job is None or not self._page_job.done():return
        future,self._page_job=self._page_job,None
        try:result=future.result()
        except Exception:
            self.getControl(501).setLabel('Could not load titles · Retry');return
        if result is None:return
        rows,self.jobs=result
        self._append(rows)
        if self.rows:self.setFocusId(500)

    def close(self):
        self._alive=False
        if self._page_job:self._page_job.cancel()
        super().close()

    def _append(self,rows):
        seen={(r['target']['media_type'],r['target']['canonical_id']) for r in self.rows}
        items=[]
        watched=simkl_watched.snapshot()
        wide=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_card_shape')=='landscape'
        for row in rows:
            target=row['target'];key=(target['media_type'],target['canonical_id'])
            if key in seen:continue
            seen.add(key);self.rows.append(row)
            art=(row.get('landscape') or row.get('fanart') or row.get('poster')) if wide else row.get('poster')
            item=xbmcgui.ListItem(label=row['title']);item.setArt(art_cache.art({'poster':art or ''}))
            item.setProperty('watched','1' if simkl_watched.state(watched,target['media_type'],target['canonical_id']).get('watched') else '')
            items.append(item)
        self.getControl(500).addItems(items)
        self.getControl(501).setLabel('No more titles' if all(j['done'] for j in self.jobs) else 'Load more')
        if not self.rows:self.getControl(501).setLabel('No titles found — Back')
        elif 'rows' in self.params:self.getControl(501).setLabel('Back')
    def onClick(self,cid):
        if cid==501:
            if 'rows' in self.params:self.close()
            else:self._more()
            return
        if cid==500 and self.rows:
            from .details import open_context
            self._selected=self.getControl(500).getSelectedPosition()
            self.outcome=self.child(open_context,self.rows[self._selected]['target'],row=self.rows[self._selected])
            if self.outcome=='playing' or isinstance(self.outcome,dict):self.close()
            else:
                watched=simkl_watched.snapshot()
                for i,row in enumerate(self.rows):
                    target=row['target'];entry=simkl_watched.state(watched,target['media_type'],target['canonical_id'])
                    self.getControl(500).getListItem(i).setProperty('watched','1' if entry.get('watched') else '')
    def onAction(self,action):
        if action.getId() in (9,10,92,216):self.close()
        elif action.getId() in (117,101,1009,11) and self.getFocusId()==500 and self.rows:
            from .details import context_menu
            self._selected=self.getControl(500).getSelectedPosition()
            self.outcome=self.child(context_menu,self.rows[self._selected]['target'],info=action.getId()==11,row=self.rows[self._selected])
            if self.outcome=='playing' or isinstance(self.outcome,dict):self.close()

def open_catalog(params):
    wide=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_card_shape')=='landscape'
    win=Catalog('nuvio_catalog_landscape.xml' if wide else 'nuvio_catalog.xml',xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),'Default','1080i',params=params)
    try:win.doModal();return win.outcome
    except ValueError as exc:xbmcgui.Dialog().ok('Collections',str(exc));return ''
    finally:win.close()
