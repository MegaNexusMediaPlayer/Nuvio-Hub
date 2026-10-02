"""Immediate card data plus shared, bounded full-detail requests."""
from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
import json
import threading
import time
from resources.lib import backend_api, settings_cache, browse_cache, metadata_providers

_CACHE=OrderedDict()          # key -> (expires, meta, json bytes)
_PENDING={}
_LOCK=threading.RLock()
_BYTES=0
_GENERATION=0
_WANTED=[None,None]           # title the cursor rests on, its queued prefetch
_PREFETCH_POOL=None
META_TTL=1800
META_RAM={'ram256':32*1024*1024}   # full details in RAM, by image-cache preset
META_RAM_SMALL=12*1024*1024
PREFETCH_WAIT=.3
PREFETCH_RETRY=120
_FAILED={}


def identity(context):
    mt=context.get('media_type') or context.get('type') or 'movie'
    if mt in ('tv','show','tvshow','episode','anime'):mt='series'
    return (browse_cache.key(metadata_providers.signature(), context.get('source_provider_id') or ''),mt,
            context.get('canonical_id') or context.get('id') or '')


def seed(context,row=None):
    row=row or {};_,mt,mid=identity(context)
    art=context.get('ui_seed') or {}
    return {'id':mid,'type':mt,'name':row.get('title') or context.get('title') or mid,
            'poster':row.get('poster') or art.get('poster') or '', 'background':row.get('fanart') or row.get('landscape') or art.get('fanart') or '',
            'description':row.get('plot') or '', 'trailer':row.get('trailer') or '',
            'releaseInfo':row.get('subtitle') if str(row.get('subtitle') or '')[:4].isdigit() else ''}


def _ram_limit():
    try:mode=settings_cache.cached_addon().getSetting('nuvio_art_cache') or 'auto'
    except Exception:mode=''
    from resources.lib import ram_profile   # 6.0.39: by device memory
    return ram_profile.details(mode,META_RAM_SMALL) if mode in ('','auto') or mode.startswith('ram') else META_RAM_SMALL


def _remember(key,meta):
    """Keep full details in this pool's RAM (6.0.32: separate from catalog pages,
    so opening titles no longer pushes collections out of memory)."""
    global _BYTES
    size=len(json.dumps(meta,ensure_ascii=False,separators=(',',':'),default=str))
    limit=_ram_limit()
    if size>limit:return
    with _LOCK:
        old=_CACHE.pop(key,None)
        if old:_BYTES-=old[2]
        _CACHE[key]=(time.monotonic()+META_TTL,deepcopy(meta),size);_BYTES+=size
        while _BYTES>limit and _CACHE:
            _BYTES-=_CACHE.popitem(last=False)[1][2]


def cached(context):
    key=identity(context)
    with _LOCK:
        entry=_CACHE.get(key)
        if not entry or entry[0]<time.monotonic():
            return None
        _CACHE.move_to_end(key)
        return deepcopy(entry[1])


def _load(context,key,generation):
    disk_key=browse_cache.key('metadata', *key)
    hit=browse_cache.instance().get(disk_key,remember=False)
    if hit is not None:
        _remember(key,hit);return hit
    options={'preferred':context['source_provider_id']} if context.get('source_provider_id') else {}
    meta=backend_api.metadata(key[1],key[2],**options)
    if not meta:return None
    with _LOCK:
        if generation == _GENERATION:
            browse_cache.instance().put(disk_key, meta, ttl=META_TTL, remember=False)
            _remember(key,meta)
    return meta


def _track(key,future):
    _PENDING[key]=future
    def done(result):
        with _LOCK:
            if _PENDING.get(key) is result:_PENDING.pop(key,None)
    future.add_done_callback(done)
    return future


def request(context):
    key=identity(context)
    with _LOCK:
        hit=cached(context)
        if hit is not None:
            future=Future();future.set_result(hit);return future
        previous=_PENDING.get(key)
        if previous is not None and not previous.done():return previous
        generation=_GENERATION
        from .playback import _JOBS
        return _track(key,_JOBS.submit(lambda:_load(context,key,generation)))


def prefetch(context):
    """Details of the title under the cursor, loaded quietly before it is opened
    (6.0.32). Latest wins: a title the cursor already left is skipped. Waits
    while a catalog the user opened is loading or a video plays; an open of the
    same title shares the running request."""
    global _PREFETCH_POOL
    if not context or context.get('person'):return
    key=identity(context)
    if not key[2]:return
    with _LOCK:
        if cached(context) is not None or key in _PENDING:return
        if _WANTED[0]==key and _WANTED[1] is not None and not _WANTED[1].done():return  # already queued
        if time.monotonic()<_FAILED.get(key,0):return  # no retry storm for a title that failed
        if _PREFETCH_POOL is None:
            from concurrent.futures import ThreadPoolExecutor
            _PREFETCH_POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix='NuvioDetailsPrefetch')
        _WANTED[0]=key
        _WANTED[1]=_PREFETCH_POOL.submit(_prefetch_job,dict(context),key,_GENERATION)


def _prefetch_job(context,key,generation):
    for _ in range(100):
        if _WANTED[0]!=key or generation!=_GENERATION:return
        if not (browse_cache.foreground_busy() or browse_cache.playback_busy()):break
        time.sleep(PREFETCH_WAIT)
    else:
        return
    with _LOCK:
        if _WANTED[0]!=key or key in _PENDING or cached(context) is not None:return
        future=_track(key,Future())
    try:
        result=_load(context,key,generation)
    except Exception as exc:
        result=None;future.set_exception(exc)
    else:
        future.set_result(result)
    if result is None:
        with _LOCK:
            if len(_FAILED)>256:_FAILED.clear()
            _FAILED[key]=time.monotonic()+PREFETCH_RETRY


def clear(persistent=False):
    global _BYTES,_GENERATION
    with _LOCK:
        _GENERATION+=1;_CACHE.clear();_BYTES=0;_WANTED[0]=None;_FAILED.clear()
        if persistent:browse_cache.instance().clear()
        for future in list(_PENDING.values()):future.cancel()
        _PENDING.clear()
