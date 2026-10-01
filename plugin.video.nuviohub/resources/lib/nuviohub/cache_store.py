# -*- coding: utf-8 -*-
import json
import os
import sqlite3
import threading
import time
import uuid

from .common import profile_path

DB_PATH = os.path.join(profile_path(), 'cache.db')

_MEM = {}
_MEM_ORDER = []
_MEM_MAX = 256
_LOCK = threading.RLock()
_DB_READY = False
# v4.8.6: on Android the addon-data directory can be read-only (external
# storage permissions, a profile restored from backup, a DB left owned by
# another install). SQLite then raises "attempt to write a readonly
# database" — and that used to escape into the source-scan worker threads,
# killing one per stream row: the crash, the stutter and the failed
# playback in the user's log all traced back here. When the disk refuses
# writes we say so ONCE and run entirely from the in-memory cache, which is
# what every read already consults first.
_DISK_DISABLED = False


def _disable_disk(exc):
    global _DISK_DISABLED
    if _DISK_DISABLED:
        return
    _DISK_DISABLED = True
    try:
        import xbmc
        xbmc.log('[NuvioHub] cache store: disk cache disabled for this session '
                 '(%s) — running from memory' % exc, xbmc.LOGWARNING)
    except Exception:
        pass


def _mem_put(kind, cache_key, payload):
    key = '%s:%s' % (kind or '', cache_key or '')
    with _LOCK:
        if key not in _MEM:
            _MEM_ORDER.append(key)
        _MEM[key] = payload
        while len(_MEM_ORDER) > _MEM_MAX:
            old = _MEM_ORDER.pop(0)
            _MEM.pop(old, None)


def _mem_get(kind, cache_key):
    with _LOCK:
        return _MEM.get('%s:%s' % (kind or '', cache_key or ''))


def _conn():
    global _DB_READY
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA busy_timeout=10000')
        conn.execute('PRAGMA temp_store=MEMORY')
    except Exception:
        pass
    if not _DB_READY:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_items (
                cache_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_kind_created ON cache_items(kind, created_at DESC)")
        conn.commit()
        _DB_READY = True
    return conn


def put(kind, payload, ttl_hours=24):
    """Store a payload and return its key.

    The key is generated here and the in-memory copy is always written, so
    a disk failure can never cost the caller its handle to the data — the
    row still plays, it just is not remembered across restarts.
    """
    now = int(time.time())
    key = uuid.uuid4().hex
    cutoff = now - int(ttl_hours * 3600)
    with _LOCK:
        _mem_put(kind, key, payload)          # first: this must never fail
        if _DISK_DISABLED:
            return key
        conn = None
        try:
            encoded = json.dumps(payload, ensure_ascii=False)
            conn = _conn()
            conn.execute(
                "INSERT OR REPLACE INTO cache_items(cache_key, kind, payload, created_at) VALUES(?,?,?,?)",
                (key, kind, encoded, now),
            )
            conn.execute("DELETE FROM cache_items WHERE created_at < ?", (cutoff,))
            conn.commit()
        except sqlite3.Error as exc:
            # readonly / locked / disk-full / corrupt — all the same answer
            _disable_disk(exc)
        except Exception as exc:
            _disable_disk(exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return key


def get(kind, cache_key):
    cached = _mem_get(kind, cache_key)
    if cached is not None:
        return cached
    if _DISK_DISABLED:
        return None
    row = None
    with _LOCK:
        conn = None
        try:
            conn = _conn()
            row = conn.execute("SELECT payload FROM cache_items WHERE kind=? AND cache_key=?", (kind, cache_key)).fetchone()
        except Exception as exc:
            # a DB that cannot even be opened must not break a lookup
            _disable_disk(exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    if not row:
        return None
    try:
        payload = json.loads(row[0])
        _mem_put(kind, cache_key, payload)
        return payload
    except Exception:
        return None


def update(kind, cache_key, payload):
    if not cache_key:
        return None
    now = int(time.time())
    with _LOCK:
        _mem_put(kind, cache_key, payload)     # memory first, always
        if _DISK_DISABLED:
            return cache_key
        conn = None
        try:
            encoded = json.dumps(payload, ensure_ascii=False)
            conn = _conn()
            conn.execute(
                "INSERT OR REPLACE INTO cache_items(cache_key, kind, payload, created_at) VALUES(?,?,?,?)",
                (cache_key, kind, encoded, now),
            )
            conn.commit()
        except Exception as exc:
            _disable_disk(exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return cache_key


def clear_all(kind=None):
    with _LOCK:
        _MEM.clear()
        del _MEM_ORDER[:]
        if _DISK_DISABLED:
            return
        conn = None
        try:
            conn = _conn()
            if kind:
                conn.execute("DELETE FROM cache_items WHERE kind=?", (kind,))
            else:
                conn.execute("DELETE FROM cache_items")
            conn.commit()
        except Exception as exc:
            _disable_disk(exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        if kind:
            prefix = '%s:' % (kind or '')
            for key in list(_MEM.keys()):
                if key.startswith(prefix):
                    _MEM.pop(key, None)
            _MEM_ORDER[:] = [k for k in _MEM_ORDER if not k.startswith(prefix)]
        else:
            _MEM.clear()
            _MEM_ORDER[:] = []
