"""Trakt lists as collection sources (6.0.37), like the Nuvio apps.

A Nuvio collection source ``{"provider": "trakt", "traktListId": 123,
"mediaType": "MOVIE"|"TV", "sortBy": "rank", "sortHow": "asc", "title": ...}``
becomes a virtual catalog that Home, collections and the catalog grid load
like any add-on catalog (same cache). Public lists need no sign-in; when Trakt
is connected the request is signed, so the user's private lists work too.
Read the same way as Nuvio TV: ``lists/{id}/items/{type}`` with
``extended=full,images``, ``page``/``limit``, ``sort_by``/``sort_how``.
"""
from urllib.parse import urlencode

KIND = 'trakt'
PAGE = 50
SORTS = ('rank', 'added', 'title', 'released', 'runtime', 'popularity', 'percentage', 'votes')
PROVIDER = {'id': 'trakt-lists', 'name': 'Trakt', 'kind': KIND,
            'manifest': {'id': 'meganexus.trakt.lists', 'name': 'Trakt lists', 'version': '1',
                         'resources': ['catalog'], 'types': ['movie', 'series'], 'catalogs': []}}


def normalize(source):
    """A Nuvio export's Trakt source -> stored collection source, or None."""
    try:
        list_id = int(source.get('traktListId') or source.get('trakt_list_id') or 0)
    except (TypeError, ValueError):
        return None
    if list_id <= 0:
        return None
    media = str(source.get('mediaType') or source.get('type') or 'MOVIE').strip().lower()
    sort_by = str(source.get('sortBy') or 'rank').strip().lower()
    sort_how = str(source.get('sortHow') or 'asc').strip().lower()
    return {'provider': KIND, 'listId': list_id,
            'type': 'series' if media in ('tv', 'series', 'show', 'shows') else 'movie',
            'sortBy': sort_by if sort_by in SORTS else 'rank',
            'sortHow': sort_how if sort_how in ('asc', 'desc') else 'asc',
            'title': str(source.get('title') or ''), 'enabled': source.get('enabled') is not False}


def is_trakt(source):
    return isinstance(source, dict) and source.get('provider') == KIND and source.get('listId')


def job(source):
    """(provider, catalog, extra) for the loaders."""
    catalog = {'id': 'trakt.list.%s.%s.%s' % (source['listId'], source['sortBy'], source['sortHow']),
               'type': source['type'], 'name': source.get('title') or 'Trakt list',
               'trakt': {'list': source['listId'], 'sort_by': source['sortBy'], 'sort_how': source['sortHow']}}
    return PROVIDER, catalog, {}


def label(source):
    kind = 'Series' if source.get('type') == 'series' else 'Movies'
    return 'Trakt · %s (%s)' % (source.get('title') or 'list %s' % source.get('listId'), kind)


def _poster(node, images):
    for key in ('poster', 'thumb'):
        value = (images or {}).get(key)
        if isinstance(value, list) and value:
            value = value[0]
        if isinstance(value, str) and value:
            return value if value.startswith('http') else 'https://' + value
    imdb = str((node.get('ids') or {}).get('imdb') or '')
    return 'https://images.metahub.space/poster/medium/%s/img' % imdb if imdb.startswith('tt') else ''


def _background(images):
    value = (images or {}).get('fanart')
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, str) and value:
        return value if value.startswith('http') else 'https://' + value
    return ''


def to_meta(row, media_type):
    node = row.get('movie') if media_type == 'movie' else row.get('show')
    if not isinstance(node, dict):
        return None
    ids = node.get('ids') or {}
    imdb = str(ids.get('imdb') or '')
    if imdb.startswith('tt'):
        mid = imdb
    elif ids.get('tmdb'):
        mid = 'tmdb:%s' % ids['tmdb']
    else:
        return None
    images = node.get('images') or {}
    return {'id': mid, 'type': media_type, 'name': node.get('title') or mid,
            'poster': _poster(node, images), 'background': _background(images),
            'description': node.get('overview') or '', 'releaseInfo': str(node.get('year') or ''),
            'imdbRating': str(node.get('rating') or '') if node.get('rating') else ''}


def fetch(catalog, extra=None, timeout=8):
    """One page of a Trakt list as a Stremio catalog response {'metas': [...]}."""
    from . import trakt
    info = catalog['trakt']
    media_type = catalog.get('type') or 'movie'
    kind = 'movies' if media_type == 'movie' else 'shows'
    try:
        skip = max(0, int((extra or {}).get('skip') or 0))
    except (TypeError, ValueError):
        skip = 0
    query = {'extended': 'full,images', 'page': skip // PAGE + 1, 'limit': PAGE,
             'sort_by': info.get('sort_by') or 'rank', 'sort_how': info.get('sort_how') or 'asc'}
    path = '/lists/%s/items/%s?%s' % (info['list'], kind, urlencode(query))
    rows = trakt._request(path, method='GET', auth=trakt.authorized(), timeout=timeout) or []
    metas = [m for m in (to_meta(r, media_type) for r in rows if isinstance(r, dict)) if m]
    return {'metas': metas}
