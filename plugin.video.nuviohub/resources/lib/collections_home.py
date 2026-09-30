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
    """Require the manifest identity AND catalog identity; names are not identifiers."""
    if selected is None:selected=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_metadata_provider')
    for provider in providers:
        manifest = provider.get('manifest') or {}
        if selected and provider.get('id')!=selected:
            continue
        if manifest.get('id') != source.get('addonId') and not (selected and provider.get('id')==selected):
            continue
        for catalog in manifest.get('catalogs') or []:
            if catalog.get('id') == source.get('catalogId') and catalog.get('type') == source.get('type'):
                return provider, catalog
    return None


def folder_shelf(folder, providers, media_type=None, title=None):
    from . import home_data as hd
    p = hd._api()
    jobs = []
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
            'Connect collection catalogs', 'Select the metadata provider for all collections in Settings > Collections.',
            p.build_url(action='first_run_wizard'), folder=False)]}
    return {'title': title or folder['title'], 'path': path, 'collection_job': jobs,
            'rows': [hd.placeholder('Loading titles', 'Loading your collection.', path)]}


def tiles(group):
    from .home_data import placeholder
    rows = []
    shape='poster' if group.get('id') in ('collections.genres','collections.themes') or str(group.get('title','')).lower() in ('genres','themes') else 'landscape'
    base = 'special://home/addons/script.nuvio'
    def art(value):
        if value.startswith(('http://','https://','special://')) or os.path.isabs(value):return value
        return os.path.join(base,value).replace('\\','/') if value else ''
    animated=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_animated_art')=='true'
    built_in={}
    if animated:
        try:
            with open(os.path.join(xbmcaddon.Addon('plugin.video.nuviohub').getAddonInfo('path'),'resources','collection_animations.json'),encoding='utf-8') as stream:built_in=json.load(stream)
        except (OSError,ValueError):pass
    try:overrides=json.loads(xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_animation_map') or '{}')
    except ValueError:overrides={}
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
    from .dexhub import store
    rows=[tiles(group) for group in groups()]
    return [row for row in rows if row['rows']]


def collection_shelves(collection_id):
    from .dexhub import store
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
    from .dexhub import store
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
