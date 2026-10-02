"""TMDB collection sources (6.0.37), like the Nuvio apps - with the user's
own TMDb API key (HUB Settings > Add-ons > TMDb API key; v3 key or v4 token).

A Nuvio source ``{"provider": "tmdb", "tmdbSourceType": "NETWORK", "tmdbId":
213, "mediaType": "TV", "sortBy": "popularity.desc", "filters": {...}}``
becomes a virtual catalog loaded like an add-on catalog (same cache):
LIST /list/{id}, COLLECTION /collection/{id}, COMPANY / NETWORK / PERSON /
DIRECTOR / DISCOVER through /discover/{movie|tv} with Nuvio's filters.
"""
KIND = 'tmdb'
PAGE = 20     # TMDB page size
TYPES = ('LIST', 'COLLECTION', 'COMPANY', 'NETWORK', 'DISCOVER', 'PERSON', 'DIRECTOR')
IMAGE = 'https://image.tmdb.org/t/p/'
PROVIDER = {'id': 'tmdb-sources', 'name': 'TMDB', 'kind': KIND,
            'manifest': {'id': 'meganexus.tmdb.sources', 'name': 'TMDB', 'version': '1',
                         'resources': ['catalog'], 'types': ['movie', 'series'], 'catalogs': []}}
# Nuvio TmdbCollectionFilters -> TMDB discover parameters ({movie}/{tv} differ for dates).
FILTERS = {
    'withGenres': 'with_genres', 'withoutGenres': 'without_genres',
    'voteAverageGte': 'vote_average.gte', 'voteAverageLte': 'vote_average.lte', 'voteCountGte': 'vote_count.gte',
    'withOriginalLanguage': 'with_original_language', 'withOriginCountry': 'with_origin_country',
    'withKeywords': 'with_keywords', 'withoutKeywords': 'without_keywords',
    'withCompanies': 'with_companies', 'withoutCompanies': 'without_companies', 'withNetworks': 'with_networks',
    'watchRegion': 'watch_region', 'withWatchProviders': 'with_watch_providers',
    'withoutWatchProviders': 'without_watch_providers',
}
DATES = {'movie': ('primary_release_date.gte', 'primary_release_date.lte', 'primary_release_year'),
         'series': ('first_air_date.gte', 'first_air_date.lte', 'first_air_date_year')}


def has_key():
    try:
        from .tmdb_direct import _api_key
        return bool(_api_key())
    except Exception:
        return False


def normalize(source):
    kind = str(source.get('tmdbSourceType') or source.get('sourceType') or '').strip().upper()
    if kind not in TYPES:
        return None
    try:
        tmdb_id = int(source.get('tmdbId') or source.get('tmdb_id') or 0)
    except (TypeError, ValueError):
        tmdb_id = 0
    if kind != 'DISCOVER' and tmdb_id <= 0:
        return None
    media = str(source.get('mediaType') or source.get('type') or 'MOVIE').strip().lower()
    filters = source.get('filters') if isinstance(source.get('filters'), dict) else {}
    filters = {k: v for k, v in filters.items() if v not in (None, '') and not isinstance(v, (dict, list))}
    return {'provider': KIND, 'sourceType': kind, 'tmdbId': tmdb_id,
            'type': 'series' if media in ('tv', 'series', 'show', 'shows') else 'movie',
            'sortBy': str(source.get('sortBy') or 'popularity.desc'), 'filters': filters,
            'title': str(source.get('title') or ''), 'enabled': source.get('enabled') is not False}


def is_tmdb(source):
    return isinstance(source, dict) and source.get('provider') == KIND and source.get('sourceType') in TYPES


def job(source):
    key = '%s.%s.%s.%s' % (source['sourceType'].lower(), source.get('tmdbId') or 0, source['type'], source.get('sortBy') or '')
    if source.get('filters'):
        key += '.' + '.'.join('%s=%s' % kv for kv in sorted(source['filters'].items()))
    catalog = {'id': 'tmdb.' + key, 'type': source['type'], 'name': source.get('title') or 'TMDB',
               'extra': [{'name': 'skip'}], 'tmdb': dict(source)}
    return PROVIDER, catalog, {}


