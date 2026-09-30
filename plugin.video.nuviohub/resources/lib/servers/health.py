# -*- coding: utf-8 -*-
"""Small local health router for Plex/Emby/Jellyfin servers.

It prevents a repeatedly offline server from consuming every search budget,
while never deleting accounts or disabling a server permanently.
"""
from __future__ import absolute_import
import json
import os
import threading
import time

try:
    import xbmcvfs
    _PROFILE = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.nuviohub/')
except Exception:
    _PROFILE = ''
_PATH = os.path.join(_PROFILE, 'server_health.json') if _PROFILE else ''
_LOCK = threading.RLock()
_CACHE = None
_MAX = 64


def server_key(backend, server):
    server = server or {}
    ident = (server.get('id') or server.get('machine_id') or server.get('server_id')
             or server.get('url') or server.get('name') or 'unknown')
    return '%s:%s' % (str(backend or 'server').lower(), str(ident))


def _load():
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        data = {}
        try:
            if _PATH and os.path.exists(_PATH):
                with open(_PATH, 'r', encoding='utf-8') as fh:
                    raw = json.load(fh)
                    if isinstance(raw, dict): data = raw
        except Exception:
            data = {}
        _CACHE = data
        return _CACHE


def _save(data):
    if not _PATH:
        return
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        if len(data) > _MAX:
            ordered = sorted(data.items(), key=lambda x: float((x[1] or {}).get('last_seen') or 0), reverse=True)
            data = dict(ordered[:_MAX])
            global _CACHE
            _CACHE = data
        tmp = _PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, _PATH)
    except Exception:
        pass


def should_query(backend, server, now=None):
    row = _load().get(server_key(backend, server), {})
    return float((row or {}).get('cooldown_until') or 0) <= float(now or time.time())


def record_result(backend, server, elapsed, success, result_count=0):
    now = time.time()
    key = server_key(backend, server)
    with _LOCK:
        data = _load()
        row = dict(data.get(key) or {})
        old = float(row.get('latency_ms') or 0)
        current = max(1.0, float(elapsed or 0) * 1000.0)
        row['latency_ms'] = round(current if old <= 0 else (old * 0.7 + current * 0.3), 1)
        row['last_seen'] = now
        if success:
            row['successes'] = int(row.get('successes') or 0) + 1
            row['failures'] = 0
            row['last_success'] = now
            row['cooldown_until'] = 0
            row['last_results'] = int(result_count or 0)
        else:
            failures = int(row.get('failures') or 0) + 1
            row['failures'] = failures
            # 15s, 30s, 60s, then max 2 minutes. Temporary only.
            row['cooldown_until'] = now + min(120, 15 * (2 ** min(failures - 1, 3)))
        data[key] = row
        _save(data)


def score(backend, server):
    row = _load().get(server_key(backend, server), {}) or {}
    cooldown = 1 if float(row.get('cooldown_until') or 0) > time.time() else 0
    failures = int(row.get('failures') or 0)
    latency = float(row.get('latency_ms') or 1500)
    has_results = 0 if int(row.get('last_results') or 0) > 0 else 1
    return (cooldown, failures, has_results, latency)


def order_native_targets(targets):
    def _key(target):
        provider = (target or ({}, ''))[0] or {}
        pid = provider.get('id')
        if pid == '__plex__': backend = 'plex'
        elif pid == '__emby__': backend = 'emby'
        else: return (0, 0, 0, 0)
        return score(backend, provider.get('_server') or {})
    return sorted(list(targets or []), key=_key)
