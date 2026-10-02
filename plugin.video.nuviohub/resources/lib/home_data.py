"""Small home payloads. Local shelves first; bounded catalog work on demand."""
import json
from urllib.parse import urlsplit, parse_qs

MAX_ROWS = 24
PAGE_SIZE = 16


def _api():
    from . import plugin
    return plugin


def placeholder(title, plot, path='', folder=True):
    return {'title': title, 'plot': plot, 'path': path, 'is_folder': folder,
            'poster': '', 'fanart': '', 'subtitle': 'Browse', 'meta_line': ''}


def media_card(meta, provider=None, media_type='movie', next_episode=False):
    if (meta or {}).get('type',media_type) in ('person','people','actor'):
        from .search_catalogs import person_card
        return person_card(meta,provider)
    p = _api()
    meta = dict(meta or {})
    from .display_text import clean
    title = clean(meta.get('name') or meta.get('title') or 'Untitled').strip()
    mid = str(meta.get('id') or meta.get('canonical_id') or '')
    media_type = meta.get('type') or meta.get('media_type') or media_type
    poster = meta.get('poster') or ''
    fanart = meta.get('background') or meta.get('fanart') or ''
    logo = meta.get('clearlogo') or meta.get('logo') or ''
    year = str(meta.get('year') or meta.get('releaseInfo') or '')[:4]
    series = media_type in ('series', 'show', 'tv', 'tvshow', 'anime')
    subtitle = year
    if next_episode:
        subtitle = 'S%s E%s' % (meta.get('season') or '', meta.get('episode') or '')
    ids = p.extract_ids(meta)
    from .trailer_support import trailer_url
    rating = rating_label(meta)
    return {
        'trailer': trailer_url(meta),
        'title': title, 'subtitle': subtitle, 'poster': poster, 'fanart': fanart,
        'clearlogo': logo, 'plot': meta.get('description') or meta.get('overview') or meta.get('plot') or '',
        'meta_line': '  |  '.join(x for x in (year, 'Series' if series else 'Movie', rating) if x),
        'rating': rating,
        'target': dict(media_type=media_type, canonical_id=mid, title=title,
                       source_provider_id=(provider or {}).get('id') or '',
                       season=meta.get('season') if next_episode else '',
                       episode=meta.get('episode') if next_episode else '',
                       video_id=meta.get('video_id') if next_episode else '',
                       tmdb_id=ids.get('tmdb_id') or '', imdb_id=ids.get('imdb_id') or '',
                       tvdb_id=ids.get('tvdb_id') or '',
                       ui_seed={'poster': poster, 'fanart': fanart, 'clearlogo': logo}),
        'is_folder': series and not next_episode,
    }


def rating_label(meta):
    """'IMDb 7.8' from the metadata add-on's own fields; '' when it supplies none
    or ratings are switched off in Settings > Appearance."""
    try:
        from .settings_cache import cached_addon
        if cached_addon().getSetting('nuvio_show_ratings') == 'false':
            return ''
    except Exception:
        pass
    meta = meta or {}
    for label, value in (('IMDb', meta.get('imdbRating') or meta.get('imdb_rating')),
                         ('IMDb', (meta.get('ratings') or {}).get('imdb') if isinstance(meta.get('ratings'), dict) else None),
                         ('TMDb', meta.get('tmdbRating') or meta.get('vote_average'))):
        try:
            number = float(str(value).split('/')[0].replace(',', '.'))
        except (TypeError, ValueError):
            continue
        if 0 < number <= 10:
            return '%s %.1f' % (label, number)
    return ''


