"""Sports add-ons (6.0.35, GitHub issue #8).

Sports add-ons get their own Sports screen and never enter the movie/series
Home, Search, Continue Watching or the tracking services (like IPTV channels).

An add-on is a sports add-on when its manifest or catalogs use a sports type
(``sport``, ``sports``, ``events``...) or its name/id/description is clearly
about sports. Its catalogs are loaded with a short cache (live events change
during the day) and its streams are played as previews, which the playback
companion never tracks.
"""
import re
import time

SPORT_TYPES = {'sport', 'sports', 'event', 'events', 'live', 'match', 'matches'}
_WORDS = re.compile(r'\b(sports?|football|soccer|nba|nfl|nhl|mlb|ufc|mma|boxing|f1|formula ?1|motogp|'
                    r'cricket|rugby|tennis|darts|wrestling|live ?events?)\b', re.I)
CATALOG_TTL = 300            # seconds a sports page counts as fresh
CATALOG_STALE = 24 * 3600    # shown at once while it refreshes
STREAM_TIMEOUT = 15


def _manifest(provider):
    return (provider or {}).get('manifest') or {}


def _types(manifest):
    found = {str(t).lower() for t in manifest.get('types') or [] if isinstance(t, str)}
    for catalog in manifest.get('catalogs') or []:
        if isinstance(catalog, dict) and catalog.get('type'):
            found.add(str(catalog['type']).lower())
    for resource in manifest.get('resources') or []:
        if isinstance(resource, dict):
            found.update(str(t).lower() for t in resource.get('types') or [] if isinstance(t, str))
    return found


def is_sports_provider(provider):
    manifest = _manifest(provider)
    types = _types(manifest)
    if types & SPORT_TYPES:
        return True
    if types & {'movie', 'series'}:
        # A movie/series add-on only counts when its name says so.
        text = ' '.join(str(x or '') for x in (manifest.get('name'), provider.get('name'), manifest.get('id')))
    else:
        text = ' '.join(str(x or '') for x in (manifest.get('name'), provider.get('name'), manifest.get('id'),
                                               manifest.get('description')))
    return bool(_WORDS.search(text))


def is_sports_type(media_type):
    return str(media_type or '').lower() in SPORT_TYPES


def providers(all_providers=None):
    from .nuviohub import store
    rows = store.list_providers() if all_providers is None else all_providers
    return [p for p in rows if is_sports_provider(p)]


def _usable(catalog):
    if not isinstance(catalog, dict) or not catalog.get('id') or not catalog.get('type'):
        return False
    if catalog.get('extraRequired'):
        return False
    return not any(isinstance(e, dict) and e.get('isRequired') for e in catalog.get('extra') or [])


def catalogs(all_providers=None):
    """[(provider, catalog)] in manifest order, live/today first."""
    found = []
    for provider in providers(all_providers):
        for catalog in _manifest(provider).get('catalogs') or []:
            if _usable(catalog):
                found.append((provider, catalog))

    def rank(pair):
        name = '%s %s' % (pair[1].get('id'), pair[1].get('name'))
        return 0 if re.search(r'live', name, re.I) else (1 if re.search(r'today|now', name, re.I) else 2)
    return sorted(found, key=rank)


def _key(provider, catalog):
    from . import browse_cache
    return browse_cache.key('sports-v1', browse_cache.provider_key(provider), catalog.get('type'), catalog.get('id'))


def cached_page(provider, catalog):
    """(metas, fresh) from the cache, without network."""
    from . import browse_cache
    value, fresh = browse_cache.instance().lookup(_key(provider, catalog))
    metas = (value or {}).get('metas') if isinstance(value, dict) else None
    return (metas if isinstance(metas, list) else None), fresh


def load_page(provider, catalog, timeout=8):
    """First page of a sports catalog from the add-on (and into the cache)."""
    from . import browse_cache
    from .nuviohub.client import get_json, build_resource_url
    # No HTTP-level cache: live events change during the day.
    data = get_json(build_resource_url(provider, 'catalog', catalog['type'], catalog['id'], extra={}),
                    ttl_seconds=0, timeout_override=timeout, retry=False, rate_wait=.1)
    metas = [m for m in (data or {}).get('metas') or [] if isinstance(m, dict) and m.get('id')]
    browse_cache.instance().put(_key(provider, catalog), {'metas': metas}, ttl=CATALOG_TTL, stale=CATALOG_STALE)
    return metas


def card(provider, catalog, meta):
    from .plugin import _normalize_meta_art_urls
    try:
        meta = _normalize_meta_art_urls(provider, meta)
    except Exception:
        pass
    art = meta.get('poster') or meta.get('background') or meta.get('logo') or ''
    return {'title': str(meta.get('name') or meta.get('id')), 'id': meta['id'], 'type': meta.get('type') or catalog['type'],
            'art': art, 'background': meta.get('background') or art, 'description': meta.get('description') or '',
            'info': meta.get('releaseInfo') or '', 'provider_id': provider['id'],
            'live': 'live' in str(meta.get('releaseInfo') or '').lower()}


def poster_urls(rows, per_row=8):
    urls, seen = [], set()
    for row in rows:
        for item in row[:per_row]:
            url = str(item.get('art') or '')
            if url.startswith(('https://', 'http://')) and '|' not in url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def _play_url(stream):
    """Kodi URL for one stream, with the add-on's request headers."""
    from urllib.parse import urlencode
    url = str(stream.get('url') or '')
    if not url.startswith(('http://', 'https://')):
        return ''
    hints = stream.get('behaviorHints') or {}
    headers = {}
    proxy = hints.get('proxyHeaders') or {}
    request = proxy.get('request') if isinstance(proxy.get('request'), dict) else proxy
    if isinstance(request, dict):
        headers.update({str(k): str(v) for k, v in request.items() if isinstance(v, (str, int))})
    if isinstance(stream.get('requestHeaders'), dict):
        headers.update({str(k): str(v) for k, v in stream['requestHeaders'].items()})
    return url + ('|' + urlencode(headers) if headers else '')


def streams(item, all_providers=None):
    """Playable streams of one sports event from every sports add-on that serves it."""
    from concurrent.futures import ThreadPoolExecutor
    from .nuviohub.client import get_json, build_resource_url
    from .resource_support import supports
    sources = [p for p in providers(all_providers) if supports(p, 'stream', item['type'], item['id'])]
    if not sources:
        sources = [p for p in providers(all_providers) if p['id'] == item.get('provider_id')]

    def fetch(source):
        data = get_json(build_resource_url(source, 'stream', item['type'], item['id']),
                        ttl_seconds=0, timeout_override=STREAM_TIMEOUT, retry=False, rate_wait=.1)
        rows = []
        for stream in (data or {}).get('streams') or []:
            if not isinstance(stream, dict):
                continue
            url = _play_url(stream)
            if url:
                label = str(stream.get('name') or source.get('name') or 'Stream').replace('\n', ' · ')
                detail = str(stream.get('title') or stream.get('description') or '').replace('\n', ' · ')
                rows.append({'label': label, 'detail': detail, 'url': url})
        return rows
    result = []
    if not sources:
        return result
    with ThreadPoolExecutor(max_workers=min(4, len(sources)), thread_name_prefix='NuvioSportStreams') as pool:
        for future in [pool.submit(fetch, s) for s in sources]:
            try:
                result.extend(future.result(timeout=STREAM_TIMEOUT + 2))
            except Exception:
                continue
    return result


def now():
    return time.time()
