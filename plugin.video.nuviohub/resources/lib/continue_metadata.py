"""Enrich incomplete cloud progress without rewriting position or timestamps."""
from . import backend_api
import re


def metadata_identity(target):
    mt=str(target.get('media_type') or 'movie').lower()
    if mt in ('tv','tvshow','show','episode','anime'):mt='series'
    cid=str(target.get('imdb_id') or target.get('canonical_id') or target.get('video_id') or '').strip()
    if not cid and target.get('tmdb_id'):
        value=str(target['tmdb_id']);cid=value if value.startswith('tmdb:') else 'tmdb:'+value
    match=re.fullmatch(r'(tt\d+|tmdb:\d+)(?::\d+:\d+)?',cid)
    if match:cid=match.group(1)
    if cid.isdigit():cid='tmdb:'+cid
    return mt,cid


def _missing_title(value):
    return str(value or '').strip().lower() in ('unknown','untitled','','loading title…')

def _enrich_rows(rows):
    result=[]
    for original in rows:
        row=dict(original);target=dict(row.get('target') or {})
        mt,lookup=metadata_identity(target)
        if lookup:
            target.update(canonical_id=lookup,media_type=mt)
            row['target']=target
        if row.get('poster') and not _missing_title(row.get('title')):
            result.append(row);continue
        if lookup:
            try:
                meta=backend_api.metadata(mt,lookup)
                name=meta.get('name') or meta.get('title')
                if not _missing_title(name):row['title']=name
                row['poster']=meta.get('poster') or row.get('poster') or ''
                row['fanart']=meta.get('background') or row.get('fanart') or ''
                row['clearlogo']=meta.get('logo') or meta.get('clearlogo') or row.get('clearlogo') or ''
                row['plot']=meta.get('description') or meta.get('overview') or row.get('plot') or ''
                year=str(meta.get('year') or meta.get('releaseInfo') or '')[:4]
                row['meta_line']='  |  '.join(x for x in (year,'Series' if mt=='series' else 'Movie',row.get('subtitle')) if x)
                target.update(title=row.get('title') or '')
                row['target']=target
                key=row.get('progress_key')
                if isinstance(key,(list,tuple)) and len(key)==3:
                    from .dexhub.playback_store import update_metadata
                    update_metadata(*key,title='' if _missing_title(row.get('title')) else row['title'],
                                    poster=row['poster'],background=row['fanart'],clearlogo=row['clearlogo'])
            except Exception:
                pass
        if _missing_title(row.get('title')):
            row['title']='Saved '+('episode' if mt=='series' else 'movie')+(' · '+lookup if lookup else '')
        result.append(row)
    return result

def enrich(rows,on_update=None,should_stop=lambda:False):
    from concurrent.futures import ThreadPoolExecutor,as_completed
    result=[dict(r) for r in rows]
    pool=ThreadPoolExecutor(max_workers=2)
    tasks={pool.submit(_enrich_rows,[row]):i for i,row in enumerate(rows)}
    try:
        for task in as_completed(tasks):
            if should_stop():break
            result[tasks[task]]=task.result()[0]
            if on_update:on_update(list(result))
    finally:
        # Kodi 21 on Windows still embeds Python 3.8 (no cancel_futures kwarg).
        for task in tasks:task.cancel()
        pool.shutdown(wait=False)
    return result