def initial_shelves(bucket=''):
    """No network: display saved progress and catalogs immediately."""
    p = _api()
    shelves = []
    if bucket.startswith('group:'):
        from .collections_home import groups,tiles
        selected=next((g for g in groups() if g['id']==bucket.split(':',1)[1]),None)
        return [tiles(selected)] if selected else [{'title':'Collections','rows':[placeholder('Collection unavailable','Sync your Nuvio collections again.')]}]
    if bucket == 'collections':
        from .collections_home import groups, tiles
        all_groups = groups()
        if len(all_groups) > MAX_ROWS:
            all_groups[MAX_ROWS-1]['folders'].extend(f for g in all_groups[MAX_ROWS:] for f in g['folders'])
            all_groups[MAX_ROWS-1]['title']='More collections'
        return [tiles(g) for g in all_groups[:MAX_ROWS]]
    if not bucket:
        try:
            from .settings_cache import cached_addon
            show_continue = cached_addon().getSetting('nuvio_home_continue') != 'false'
        except Exception:
            show_continue = True
        if show_continue:
            shelves.append(continue_shelf())
        from .collections_home import home_rows
        try:shelves.extend(home_rows())
        except Exception:
            shelves.append({'title':'Collections','rows':[placeholder('Open Settings',
                'Your collections could not load. Import them again from Nuvio.',p.build_url(action='setup_center'))]})
        if len(shelves)>MAX_ROWS:
            from .collections_home import groups,tiles
            extra=[]
            for group in groups()[MAX_ROWS-2:]:
                cards=tiles(group)['rows'];art=cards[0] if cards else {}
                extra.append(dict(placeholder(group['title'],'Open this collection group.'),group_id=group['id'],poster=art.get('poster',''),fanart=art.get('fanart','')))
            shelves=shelves[:MAX_ROWS-1]+[{'title':'More collection groups','shape':'landscape','rows':extra}]
        return shelves[:MAX_ROWS]

    pins = p._load_catalog_pins() or []
    pinned = {(r.get('provider_id'), r.get('catalog_id'), r.get('media_type')): i for i, r in enumerate(pins)}
    from .backend_api import catalog_entries
    entries = catalog_entries(bucket)
    entries.sort(key=lambda e: pinned.get((e[0].get('id'), e[1].get('id'), e[1].get('type')), len(pins)))
    seen = set()
    for provider, catalog, kind in entries:
        if not p._home_bucket_visible(kind):
            continue
        # Search-only/required-genre catalogs cannot be fetched without user input.
        if any(isinstance(extra, dict) and extra.get('isRequired') for extra in catalog.get('extra') or []):
            continue
        key = (provider.get('id'), catalog.get('type'), catalog.get('id'))
        if key in seen:
            continue
        seen.add(key)
        title = str(catalog.get('name') or catalog.get('id') or 'Catalog')
        path = p.build_url(action='catalog_all', provider_id=provider.get('id'),
                           media_type=catalog.get('type') or 'movie', catalog_id=catalog.get('id'), label=title)
        shelves.append({'title': title, 'rows': [placeholder('Loading titles',
                        'Your catalog is loading. You can keep browsing.', path)],
                        'job': (provider, catalog), 'path': path})
        if len(shelves) >= MAX_ROWS:
            break
    if not shelves or not entries:
        if len(shelves) < MAX_ROWS:
            shelves.append({'title': 'Discover', 'rows': [placeholder('Connect your catalogs',
                'Sign in to Nuvio or add your metadata manifest in Settings > Add-ons.',
                p.build_url(action='setup_center'))]})
    return shelves[:MAX_ROWS]


def _job_rows(provider, catalog, extra, data):
    p = _api()
    mt = catalog.get('type') or 'movie'
    metas = [m for m in (data or {}).get('metas', []) if isinstance(m, dict) and m.get('id')][:PAGE_SIZE]
    # AIOMetadata owns these catalogs and their metadata. No second enrichment layer.
    return [media_card(p._normalize_meta_art_urls(provider, m), provider, mt) for m in metas]


def _fetch_job(provider, catalog, extra, cached_only=False):
    from . import browse_cache
    if cached_only:
        return browse_cache.peek(provider, catalog, extra or {}, memory_only=cached_only == 'memory')
    return browse_cache.catalog(provider, catalog, extra or {},
                                timeout=8 if (extra or {}).get('search') else 4)


