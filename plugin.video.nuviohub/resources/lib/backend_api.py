"""Nuvio data/playback boundary. No skins, source races, sorting or quality filters."""
import re
import xbmcaddon

ADDON_ID = 'plugin.video.nuviohub'


def provider(role, providers=None):
    from .dexhub import store
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


def metadata(media_type, canonical_id, timeout=8):
    from .dexhub.client import fetch_meta
    source = provider('metadata')
    if not source: raise ValueError('Connect AIOMetadata in Settings > Add-ons.')
    data = fetch_meta(source, media_type, canonical_id, timeout_override=timeout,retry=False,rate_wait=.1)
    meta = (data or {}).get('meta')
    if not isinstance(meta, dict): raise ValueError('AIOMetadata did not return details for this title.')
    from .plugin import _normalize_meta_art_urls
    meta=_normalize_meta_art_urls(source,meta)
    from .title_details import normalize_people_art
    meta=normalize_people_art(meta,source)
    result=dict(meta, id=canonical_id, type=media_type)
    if media_type=='series':
        try:
            from .watch_nextup import remember
            remember(result,source['id'])
        except Exception:pass
    return result


def streams(media_type, video_id):
    from .dexhub.client import get_json, build_resource_url
    source = provider('streams')
    if not source: raise ValueError('Connect AIOStreams in Settings > Add-ons.')
    # AIOStreams already owns filtering, ranking, debrid and formatting. Preserve its
    # response order, duplicates, labels and hints. Do not call the legacy race pipeline.
    data = get_json(build_resource_url(source, 'stream', media_type, video_id),
                    ttl_seconds=0, timeout_override=20, retry=False, rate_wait=0.25)
    rows = (data or {}).get('streams')
    if not isinstance(rows, list): raise ValueError('AIOStreams returned an invalid stream response.')
    if any(not isinstance(row, dict) for row in rows): raise ValueError('AIOStreams returned an invalid stream entry.')
    return source, rows


def playback_context(meta, row, source, season='', episode='', video_id='', resume_seconds=0):
    from . import plugin as p, title_details
    url = p._stream_play_url_from_row(row)
    if not url:
        raise ValueError('This AIOStreams result has no Kodi-playable URL. Check its provider/debrid configuration or choose another result.')
    ids = p.extract_ids(meta)
    info = p._meta_info(meta)
    try:resume_seconds=max(0.0,float(resume_seconds or 0))
    except (TypeError,ValueError):resume_seconds=0.0
    return {
        'media_type': meta.get('type') or 'movie', 'canonical_id': meta['id'],
        'video_id': video_id or meta['id'], 'season': season, 'episode': episode,
        'title': meta.get('name') or meta.get('title') or meta['id'],
        'show_title': meta.get('name') or meta.get('title') or '',
        'stream_url': url, 'provider_id': source['id'], 'provider_name': source.get('name') or 'AIOStreams',
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
    source = provider('metadata')
    if not source: return []
    desired = {'movies':'movie','series':'series'}.get(bucket)
    result=[]
    for catalog in (source.get('manifest') or {}).get('catalogs') or []:
        mt=catalog.get('type')
        if mt not in ('movie','series') or desired and mt!=desired: continue
        if bucket=='anime' and 'anime' not in (str(catalog.get('id',''))+str(catalog.get('name',''))).lower(): continue
        result.append((source,catalog,'movies' if mt=='movie' else 'series'))
    return result
