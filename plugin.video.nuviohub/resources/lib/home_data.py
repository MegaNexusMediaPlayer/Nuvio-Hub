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
    p = _api()
    meta = dict(meta or {})
    title = str(meta.get('name') or meta.get('title') or 'Untitled').strip()
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
    return {
        'trailer': trailer_url(meta),
        'title': title, 'subtitle': subtitle, 'poster': poster, 'fanart': fanart,
        'clearlogo': logo, 'plot': meta.get('description') or meta.get('overview') or meta.get('plot') or '',
        'meta_line': '  |  '.join(x for x in (year, 'Series' if series else 'Movie') if x),
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


def load_catalog(shelf, stopped=None):
    if stopped and stopped():return []
    p = _api()
    if shelf.get('collection_job'):
        results = []
        for provider, catalog, extra in shelf['collection_job']:
            if stopped and stopped():return []
            rows = load_catalog({'job': (provider, catalog), 'extra': extra, 'path': shelf['path'], 'no_more': True},stopped)
            results.append(rows)
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
        rows.append(placeholder('Browse all', 'Open movies and series with the collection filters.', shelf['path']))
        return rows
    provider, catalog = shelf['job']
    mt = catalog.get('type') or 'movie'
    # The HTTP client supplies persistent cache; hard request timeout bounds each shelf.
    from .dexhub.client import get_json, build_resource_url, catalog_ttl
    url = build_resource_url(provider, 'catalog', mt, catalog.get('id'), extra=shelf.get('extra') or {})
    data = get_json(url, ttl_seconds=catalog_ttl(), timeout_override=4, retry=False, rate_wait=0.25)
    metas = [m for m in (data or {}).get('metas', []) if isinstance(m, dict) and m.get('id')][:PAGE_SIZE]
    # AIOMetadata owns these catalogs and their metadata. No second enrichment layer.
    rows = [media_card(p._normalize_meta_art_urls(provider, m), provider, mt) for m in metas]
    # Full listing owns per-provider metadata enrichment and pagination.
    if not shelf.get('no_more'):
        rows.append(placeholder('Browse all', 'Open the full catalog with your metadata settings and filters.', shelf['path']))
    return rows or [placeholder('No titles found', 'AIOMetadata returned no titles for this selection.')]


def search_shelves(query):
    from .backend_api import catalog_entries
    shelves=[]
    p=_api()
    for provider,catalog,kind in catalog_entries():
        if not any((e.get('name') if isinstance(e,dict) else e)=='search' for e in catalog.get('extra') or []):continue
        path=p.build_url(action='catalog_all',provider_id=provider['id'],media_type=catalog['type'],catalog_id=catalog['id'])
        shelves.append({'title':catalog.get('name') or ('Movies' if catalog['type']=='movie' else 'Series'),
                        'job':(provider,catalog),'extra':{'search':query},'no_more':True,'path':path,
                        'rows':[placeholder('Searching','Searching AIOMetadata...')]})
        if len(shelves)>=MAX_ROWS:break
    return shelves or [{'title':'Search','rows':[placeholder('Connect AIOMetadata','Your metadata provider must expose a searchable catalog.',p.build_url(action='first_run_wizard'),False)]}]


def continue_shelf():
    from . import simkl_watched, watch_nextup, continue_local
    from dexhub import playback_store
    p=_api(); rows=[]; watched=simkl_watched.snapshot()
    local=continue_local.recent()
    # Local user actions win over account imports. Completed local titles also
    # suppress their stale remote resume, without discarding the watched archive.
    merged={continue_local.identity(r):(r,False) for r in playback_store.list_continue_items(limit=50)}
    for r in local:
        key=continue_local.identity(r)
        remote=merged.get(key)
        if not remote or float(r.get('updated_at') or 0)>=float(remote[0].get('updated_at') or 0):
            merged[key]=(r,True)
    # Imported timestamps can describe a sync/import rather than a local watch.
    # Keep the local journal first, newest watch first; remote-only titles follow.
    local_order={continue_local.identity(r):float(r.get('updated_at') or 0) for r in local}
    def display_order(value):
        raw=value[0];key=continue_local.identity(raw)
        return key in local_order,local_order.get(key,float(raw.get('updated_at') or 0))
    for raw,is_local in sorted(merged.values(),key=display_order,reverse=True):
        if raw.get('event_type')=='watched' or float(raw.get('percent') or 0)>=95:continue
        mt='movie' if raw.get('media_type')=='movie' else 'series'
        mid=raw.get('canonical_id') or ''
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
            plot=raw.get('plot') or '',resume_label='Resume',
            progress_key=[raw.get('media_type'),mid,raw.get('video_id') or mid],
            path=p.build_url(action='cw_resume',**{k:v for k,v in target.items() if v is not None})))
    try:rows=watch_nextup.augment(rows)
    except Exception:pass
    return {'title':'Continue Watching','continue_job':True,'rows':rows[:50] or [placeholder(
        'Your next watch starts here','Movies and episodes you start will appear here with their saved progress.',p.build_url(action='continue'))]}
