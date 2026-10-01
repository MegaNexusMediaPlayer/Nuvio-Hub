"""Out-of-the-box setup: Cinemeta metadata and catalogs plus default collections.

Nuvio never blocks on setup. When nothing is configured (no Nuvio import, no
metadata add-on, no collections) Cinemeta - Stremio's public metadata add-on,
which needs no account or configuration - supplies metadata and the Home
collections. The numb3rs collection set (resources/collections.json) is the
optional second choice; it needs AIOMetadata configured as described at
NUMB3RS_URL.
"""
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

NUMB3RS_HELP = (
    'The numb3rs collections use catalogs from AIOMetadata set up the numb3rs way.\n\n'
    '1. Open ' + NUMB3RS_URL + ' on a phone or PC and follow its AIOMetadata setup.\n'
    '2. Copy your AIOMetadata manifest URL (it ends with /manifest.json).\n'
    '3. Nuvio Settings > Add-ons > Add configured manifest URL, then switch it ON\n'
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


def install_cinemeta(timeout=8):
    """Add Cinemeta (if missing) and switch it ON for metadata. Returns the provider."""
    from .nuviohub import store, client
    from . import metadata_providers
    provider = cinemeta_provider(store.list_providers())
    if provider is None:
        manifest = client.get_json(CINEMETA_URL, ttl_seconds=3600, timeout_override=timeout,
                                   retry=False, rate_wait=.25)
        if not isinstance(manifest, dict) or manifest.get('id') != CINEMETA_ID:
            raise ValueError('Cinemeta did not return its manifest.')
        provider = store.add_provider('Cinemeta', CINEMETA_URL, manifest)
    if not any(p['id'] == provider['id'] for p in metadata_providers.enabled()):
        metadata_providers.set_enabled(provider['id'], True)
    return provider
