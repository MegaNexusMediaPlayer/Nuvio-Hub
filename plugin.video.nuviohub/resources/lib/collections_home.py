"""Local collection presets mapped to the user's installed Stremio providers."""
import json
import os

import xbmcaddon


def groups():
    from .collection_profile import load
    return load()


def find_collection(collection_id):
    for group in groups():
        for folder in group['folders']:
            if folder['id'] == collection_id:
                return folder
    return None


def matching_catalog(source, providers, selected=None):
    """Exact manifest/catalog/type identity; ambiguous configured variants fail closed.

    ``selected`` is retained for callers from older builds, never an ID override.
    Catalog-only add-ons may supply lists that enabled metadata add-ons resolve.
    """
    matches = []
    for provider in providers:
        manifest = provider.get('manifest') or {}
        if not source.get('addonId') or manifest.get('id') != source['addonId']:
            continue
        if source.get('providerId') and provider.get('id') != source['providerId']:
            continue
        for catalog in manifest.get('catalogs') or []:
            if catalog.get('id') == source.get('catalogId') and catalog.get('type') == source.get('type'):
                matches.append((provider, catalog))
    return matches[0] if len(matches) == 1 else None


def folder_shelf(folder, providers, media_type=None, title=None):
    from . import home_data as hd
    p = hd._api()
    jobs = []
    from .metadata_providers import entries
    switches={p['id']:on for p,on in entries(providers)}
    providers=[p for p in providers if switches.get(p['id'],True)]
    selected=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_metadata_provider')
    for source in folder['sources']:
        if media_type and source['type'] != media_type:
            continue
        match = matching_catalog(source, providers, selected)
        if match:
            provider, catalog = match
            genre = source.get('genre')
            # "None" in the Nuvio export means no filter, not the literal genre.
            extra = dict(source.get('extra') or {})
            if genre and genre != 'None':extra['genre']=genre
            jobs.append((provider, catalog, extra))
    path = p.build_url(action='nuvio_collection', collection_id=folder['id'])
    if not jobs:
        return {'title': title or folder['title'], 'rows': [hd.placeholder(
            'Connect collection catalogs', 'Validate this collection against your configured add-ons in Settings > Collections.',
            p.build_url(action='first_run_wizard'), folder=False)]}
    return {'title': title or folder['title'], 'path': path, 'collection_job': jobs,
            'rows': [hd.placeholder('Loading titles', 'Loading your collection.', path)]}


_ANIMATIONS = {}


def _built_in_animations(addon):
    path = os.path.join(addon.getAddonInfo('path'), 'resources', 'collection_animations.json')
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return {}
    if _ANIMATIONS.get('key') != (path, stamp):
        try:
            with open(path, encoding='utf-8') as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            data = {}
        _ANIMATIONS.clear()
        _ANIMATIONS.update(key=(path, stamp), data=data if isinstance(data, dict) else {})
    return _ANIMATIONS['data']


def tile_settings():
    """Read artwork settings once per Home build instead of per collection group."""
    addon = xbmcaddon.Addon('plugin.video.nuviohub')
    animated = addon.getSetting('nuvio_animated_art') == 'true'
    try:
        overrides = json.loads(addon.getSetting('nuvio_animation_map') or '{}')
    except ValueError:
        overrides = {}
    return {'animated': animated, 'built_in': _built_in_animations(addon) if animated else {},
            'overrides': overrides if isinstance(overrides, dict) else {}}


def tiles(group, settings=None):
    from .home_data import placeholder
    rows = []
    shape='poster' if group.get('id') in ('collections.genres','collections.themes') or str(group.get('title','')).lower() in ('genres','themes') else 'landscape'
    base = 'special://home/addons/script.nuvio'
    def art(value):
        if value.startswith(('http://','https://','special://')) or os.path.isabs(value):return value
        return os.path.join(base,value).replace('\\','/') if value else ''
    settings = settings or tile_settings()
    animated, built_in, overrides = settings['animated'], settings['built_in'], settings['overrides']
    for folder in group['folders']:
        if folder.get('hidden'):continue
        animation=folder.get('animation') or ''
        if animation.startswith('https://cdn.jsdelivr.net/gh/luckynumb3rs/stremio-perfect-setup/collections/') and animation.endswith('/focused/'+folder['id'].rsplit('.',1)[-1]+'.webp'):
            animation=built_in.get(folder['id']) or animation
        row = placeholder(folder['title'], 'Browse movies and series in the %s collection.' % folder['title'])
        row.update(collection_id=folder['id'], shape=shape,
                   hide_title='1' if folder.get('hideTitle') else '',
                   poster=art(folder.get('cover') or ''),
                   fanart=art(folder.get('backdrop') or folder.get('cover') or ''),
                   animation=art(overrides.get(folder['id']) or animation or built_in.get(folder['id']) or '') if animated else '')
        rows.append(row)
    return {'title': 'Streaming Services' if group['id'] == 'collections.streaming' else group['title'],
            'shape': shape, 'rows': rows}


def home_rows():
    settings=tile_settings()
    rows=[tiles(group,settings) for group in groups()]
    return [row for row in rows if row['rows']]


def collection_shelves(collection_id):
    from .nuviohub import store
    from .home_data import placeholder, _api
    folder = find_collection(collection_id)
    if not folder:
        return [{'title': 'Collection unavailable', 'rows': [placeholder('Open Setup', 'Choose another collection.', _api().build_url(action='setup_center'))]}]
    providers = store.list_providers()
    types = {s['type'] for s in folder['sources']}
    return [folder_shelf(folder, providers, mt, folder['title'] + (' — Movies' if mt == 'movie' else ' — Series'))
            for mt in ('movie', 'series') if mt in types]


def render_native(collection_id):
    """Full catalog links preserve required genre filters and native pagination."""
    from .home_data import _api
    from .nuviohub import store
    p = _api()
    folder = find_collection(collection_id)
    for source in (folder or {}).get('sources', []):
        match = matching_catalog(source, store.list_providers())
        if not match:
            continue
        provider, catalog = match
        label = '%s — %s' % (folder['title'], 'Movies' if source['type'] == 'movie' else 'Series')
        genre = source.get('genre') or ''
        p.add_item(label, p.build_url(action='catalog_all', provider_id=provider['id'], media_type=source['type'],
                   catalog_id=catalog['id'], genre='' if genre == 'None' else genre, label=label))
    p.end_dir()
