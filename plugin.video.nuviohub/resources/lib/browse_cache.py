"""Bounded JSON-byte LRU with private, restart-safe disk backing.

Forty MiB of serialized metadata plus 256 MiB of compressed image bytes form the
RAM-200 cache preset. Python objects, SQLite pages and Kodi's decoded textures
are not included in these data budgets. Network work happens only in
``catalog``/``refresh`` worker calls, never in ``peek``.

Catalog pages use stale-while-revalidate: an entry is *fresh* until its TTL and
remains usable as a stale page for STALE_SECONDS more. Stale pages are shown at
once and refreshed on a single bounded background worker, so reopening a
collection after the TTL no longer waits for the provider.
"""
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import queue
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

RAM_LIMIT = 40 * 1024 * 1024
DISK_LIMIT = 128 * 1024 * 1024
MAX_ENTRY = 2 * 1024 * 1024
STALE_SECONDS = 7 * 24 * 3600
FRESH_SECONDS = 3 * 3600  # catalog pages change slowly; fewer background refreshes
REFRESH_QUEUE = 64
_CACHE = None
_INIT_LOCK = threading.Lock()
_FLIGHT_LOCK = threading.Lock()
_FLIGHTS = {}
_REFRESH = None
_FOREGROUND = [0, 0.0]  # catalog requests the user is waiting for, last finish time
FOREGROUND_QUIET = 1.5
_REFRESH_LOCK = threading.Lock()


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
            columns = {row[1] for row in db.execute('PRAGMA table_info(cache)')}
            if 'fresh' not in columns:
                # 6.0.10 rows had no stale window: their hard expiry is their freshness.
                db.execute('ALTER TABLE cache ADD COLUMN fresh REAL NOT NULL DEFAULT 0')
                db.execute('UPDATE cache SET fresh=expires')
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

    def _remember(self, key, value, expires, fresh=None):
        old = self.memory.pop(key, None)
        if old:
            self.bytes -= len(old[0])
        if len(value) > self.ram_limit:
            return
        self.memory[key] = (value, expires, expires if fresh is None else fresh)
        self.bytes += len(value)
        while self.bytes > self.ram_limit and self.memory:
            _, old = self.memory.popitem(last=False)
            self.bytes -= len(old[0])

    def get(self, key, memory_only=False):
        """Fresh value only; stale pages are available through ``lookup``."""
        value, fresh = self.lookup(key, memory_only=memory_only)
        return value if fresh else None

    def lookup(self, key, memory_only=False):
        """Return ``(value, fresh)``; ``(None, False)`` when absent or expired."""
        now = self.clock()
        with self.lock:
            hit = self.memory.get(key)
            if hit and hit[1] > now:
                self.memory.move_to_end(key)
                return json.loads(hit[0]), hit[2] > now
            if hit:
                self.bytes -= len(self.memory.pop(key)[0])
            if memory_only:
                return None, False
            try:
                with self._connect() as db:
                    row = db.execute('SELECT value,expires,fresh FROM cache WHERE key=? AND expires>?', (key, now)).fetchone()
                    if row:
                        db.execute('UPDATE cache SET touched=? WHERE key=?', (now, key))
                if row:
                    self._remember(key, bytes(row[0]), row[1], row[2])
                    return json.loads(row[0]), row[2] > now
            except (sqlite3.Error, ValueError, TypeError):
                return None, False
        return None, False

    def lookup_many(self, keys):
        """Promote several disk entries with one SQLite connection (startup check)."""
        now = self.clock()
        result = {}
        with self.lock:
            missing = []
            for key in keys:
                hit = self.memory.get(key)
                if hit and hit[1] > now:
                    result[key] = hit[2] > now
                else:
                    missing.append(key)
            if not missing:
                return result
            try:
                with self._connect() as db:
                    for start in range(0, len(missing), 200):
                        chunk = missing[start:start + 200]
                        marks = ','.join('?' * len(chunk))
                        for key, value, expires, fresh in db.execute(
                                'SELECT key,value,expires,fresh FROM cache WHERE expires>? AND key IN (%s)' % marks,
                                [now] + chunk):
                            self._remember(key, bytes(value), expires, fresh)
                            result[key] = fresh > now
            except sqlite3.Error:
                pass
        return result

    def put(self, key, value, ttl=900, stale=0):
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str).encode('utf-8')
        if len(raw) > MAX_ENTRY or len(raw) > self.disk_limit or ttl <= 0:
            return False
        now = self.clock()
        fresh, expires = now + ttl, now + ttl + max(0, stale)
        with self.lock:
            self._remember(key, raw, expires, fresh)
            try:
                with self._connect() as db:
                    db.execute('INSERT OR REPLACE INTO cache(key,value,expires,touched,bytes,fresh) VALUES(?,?,?,?,?,?)',
                               (key, raw, expires, now, len(raw), fresh))
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

    def import_legacy(self, legacy):
        """Carry 6.0.10 pages into this file once, then remove the old file.

        A separate file keeps a rollback to 6.0.10 working: that build writes
        five-column rows and would fail on this schema.
        """
        legacy = Path(legacy)
        if not legacy.exists():
            return 0
        imported = 0
        with self.lock:
            try:
                with self._connect() as db:
                    db.execute('ATTACH DATABASE ? AS legacy', (str(legacy),))
                    try:
                        imported = db.execute(
                            'INSERT OR IGNORE INTO cache(key,value,expires,touched,bytes,fresh) '
                            'SELECT key,value,expires,touched,bytes,expires FROM legacy.cache '
                            'WHERE expires>? AND bytes<=?', (self.clock(), MAX_ENTRY)).rowcount
                    finally:
                        db.commit()
                        db.execute('DETACH DATABASE legacy')
            except sqlite3.Error:
                imported = 0
        for suffix in ('', '-wal', '-shm', '-journal'):
            try:
                Path(str(legacy) + suffix).unlink()
            except OSError:
                pass
        return imported

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
            folder = Path(root) / 'cache'
            _CACHE = Cache(folder / 'browse611.db')
            _CACHE.import_legacy(folder / 'browse610.db')
        return _CACHE


