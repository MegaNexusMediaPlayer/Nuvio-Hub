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
        specs=(folder or {}).get('sources') or []
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

def fetch_page(jobs,stopped=None):
    from .nuviohub.client import fetch_catalog
    from .home_data import media_card
    rows=[];states=[]
    for job in jobs:
        if stopped and stopped():return None
        updated=dict(job)
        if job['done']:states.append(updated);continue
        c=job['catalog'];extra=dict(job['extra'])
        if job['offset']:extra['skip']=job['offset']
        from . import browse_cache
        data=browse_cache.catalog(job['provider'], c, extra, timeout=8)
        raw=(data or {}).get('metas') or []
        rows.extend(media_card(m,job['provider'],c['type']) for m in raw if isinstance(m,dict) and m.get('id'))
        updated['offset']+=len(raw)
        updated['done']=not raw or not any((x.get('name') if isinstance(x,dict) else x)=='skip' for x in c.get('extra') or [])
        states.append(updated)
    return rows,states
