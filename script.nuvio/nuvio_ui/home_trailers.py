"""One bounded preview job, no UI-thread waits, first-frame reveal and miss cache."""
import threading
import time
import uuid
import queue
import os
from urllib.parse import unquote, urlsplit
from collections import OrderedDict
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from resources.lib.settings_cache import cached_addon
from resources.lib.trailer_support import trailer_url,selected_trailer

_CACHE=OrderedDict()

def local_path(value):
    """Kodi may report a translated/special/file URI for the same local clip."""
    if value.startswith('file://'):value=unquote(urlsplit(value).path)
    return os.path.normcase(os.path.realpath(xbmcvfs.translatePath(value))) if value else ''

class PreviewPlayer(xbmc.Player):
    def __init__(self):
        super().__init__();self.token='';self.path='';self.av_path='';self.stop_requested=False;self.cancelled=False;self.ready=False;self.failed=False
    def owns(self):
        try:
            if not self.token or not self.isPlayingVideo():return False
            if xbmcgui.Window(10000).getProperty('nuvio.preview.active')!=self.token:return False
            current=self.getPlayingFile()
            return bool(current and self.path and (current==self.av_path or local_path(current)==local_path(self.path)))
        except Exception:return False
    def onAVStarted(self):
        self.av_path=''
        self.ready=False
        if not self.token or xbmcgui.Window(10000).getProperty('nuvio.preview.active')!=self.token:return
        try:
            # The ListItem token survives Kodi's internal path substitution.
            # Read it once on AV start; never accept the Home token alone.
            if self.token and self.getPlayingItem().getProperty('nuvio.preview')==self.token:
                self.av_path=self.getPlayingFile()
        except Exception:pass
        self.ready=self.owns()
        if self.cancelled:self.stop_owned()
    def _ended(self):
        home=xbmcgui.Window(10000)
        for key in ('nuvio.preview.active','nuvio.preview.silent','nuvio.preview.pending'):
            if home.getProperty(key)==self.token:home.clearProperty(key)
    def onPlayBackStopped(self):self._ended()
    def onPlayBackEnded(self):self._ended()
    def onPlayBackError(self):self.failed=True;self._ended()
    def cancel(self):
        # Signal-only; the owner/AV callback queues an asynchronous Kodi Stop.
        self.cancelled=True
    def stop_owned(self):
        if not self.stop_requested and self.owns():
            self.stop_requested=True
            xbmc.executebuiltin('PlayerControl(Stop)')

