# -*- coding: utf-8 -*-
"""Short-lived, in-process source result sessions.

The source scanner and ``SourcesWindow`` live in the same Python interpreter.
Persisting every growing result snapshot to SQLite therefore added JSON
encoding, a database connection and a commit after each provider without
providing any recovery benefit.  A bounded condition-backed store is both
lighter and lets the picker sleep until a real update arrives instead of
polling the cache database several times per second.
"""
import threading
import time
import uuid


_TTL_SECONDS = 30 * 60
_MAX_SESSIONS = 16
_LOCK = threading.RLock()
_CHANGED = threading.Condition(_LOCK)
_SESSIONS = {}


def _copy_payload(payload):
    value = dict(payload or {})
    value['entries'] = list(value.get('entries') or [])
    return value


def _purge_locked(now=None):
    now = float(now or time.monotonic())
    stale = [key for key, state in _SESSIONS.items()
             if now - float(state.get('_touched') or 0.0) >= _TTL_SECONDS]
    for key in stale:
        _SESSIONS.pop(key, None)
    if len(_SESSIONS) <= _MAX_SESSIONS:
        return
    oldest = sorted(
        _SESSIONS,
        key=lambda key: float((_SESSIONS.get(key) or {}).get('_touched') or 0.0),
    )
    for key in oldest[:max(0, len(_SESSIONS) - _MAX_SESSIONS)]:
        _SESSIONS.pop(key, None)


def create(entries, done=False, version=1):
    key = uuid.uuid4().hex
    payload = {
        'entries': list(entries or []),
        'done': bool(done),
        'version': int(version or 1),
        '_touched': time.monotonic(),
    }
    with _CHANGED:
        _SESSIONS[key] = payload
        _purge_locked(payload['_touched'])
        _CHANGED.notify_all()
    return key


def update(session_key, payload):
    if not session_key:
        return False
    value = _copy_payload(payload)
    value['_touched'] = time.monotonic()
    with _CHANGED:
        _SESSIONS[session_key] = value
        _purge_locked(value['_touched'])
        _CHANGED.notify_all()
    return True


def get(session_key, default=None):
    if not session_key:
        return default
    with _LOCK:
        _purge_locked()
        value = _SESSIONS.get(session_key)
        if value is None:
            return default
        value['_touched'] = time.monotonic()
        return _copy_payload(value)


def wait_for_update(session_key, since_version=0, timeout=0.5, default=None):
    """Sleep until ``version`` changes, then return the newest snapshot.

    The wait is signalled directly by the source refresh worker.  It has no
    disk I/O and wakes immediately on a provider result; ``timeout`` merely
    lets the dialog's shutdown flag be checked periodically.
    """
    if not session_key:
        return default
    deadline = time.monotonic() + max(0.0, float(timeout or 0.0))
    with _CHANGED:
        _purge_locked()
        while True:
            value = _SESSIONS.get(session_key)
            if value is None:
                return default
            try:
                version = int(value.get('version') or 0)
            except Exception:
                version = 0
            if version != int(since_version or 0):
                value['_touched'] = time.monotonic()
                return _copy_payload(value)
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                return default
            _CHANGED.wait(remaining)
