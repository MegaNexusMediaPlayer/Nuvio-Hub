"""Bounded image-byte cache. Kodi retains ownership of decoded GUI textures.

Only presentation URLs pass through this cache; provider/playback metadata never
stores loopback URLs. Four HTTP workers cap concurrent upstream downloads.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote
from urllib.request import Request, urlopen
import hashlib
import os
import threading
import time

LIMITS = {'ram150':150*1024*1024, 'disk246':246*1024*1024, 'disk512':512*1024*1024}
MAX_IMAGE = 8*1024*1024
_BASE = ('',0)
_SERVICE = None


def image_type(data):
    if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if data[:6] in (b'GIF87a',b'GIF89a'):return 'image/gif'
    if data[:4]==b'RIFF' and data[8:12]==b'WEBP':return 'image/webp'
    return ''


def fetch(url):
    if urlsplit(url).scheme not in ('http','https'):raise ValueError('Not a remote image')
    with urlopen(Request(url,headers={'User-Agent':'Nuvio/6.0'}),timeout=5) as response:
        size=int(response.headers.get('Content-Length') or 0)
        if size>MAX_IMAGE:raise ValueError('Image too large')
        data=response.read(MAX_IMAGE+1)
    if len(data)>MAX_IMAGE or not image_type(data):raise ValueError('Unsupported image')
    return data


class Cache:
    def __init__(self,folder,mode='disk246',limits=None,fetcher=fetch):
        self.folder=Path(folder);self.limits=limits or LIMITS;self.fetcher=fetcher
        self.lock=threading.RLock();self.memory=OrderedDict();self.disk=OrderedDict()
        self.bytes=0;self.mode='off';self.generation=0;self.pending={};self.misses=OrderedDict()
        self.folder.mkdir(parents=True,exist_ok=True)
        files=[]
        for path in self.folder.glob('*.img'):
            try:files.append((path.stat().st_mtime,path.name,path.stat().st_size))
            except OSError:pass
        for _,name,size in sorted(files):self.disk[name]=size
        for path in self.folder.glob('*.part'):
            try:path.unlink()
            except OSError:pass
        self.configure(mode)

    def configure(self,mode):
        with self.lock:
            mode=mode if mode in self.limits else 'off'
            if mode==self.mode:return
            self.generation+=1;self.memory.clear();self.mode=mode;self.misses.clear()
            self.bytes=sum(self.disk.values()) if mode.startswith('disk') else 0
            self._evict()

    def _evict(self):
        budget=self.limits.get(self.mode,0)
        if self.mode.startswith('disk'):
            while self.disk and self.bytes>budget:
                name,size=self.disk.popitem(last=False)
                try:(self.folder/name).unlink()
                except FileNotFoundError:pass
                self.bytes-=size
        elif self.mode.startswith('ram'):
            while self.memory and self.bytes>budget:
                _,data=self.memory.popitem(last=False);self.bytes-=len(data)

    def _read(self,key):
        if self.mode.startswith('ram'):
            data=self.memory.get(key)
            if data is not None:self.memory.move_to_end(key)
            return data
        if self.mode.startswith('disk') and key in self.disk:
            try:data=(self.folder/key).read_bytes()
            except OSError:
                self.bytes-=self.disk.pop(key);return None
            if not image_type(data):
                self.bytes-=self.disk.pop(key)
                try:(self.folder/key).unlink()
                except OSError:pass
                return None
            self.disk.move_to_end(key)
            # Persist recency without rewriting the image on every read.
            try:
                if time.time()-(self.folder/key).stat().st_mtime>60:os.utime(self.folder/key,None)
            except OSError:pass
            return data
        return None

    def get(self,url):
        key=hashlib.sha256(url.encode()).hexdigest()+'.img'
        with self.lock:
            data=self._read(key)
            if data is not None:return data
            if self.misses.get(key,0)>time.monotonic():raise ValueError('Image temporarily unavailable')
            event=self.pending.get(key)
            if event is None:
                event=threading.Event();self.pending[key]=event;owner=True
            else:owner=False
            generation=self.generation
        if not owner:
            if not event.wait(7):raise ValueError('Image busy')
            with self.lock:data=self._read(key)
            if data is None:raise ValueError('Image unavailable')
            return data
        try:
            data=self.fetcher(url)
            if len(data)>MAX_IMAGE or not image_type(data):raise ValueError('Unsupported image')
            with self.lock:
                if generation==self.generation and len(data)<=self.limits.get(self.mode,0):
                    if self.mode.startswith('ram'):self.memory[key]=data
                    elif self.mode.startswith('disk'):
                        temporary=self.folder/(key+'.part');temporary.write_bytes(data);os.replace(temporary,self.folder/key)
                        self.disk[key]=len(data)
                    self.bytes+=len(data);self._evict()
            return data
        except Exception:
            with self.lock:
                self.misses[key]=time.monotonic()+30
                while len(self.misses)>128:self.misses.popitem(last=False)
            raise
        finally:
            with self.lock:self.pending.pop(key,None);event.set()

    def clear(self):
        with self.lock:
            self.generation+=1;self.memory.clear();self.misses.clear()
            for key in list(self.disk):
                try:(self.folder/key).unlink()
                except FileNotFoundError:pass
            self.disk.clear();self.bytes=0

    def stats(self):
        with self.lock:return self.mode,self.bytes,len(self.memory if self.mode.startswith('ram') else self.disk)


class Server(HTTPServer):
    allow_reuse_address=True
    request_queue_size=16
    def __init__(self,address,cache):
        self.cache=cache;self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='NuvioArt')
        self.slots=threading.BoundedSemaphore(8)
        super().__init__(address,Handler)
    def process_request(self,request,address):
        if not self.slots.acquire(False):
            self.shutdown_request(request);return
        self.pool.submit(self._serve,request,address)
    def _serve(self,request,address):
        try:
            request.settimeout(8);self.finish_request(request,address)
        except Exception:pass
        finally:self.shutdown_request(request);self.slots.release()
    def server_close(self):
        super().server_close();self.pool.shutdown(wait=False)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass  # Image URLs may contain provider credentials.
    def do_GET(self):self._get(False)
    def do_HEAD(self):self._get(True)
    def _get(self,head):
        try:
            parsed=urlsplit(self.path)
            if parsed.path!='/image':self.send_error(404);return
            target=parse_qs(parsed.query).get('url',[''])[0]
            if len(target)>8192 or urlsplit(target).scheme not in ('http','https'):self.send_error(400);return
            data=self.server.cache.get(target)
            self.send_response(200);self.send_header('Content-Type',image_type(data))
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','public, max-age=86400');self.end_headers()
            if not head:self.wfile.write(data)
        except Exception:
            # Uncached/offline failures stay short; Kodi can retry later.
            try:self.send_error(502)
            except Exception:pass


class Service:
    def __init__(self):
        self.events=threading.Event();self.stopped=threading.Event();self.clear_requested=False
        self.server=None;self.worker=threading.Thread(target=self.run,name='NuvioArtCache',daemon=True)
        self.worker.start()
    def notify(self,method):
        if method.endswith('artcache.clear'):self.clear_requested=True
        self.events.set()
    def run(self):
        import xbmc,xbmcaddon,xbmcgui
        from .dexhub.common import profile_path
        home=xbmcgui.Window(10000);root=Path(profile_path())/'art-cache'
        try:
            cache=Cache(root,xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_art_cache') or 'disk246')
            portfile=root/'port'
            try:port=int(portfile.read_text())
            except (ValueError,OSError):port=0
            try:self.server=Server(('127.0.0.1',port),cache)
            except OSError:self.server=Server(('127.0.0.1',0),cache)
            portfile.write_text(str(self.server.server_port))
            thread=threading.Thread(target=self.server.serve_forever,name='NuvioArtHTTP',daemon=True);thread.start()
            monitor=xbmc.Monitor()
            while not self.stopped.is_set() and not monitor.abortRequested():
                mode=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_art_cache') or 'disk246'
                cache.configure(mode)
                if self.clear_requested:self.clear_requested=False;cache.clear()
                home.setProperty('nuvio.art_cache.base',('http://127.0.0.1:%d'%self.server.server_port) if mode in LIMITS else '')
                _,size,count=cache.stats()
                home.setProperty('nuvio.art_cache.usage','%.1f MB · %d images'%(size/1024/1024,count))
                self.events.wait(1);self.events.clear()
        except Exception:
            xbmc.log('[Nuvio] Image cache unavailable; using provider images directly',xbmc.LOGWARNING)
        finally:
            home.clearProperty('nuvio.art_cache.base')
            if self.server:self.server.shutdown();self.server.server_close()
    def stop(self):self.stopped.set();self.events.set()


def start():
    global _SERVICE
    if _SERVICE is None:_SERVICE=Service()


def notify(method):
    if _SERVICE:_SERVICE.notify(method)


def stop():
    if _SERVICE:_SERVICE.stop()


def url(value):
    global _BASE
    value=str(value or '')
    if not value.startswith(('http://','https://')) or '|' in value:return value
    now=time.monotonic()
    if now>=_BASE[1]:
        import xbmcgui
        _BASE=(xbmcgui.Window(10000).getProperty('nuvio.art_cache.base'),now+1)
    base=_BASE[0]
    if not base or value.startswith(base+'/'):return value
    return base+'/image?url='+quote(value,safe='')


def art(values):return {key:url(value) for key,value in values.items()}
