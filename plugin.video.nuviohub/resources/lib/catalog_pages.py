"""Paged catalog jobs; exact IDs and collection filters are preserved."""
from . import backend_api

def jobs_for(params):
    from .nuviohub import store
    from .collections_home import matching_catalog
    providers = store.list_providers()
    from .metadata_providers import entries
    switches={p['id']:on for p,on in entries(providers)}
    providers=[p for p in providers if switches.get(p['id'],True)]
    specs=[]
    if params.get('collection_id'):
        from .collections_home import find_collection
        folder=find_collection(params['collection_id'])
        from .collections_home import active_sources
        specs=active_sources(folder)
    else:
        source = next((p for p in providers if p['id'] == params.get('provider_id')), None)
        if not source:
            raise ValueError('This catalog provider is not configured.')
        specs=[{'addonId':(source.get('manifest') or {}).get('id'), 'providerId': source['id'],
                'catalogId':params.get('catalog_id'),'type':params.get('media_type') or 'movie',
                'extra':{k:params[k] for k in ('genre','search','year') if params.get(k)}}]
    jobs=[]
    for spec in specs:
        match = matching_catalog(spec, providers)
        if match:
            source, catalog = match
            extra=dict(spec.get('extra') or {})
            if spec.get('genre') and spec['genre']!='None':extra['genre']=spec['genre']
            jobs.append({'provider':source,'catalog':catalog,'extra':extra,'offset':0,'done':False})
    if not jobs:raise ValueError('Enable this collection’s catalog in your metadata provider.')
    return jobs

def _page(job):
    from . import browse_cache
    extra=dict(job['extra'])
    if job['offset']:extra['skip']=job['offset']
    return browse_cache.catalog(job['provider'], job['catalog'], extra, timeout=8)


def prefetch_next(jobs):
    """Queue the next page of every unfinished source for the background
    refresher (6.0.32): "Load more" then opens from memory. Pages already
    cached are left alone; the refresher waits while the user is loading."""
    from . import browse_cache
    queued=0
    for job in jobs:
        if job['done']:continue
        extra=dict(job['extra'])
        if job['offset']:extra['skip']=job['offset']
        if browse_cache.peek(job['provider'],job['catalog'],extra,revalidate=False) is None:
            queued+=bool(browse_cache.refresh(job['provider'],job['catalog'],extra,timeout=8))
    return queued


def fetch_page(jobs,stopped=None):
    """Next page of every unfinished source, fetched concurrently.

    A failed source stays unfinished for the next "Load more"; the page fails
    only when every requested source failed.
    """
    from .home_data import media_card, _api
    active=[job for job in jobs if not job['done']]
    if stopped and stopped():return None
    results={}
    if len(active)==1:
        results[id(active[0])]=_page(active[0])
    elif active:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(4,len(active)),thread_name_prefix='NuvioPage') as pool:
            futures={id(job):pool.submit(_page,job) for job in active}
            errors=[]
            for key,future in futures.items():
                try:results[key]=future.result()
                except Exception as exc:errors.append(exc)
        if errors and len(errors)==len(active):raise errors[0]
    if stopped and stopped():return None
    p=_api();rows=[];states=[]
    for job in jobs:
        updated=dict(job)
        if job['done'] or id(job) not in results:states.append(updated);continue
        c=job['catalog']
        raw=(results[id(job)] or {}).get('metas') or []
        rows.extend(media_card(p._normalize_meta_art_urls(job['provider'],m),job['provider'],c['type'])
                    for m in raw if isinstance(m,dict) and m.get('id'))
        updated['offset']+=len(raw)
        updated['done']=not raw or not any((x.get('name') if isinstance(x,dict) else x)=='skip' for x in c.get('extra') or [])
        states.append(updated)
    return rows,states