class Controller:
    def __init__(self,window):
        self.window=window;self.stop_event=threading.Event();self.player=PreviewPlayer()
        self.job=None;self.failed_session=False;self.play_started=0;self.resolve_cancel=threading.Event()
        self.results=queue.Queue();self.previous=None;self.changed=time.monotonic();self.attempted=False;self.last_tick=0
    def start(self):pass  # The window owner calls tick; workers must never call GUI/Player APIs.
    def close(self):
        self.stop_event.set();self.resolve_cancel.set();self.player.cancel()
        self.window.setProperty('nuvio.preview','')
        self.window.setProperty('nuvio.preview.loading','')
        # Never wait for network, Player.play or a lock from a Kodi onClick handler.
    def finish(self):
        self.close();self.player.stop_owned();self._clear()
    def pause(self):
        self.resolve_cancel.set();self.player.cancel();self.player.stop_owned();self._clear()
        self.previous=None;self.changed=time.monotonic();self.attempted=False
    def _clear(self):
        self.window.setProperty('nuvio.preview','')
        self.window.setProperty('nuvio.preview.loading','')
        home=xbmcgui.Window(10000)
        # Retain the ownership token until the asynchronous Stop/AV callback.
        # A cancelled clip may still be opening; it must stop on its late AV.
        keys=('nuvio.preview.pending',) if self.player.path else ('nuvio.preview.active','nuvio.preview.silent','nuvio.preview.pending')
        for key in keys:
            if home.getProperty(key)==self.player.token:home.clearProperty(key)
    def _resolve(self,key,row,direct_only,cancelled=None):
        target=row.get('target') or {};cache_key=(target.get('media_type'),target.get('canonical_id'),direct_only)
        cached=_CACHE.get(cache_key)
        if cached and cached[0]>time.monotonic() and os.path.isfile(cached[1]):return cached[1]
        from resources.lib.trailer_cache import prepare
        selected=selected_trailer(row,direct_only=direct_only)
        url=prepare({'trailer':selected}, cancelled or self.resolve_cancel)
        # Cancelled/busy resolution is not evidence that this title lacks a trailer.
        if url:_CACHE[cache_key]=(time.monotonic()+1800,url)
        while len(_CACHE)>64:_CACHE.popitem(last=False)
        return url
    def _work(self,key,row,direct_only,token,cancelled):
        try:
            url=self._resolve(key,row,direct_only,cancelled)
        except Exception:url=''
        self.results.put((key,row,token,url))
    def tick(self):
        now=time.monotonic()
        if self.stop_event.is_set() or now-self.last_tick<.25:return
        self.last_tick=now
        addon=cached_addon();home=xbmcgui.Window(10000)
        from resources.lib.saver_state import active as screensaver_active
        if screensaver_active():
            self.pause()
            return
        def number(key,default,low,high):
            try:return min(high,max(low,float(addon.getSetting(key) or default)))
            except ValueError:return default
        enabled=addon.getSetting('nuvio_auto_trailers')=='true'
        if not enabled and not self.player.token and not self.job:return
        selection=self.window.preview_selection();key,row=selection if selection else (None,{})
        if key!=self.previous or not enabled:
            self.resolve_cancel.set()
            self.player.cancel();self.player.stop_owned();self._clear()
            self.previous=key;self.changed=now;self.attempted=False;self.play_started=0;self.failed_session=False
        while not self.results.empty():
            resolved_key,resolved_row,token,url=self.results.get_nowait()
            if home.getProperty('nuvio.preview.pending')==token:home.clearProperty('nuvio.preview.pending')
            if not enabled or not url or key!=resolved_key or self.player.cancelled or token!=self.player.token:continue
            if self.player.isPlaying():continue
            item=xbmcgui.ListItem(label='Preview: '+resolved_row.get('title',''))
            item.setProperty('nuvio.preview',token);item.setProperty('IsPlayable','true')
            home.setProperty('nuvio.preview.active',token);home.setProperty('nuvio.preview.silent',token)
            self.window.setProperty('nuvio.preview.loading','1')
            self.play_started=now;self.player.path=url;self.player.play(url,item,windowed=True)
        if self.play_started and self.player.ready and not self.player.isPlayingVideo():
            self._clear();self.play_started=0
        if not enabled or not key or self.failed_session:return
        if not self.player.cancelled and self.player.owns():
            if self.player.ready or self.player.getTime()>.15:
                self.player.ready=True;self.window.setProperty('nuvio.preview','1')
                self.window.setProperty('nuvio.preview.loading','')
            duration=number('nuvio_trailer_duration',90,0,600)
            if duration>0 and self.player.getTime()>=duration:
                self.player.cancel();self.player.stop_owned();self._clear()
        if self.player.failed or (self.play_started and not self.player.ready and now-self.play_started>20):
            self.player.cancel();self.player.stop_owned();self.failed_session=True;self._clear();return
        if self.attempted or now-self.changed<number('nuvio_trailer_delay',6,3,30):return
        if (self.job and self.job.is_alive()) or self.player.isPlaying():return
        self.attempted=True;self.play_started=0;self.player=PreviewPlayer();self.player.token=uuid.uuid4().hex
        self.resolve_cancel=threading.Event()
        token=self.player.token;home.setProperty('nuvio.preview.pending',token)
        self.job=threading.Thread(target=self._work,args=(key,dict(row),False,token,self.resolve_cancel),name='NuvioPreviewFetch',daemon=True);self.job.start()
