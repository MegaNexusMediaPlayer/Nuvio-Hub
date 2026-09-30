"""Ordered Nuvio collection profiles and one metadata binding for the whole home."""
import json
import os
from pathlib import Path
import xbmcaddon

ADDON_ID='plugin.video.nuviohub'

def profile_file():
    import xbmcvfs
    return Path(xbmcvfs.translatePath(xbmcaddon.Addon(ADDON_ID).getAddonInfo('profile')))/'nuvio_collections.json'

def normalize(data):
    if isinstance(data,dict): data=data.get('collections') or data.get('groups') or data.get('data') or []
    if not isinstance(data,list): raise ValueError('Choose a Nuvio collections JSON export.')
    groups=[]
    for g in data:
        if not isinstance(g,dict):continue
        gid=str(g.get('id') or g.get('title') or g.get('name') or '')
        name=str(g.get('title') or g.get('name') or 'Collections')
        if gid.rsplit('.',1)[-1].lower() in ('world','sports') or name.strip().lower() in ('world','sports','world & sports'):continue
        folders=[]
        for f in g.get('folders') or g.get('entries') or []:
            if not isinstance(f,dict):continue
            fid=str(f.get('id') or '')
            fname=str(f.get('title') or f.get('name') or '')
            if fid.rsplit('.',1)[-1].lower() in ('world','sports') or fname.strip().lower() in ('world','sports','world & sports'):continue
            payload=f.get('payload') or (f.get('dataSource') or {}).get('payload') or {}
            sources=f.get('catalogSources') or f.get('sources') or payload.get('sources') or ([payload] if payload.get('catalogId') else [])
            clean=[]
            for s in sources:
                if not isinstance(s,dict):continue
                cid=s.get('catalogId') or s.get('catalog_id')
                if cid:clean.append({'addonId':s.get('addonId') or s.get('addon_id') or '',
                    'catalogId':cid,'type':s.get('type') or s.get('catalogType') or 'movie',
                    'genre':s.get('genre') or '', 'extra':s.get('extra') or {}})
            if not clean:continue
            folders.append({'id':str(f.get('id') or gid+'.'+str(len(folders))),
                'title':f.get('title') or f.get('name') or 'Collection','sources':clean,
                'cover':f.get('cover') or f.get('coverImageUrl') or f.get('background') or f.get('backgroundImageURL') or '',
                'backdrop':f.get('backdrop') or f.get('heroBackdropUrl') or '',
                'animation':f.get('animation') or f.get('focusGifUrl') or '',
                'hideTitle':bool(f.get('hideTitle')), 'hidden':bool(f.get('hidden'))})
        if folders:groups.append({'id':gid,'title':name,'folders':folders})
    return groups

def save(data):
    groups=normalize(data)
    if not groups:raise ValueError('This export has no supported movie or series collections.')
    path=profile_file();path.parent.mkdir(parents=True,exist_ok=True)
    from .dexhub.safe_io import write_json
    write_json(str(path),groups)
    return sum(len(g['folders']) for g in groups)

def load():
    path=profile_file()
    if path.exists():
        try:return normalize(json.loads(path.read_text(encoding='utf-8-sig')))
        except (ValueError,OSError):pass
    return defaults()


def defaults():
    # The supplied Nuvio design is fixed until the user explicitly edits/imports it.
    root=Path(xbmcaddon.Addon(ADDON_ID).getAddonInfo('path'))
    return normalize(json.loads((root/'resources/collections.json').read_text(encoding='utf-8')))

def mapping_report():
    from .collections_home import matching_catalog
    from .dexhub import store
    providers=store.list_providers();matched=missing=0
    for group in load():
        for folder in group['folders']:
            for source in folder['sources']:
                if matching_catalog(source,providers):matched+=1
                else:missing+=1
    return matched,missing

def sync_from_nuvio():
    from .dexhub import nuvio_stremio_sync as sync
    if not sync.Nuvio.is_linked():raise ValueError('Sign in to Nuvio in Settings > Account first.')
    # Never upload local presets over somebody's Nuvio profile.
    remote=sync.Nuvio.sync_collections([],direction='pull')
    return save(remote)
