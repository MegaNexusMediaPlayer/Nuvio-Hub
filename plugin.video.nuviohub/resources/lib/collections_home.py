"""Local collection presets mapped to the user's installed Stremio providers."""
import json
import os
import re

import xbmcaddon


def groups(include_hidden=False):
    """Collection groups; rows hidden in Settings > Collections > Home rows are
    left out of Home unless ``include_hidden``."""
    from .collection_profile import load
    return [g for g in load() if include_hidden or not g.get('hidden')]


def find_collection(collection_id):
    for group in groups(include_hidden=True):
        for folder in group['folders']:
            if folder['id'] == collection_id:
                return folder
    return None


def _norm(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').lower())


def active_sources(folder):
    """Sources switched ON in the collection editor (all sources by default)."""
    return [s for s in (folder or {}).get('sources') or [] if s.get('enabled') is not False]


SERIES_TYPES = {'series', 'tv', 'show', 'shows', 'tvshow', 'tvshows'}
MOVIE_TYPES = {'movie', 'movies', 'film', 'films'}
# Catalog IDs too general to move to another add-on by their ID alone.
GENERIC_CATALOGS = {'top', 'popular', 'trending', 'year', 'imdbrating', 'new', 'featured', 'latest', 'search'}


def kind(media_type):
    """'movie' / 'series' / the type itself - like Nuvio's catalogTypeKey."""
    value = str(media_type or '').strip().lower()
    if value in SERIES_TYPES:
        return 'series'
    if value in MOVIE_TYPES:
        return 'movie'
    return value


def _find_catalog(manifest, source):
    """Nuvio's findCollectionCatalog: same ID (also the part before a comma)
    and the same type, aliases allowed (tv = series)."""
    wanted_id = str(source.get('catalogId') or '')
    wanted_type = str(source.get('type') or '')
    catalogs = [c for c in manifest.get('catalogs') or [] if isinstance(c, dict)]
    for cid in (wanted_id, wanted_id.split(',', 1)[0]):
        found = [c for c in catalogs if c.get('id') == cid]
        exact = next((c for c in found if c.get('type') == wanted_type), None)
        if exact:
            return exact
        alike = [c for c in found if kind(c.get('type')) == kind(wanted_type)]
        if len(alike) == 1:
            return alike[0]
    return None


def _family(value):
    return {w for w in re.split(r'[^a-z0-9]+', str(value or '').lower()) if len(w) > 2}


def matching_catalog(source, providers, selected=None):
    """Resolve a collection source to one installed add-on catalog.

    The manifest ID must match (the same ID written with different separators,
    e.g. ``aio-metadata``/``aiometadata``, counts as the same ID) and that add-on
    must publish this catalog ID and type. When the same add-on is installed
    more than once, the exported ``providerId`` wins, then an enabled metadata
    add-on, then the first configured install.

    6.0.36: collections shared by other people name *their* instance of an
    add-on (another host or configuration = another manifest ID). When no
    installed add-on has that ID, the one installed add-on that publishes the
    same catalog is used (several: the most similar name/ID, then an enabled
    metadata add-on). General catalog IDs ("top", "popular"...) only move to an
    add-on with a similar name. ``selected`` is retained for older callers.
    """
    addon = source.get('addonId') or ''
    if not source.get('catalogId'):
        return None
    exact, similar = [], []
    for provider in providers:
        manifest = provider.get('manifest') or {}
        mid = manifest.get('id') or ''
        if addon and mid == addon:
            bucket = exact
        elif addon and _norm(mid) and _norm(mid) == _norm(addon):
            bucket = similar
        else:
            continue
        catalog = _find_catalog(manifest, source)
        if catalog:
            bucket.append((provider, catalog))
    matches = exact or similar
    try:
        from .metadata_providers import entries
        switches = {p['id']: on for p, on in entries(providers)}
    except Exception:
        switches = {}
    if not matches:
        wanted_family = _family(addon)
        generic = _norm(str(source.get('catalogId') or '').split(',', 1)[0]) in GENERIC_CATALOGS
        for provider in providers:
            manifest = provider.get('manifest') or {}
            catalog = _find_catalog(manifest, source)
            if not catalog:
                continue
            overlap = len(wanted_family & (_family(manifest.get('id')) | _family(manifest.get('name')) | _family(provider.get('name'))))
            if generic and not overlap:
                continue
            matches.append((overlap, provider, catalog))
        if not matches:
            return None
        matches.sort(key=lambda m: (-m[0], not switches.get(m[1].get('id'))))
        return matches[0][1], matches[0][2]
    if len(matches) == 1:
        return matches[0]
    wanted = source.get('providerId')
    for match in matches:
        if wanted and match[0].get('id') == wanted:
            return match
    return next((m for m in matches if switches.get(m[0].get('id'))), matches[0])


def folder_shelf(folder, providers, media_type=None, title=None):
    from . import home_data as hd
    p = hd._api()
    jobs = []
    from .metadata_providers import entries
    switches={p['id']:on for p,on in entries(providers)}
    providers=[p for p in providers if switches.get(p['id'],True)]
    selected=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_metadata_provider')
    for source in active_sources(folder):
        if media_type and kind(source['type']) != media_type:
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


LAYOUT_SETTING = 'nuvio_home_layout'
LAYOUTS = ('collections', 'rows')
LAYOUT_LABELS = {'collections': 'MegaNexus collections · cards that open catalogs',
                 'rows': 'Catalog rows · posters right on Home (like the Nuvio apps)'}


def layout(addon=None):
    """Home layout (6.0.35, GitHub issue #9). MegaNexus collections stay the default."""
    try:
        if addon is None:
            from .settings_cache import cached_addon
            addon = cached_addon()
        value = addon.getSetting(LAYOUT_SETTING)
    except Exception:
        value = ''
    return value if value in LAYOUTS else 'collections'


def catalog_rows(limit):
    """Nuvio-style Home: every visible catalog is a poster row - Movies and
    Series as two rows, one under the other; the rest stay reachable through a
    last row of collection cards."""
    from .nuviohub import store
    providers = store.list_providers()
    if limit <= 0:
        return []
    wanted = []   # (folder, media_type, title)
    for group in groups():
        for folder in group['folders']:
            if folder.get('hidden'):
                continue
            types = [mt for mt in ('movie', 'series') if any(kind(s.get('type')) == mt for s in active_sources(folder))]
            if len(types) == 2:
                wanted += [(folder, 'movie', folder['title'] + ' · Movies'), (folder, 'series', folder['title'] + ' · Series')]
            else:
                wanted.append((folder, types[0] if types else None, folder['title']))
    overflow = wanted[limit - 1:] if len(wanted) > limit else []
    shown = wanted[:limit - 1] if overflow else wanted
    shelves = [dict(folder_shelf(f, providers, mt, title), catalog_row=True) for f, mt, title in shown]
    if overflow:
        rest, seen = [], set()
        for folder, _, _ in overflow:
            if folder['id'] not in seen:
                seen.add(folder['id'])
                rest.append(folder)
        shelves.append(tiles({'id': 'more', 'title': 'More catalogs', 'folders': rest}))
    return shelves


def collection_shelves(collection_id):
    from .nuviohub import store
    from .home_data import placeholder, _api
    folder = find_collection(collection_id)
    if not folder:
        return [{'title': 'Collection unavailable', 'rows': [placeholder('Open Setup', 'Choose another collection.', _api().build_url(action='setup_center'))]}]
    providers = store.list_providers()
    types = {kind(s['type']) for s in active_sources(folder)}
    return [folder_shelf(folder, providers, mt, folder['title'] + (' — Movies' if mt == 'movie' else ' — Series'))
            for mt in ('movie', 'series') if mt in types]


def render_native(collection_id):
    """Full catalog links preserve required genre filters and native pagination."""
    from .home_data import _api
    from .nuviohub import store
    p = _api()
    folder = find_collection(collection_id)
    for source in active_sources(folder):
        match = matching_catalog(source, store.list_providers())
        if not match:
            continue
        provider, catalog = match
        label = '%s — %s' % (folder['title'], 'Movies' if source['type'] == 'movie' else 'Series')
        genre = source.get('genre') or ''
        p.add_item(label, p.build_url(action='catalog_all', provider_id=provider['id'], media_type=source['type'],
                   catalog_id=catalog['id'], genre='' if genre == 'None' else genre, label=label))
    p.end_dir()
