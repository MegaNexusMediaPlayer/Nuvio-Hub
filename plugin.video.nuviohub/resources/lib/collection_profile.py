"""Ordered Nuvio collection profiles and validated per-catalog metadata bindings."""
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
                extra=s.get('extra') or {}
                if not isinstance(extra,dict) or any(not isinstance(k,str) or isinstance(v,(dict,list)) for k,v in extra.items()):
                    raise ValueError('Collection filters must be an object of text values.')
                cid=s.get('catalogId') or s.get('catalog_id')
                if cid:clean.append({'addonId':s.get('addonId') or s.get('addon_id') or '',
                    'providerId':s.get('providerId') or s.get('provider_id') or '',
                    'catalogId':cid,'type':s.get('type') or s.get('catalogType') or 'movie',
                    'genre':s.get('genre') or '', 'extra':s.get('extra') or {},
                    'enabled':s.get('enabled') is not False})
            if not clean:continue
            folders.append({'id':str(f.get('id') or gid+'.'+str(len(folders))),
                'title':f.get('title') or f.get('name') or 'Collection','sources':clean,
                'cover':f.get('cover') or f.get('coverImageUrl') or f.get('background') or f.get('backgroundImageURL') or '',
                'backdrop':f.get('backdrop') or f.get('heroBackdropUrl') or '',
                'animation':f.get('animation') or f.get('focusGifUrl') or '',
                'hideTitle':bool(f.get('hideTitle')), 'hidden':bool(f.get('hidden'))})
        if folders:groups.append({'id':gid,'title':name,'folders':folders,'hidden':bool(g.get('hidden'))})
    return groups

def save(data, validation=None, auto=False):
    """Save the Home layout. Nothing is network-checked or blocked here (6.0.15):
    an unavailable catalog just stays empty on Home. ``validation`` - a report
    from Settings > Collections > Recheck - is stored for reference only.
    Any save that is not ``auto`` makes the layout the user's own, so automatic
    Cinemeta/catalog layouts never replace it."""
    groups = normalize(data)
    if not groups:
        raise ValueError('This export has no supported movie or series collections.')
    path = profile_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    from .nuviohub.safe_io import write_json
    write_json(str(path), groups)
    if isinstance(validation, dict):
        write_json(str(path.with_suffix('.verified.json')), validation)
    _LOADED.clear()  # Coarse file timestamps must not hide a same-size rewrite.
    if not auto:
        try:
            xbmcaddon.Addon(ADDON_ID).setSetting('nuvio_auto_layout', '')
        except Exception:
            pass
    return sum(len(g['folders']) for g in groups)


_LOADED={}


def load():
    """Normalized profile; parsed once per file change. Each call gets a fresh copy."""
    path=profile_file()
    try:
        stat=path.stat()
        memo=(str(path),stat.st_mtime_ns,stat.st_size)
    except OSError:
        return []
    if _LOADED.get('key')!=memo:
        try:groups=normalize(json.loads(path.read_text(encoding='utf-8-sig')))
        except (ValueError,OSError):return []
        _LOADED.clear();_LOADED.update(key=memo,text=json.dumps(groups,ensure_ascii=False))
    return json.loads(_LOADED['text'])


def defaults():
    # Presets are candidates only. They must pass validation before installation.
    root=Path(xbmcaddon.Addon(ADDON_ID).getAddonInfo('path'))
    return normalize(json.loads((root/'resources/collections.json').read_text(encoding='utf-8')))

def mapping_report():
    from .collections_home import matching_catalog
    from .nuviohub import store
    providers=store.list_providers();matched=missing=0
    for group in load():
        for folder in group['folders']:
            for source in folder['sources']:
                if matching_catalog(source,providers):matched+=1
                else:missing+=1
    return matched,missing

def sync_from_nuvio():
    from .nuviohub import nuvio_stremio_sync as sync
    if not sync.Nuvio.is_linked():raise ValueError('Sign in to Nuvio in Settings > Account first.')
    # Never upload local presets over somebody's Nuvio profile.
    remote=sync.Nuvio.sync_collections([],direction='pull')
    return save(remote)
