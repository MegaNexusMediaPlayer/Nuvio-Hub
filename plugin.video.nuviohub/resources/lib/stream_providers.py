"""Independent, persistent stream switches; metadata selection is never changed.

An unset configuration retains the 6.0.8 single-provider choice. New providers
are visible but opt-in, so updating/importing an account does not silently send
playback requests to every installed add-on. An explicit empty list means OFF.
"""
import json
import xbmcaddon

SETTING = 'nuvio_stream_providers'


def candidates(providers=None):
    from .nuviohub import store
    providers = store.list_providers() if providers is None else providers
    result = []
    for provider in providers:
        resources = (provider.get('manifest') or {}).get('resources') or []
        if any((r.get('name') if isinstance(r, dict) else r) == 'stream' for r in resources):
            result.append(provider)
    return result


def preferred(available):
    """The single stream add-on to use when none was chosen: AIOStreams-style
    aggregators first (one request covers many sources), else the first."""
    import re
    available = list(available or [])
    for provider in available:
        text = re.sub(r'[^a-z0-9]', '', ' '.join(str(x or '') for x in (
            provider.get('id'), provider.get('name'), (provider.get('manifest') or {}).get('id'),
            (provider.get('manifest') or {}).get('name'))).lower())
        if 'aiostreams' in text:
            return provider
    return available[0] if available else None


def _saved():
    raw = xbmcaddon.Addon('plugin.video.nuviohub').getSetting(SETTING)
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []  # A damaged setting must not enable unknown providers.
    return data if isinstance(data, list) else []


def entries(providers=None):
    from . import backend_api
    available = candidates(providers)
    saved = _saved()
    if saved is None:
        # Never configured: one stream add-on is ON (the earlier choice, else
        # the preferred one). Every extra add-on adds its full response time to
        # "Loading video", so more are only ever switched on by the user.
        chosen = backend_api.provider('streams', available) or preferred(available)
        return [(p, p.get('id') == (chosen or {}).get('id')) for p in available]
    by_id = {p['id']: p for p in available}
    result, seen = [], set()
    for row in saved:
        if not isinstance(row, dict):
            continue
        pid = row.get('id')
        if not isinstance(pid, str) or pid not in by_id or pid in seen:
            continue
        seen.add(pid)
        result.append((by_id[pid], row.get('enabled') is True))
    result.extend((p, False) for p in available if p['id'] not in seen)
    return result


def set_enabled(provider_id, enabled):
    rows = entries()
    if not any(p['id'] == provider_id for p, _ in rows):
        raise ValueError('This add-on does not advertise a stream resource.')
    value = [{'id': p['id'], 'enabled': bool(enabled) if p['id'] == provider_id else on}
             for p, on in rows]
    xbmcaddon.Addon('plugin.video.nuviohub').setSetting(SETTING, json.dumps(value))
    from . import settings_cache
    settings_cache.invalidate()


def supports(provider, media_type, video_id):
    from .resource_support import supports as resource_supports
    return resource_supports(provider, 'stream', media_type, video_id)


def enabled(media_type=None, video_id=''):
    return [p for p, on in entries() if on and
            (media_type is None or supports(p, media_type, video_id))]
