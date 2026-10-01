from resources.lib import art_cache
"""Rounded source selection and artwork that stays visible until AV starts."""
import queue
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

class JobPool:
    """Bounded workers which can close and reopen with Kodi's reused invoker."""
    def __init__(self,workers=2,name="NuvioLoad"):
        self.lock=threading.RLock();self.pool=None;self.pending=set();self.workers=workers;self.name=name
    def submit(self,fn):
        with self.lock:
            if self.pool is None:self.pool=ThreadPoolExecutor(max_workers=self.workers,thread_name_prefix=self.name)
            future=self.pool.submit(fn);self.pending.add(future)
            future.add_done_callback(self._done)
            return future
    def _done(self,future):
        with self.lock:self.pending.discard(future)
    def shutdown(self):
        with self.lock:
            pool=self.pool;self.pool=None;pending=list(self.pending);self.pending.clear()
        for future in pending:future.cancel()
        if pool:pool.shutdown(wait=False)

_JOBS=JobPool()
_BACKGROUND=JobPool(1,"NuvioDetailsExtras")
_CATALOG=JobPool(2,"NuvioCatalog")
import xbmc
import xbmcaddon
import xbmcgui
from resources.lib import backend_api

ROOT=xbmcaddon.Addon('script.nuvio').getAddonInfo('path')

from .source_text import plain as plain_label, normalized as normalized_source

class Loading(xbmcgui.WindowXMLDialog):
    def __init__(self,*args,**kwargs):
        super().__init__(*args);self.meta=kwargs.get('meta') or {};self.full=kwargs.get('full',False);self.label=kwargs.get('label','Loading sources');self.cancelled=False
    def onInit(self):
        xbmcgui.Window(10000).setProperty('nuvio.loading.active','1')
        self.setProperty('nuvio.full','1' if self.full else '')
        self.setProperty('nuvio.loading',self.label)
        self.setProperty('nuvio.art',art_cache.url(self.meta.get('background') or self.meta.get('poster') or ''))
        self.setProperty('nuvio.poster',art_cache.url(self.meta.get('poster') or ''))
        self.setProperty('nuvio.title',self.meta.get('name') or self.meta.get('title') or '')
    def onAction(self,action):
        if action.getId() in (9,10,92,216):self.cancelled=True
    def close(self):
        xbmcgui.Window(10000).clearProperty('nuvio.loading.active')
        super().close()

def job(fn,meta=None,full=False,label='Loading sources',cancel=None):
    win=Loading('nuvio_loading.xml',ROOT,'Default','1080i',meta=meta,full=full,label=label)
    results=queue.Queue()
    def work():
        try:results.put((True,fn()))
        except Exception as exc:results.put((False,exc))
    win.show();future=_JOBS.submit(work)
    try:
        while not win.cancelled and not xbmc.Monitor().abortRequested():
            try:
                ok,value=results.get_nowait()
                if win.cancelled or xbmc.Monitor().abortRequested():return None
                if not ok:raise value
                return value
            except queue.Empty:
                xbmc.Monitor().waitForAbort(.05)
        return None
    finally:
        if cancel is not None:cancel.set()
        future.cancel();win.close()

class Sources(xbmcgui.WindowXMLDialog):
    def __init__(self,*args,**kwargs):
        super().__init__(*args);self.rows=kwargs['rows'];self.choice=-1;self.closed=False;self.ready=False
    def onInit(self):
        items=[]
        for i,row in enumerate(self.rows):
            name=' '.join(plain_label(row.get('name')).split()) or 'Source %d'%(i+1)
            provider=plain_label((row.get('_nuvio_source') or {}).get('name') or '')
            if provider:name=provider+' · '+name
            details='  |  '.join(plain_label(row.get('title') or row.get('description')).splitlines())
            item=xbmcgui.ListItem(label=name,label2=details)
            item.setProperty('provider',provider)
            item.setProperty('size',source_size(row))
            for index,badge in enumerate(source_badges(row)):item.setProperty('badge%d'%index,badge)
            items.append(item)
        self.getControl(500).addItems(items)
        if items:self.getControl(500).selectItem(0)
        self.setFocusId(500);self.ready=True
    def close(self):
        self.closed=True;super().close()
    def onClick(self,cid):
        if cid==500:self.choice=self.getControl(500).getSelectedPosition();self.close()
    def onAction(self,action):
        if action.getId() in (9,10,92,216):self.close()

def select_source(rows):
    win=Sources('nuvio_sources.xml',ROOT,'Default','1080i',rows=rows)
    try:
        win.show();monitor=xbmc.Monitor();focused=False
        while not win.closed and not monitor.abortRequested():
            monitor.waitForAbort(.05)
            # Loading.close and Sources.show can land in the same GUI frame.
            # Apply focus after activation, when Kodi has finished closing Loading.
            if win.ready and not focused and not win.closed:
                win.setFocusId(500);focused=True
        return win.choice
    finally:win.close()


