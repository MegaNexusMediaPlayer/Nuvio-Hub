"""Paged catalog jobs; exact IDs and collection filters are preserved."""
from . import backend_api

def jobs_for(params):
    source=backend_api.provider('metadata')
    if not source:raise ValueError('Choose your metadata provider in Settings > Collections.')
    specs=[]
    if params.get('collection_id'):
        from .collections_home import find_collection
        folder=find_collection(params['collection_id'])
        specs=(folder or {}).get('sources') or []
    else:specs=[{'catalogId':params.get('catalog_id'),'type':params.get('media_type') or 'movie','extra':{k:params[k] for k in ('genre','search','year') if params.get(k)}}]
    jobs=[]
    for spec in specs:
        catalog=next((c for c in (source.get('manifest') or {}).get('catalogs') or [] if c.get('id')==spec.get('catalogId') and c.get('type')==spec.get('type')),None)
        if catalog:
            extra=dict(spec.get('extra') or {})
            if spec.get('genre') and spec['genre']!='None':extra['genre']=spec['genre']
            jobs.append({'provider':source,'catalog':catalog,'extra':extra,'offset':0,'done':False})
    if not jobs:raise ValueError('Enable this collection’s catalog in your metadata provider.')
    return jobs

def fetch_page(jobs,stopped=None):
    from .dexhub.client import fetch_catalog
    from .home_data import media_card
    rows=[];states=[]
    for job in jobs:
        if stopped and stopped():return None
        updated=dict(job)
        if job['done']:states.append(updated);continue
        c=job['catalog'];extra=dict(job['extra'])
        if job['offset']:extra['skip']=job['offset']
        data=fetch_catalog(job['provider'],c['type'],c['id'],extra=extra,timeout_override=8,retry=False,rate_wait=.1)
        raw=(data or {}).get('metas') or []
        rows.extend(media_card(m,job['provider'],c['type']) for m in raw if isinstance(m,dict) and m.get('id'))
        updated['offset']+=len(raw)
        updated['done']=not raw or not any((x.get('name') if isinstance(x,dict) else x)=='skip' for x in c.get('extra') or [])
        states.append(updated)
    return rows,states
