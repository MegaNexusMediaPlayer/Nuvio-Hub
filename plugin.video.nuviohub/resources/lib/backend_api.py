"""Nuvio data/playback boundary. No skins, source races, sorting or quality filters."""
import re
import xbmcaddon

ADDON_ID = 'plugin.video.nuviohub'


def provider(role, providers=None):
    from .nuviohub import store
    providers = list(providers if providers is not None else store.list_providers())
    chosen = xbmcaddon.Addon(ADDON_ID).getSetting('nuvio_' + role + '_provider')
    if chosen:
        return next((p for p in providers if p.get('id') == chosen), None)
    needle = 'aiometadata' if role == 'metadata' else 'aiostreams'
    candidates = [p for p in providers if needle in re.sub(r'[^a-z0-9]', '',
        (str((p.get('manifest') or {}).get('id','')) + str((p.get('manifest') or {}).get('name','')) + str(p.get('name',''))).lower())]
    if len(candidates)==1:return candidates[0]
    resource='meta' if role=='metadata' else 'stream'
    compatible=[p for p in providers if resource in {r.get('name') if isinstance(r,dict) else r for r in (p.get('manifest') or {}).get('resources') or []}]
    return compatible[0] if len(compatible)==1 else None


def metadata(media_type, canonical_id, timeout=8, preferred=''):
    """Resolve only through enabled, compatible add-ons; never relabel another title."""
    import time
    from .nuviohub.client import fetch_meta
    from . import metadata_providers
    from .resource_support import same_identity
    sources = metadata_providers.enabled(media_type, canonical_id, preferred=preferred)
    if not sources:
        raise ValueError('Enable a metadata add-on supporting this title ID in Settings > Add-ons.')
    deadline = time.monotonic() + max(1, timeout)
    for index, source in enumerate(sources):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            data = fetch_meta(source, media_type, canonical_id,
                              timeout_override=max(.25, min(4, remaining / max(1, len(sources)-index))), retry=False, rate_wait=.1)
            meta = (data or {}).get('meta')
            if not same_identity(meta, media_type, canonical_id):
                continue
            from .plugin import _normalize_meta_art_urls
            from .title_details import normalize_people_art
            meta = normalize_people_art(_normalize_meta_art_urls(source, meta), source)
            result = dict(meta, id=canonical_id, type=media_type,
                          _nuvio_metadata_provider=source['id'])
            if media_type == 'series':
                try:
                    from .watch_nextup import remember
                    remember(result, source['id'])
                except Exception:
                    pass
            return result
        except Exception:
            # Configured URLs and keys must not escape into logs or UI errors.
            continue
    raise ValueError('No enabled metadata add-on returned matching details. Check the collection mapping and connection.')


STREAM_TIMEOUT = 20
STREAM_GRACE = 2.5


def streams(media_type, video_id):
    """Query enabled providers independently and retain each provider's ordering."""
    from concurrent.futures import ThreadPoolExecutor
    from . import stream_providers
    from .nuviohub.client import get_json, build_resource_url
    sources = stream_providers.enabled(media_type, video_id)
    if not sources:
        raise ValueError('Enable a compatible stream add-on in Settings > Add-ons > Stream add-ons.')

    def fetch(source):
        data = get_json(build_resource_url(source, 'stream', media_type, video_id),
                        ttl_seconds=0, timeout_override=20, retry=False, rate_wait=0.25)
        rows = (data or {}).get('streams')
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Invalid stream response')
        # A provider cannot spoof provenance. Never alter its labels, hints,
        # duplicate streams, headers, or ranking; attach our own trusted origin.
        origin = {key: source.get(key) or '' for key in ('id', 'name', 'base_url')}
        origin['name'] = origin['name'] or (source.get('manifest') or {}).get('name') or source['id']
        return [dict(row, _nuvio_source=origin) for row in rows]

    # Every add-on starts at once. As soon as one returns streams, the others
    # get STREAM_GRACE more seconds; stragglers are skipped (they finish in the
    # background) instead of holding "Loading video" for up to 20 seconds.
    import time
    from concurrent.futures import wait, FIRST_COMPLETED
    results, errors, slow = {}, [], []
    pool = ThreadPoolExecutor(max_workers=min(8, len(sources)), thread_name_prefix='NuvioStreams')
    futures = {pool.submit(fetch, source): source for source in sources}
    pending = set(futures)
    deadline = time.monotonic() + STREAM_TIMEOUT
    grace = None
    try:
        while pending:
            remaining = (grace or deadline) - time.monotonic()
            if remaining <= 0:
                break
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            for future in done:
                source = futures[future]
                try:
                    found = future.result()
                except Exception:
                    # Do not log configured URLs: they can contain account tokens.
                    errors.append(source.get('name') or source['id'])
                    continue
                results[source['id']] = found
                if found and grace is None:
                    grace = min(deadline, time.monotonic() + STREAM_GRACE)
    finally:
        pool.shutdown(wait=False)
    slow = [s.get('name') or s['id'] for s in (futures[f] for f in pending)]
    # Keep the configured add-on order, not arrival order.
    rows = [row for source in sources for row in results.get(source['id'], [])]
    if not rows and len(errors) + len(slow) == len(sources):
        raise ValueError('Stream add-ons could not respond. Check their configuration and connection.')
    return dict(sources[0], _nuvio_errors=errors, _nuvio_slow=slow), rows