def source_size(row):
    size=(row.get('behaviorHints') or {}).get('videoSize') or row.get('size')
    try:
        size=float(size)
        if size>0:return ('%.2f GB'%(size/1_000_000_000))
    except (TypeError,ValueError):pass
    match=re.search(r'\b\d+(?:[.,]\d+)?\s*(?:GiB|GB|MiB|MB|TB)\b',str(row.get('title') or row.get('description') or ''),re.I)
    return match.group(0) if match else ''

class StartListener(xbmc.Player):
    def __init__(self,token):super().__init__();self.started=False;self.failed=False;self.token=token
    def onAVStarted(self):
        try:
            self.started=xbmcgui.Window(10000).getProperty('nuvio.playback.started')==self.token
        except Exception:pass
    def onPlayBackError(self):self.failed=True

def play(meta,context):
    auto=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_autoplay')=='true' and not context.get('force_manual')
    loading_label='Loading video…' if auto else 'Loading sources'
    result=job(lambda:backend_api.streams(meta.get('type') or 'movie',context.get('video_id') or meta['id']),meta,auto,label=loading_label)
    if result is None:return False
    source,rows=result
    if source.get('_nuvio_errors'):
        xbmcgui.Dialog().notification('Stream add-ons', '%d add-on(s) unavailable; showing available results.' % len(source['_nuvio_errors']))
    if not rows:xbmcgui.Dialog().ok('Sources','No streams matched your provider configuration.');return False
    selected=0 if auto else select_source(rows)
    if selected<0:return False
    ctx=backend_api.playback_context(meta,rows[selected],source,context.get('season',''),context.get('episode',''),context.get('video_id') or meta['id'],context.get('resume_seconds') or 0)
    ctx['resume_percent']=context.get('resume_percent') or 0
    import uuid
    token=uuid.uuid4().hex;ctx['nuvio_request_id']=token
    home=xbmcgui.Window(10000);home.clearProperty('nuvio.preview.active')
    home.clearProperty('nuvio.preview.silent')
    listener=StartListener(token)
    win=Loading('nuvio_loading.xml',ROOT,'Default','1080i',meta=meta,full=True,label='Loading video…' if auto else 'Starting playback')
    win.show()
    try:
        xbmc.executebuiltin('RunPlugin("%s")'%backend_api.queue_playback(ctx))
        deadline=time.monotonic()+60
        while not listener.started and not listener.failed and not win.cancelled and time.monotonic()<deadline:
            # The long-lived service also confirms resolver handoffs which lose item properties.
            if home.getProperty('nuvio.playback.started')==token:
                listener.started=True;break
            if xbmc.Monitor().waitForAbort(.1):break
        if listener.started:
            xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')
            return True
        home.setProperty('nuvio.cancelled.'+token,'1')
        if not win.cancelled:xbmcgui.Dialog().ok('Playback','The selected source did not start. Try another source or check your provider.')
        return False
    finally:win.close()


def source_badges(row):
    """Portable text pills replace font-dependent provider emoji badges."""
    raw=normalized_source(' '.join(str(row.get(k) or '') for k in ('name','title','description')))
    text=raw.upper(); result=[]
    for label,pattern in [('4K',r'\b(?:2160P|4K|UHD)\b'),('1080p',r'\b1080P\b'),('720p',r'\b720P\b'),
                          ('Dolby Vision',r'\b(?:DV|DOVI|DOLBY VISION)\b'),('HDR10+',r'HDR10\+'),('HDR',r'\bHDR(?:10)?\b'),
                          ('DD+',r'\b(?:DDP|DD\+|E[ .-]?AC[ .-]?3)(?![A-Z])'),('DTS',r'\bDTS\b'),('HEVC',r'\b(?:HEVC|X265|H[ .]?265)\b'),('AV1',r'\bAV1\b'),('Atmos',r'\bATMOS\b'),
                          ('Remux',r'\bREMUX\b'),('WEB-DL',r'\bWEB[ .-]?DL\b')]:
        if re.search(pattern,text):result.append(label)
    if any(c in raw for c in ('⚡','🚀')) or re.search(r'\bCACHED\b',text):result.append('Cached')
    if '🇭🇷' in raw or re.search(r'\b(?:CROATIAN|HRV|HRVATSKI)\b',text):result.append('HR')
    if '🇬🇧' in raw or '🇺🇸' in raw or re.search(r'\b(?:ENGLISH|ENG)\b',text):result.append('EN')
    return result[:8]