def _collection_batches(jobs, stopped=None, cached_only=False):
    """Fetch every collection source concurrently; one failed source is not fatal."""
    if cached_only:
        batches = []
        for provider, catalog, extra in jobs:
            data = _fetch_job(provider, catalog, extra, True)
            if data is None:
                return None
            batches.append(_job_rows(provider, catalog, extra, data))
        return batches
    if len(jobs) == 1:
        provider, catalog, extra = jobs[0]
        return [_job_rows(provider, catalog, extra, _fetch_job(provider, catalog, extra))]
    from concurrent.futures import ThreadPoolExecutor
    batches, errors = [], []
    with ThreadPoolExecutor(max_workers=min(4, len(jobs)), thread_name_prefix='NuvioCollection') as pool:
        futures = [(job, pool.submit(_fetch_job, *job)) for job in jobs]
        for (provider, catalog, extra), future in futures:
            if stopped and stopped():
                for _, pending in futures:
                    pending.cancel()
                return []
            try:
                batches.append(_job_rows(provider, catalog, extra, future.result()))
            except Exception as exc:
                errors.append(exc)
                batches.append([])
    if errors and len(errors) == len(jobs):
        raise errors[0]
    return batches


def load_catalog(shelf, stopped=None, cached_only=False):
    """Rows for one Home shelf. ``cached_only`` (True, or 'memory' to skip the
    disk) never touches the network and returns ``None`` unless every source
    already has a cached page."""
    if stopped and stopped():return []
    if shelf.get('people_job'):
        if cached_only:return None
        from .search_catalogs import search_people
        return search_people(shelf['people_job']) or [placeholder('No actors found','Try another name.')]
    if shelf.get('collection_job'):
        results = _collection_batches(shelf['collection_job'], stopped, cached_only)
        if results is None:return None
        if stopped and stopped():return []
        # Alternate films and series so both configured sources are represented.
        rows, seen = [], set()
        for index in range(PAGE_SIZE):
            for batch in results:
                if index < len(batch) and batch[index].get('target'):
                    row = batch[index]
                    target = row.get('target') or {}
                    key = (target.get('media_type'), target.get('canonical_id'))
                    if key not in seen:
                        rows.append(row)
                        seen.add(key)
        rows = rows[:PAGE_SIZE]
        if cached_only and not rows:return None
        rows.append(placeholder('Browse all', 'Open movies and series with the collection filters.', shelf['path']))
        return rows
    provider, catalog = shelf['job']
    extra = shelf.get('extra') or {}
    data = _fetch_job(provider, catalog, extra, cached_only)
    if data is None and cached_only:return None
    rows = _job_rows(provider, catalog, extra, data)
    if cached_only and not rows:return None
    # Full listing owns per-provider metadata enrichment and pagination.
    if not shelf.get('no_more'):
        rows.append(placeholder('Browse all', 'Open the full catalog with your metadata settings and filters.', shelf['path']))
    return rows or [placeholder('No titles found', 'AIOMetadata returned no titles for this selection.')]


def search_shelves(query):
    from . import backend_api, search_catalogs, tmdb_direct
    from .metadata_providers import enabled
    shelves=[];p=_api()
    query=str(query or '').strip()
    if not query:return []
    from .sports import is_sports_provider
    for source in enabled():
        if is_sports_provider(source):continue  # 6.0.35: sports stay in the Sports screen
        for catalog in search_catalogs.entries(source):
            path=p.build_url(action='catalog_all',provider_id=source['id'],media_type=catalog['type'],
                             catalog_id=catalog['id'],search=query)
            shelves.append({'title':search_catalogs.title(catalog)+' · '+(source.get('name') or source['id']),
                            'job':(source,catalog), 'extra':{'search':query},'no_more':False,'path':path,
                            'rows':[placeholder('Searching','Searching your metadata add-ons…')]})
    if tmdb_direct._api_key():
        shelves.insert(0,{'title':'Actors & crew','people_job':query,'rows':[placeholder('Searching actors','Loading people…')]})
    # No metadata catalog type filter: include movies, series, anime and the
    # other searchable types the provider advertises. Never invent endpoint IDs.
    if len(shelves)>MAX_ROWS:
        overflow=shelves[MAX_ROWS-1:]
        shelves=shelves[:MAX_ROWS-1]+[{'title':'More search categories','rows':[
            placeholder(s['title'],'Search this metadata catalog for '+query,s.get('path','')) for s in overflow]}]
    return shelves or [{'title':'Search movies, series, actors & more','rows':[
        placeholder('Configure metadata search','Enable title and People Search catalogs in your metadata add-on, then refresh its manifest.',p.build_url(action='setup_center'),False)]}]


