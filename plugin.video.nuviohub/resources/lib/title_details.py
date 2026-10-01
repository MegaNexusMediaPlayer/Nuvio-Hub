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
    from .search_catalogs import person_id
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
            from .display_text import clean
            name = clean(row['name']).strip()
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
                           'tmdb_id': person_id(row),
                           'imdb_id': row.get('imdbId') or row.get('imdb_id') or '',
                           'source_provider_id': meta.get('_nuvio_metadata_provider') or ''})
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
    from .nuviohub.client import fetch_catalog
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
    """Query both film and TV credits using advertised People Search catalogs."""
    if not source:return []
    from .nuviohub.client import fetch_catalog
    from . import home_data, search_catalogs
    from concurrent.futures import ThreadPoolExecutor
    catalogs=[c for c in search_catalogs.entries(source) if search_catalogs.is_people(c)
              and c['type'] in ('movie','series','tv','anime','anime.movie','anime.series')]
    errors=[]
    def fetch(catalog):
        # People search can be slower than a cached home catalog (provider ID
        # resolution/credits/artwork). Keep it bounded, but not at six seconds.
        data=fetch_catalog(source,catalog['type'],catalog['id'],
                           extra={'search':person['name']},timeout_override=15)
        if not isinstance(data,dict) or not isinstance(data.get('metas'),list):
            raise ValueError('Metadata add-on returned an invalid filmography.')
        return [(row,catalog['type']) for row in data['metas'] if isinstance(row,dict) and row.get('id')]
    result=[];seen=set()
    if catalogs:
        with ThreadPoolExecutor(max_workers=min(4,len(catalogs))) as pool:
            futures=[pool.submit(fetch,c) for c in catalogs]
            for future in futures:
                try:values=future.result()
                except Exception:errors.append(True);continue
                for row,mt in values:
                    mt=row.get('type') or mt
                    if mt in ('person','people','actor'):continue
                    identity=(mt,str(row['id']))
                    if identity in seen:continue
                    seen.add(identity)
                    from .plugin import _normalize_meta_art_urls
                    result.append(home_data.media_card(_normalize_meta_art_urls(source,row),source,mt))
    if errors and not result:
        raise ValueError('The metadata add-on could not load this filmography. Check its connection and retry.')
    return result


def person_titles(person):
    """Use provider credits first, with optional authenticated TMDb fallback."""
    from . import tmdb_direct, home_data, backend_api, search_catalogs
    import time
    name=str(person.get('name') or '').strip()
    if not name:raise ValueError('This cast entry has no actor name.')
    from . import metadata_providers
    sources=metadata_providers.enabled(preferred=person.get('source_provider_id') or '')
    source=sources[0] if sources else None
    catalogs=tuple((c['type'],c['id']) for c in search_catalogs.entries(source))
    key=(metadata_providers.signature(),search_catalogs.person_id(person),name,catalogs)
    cached=_PERSON_CACHE.get(key)
    if cached and time.monotonic()-cached[0]<3600:return cached[1]
    result=[];provider_error=None
    exact_tmdb=bool(search_catalogs.person_id(person) and tmdb_direct._api_key())
    if not exact_tmdb:
        for candidate in sources:
            try:result.extend(_provider_person_titles(dict(person,name=name),candidate))
            except ValueError as exc:provider_error=exc
    if not result and tmdb_direct._api_key():
        pid=search_catalogs.person_id(person)
        if not pid and person.get('imdb_id'):
            found=tmdb_direct._request('/find/'+str(person['imdb_id']),{'external_source':'imdb_id'},timeout=10)
            matches=found.get('person_results') or []
            if matches:pid=str(matches[0]['id'])
        if not pid:
            data=tmdb_direct._request('/search/person',{'query':name},timeout=10)
            matches=[p for p in data.get('results') or [] if str(p.get('name') or '').casefold()==name.casefold()]
            if matches:pid=str(max(matches,key=lambda p:float(p.get('popularity') or 0))['id'])
        if pid:
            data=tmdb_direct._request('/person/%s/combined_credits'%pid,timeout=10)
            values=(data.get('cast') or [])+(data.get('crew') or [])
            values=[r for r in values if isinstance(r,dict) and r.get('media_type') in ('movie','tv') and r.get('id')]
            values.sort(key=lambda r:float(r.get('popularity') or 0),reverse=True)
            seen=set()
            for row in values:
                mt='series' if row['media_type']=='tv' else 'movie';identity=(mt,row['id'])
                if identity in seen:continue
                seen.add(identity)
                meta=dict(row,id='tmdb:%s'%row['id'],type=mt,name=row.get('title') or row.get('name'),
                          poster=tmdb_direct._image_url(row.get('poster_path')),
                          background=tmdb_direct._image_url(row.get('backdrop_path'),'backdrop'),description=row.get('overview') or '')
                result.append(home_data.media_card(meta,source,mt))
    if not result and exact_tmdb:
        try:result=_provider_person_titles(dict(person,name=name),source)
        except ValueError as exc:provider_error=exc
    if not result:
        if provider_error:raise provider_error
        if not any(search_catalogs.is_people(c) for c in search_catalogs.entries(source)) and not tmdb_direct._api_key():
            raise ValueError('Enable People Search for movies and series in your metadata add-on and re-import its manifest, or set the optional TMDb key in Settings → Add-ons → Actor search fallback.')
        return []
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


def person_page(person):
    from . import tmdb_direct, search_catalogs
    from .display_text import clean
    profile = dict(person, name=clean(person.get('name') or 'Filmography'))
    rows = person_titles(person)
    pid = search_catalogs.person_id(person)
    if tmdb_direct._api_key():
        try:
            if not pid:
                data = tmdb_direct._request('/search/person', {'query': profile['name']}, timeout=5)
                matches = [r for r in data.get('results') or [] if clean(r.get('name')).casefold() == profile['name'].casefold()]
                if matches:
                    match = max(matches, key=lambda r: float(r.get('popularity') or 0))
                    pid = str(match['id'])
                    if match.get('profile_path'):
                        profile['photo'] = tmdb_direct._image_url(match['profile_path'])
            if pid and not profile.get('photo'):
                data = tmdb_direct._request('/person/' + pid, timeout=5)
                if data.get('profile_path'):
                    profile['photo'] = tmdb_direct._image_url(data['profile_path'])
                profile['role'] = data.get('known_for_department') or profile.get('role') or 'Filmography'
        except Exception:
            pass  # Keep the provider portrait/name, never invent a translated name.
    result = {'person': profile, 'movies': [], 'series': []}
    seen = set()
    for row in rows:
        target = row.get('target') or {}
        mt, cid = target.get('media_type'), target.get('canonical_id')
        if mt not in ('movie', 'series') or (mt, cid) in seen:
            continue
        seen.add((mt, cid))
        result['movies' if mt == 'movie' else 'series'].append(row)
    return result
