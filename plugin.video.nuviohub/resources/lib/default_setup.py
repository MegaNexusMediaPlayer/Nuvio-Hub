"""Out-of-the-box setup: Cinemeta metadata and catalogs plus default collections.

Nuvio never blocks on setup. Rules (checked on every Nuvio entry, cheap):

* Collections the user imported, chose or edited always win (``auto`` layout
  mode cleared by any non-automatic save).
* Otherwise, when an added add-on offers movie/series catalogs, Home is laid
  out from those catalogs; when none does, from Cinemeta.
* Cinemeta is always installed (6.0.23). It is switched ON for metadata only
  while the user has no other metadata add-on. If Cinemeta was switched on
  automatically, adding another metadata add-on switches it OFF again. When
  the user already has their own add-ons, Cinemeta is added OFF. It always
  stays in the Metadata add-ons list to be switched on or off by hand.

The numb3rs collection set (resources/collections.json) is an optional choice;
it needs AIOMetadata configured as described at NUMB3RS_URL.
"""
import hashlib
import json
import os
import time

CINEMETA_URL = 'https://v3-cinemeta.strem.io/manifest.json'
CINEMETA_ID = 'com.linvo.cinemeta'
NUMB3RS_URL = 'https://numb3rs.stream'
NUMB3RS_ADDON_ID = 'aio-metadata'
MEDIA = 'resources/media/collections/'

# (title, cover) - genres Cinemeta offers for movies and series, with our art.
GENRES = (('Action', 'action'), ('Animation', 'animation'), ('Comedy', 'comedy'), ('Crime', 'crime'),
          ('Documentary', 'documentary'), ('Drama', 'drama'), ('Family', 'family'), ('Fantasy', 'fantasy'),
          ('History', 'history'), ('Horror', 'horror'), ('Mystery', 'mystery'), ('Romance', 'romance'),
          ('Thriller', 'thriller'), ('Western', 'western'))

AUTO_LAYOUT = 'nuvio_auto_layout'          # '', 'cinemeta' or 'catalogs'
AUTO_LAYOUT_KEY = 'nuvio_auto_layout_key'  # providers the catalog layout was built from
CINEMETA_AUTO = 'nuvio_cinemeta_auto'      # 'true' while Cinemeta was switched on automatically
MAX_AUTO_FOLDERS = 30

NUMB3RS_HELP = (
    'The numb3rs collections use catalogs from AIOMetadata set up the numb3rs way.\n\n'
    '1. Open ' + NUMB3RS_URL + ' on a phone or PC and follow its AIOMetadata setup.\n'
    '2. Copy your AIOMetadata manifest URL (it ends with /manifest.json).\n'
    '3. HUB Settings > Add-ons > Add configured manifest URL, then switch it ON\n'
    '   under Metadata add-ons.\n\n'
    'Until then those collections stay empty; Cinemeta keeps working. You can also\n'
    'set collections up in Nuvio web and import them from your Nuvio account.')


def _both(catalog_id, genre='None', **extra):
    return [{'addonId': CINEMETA_ID, 'catalogId': catalog_id, 'type': kind, 'genre': genre, 'extra': dict(extra)}
            for kind in ('movie', 'series')]


def cinemeta_collections(year=None):
    """Home layout built only from Cinemeta catalogs (no account, no setup)."""
    year = str(year or time.localtime().tm_year)
    discover = [
        {'id': 'cinemeta.popular', 'title': 'Popular', 'sources': _both('top'),
         'cover': MEDIA + 'collections_discover_popular_cover.webp'},
        {'id': 'cinemeta.featured', 'title': 'Top Rated', 'sources': _both('imdbRating'),
         'cover': MEDIA + 'collections_discover_top-rated_cover.webp'},
        {'id': 'cinemeta.new', 'title': 'New in ' + year, 'sources': _both('year', year),
         'cover': MEDIA + 'collections_discover_trending_cover.webp'},
    ]
    genres = [{'id': 'cinemeta.genre.' + slug, 'title': title, 'sources': _both('top', title),
               'cover': MEDIA + 'collections_genres_%s_cover.webp' % slug} for title, slug in GENRES]
    return [{'id': 'cinemeta.discover', 'title': 'Discover', 'folders': discover},
            {'id': 'collections.genres', 'title': 'Genres', 'folders': genres}]


def cinemeta_provider(providers):
    return next((p for p in providers if (p.get('manifest') or {}).get('id') == CINEMETA_ID), None)


def numb3rs_ready(providers):
    return any((p.get('manifest') or {}).get('id') == NUMB3RS_ADDON_ID for p in providers)