def label(source):
    kind = 'Series' if source.get('type') == 'series' else 'Movies'
    name = source.get('title') or '%s %s' % (source.get('sourceType', '').title(), source.get('tmdbId') or '')
    return 'TMDB · %s (%s)%s' % (name, kind, '' if has_key() else ' · needs your TMDb API key')


def _image(path, size):
    return IMAGE + size + path if path else ''


def to_meta(row, media_type):
    if not isinstance(row, dict) or not row.get('id'):
        return None
    if row.get('media_type') in ('movie', 'tv'):
        media_type = 'movie' if row['media_type'] == 'movie' else 'series'
    elif row.get('media_type'):
        return None   # people in a list
    date = row.get('release_date') or row.get('first_air_date') or ''
    return {'id': 'tmdb:%s' % row['id'], 'type': media_type, 'name': row.get('title') or row.get('name') or '',
            'poster': _image(row.get('poster_path'), 'w500'), 'background': _image(row.get('backdrop_path'), 'w1280'),
            'description': row.get('overview') or '', 'releaseInfo': str(date)[:4],
            'imdbRating': ('%.1f' % row['vote_average']) if row.get('vote_average') else ''}


def _discover_params(source):
    media = source['type']
    params = {}
    kind = source['sourceType']
    if kind == 'COMPANY':
        params['with_companies'] = source['tmdbId']
    elif kind == 'NETWORK':
        params['with_networks'] = source['tmdbId']
    elif kind == 'PERSON':
        params['with_people'] = source['tmdbId']
    elif kind == 'DIRECTOR':
        params['with_crew'] = source['tmdbId']
    for name, value in (source.get('filters') or {}).items():
        if name in FILTERS:
            params[FILTERS[name]] = value
    gte, lte, year = DATES[media]
    filters = source.get('filters') or {}
    if filters.get('releaseDateGte'):
        params[gte] = filters['releaseDateGte']
    if filters.get('releaseDateLte'):
        params[lte] = filters['releaseDateLte']
    if filters.get('year'):
        params[year] = filters['year']
    sort = source.get('sortBy') or 'popularity.desc'
    if sort != 'original':
        params['sort_by'] = sort
    return params


def fetch(catalog, extra=None, timeout=8):
    """One page as a Stremio catalog response {'metas': [...]}."""
    from .tmdb_direct import _request
    if not has_key():
        raise ValueError('Add your TMDb API key: HUB Settings > Add-ons > TMDb API key.')
    source = catalog['tmdb']
    media = source['type']
    try:
        skip = max(0, int((extra or {}).get('skip') or 0))
    except (TypeError, ValueError):
        skip = 0
    page = skip // PAGE + 1
    kind = source['sourceType']
    if kind == 'COLLECTION':
        if page > 1:
            return {'metas': []}
        data = _request('/collection/%s' % source['tmdbId'], timeout=timeout) or {}
        rows = data.get('parts') or []
        if (source.get('sortBy') or '') != 'original':
            rows = sorted(rows, key=lambda r: r.get('release_date') or '')
        return {'metas': [m for m in (to_meta(dict(r, media_type='movie'), 'movie') for r in rows) if m]}
    if kind == 'LIST':
        data = _request('/list/%s' % source['tmdbId'], {'page': page}, timeout=timeout) or {}
        rows = data.get('items') or []
        return {'metas': [m for m in (to_meta(r, media) for r in rows) if m]}
    path = '/discover/%s' % ('movie' if media == 'movie' else 'tv')
    params = dict(_discover_params(source), page=page)
    data = _request(path, params, timeout=timeout) or {}
    return {'metas': [m for m in (to_meta(r, media) for r in data.get('results') or []) if m]}
