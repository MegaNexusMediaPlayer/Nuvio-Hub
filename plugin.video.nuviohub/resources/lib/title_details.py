"""Small, provider-aware models for title details. No GUI work here."""
from urllib.parse import urljoin


def number(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def episodes(meta, season=None):
    rows = [v for v in meta.get('videos') or [] if isinstance(v, dict)
            and v.get('id') and v.get('episode') is not None]
    if season is not None:
        rows = [v for v in rows if number(v.get('season'), 1) == number(season)]
    return sorted(rows, key=lambda v: number(v.get('episode'), 9999))


def seasons(meta):
    values = {number(v.get('season'), 1) for v in episodes(meta)}
    return sorted(values, key=lambda value: (value == 0, value))


def season_label(value):
    return 'Specials' if number(value) == 0 else 'Season %s' % value


def people(meta):
    extras = meta.get('app_extras') or {}
    if not isinstance(extras, dict):
        extras = {}
    result, seen = [], set()
    for key, fallback, role in (('directors', 'director', 'Director'),
                                ('cast', 'cast', 'Cast'),
                                ('writers', 'writer', 'Writer'),
                                ('producers', 'producer', 'Producer')):
        rows = extras.get(key) or meta.get(key) or meta.get(fallback) or []
        if isinstance(rows, str):
            rows = [rows]
        if not isinstance(rows, list):
            continue
        for row in rows:
            row = {'name': row} if isinstance(row, str) else row
            if not isinstance(row, dict) or not row.get('name'):
                continue
            name = str(row['name']).strip()
            credit = str(row.get('character') or row.get('role') or 'Cast') if role == 'Cast' else role
            identity = (name.casefold(), credit.casefold())
            if identity in seen:
                continue
            seen.add(identity)
            photo = row.get('photo') or row.get('thumbnail') or row.get('image') or ''
            if not photo and row.get('profile_path'):
                path = str(row['profile_path'])
                photo = path if path.startswith('http') else 'https://image.tmdb.org/t/p/w185' + path
            result.append({'name': name, 'role': credit, 'photo': photo,
                           'tmdb_id': row.get('tmdbId') or row.get('tmdb_id') or row.get('id') or '',
                           'imdb_id': row.get('imdbId') or row.get('imdb_id') or ''})
    return result[:80]


def normalize_people_art(meta, source):
    """AIOMetadata may return profile-relative photos as well as CDN URLs."""
    meta = dict(meta)
    base = source.get('base_url') or source.get('url') or ''
    credits = people(meta)
    for credit in credits:
        if credit['photo'] and base:
            credit['photo'] = urljoin(base.rstrip('/') + '/', credit['photo'])
    meta['nuvio_people'] = credits
    return meta


def _genres(meta):
    values = meta.get('genres') or meta.get('genre') or []
    if isinstance(values, str):
        values = [values]
    return {str(v.get('name') if isinstance(v, dict) else v).casefold() for v in values}


def related(meta, limit=24):
    """Prefer actual recommendations; otherwise use advertised genre catalogs.

    Never send invented catalog IDs to a provider. Existing TMDb credentials
    are optional; the configured metadata provider works without another key.
    """
    from . import backend_api, home_data
    from .dexhub.client import fetch_catalog
    mt = meta.get('type') or 'movie'
    source = backend_api.provider('metadata')
    rows = []
    extras = meta.get('app_extras') or {}
    for container in (meta, extras if isinstance(extras, dict) else {}):
        for key in ('recommendations', 'similar'):
            value = container.get(key) or []
            if isinstance(value, dict):
                value = value.get('metas') or value.get('results') or []
            if isinstance(value, list):
                rows.extend(v for v in value if isinstance(v, dict) and v.get('id'))
    if not rows:
        from . import tmdb_direct
        if tmdb_direct._api_key():
            from .plugin import extract_ids
            ids = extract_ids(meta)
            kind = 'tv' if mt == 'series' else 'movie'
            tid = ids.get('tmdb_id')
            try:
                if not tid and ids.get('imdb_id'):
                    found = tmdb_direct._request('/find/' + ids['imdb_id'], {'external_source': 'imdb_id'}, timeout=6)
                    matches = found.get(kind + '_results') or []
                    tid = matches[0]['id'] if matches else None
                if tid:
                    data = tmdb_direct._request('/%s/%s/recommendations' % (kind, tid), timeout=6)
                    for value in data.get('results') or []:
                        rows.append(dict(value, id='tmdb:%s' % value['id'], type=mt,
                                         name=value.get('title') or value.get('name'),
                                         poster=tmdb_direct._image_url(value.get('poster_path')),
                                         background=tmdb_direct._image_url(value.get('backdrop_path'), 'backdrop')))
            except Exception:
                pass  # Provider genre catalogs remain usable during TMDb outages.
    genres = _genres(meta)
    if not rows and source and genres:
        attempts = 0
        for catalog in (source.get('manifest') or {}).get('catalogs') or []:
            if catalog.get('type') != mt:
                continue
            advertised = [x for x in catalog.get('extra') or [] if isinstance(x, dict)]
            if any(x.get('isRequired') and x.get('name') != 'genre' for x in advertised):
                continue
            genre_spec = next((x for x in advertised if x.get('name') == 'genre'), None)
            if not genre_spec:
                continue
            options = genre_spec.get('options') or sorted(genres)
            match = next((x for x in options if str(x).casefold() in genres), None)
            if not match:
                continue
            attempts += 1
            try:
                data = fetch_catalog(source, mt, catalog['id'], extra={'genre': match}, timeout_override=6)
                rows.extend(v for v in (data or {}).get('metas') or [] if isinstance(v, dict))
            except Exception:
                pass
            if len(rows) >= limit or attempts >= 2:
                break
        rows.sort(key=lambda value: len(genres & _genres(value)), reverse=True)
    result, seen = [], {(mt, str(meta.get('id')))}
    for row in rows:
        row_type = row.get('type') or mt
        identity = (row_type, str(row.get('id') or ''))
        if not row.get('id') or identity in seen or row_type != mt:
            continue
        seen.add(identity)
        result.append(home_data.media_card(row, source, mt))
        if len(result) >= limit:
            break
    return result


_PERSON_CACHE = {}


def _provider_person_titles(person, source):
    """AIOMetadata advertises dedicated people catalogs using its own keys."""
    if not source:return []
    from .dexhub.client import fetch_catalog
    from . import home_data
    from concurrent.futures import ThreadPoolExecutor
    catalogs=[]
    for mt in ('movie','series'):
        match=next((c for c in (source.get('manifest') or {}).get('catalogs') or []
                    if c.get('type')==mt and ('people_search' in c.get('id','') or 'people.search' in c.get('id',''))
                    and any(e.get('name')=='search' for e in c.get('extra') or [] if isinstance(e,dict))),None)
        if match:catalogs.append(match)
    def fetch(catalog):
        try:
            data=fetch_catalog(source,catalog['type'],catalog['id'],extra={'search':person['name']},timeout_override=6)
            return [(row,catalog['type']) for row in (data or {}).get('metas') or [] if isinstance(row,dict) and row.get('id')]
        except Exception:return []
    result=[];seen=set()
    if catalogs:
        with ThreadPoolExecutor(max_workers=2) as pool:
            for values in pool.map(fetch,catalogs):
                for row,mt in values:
                    identity=(mt,row['id'])
                    if identity in seen:continue
                    seen.add(identity);result.append(home_data.media_card(row,source,mt))
    return result


def person_titles(person):
    """Combined cast and crew credits, including both movies and TV series."""
    from . import tmdb_direct, home_data, backend_api
    import time
    source=backend_api.provider('metadata')
    key=(str((source or {}).get('id') or ''),str(person.get('tmdb_id') or ''),person.get('name') or '')
    cached=_PERSON_CACHE.get(key)
    if cached and time.monotonic()-cached[0]<3600:return cached[1]
    if not tmdb_direct._api_key():
        result=_provider_person_titles(person,source)
        if result:
            _PERSON_CACHE[key]=(time.monotonic(),result)
            while len(_PERSON_CACHE)>24:_PERSON_CACHE.pop(next(iter(_PERSON_CACHE)))
            return result
    pid=str(person.get('tmdb_id') or '')
    if not pid.isdigit():
        data=tmdb_direct._request('/search/person',{'query':person['name']},timeout=6)
        results=data.get('results') or []
        exact=[p for p in results if str(p.get('name') or '').casefold()==person['name'].casefold()]
        if not exact:return []
        pid=str(max(exact,key=lambda p:float(p.get('popularity') or 0))['id'])
    data=tmdb_direct._request('/person/%s/combined_credits'%pid,timeout=6)
    values=(data.get('cast') or [])+(data.get('crew') or [])
    values.sort(key=lambda r:float(r.get('popularity') or 0),reverse=True)
    result=[];seen=set()
    for row in values:
        if row.get('media_type') not in ('movie','tv') or not row.get('id'):continue
        mt='series' if row['media_type']=='tv' else 'movie'
        identity=(mt,row['id'])
        if identity in seen:continue
        seen.add(identity)
        meta=dict(row,id='tmdb:%s'%row['id'],type=mt,name=row.get('title') or row.get('name'),
                  poster=tmdb_direct._image_url(row.get('poster_path')),
                  background=tmdb_direct._image_url(row.get('backdrop_path'),'backdrop'),description=row.get('overview') or '')
        result.append(home_data.media_card(meta,source,mt))
    _PERSON_CACHE[key]=(time.monotonic(),result)
    while len(_PERSON_CACHE)>24:_PERSON_CACHE.pop(next(iter(_PERSON_CACHE)))
    return result


def next_episode(meta, video_id):
    from datetime import datetime,timezone
    rows=sorted(episodes(meta),key=lambda e:(number(e.get('season'),1)==0,number(e.get('season'),1),number(e.get('episode'))))
    index=next((i for i,e in enumerate(rows) if e['id']==video_id),None)
    if index is None:return None
    for row in rows[index+1:]:
        if number(row.get('season'),1)==0:continue
        release=str(row.get('released') or row.get('first_aired') or '')
        if release and release[:10]>datetime.now(timezone.utc).date().isoformat():return None
        return dict(media_type='series',canonical_id=meta['id'],video_id=row['id'],
                    season=number(row.get('season'),1),episode=number(row.get('episode')),
                    title=meta.get('name') or meta.get('title') or '')
    return None


def episode_description(episode):
    """Read all provider synopsis fields without substituting a broader plot."""
    for source in (episode,episode.get('app_extras') or {}):
        if not isinstance(source,dict):continue
        for key in ('overview','description','plot','synopsis'):
            text=source.get(key)
            if isinstance(text,str) and text.strip():return text.strip()
    return ''


def episode_plot(episode, meta=None, season_overview=''):
    own=episode_description(episode)
    if own:return own
    meta=meta or {}
    for source in meta.get('seasons') or []:
        if not isinstance(source,dict):continue
        if number(source.get('number',source.get('season_number',source.get('season'))),-1)==number(episode.get('season'),1):
            for key in ('overview','description','plot'):
                if source.get(key):return source[key]
    fetched=(meta.get('nuvio_season_overviews') or {}).get(str(number(episode.get('season'),1)))
    return season_overview or fetched or meta.get('description') or meta.get('overview') or 'No episode or season description available.'


_SEASON_CACHE={}
def season_descriptions(meta,season):
    """One season request fills absent episode summaries, with season fallback."""
    import time
    key=(str(meta.get('id') or ''),number(season))
    cached=_SEASON_CACHE.get(key)
    if cached and time.monotonic()-cached[0]<3600:return cached[1]
    from . import tmdb_direct
    from .plugin import extract_ids
    ids=extract_ids(meta);tid=ids.get('tmdb_id')
    if not tid and ids.get('imdb_id'):
        found=tmdb_direct._request('/find/'+ids['imdb_id'],{'external_source':'imdb_id'},timeout=5)
        matches=found.get('tv_results') or []
        tid=matches[0]['id'] if matches else None
    if not tid:return {}
    data=tmdb_direct._request('/tv/%s/season/%s'%(tid,number(season)),timeout=5)
    summaries={number(e.get('episode_number')):e.get('overview') or '' for e in data.get('episodes') or []}
    summaries['season']=data.get('overview') or ''
    # Providers often omit a translated summary while the original exists.
    if any(not value for key,value in summaries.items() if key!='season'):
        english=tmdb_direct._request('/tv/%s/season/%s'%(tid,number(season)),{'language':'en-US'},timeout=5)
        for episode in english.get('episodes') or []:
            num=number(episode.get('episode_number'))
            if not summaries.get(num):summaries[num]=episode.get('overview') or ''
        if not summaries['season']:summaries['season']=english.get('overview') or ''
    _SEASON_CACHE[key]=(time.monotonic(),summaries)
    while len(_SEASON_CACHE)>32:_SEASON_CACHE.pop(next(iter(_SEASON_CACHE)))
    return summaries