def bundled_manifest():
    """Snapshot of the Cinemeta manifest shipped with Nuvio (works offline)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cinemeta_manifest.json')
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def install_cinemeta(timeout=8, enable=True):
    """Add Cinemeta (if missing) and switch it ON for metadata. Returns the provider.

    The live manifest is preferred; offline, the bundled snapshot is used and
    refreshed the next time the manifest is fetched."""
    from .nuviohub import store, client
    from . import metadata_providers
    provider = cinemeta_provider(store.list_providers())
    added = provider is None
    if added:
        try:
            manifest = client.get_json(CINEMETA_URL, ttl_seconds=3600, timeout_override=timeout,
                                       retry=False, rate_wait=.25)
        except Exception:
            manifest = bundled_manifest()
        if not isinstance(manifest, dict) or manifest.get('id') != CINEMETA_ID:
            raise ValueError('Cinemeta did not return its manifest.')
        provider = store.add_provider('Cinemeta', CINEMETA_URL, manifest)
    if enable and not any(p['id'] == provider['id'] for p in metadata_providers.enabled()):
        metadata_providers.set_enabled(provider['id'], True)
    elif not enable and added:
        # Installed for later use: an untouched switch list would show it ON.
        metadata_providers.set_enabled(provider['id'], False)
    return provider


def _usable(catalog):
    """A catalog Home can load without user input (no required filter/search)."""
    if catalog.get('type') not in ('movie', 'series') or not catalog.get('id'):
        return False
    if catalog.get('extraRequired'):
        return False
    return not any(isinstance(e, dict) and e.get('isRequired') for e in catalog.get('extra') or [])


def catalog_providers(providers):
    """Added add-ons (other than Cinemeta) that offer usable movie/series catalogs."""
    return [p for p in providers
            if (p.get('manifest') or {}).get('id') != CINEMETA_ID
            and any(_usable(c) for c in (p.get('manifest') or {}).get('catalogs') or [])]


def catalog_collections(providers):
    """Home layout from the user's own add-ons: one row per add-on, one card per
    catalog (movies and series of the same catalog share a card)."""
    groups = []
    for provider in providers:
        manifest = provider.get('manifest') or {}
        folders, index = [], {}
        for catalog in manifest.get('catalogs') or []:
            if not _usable(catalog):
                continue
            key = catalog['id']
            if key not in index:
                if len(folders) >= MAX_AUTO_FOLDERS:
                    continue
                index[key] = {'id': 'auto.%s.%s' % (provider['id'], key),
                              'title': str(catalog.get('name') or key), 'sources': []}
                folders.append(index[key])
            index[key]['sources'].append({'addonId': manifest.get('id') or '', 'providerId': provider['id'],
                                          'catalogId': key, 'type': catalog['type'], 'genre': 'None'})
        if folders:
            groups.append({'id': 'auto.' + provider['id'],
                           'title': str(provider.get('name') or manifest.get('name') or 'Catalogs'),
                           'folders': folders})
    return groups


def is_cinemeta_layout(groups):
    ids = {g.get('id') for g in groups}
    folders = [f.get('id', '') for g in groups for f in g.get('folders') or []]
    return ids == {'cinemeta.discover', 'collections.genres'} and all(f.startswith('cinemeta.') for f in folders)


def providers_key(providers):
    value = [(p.get('id'), (p.get('manifest') or {}).get('id'),
              [(c.get('id'), c.get('type')) for c in (p.get('manifest') or {}).get('catalogs') or []])
             for p in providers]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()[:16]


def add_cinemeta_off():
    return install_cinemeta(enable=False)


def apply_defaults(addon, providers, groups, save, install=install_cinemeta, add=add_cinemeta_off):
    """Decide the automatic layout and Cinemeta switch. Returns what changed."""
    from . import metadata_providers
    changed = []
    mode = addon.getSetting(AUTO_LAYOUT)
    if not mode and groups and is_cinemeta_layout(groups):
        mode = 'cinemeta'  # created automatically by 6.0.15, before the mode existed
    own = catalog_providers(providers)
    # Metadata: Cinemeta only while nothing else is there.
    others = [p for p in metadata_providers.candidates(providers) if (p.get('manifest') or {}).get('id') != CINEMETA_ID]
    cinemeta = cinemeta_provider(providers)
    if not others:
        if cinemeta is None or not any(p['id'] == cinemeta['id'] for p in metadata_providers.enabled(providers=providers)):
            if cinemeta is None or addon.getSetting(CINEMETA_AUTO) != 'off':
                try:
                    install()
                    addon.setSetting(CINEMETA_AUTO, 'true')
                    changed.append('cinemeta-on')
                except Exception:
                    pass
    elif cinemeta is None:
        # Own metadata add-ons exist: Cinemeta is still installed, but OFF.
        try:
            add()
            changed.append('cinemeta-added-off')
        except Exception:
            pass
    elif addon.getSetting(CINEMETA_AUTO) == 'true':
        try:
            metadata_providers.set_enabled(cinemeta['id'], False)
        except ValueError:
            pass
        addon.setSetting(CINEMETA_AUTO, '')
        changed.append('cinemeta-off')
    # Layout: user-owned collections are never replaced.
    if groups and not mode:
        return changed
    if own:
        key = providers_key(own)
        if mode != 'catalogs' or addon.getSetting(AUTO_LAYOUT_KEY) != key or not groups:
            save(catalog_collections(own), auto=True)
            addon.setSetting(AUTO_LAYOUT, 'catalogs')
            addon.setSetting(AUTO_LAYOUT_KEY, key)
            changed.append('layout-catalogs')
    elif mode != 'cinemeta' or not groups:
        save(cinemeta_collections(), auto=True)
        addon.setSetting(AUTO_LAYOUT, 'cinemeta')
        changed.append('layout-cinemeta')
    return changed
