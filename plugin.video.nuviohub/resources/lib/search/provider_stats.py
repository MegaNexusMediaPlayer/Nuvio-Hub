# -*- coding: utf-8 -*-
"""Tiny adaptive provider performance index.

Keeps only rolling latency/success counters.  It never stores titles, ids,
URLs, tokens or viewing activity.  The index is used to start historically
fast/reliable providers first while every enabled provider is still queried.
"""
import json
import os
import threading
import time

try:
    import xbmcvfs
    _BASE = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.nuviohub')
except Exception:
    _BASE = os.path.expanduser('~/.kodi/userdata/addon_data/plugin.video.nuviohub')

_PATH = os.path.join(_BASE, 'provider_performance.json')
_LOCK = threading.RLock()
_CACHE = None
_MAX_ROWS = 96


def _provider_key(provider):
    p = provider or {}
    pid = str(p.get('id') or '').strip()
    if pid in ('__plex__', '__emby__'):
        srv = p.get('_server') or {}
        return '%s:%s' % (pid, str(srv.get('id') or srv.get('name') or 'default'))
    return str(pid or p.get('base_url') or p.get('manifest_url') or p.get('name') or 'unknown')[:240]


def _load():
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        try:
            with open(_PATH, 'r', encoding='utf-8') as fh:
                raw = json.load(fh)
            _CACHE = raw if isinstance(raw, dict) else {}
        except Exception:
            _CACHE = {}
        return _CACHE


def _save(data):
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        tmp = _PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, _PATH)
    except Exception:
        pass


def record(provider, elapsed, success, result_count=0):
    key = _provider_key(provider)
    now = int(time.time())
    with _LOCK:
        data = _load()
        row = dict(data.get(key) or {})
        samples = int(row.get('samples') or 0)
        old_ms = float(row.get('avg_ms') or 0.0)
        ms = max(1.0, min(float(elapsed or 0.0) * 1000.0, 120000.0))
        alpha = 0.35 if samples < 8 else 0.18
        row['avg_ms'] = round(ms if old_ms <= 0 else (old_ms * (1.0 - alpha) + ms * alpha), 1)
        row['samples'] = min(samples + 1, 100000)
        row['successes'] = min(int(row.get('successes') or 0) + (1 if success else 0), 100000)
        row['failures'] = min(int(row.get('failures') or 0) + (0 if success else 1), 100000)
        row['last_count'] = max(0, int(result_count or 0))
        row['updated_at'] = now
        data[key] = row
        if len(data) > _MAX_ROWS:
            keep = sorted(data.items(), key=lambda kv: int((kv[1] or {}).get('updated_at') or 0), reverse=True)[:_MAX_ROWS]
            data.clear(); data.update(keep)
        _save(data)


def score(provider):
    row = (_load().get(_provider_key(provider)) or {})
    samples = int(row.get('samples') or 0)
    if samples <= 0:
        # Native providers start early until real device measurements exist.
        pid = str((provider or {}).get('id') or '')
        return 600.0 if pid in ('__plex__', '__emby__') else 1000.0
    success = int(row.get('successes') or 0)
    rate = float(success) / float(max(1, samples))
    latency = float(row.get('avg_ms') or 1500.0)
    empty_penalty = 500.0 if int(row.get('last_count') or 0) <= 0 else 0.0
    return latency + ((1.0 - rate) * 3000.0) + empty_penalty


def order_targets(targets):
    indexed = list(enumerate(targets or []))
    indexed.sort(key=lambda item: (score((item[1] or ({}, ''))[0]), item[0]))
    return [target for _, target in indexed]


def clear():
    global _CACHE
    with _LOCK:
        _CACHE = {}
        try:
            os.remove(_PATH)
        except Exception:
            pass
