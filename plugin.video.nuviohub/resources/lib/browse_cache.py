"""Bounded JSON-byte LRU with private, restart-safe disk backing.

Forty MiB of serialized metadata plus 160 MiB of compressed image bytes form the
RAM-200 cache preset. Python objects, SQLite pages and Kodi's decoded textures
are not included in these data budgets. No network work occurs in this module.
"""
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

RAM_LIMIT = 40 * 1024 * 1024
DISK_LIMIT = 128 * 1024 * 1024
MAX_ENTRY = 2 * 1024 * 1024
_CACHE = None
_INIT_LOCK = threading.Lock()
_FLIGHT_LOCK = threading.Lock()
_FLIGHTS = {}


class Cache:
    def __init__(self, path, ram_limit=RAM_LIMIT, disk_limit=DISK_LIMIT, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ram_limit, self.disk_limit, self.clock = ram_limit, disk_limit, clock
        self.lock = threading.RLock()
        self.memory = OrderedDict()
        self.bytes = 0
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value BLOB NOT NULL, expires REAL NOT NULL, touched REAL NOT NULL, bytes INTEGER NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS cache_touched ON cache(touched)')
        try:
            os.chmod(str(self.path), 0o600)
        except OSError:
            pass

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=2)
        try:
            db.execute('PRAGMA busy_timeout=2000')
            with db:
                yield db
        finally:
            db.close()

    def _remember(self, key, value, expires):
        old = self.memory.pop(key, None)
        if old:
            self.bytes -= len(old[0])
        if len(value) > self.ram_limit:
            return
        self.memory[key] = (value, expires)
        self.bytes += len(value)
        while self.bytes > self.ram_limit and self.memory:
            _, old = self.memory.popitem(last=False)
            self.bytes -= len(old[0])

    def get(self, key, memory_only=False):
        now = self.clock()
        with self.lock:
            hit = self.memory.get(key)
            if hit and hit[1] > now:
                self.memory.move_to_end(key)
                return json.loads(hit[0])
            if hit:
                self.bytes -= len(self.memory.pop(key)[0])
            if memory_only:
                return None
            try:
                with self._connect() as db:
                    row = db.execute('SELECT value,expires FROM cache WHERE key=? AND expires>?', (key, now)).fetchone()
                    if row:
                        db.execute('UPDATE cache SET touched=? WHERE key=?', (now, key))
                if row:
                    self._remember(key, bytes(row[0]), row[1])
                    return json.loads(row[0])
            except (sqlite3.Error, ValueError, TypeError):
                return None
        return None

    def put(self, key, value, ttl=900):
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str).encode('utf-8')
        if len(raw) > MAX_ENTRY or len(raw) > self.disk_limit or ttl <= 0:
            return False
        now = self.clock()
        with self.lock:
            self._remember(key, raw, now + ttl)
            try:
                with self._connect() as db:
                    db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?,?,?)', (key, raw, now + ttl, now, len(raw)))
                    db.execute('DELETE FROM cache WHERE expires<=?', (now,))
                    total = db.execute('SELECT COALESCE(SUM(bytes),0) FROM cache').fetchone()[0]
                    if total > self.disk_limit:
                        for old_key, size in db.execute('SELECT key,bytes FROM cache ORDER BY touched').fetchall():
                            db.execute('DELETE FROM cache WHERE key=?', (old_key,))
                            total -= size
                            if total <= self.disk_limit:
                                break
            except sqlite3.Error:
                # Read-only/low-space disk still permits the bounded RAM cache.
                pass
        return True

    def clear(self):
        with self.lock:
            self.memory.clear()
            self.bytes = 0
            try:
                with self._connect() as db:
                    db.execute('DELETE FROM cache')
                    db.commit()
                    db.execute('VACUUM')
            except sqlite3.Error:
                pass


def instance():
    global _CACHE
    with _INIT_LOCK:
        if _CACHE is None:
            import xbmcaddon
            import xbmcvfs
            root = xbmcvfs.translatePath(xbmcaddon.Addon('plugin.video.nuviohub').getAddonInfo('profile'))
            _CACHE = Cache(Path(root) / 'cache' / 'browse610.db')
        return _CACHE


def key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()


def provider_key(provider):
    # Hash only; configured endpoint secrets never appear in file names.
    return key(provider.get('id'), provider.get('manifest_url'), provider.get('base_url'), provider.get('manifest'))


def catalog_key(provider, catalog, extra=None):
    return key('catalog-v1', provider_key(provider), catalog.get('type'), catalog.get('id'), extra or {})


def catalog(provider, catalog, extra=None, timeout=5):
    from concurrent.futures import Future
    from .nuviohub.client import fetch_catalog
    identity = catalog_key(provider, catalog, extra)
    cache = instance()
    hit = cache.get(identity)
    if hit is not None:
        return hit
    with _FLIGHT_LOCK:
        pending = _FLIGHTS.get(identity)
        owner = pending is None
        if owner:
            pending = Future()
            _FLIGHTS[identity] = pending
    if not owner:
        return json.loads(json.dumps(pending.result(timeout=max(1, timeout) + 1), ensure_ascii=False))
    try:
        # A previous owner might have populated the cache just before this lock.
        data = cache.get(identity)
        if data is None:
            data = fetch_catalog(provider, catalog['type'], catalog['id'], extra=extra or {},
                                 timeout_override=timeout, retry=False, rate_wait=.1)
            rows = (data or {}).get('metas')
            if not isinstance(rows, list) or any(not isinstance(m, dict) or not m.get('id') for m in rows):
                raise ValueError('Invalid catalog response')
            if rows:
                cache.put(identity, data, ttl=120 if (extra or {}).get('search') else 1800)
        pending.set_result(data)
        return data
    except Exception as exc:
        pending.set_exception(exc)
        raise
    finally:
        with _FLIGHT_LOCK:
            if _FLIGHTS.get(identity) is pending:
                _FLIGHTS.pop(identity, None)