def continue_shelf():
    from . import simkl_watched, watch_nextup, continue_local
    from .progress_model import timestamp
    from nuviohub import playback_store
    from .nuviohub.common import WATCHED_PERCENT
    from . import continue_rules
    p=_api(); rows=[]; watched=simkl_watched.snapshot(); removed=continue_rules.snapshot()
    local=continue_local.recent()
    # Local user actions win over account imports. Completed local titles also
    # suppress their stale remote resume, without discarding the watched archive.
    merged={continue_local.identity(r):(r,False) for r in playback_store.list_continue_items(limit=50)}
    for r in local:
        key=continue_local.identity(r)
        remote=merged.get(key)
        if not remote or timestamp(r.get('updated_at'))>=timestamp(remote[0].get('updated_at')):
            merged[key]=(r,True)
    from .progress_model import timestamp
    def display_order(value):
        return timestamp(value[0].get('updated_at'))
    for raw,is_local in sorted(merged.values(),key=display_order,reverse=True):
        if raw.get('event_type')=='watched' or float(raw.get('percent') or 0)>=WATCHED_PERCENT:continue
        mt='movie' if raw.get('media_type')=='movie' else 'series'
        mid=raw.get('canonical_id') or ''
        # 6.0.35: removed by the user (until played again) and the period (60 days).
        if continue_rules.hidden(mt,mid,raw.get('updated_at'),removed) or not continue_rules.recent_enough(raw.get('updated_at')):continue
        entry=simkl_watched.state(watched,mt,mid)
        done=entry.get('watched') if mt=='movie' else simkl_watched.is_episode_watched(entry,raw.get('season'),raw.get('episode'))
        stamp=entry.get('watched_at') if mt=='movie' else (entry.get('episode_watched_at') or {}).get('%s:%s'%(raw.get('season'),raw.get('episode')))
        if done and (not is_local or float(stamp or 0)>float(raw.get('updated_at') or 0)):continue
        target=dict(media_type=mt,canonical_id=mid,video_id=raw.get('video_id') or mid,
                    season=raw.get('season'),episode=raw.get('episode'),
                    resume_seconds=raw.get('position') or 0,resume_percent=raw.get('percent') or 0)
        title=raw.get('title') or 'Loading title…'
        percent=int(float(raw.get('percent') or 0))
        subtitle=('S%s · E%s  |  '%(raw.get('season'),raw.get('episode'))) if mt=='series' else ''
        rows.append(dict(title=title,subtitle=subtitle+'%s%% watched'%percent,
            poster=raw.get('poster') or '',fanart=raw.get('background') or '',
            landscape=raw.get('background') or '',clearlogo=raw.get('clearlogo') or '',
            percent_value=percent,percent=percent,target=target,is_folder=False,
            plot=raw.get('plot') or '',resume_label='Resume',continue_card='resume',
            progress_key=[raw.get('media_type'),mid,raw.get('video_id') or mid],
            path=p.build_url(action='cw_resume',**{k:v for k,v in target.items() if v is not None})))
    try:rows=watch_nextup.augment(rows)
    except Exception:pass
    return {'title':'Continue Watching','continue_job':True,'rows':rows[:50] or [placeholder(
        'Your next watch starts here','Movies and episodes you start will appear here with their saved progress.',p.build_url(action='continue'))]}