def playback_context(meta, row, source, season='', episode='', video_id='', resume_seconds=0):
    from . import plugin as p, title_details
    source = row.get('_nuvio_source') or source
    url = p._stream_play_url_from_row(row)
    if not url:
        raise ValueError('This stream add-on result has no Kodi-playable URL. Check its provider/debrid configuration or choose another result.')
    ids = p.extract_ids(meta)
    info = p._meta_info(meta)
    try:resume_seconds=max(0.0,float(resume_seconds or 0))
    except (TypeError,ValueError):resume_seconds=0.0
    return {
        'media_type': meta.get('type') or 'movie', 'canonical_id': meta['id'],
        'video_id': video_id or meta['id'], 'season': season, 'episode': episode,
        'title': meta.get('name') or meta.get('title') or meta['id'],
        'show_title': meta.get('name') or meta.get('title') or '',
        'stream_url': url, 'provider_id': source['id'], 'provider_name': source.get('name') or source['id'],
        'provider_base_url': source.get('base_url') or '', 'poster': meta.get('poster') or '',
        'background': meta.get('background') or '', 'clearlogo': meta.get('logo') or '',
        'tmdb_id': ids.get('tmdb_id') or '', 'imdb_id': ids.get('imdb_id') or '', 'tvdb_id': ids.get('tvdb_id') or '',
        'external_ids': ids, 'kodi_info': info, 'plot': info.get('plot') or '',
        'year': info.get('year') or 0, 'resume_seconds': resume_seconds,
        'nuvio_resume_exact': resume_seconds>0,
        'next_episode': title_details.next_episode(meta,video_id) if meta.get('type')=='series' else None,
        'subtitles': row.get('subtitles') or [], 'behaviorHints': row.get('behaviorHints') or {},
        'request_headers': p._stream_row_request_headers(row),
        'stream_name': row.get('name') or '', 'stream_title': row.get('title') or '',
    }


def queue_playback(context):
    from . import cache_store
    from .context import build_url
    key = cache_store.put('nuvio_play', context)
    return build_url(action='nuvio_play', key=key)


def play_queued(key):
    from . import cache_store, plugin
    context = cache_store.get('nuvio_play', key)
    if not isinstance(context, dict) or not context.get('stream_url'):
        raise ValueError('Playback request expired. Choose the title again.')
    import xbmcgui
    xbmcgui.Window(10000).setProperty('nuvio.subtitle.context',key)
    return plugin._play_with_context(context, use_resolved_url=False)


def catalog_entries(bucket=''):
    from .metadata_providers import enabled
    desired = {'movies': 'movie', 'series': 'series'}.get(bucket)
    result = []
    for source in enabled():
        for catalog in (source.get('manifest') or {}).get('catalogs') or []:
            mt = catalog.get('type')
            if mt not in ('movie', 'series') or (desired and mt != desired):
                continue
            if bucket == 'anime' and 'anime' not in (str(catalog.get('id', '')) + str(catalog.get('name', ''))).lower():
                continue
            result.append((source, catalog, 'movies' if mt == 'movie' else 'series'))
    return result
