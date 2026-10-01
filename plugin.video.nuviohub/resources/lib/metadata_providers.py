"""Ordered metadata providers, with independent opt-in switches and safe keys."""
import hashlib
import json
import xbmcaddon
from .resource_support import supports as _supports

SETTING = 'nuvio_metadata_providers'


def candidates(providers=None):
    from .nuviohub import store
    providers = store.list_providers() if providers is None else providers
    return [p for p in providers if p.get('id') and any(
        (r.get('name') if isinstance(r, dict) else r) == 'meta'
        for r in (p.get('manifest') or {}).get('resources') or [])]


def entries(providers=None):
    from . import backend_api
    available = candidates(providers)
    raw = xbmcaddon.Addon('plugin.video.nuviohub').getSetting(SETTING) or ''
    if not raw.strip():
        legacy = backend_api.provider('metadata', available)
        return [(p, p['id'] == (legacy or {}).get('id')) for p in available]
    try:
        saved = json.loads(raw)
    except (ValueError, TypeError):
        saved = []
    if not isinstance(saved, list):
        saved = []
    by_id = {p['id']: p for p in available}
    rows, seen = [], set()
    for row in saved:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            continue
        pid = row['id']
        if pid in by_id and pid not in seen:
            seen.add(pid)
            rows.append((by_id[pid], row.get('enabled') is True))
    rows.extend((p, False) for p in available if p['id'] not in seen)
    return rows


def supports(provider, kind, content_id):
    return _supports(provider, 'meta', kind, content_id)


def enabled(kind=None, content_id='', preferred='', providers=None):
    result = [p for p, on in entries(providers) if on and
              (kind is None or supports(p, kind, content_id))]
    # Prefer the catalog that supplied the title, without turning an OFF provider ON.
    if preferred:
        result.sort(key=lambda p: p['id'] != preferred)
    return result


def set_enabled(provider_id, on):
    rows = entries()
    if not any(p['id'] == provider_id for p, _ in rows):
        raise ValueError('This add-on does not advertise metadata.')
    value = [{'id': p['id'], 'enabled': bool(on) if p['id'] == provider_id else active}
             for p, active in rows]
    xbmcaddon.Addon('plugin.video.nuviohub').setSetting(SETTING, json.dumps(value))
    from . import settings_cache
    settings_cache.invalidate()


def signature(providers=None):
    """Opaque cache namespace: configuration changes cannot reuse other profiles."""
    rows = entries(providers)
    value = [(p['id'], on, p.get('manifest_url'), p.get('base_url'), p.get('manifest'))
             for p, on in rows]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str).encode('utf-8')).hexdigest()
