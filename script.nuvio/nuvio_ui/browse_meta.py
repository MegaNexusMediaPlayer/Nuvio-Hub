"""Immediate card data plus shared, bounded full-detail requests."""
from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
import json
import threading
import time
from resources.lib import backend_api, settings_cache

_CACHE=OrderedDict()
_PENDING={}
_LOCK=threading.RLock()
_BYTES=0
_GENERATION=0


def identity(context):
    mt=context.get('media_type') or context.get('type') or 'movie'
    if mt in ('tv','show','tvshow','episode','anime'):mt='series'
    return (settings_cache.cached_addon().getSetting('nuvio_metadata_provider'),mt,
            context.get('canonical_id') or context.get('id') or '')


def seed(context,row=None):
    row=row or {};_,mt,mid=identity(context)
    art=context.get('ui_seed') or {}
    return {'id':mid,'type':mt,'name':row.get('title') or context.get('title') or mid,
            'poster':row.get('poster') or art.get('poster') or '', 'background':row.get('fanart') or row.get('landscape') or art.get('fanart') or '',
            'description':row.get('plot') or '', 'trailer':row.get('trailer') or '',
            'releaseInfo':row.get('subtitle') if str(row.get('subtitle') or '')[:4].isdigit() else ''}


def cached(context):
    key=identity(context)
    with _LOCK:
        entry=_CACHE.get(key)
        if not entry or entry[0]<time.monotonic():return None
        _CACHE.move_to_end(key)
        return deepcopy(entry[1])


def request(context):
    key=identity(context)
    with _LOCK:
        hit=cached(context)
        if hit is not None:
            future=Future();future.set_result(hit);return future
        previous=_PENDING.get(key)
        if previous is not None and not previous.done():return previous
        generation=_GENERATION
        def load():
            global _BYTES
            meta=backend_api.metadata(key[1],key[2])
            if not meta:return None
            size=len(json.dumps(meta,ensure_ascii=False,default=str).encode('utf-8'))
            if size<=8*1024*1024:
                with _LOCK:
                    if generation==_GENERATION:
                        old=_CACHE.pop(key,None)
                        if old:_BYTES-=old[2]
                        _CACHE[key]=(time.monotonic()+300,deepcopy(meta),size);_BYTES+=size
                        while len(_CACHE)>32 or _BYTES>8*1024*1024:
                            _,entry=_CACHE.popitem(last=False);_BYTES-=entry[2]
            return meta
        from .playback import _JOBS
        future=_JOBS.submit(load);_PENDING[key]=future
        def done(result):
            with _LOCK:
                if _PENDING.get(key) is result:_PENDING.pop(key,None)
        future.add_done_callback(done)
        return future


def clear():
    global _BYTES,_GENERATION
    with _LOCK:
        _GENERATION+=1;_CACHE.clear();_BYTES=0
        for future in list(_PENDING.values()):future.cancel()
        _PENDING.clear()