def key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()


def provider_key(provider):
    # Hash only; configured endpoint secrets never appear in file names.
    return key(provider.get('id'), provider.get('manifest_url'), provider.get('base_url'), provider.get('manifest'))


def catalog_key(provider, catalog, extra=None):
    return key('catalog-v1', provider_key(provider), catalog.get('type'), catalog.get('id'), extra or {})


def _valid(data):
    rows = (data or {}).get('metas')
    if not isinstance(rows, list) or any(not isinstance(m, dict) or not m.get('id') for m in rows):
        raise ValueError('Invalid catalog response')
    return rows


def _store(cache, identity, data, extra):
    if _valid(data):
        search = bool((extra or {}).get('search'))
        cache.put(identity, data, ttl=120 if search else FRESH_SECONDS, stale=0 if search else STALE_SECONDS)


def peek(provider, catalog, extra=None, memory_only=False, revalidate=True):
    """Cached page (fresh or stale) without network; ``None`` on a miss.

    A stale hit queues one background revalidation unless ``revalidate`` is off.
    """
    value, fresh = instance().lookup(catalog_key(provider, catalog, extra), memory_only=memory_only)
    if value is not None and not fresh and revalidate:
        refresh(provider, catalog, extra)
    return value


def _refresher():
    global _REFRESH
    with _REFRESH_LOCK:
        if _REFRESH is None:
            _REFRESH = queue.Queue(maxsize=REFRESH_QUEUE)
            threading.Thread(target=_refresh_worker, args=(_REFRESH,), name='NuvioCatalogRefresh', daemon=True).start()
        return _REFRESH


def playback_busy():
    """A video is starting or playing (trailer previews do not count). Background
    catalog/artwork work waits so it never competes with the stream."""
    try:
        import xbmc
        import xbmcgui
        home = xbmcgui.Window(10000)
        if home.getProperty('nuvio.loading.active'):
            return True
        return xbmc.Player().isPlayingVideo() and not home.getProperty('nuvio.preview.active')
    except Exception:
        return False


def foreground_busy():
    """A catalog the user is waiting for is loading (or just finished)."""
    return _FOREGROUND[0] > 0 or time.monotonic() - _FOREGROUND[1] < FOREGROUND_QUIET


def _refresh_worker(jobs):
    while True:
        provider, catalog_row, extra, timeout = jobs.get()
        # Background revalidation always yields: it shares each host's rate
        # limit with the pages the user is opening.
        while playback_busy() or foreground_busy():
            time.sleep(.5)
        try:
            catalog(provider, catalog_row, extra, timeout, force=True)
        except Exception:
            pass  # The stale page stays usable; the next open retries.


def refresh(provider, catalog_row, extra=None, timeout=5):
    """Queue one background revalidation. Duplicate or overflow requests are dropped."""
    identity = catalog_key(provider, catalog_row, extra)
    with _FLIGHT_LOCK:
        if identity in _FLIGHTS:
            return False
    try:
        _refresher().put_nowait((provider, catalog_row, extra or {}, timeout))
        return True
    except queue.Full:
        return False


def catalog(provider, catalog, extra=None, timeout=5, force=False):
    """Fresh or stale cached page at once; network only on a miss or ``force``."""
    from concurrent.futures import Future
    from .nuviohub.client import fetch_catalog
    identity = catalog_key(provider, catalog, extra)
    cache = instance()
    if not force:
        hit, fresh = cache.lookup(identity)
        if hit is not None:
            if not fresh:
                refresh(provider, catalog, extra, timeout)
            return hit
    with _FLIGHT_LOCK:
        pending = _FLIGHTS.get(identity)
        owner = pending is None
        if owner:
            pending = Future()
            _FLIGHTS[identity] = pending
    if not owner:
        if force:
            return None
        return json.loads(json.dumps(pending.result(timeout=max(1, timeout) + 1), ensure_ascii=False))
    try:
        # A previous owner might have populated the cache just before this lock.
        data = None if force else cache.get(identity)
        if data is None:
            if not force:
                _FOREGROUND[0] += 1
            try:
                data = fetch_catalog(provider, catalog['type'], catalog['id'], extra=extra or {},
                                     timeout_override=timeout, retry=False, rate_wait=.1)
            finally:
                if not force:
                    _FOREGROUND[0] -= 1
                    _FOREGROUND[1] = time.monotonic()
            _store(cache, identity, data, extra)
        pending.set_result(data)
        return data
    except Exception as exc:
        pending.set_exception(exc)
        raise
    finally:
        with _FLIGHT_LOCK:
            if _FLIGHTS.get(identity) is pending:
                _FLIGHTS.pop(identity, None)
