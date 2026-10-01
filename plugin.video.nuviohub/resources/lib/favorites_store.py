# -*- coding: utf-8 -*-
"Local favorites store.\n\nLightweight SQLite-backed favourites/watchlist for users who don't have Trakt\nlinked, AND a stable mirror cache for users who do (so the home-screen\n\"\u0627\u0644\u0645\u0641\u0636\u0644\u0629\" row stays instant even when Trakt is slow/offline).\n\nSchema mirrors the Continue Watching shape so the same row-rendering code in\nplugin.py can consume both.\n"
import os
import sqlite3
import threading
import time
import xbmc

from .nuviohub.common import profile_path

DB_PATH = os.path.join(profile_path(), 'favorites.db')
_DB_READY = False
_DB_LOCK = threading.Lock()

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS favorites (
    media_type TEXT NOT NULL,
    canonical_id TEXT NOT NULL,
    title TEXT,
    poster TEXT,
    background TEXT,
    clearlogo TEXT,
    year INTEGER,
    plot TEXT,
    source TEXT NOT NULL DEFAULT 'local',
    added_at INTEGER,
    PRIMARY KEY (media_type, canonical_id, source)
)
"""


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=2.0)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
    except Exception:
        pass
    return conn


def _table_sql(conn, name):
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row[0] if row and row[0] else ''
    except Exception:
        return ''


def _needs_migration(conn):
    sql = (_table_sql(conn, 'favorites') or '').lower().replace('\n', ' ')
    if not sql:
        return False
    return 'primary key (media_type, canonical_id, source)' not in sql


def _migrate_schema(conn):
    if not _needs_migration(conn):
        return
    conn.execute('ALTER TABLE favorites RENAME TO favorites_legacy')
    conn.execute(CREATE_SQL)
    conn.execute(
        """
        INSERT OR REPLACE INTO favorites (
            media_type, canonical_id, title, poster, background,
            clearlogo, year, plot, source, added_at
        )
        SELECT
            media_type,
            canonical_id,
            title,
            poster,
            background,
            clearlogo,
            year,
            plot,
            COALESCE(NULLIF(source, ''), 'local') AS source,
            added_at
        FROM favorites_legacy
        """
    )
    conn.execute('DROP TABLE favorites_legacy')


def _ensure_db():
    global _DB_READY
    if _DB_READY:
        return
    with _DB_LOCK:
        if _DB_READY:
            return
        conn = _connect()
        try:
            if _table_sql(conn, 'favorites'):
                _migrate_schema(conn)
            else:
                conn.execute(CREATE_SQL)
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fav_added ON favorites(added_at DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fav_source ON favorites(source)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fav_identity ON favorites(media_type, canonical_id)')
            conn.commit()
        finally:
            conn.close()
        _DB_READY = True


def _mark_sync_dirty():
    """v4.8.2: tell the service a local change is waiting.

    The continuous sync loop wakes every 20s and syncs immediately when
    this flag is set, so a favourite added here reaches Nuvio in seconds
    instead of waiting for the next scheduled pull.
    """
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty('nuviohub.sync_dirty', '1')
    except Exception:
        pass


def add(media_type, canonical_id, title, poster='', background='', clearlogo='',
        year=0, plot='', source='local'):
    _ensure_db()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO favorites (media_type, canonical_id, title, poster, background,
                                   clearlogo, year, plot, source, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(media_type, canonical_id, source) DO UPDATE SET
                title=excluded.title,
                poster=CASE WHEN excluded.poster != '' THEN excluded.poster ELSE favorites.poster END,
                background=CASE WHEN excluded.background != '' THEN excluded.background ELSE favorites.background END,
                clearlogo=CASE WHEN excluded.clearlogo != '' THEN excluded.clearlogo ELSE favorites.clearlogo END,
                year=CASE WHEN excluded.year > 0 THEN excluded.year ELSE favorites.year END,
                plot=CASE WHEN excluded.plot != '' THEN excluded.plot ELSE favorites.plot END,
                added_at=excluded.added_at
            """,
            (media_type or 'movie', canonical_id or '', title or canonical_id or '',
             poster or '', background or '', clearlogo or '', int(year or 0),
             plot or '', source or 'local', int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()
    if (source or 'local') != 'nuvio':      # never echo a pulled row back
        _mark_sync_dirty()


def remove(media_type, canonical_id, source=None):
    _ensure_db()
    conn = _connect()
    try:
        if source:
            conn.execute(
                "DELETE FROM favorites WHERE media_type=? AND canonical_id=? AND source=?",
                (media_type or '', canonical_id or '', source or ''),
            )
        else:
            conn.execute(
                "DELETE FROM favorites WHERE media_type=? AND canonical_id=?",
                (media_type or '', canonical_id or ''),
            )
        conn.commit()
    finally:
        conn.close()
    _mark_sync_dirty()


def is_favorite(media_type, canonical_id):
    _ensure_db()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM favorites WHERE media_type=? AND canonical_id=? LIMIT 1",
            (media_type or '', canonical_id or ''),
        ).fetchone()
    finally:
        conn.close()
    return bool(row)




def favorite_keys():
    _ensure_db()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT media_type, canonical_id FROM favorites GROUP BY media_type, canonical_id"
        ).fetchall()
    finally:
        conn.close()
    return set((str(r[0] or ''), str(r[1] or '')) for r in rows or [])

def list_favorites(limit=200, source=None):
    _ensure_db()
    conn = _connect()
    try:
        if source:
            rows = conn.execute(
                """
                SELECT media_type, canonical_id, title, poster, background, clearlogo,
                       year, plot, source, added_at
                FROM favorites WHERE source=?
                ORDER BY added_at DESC LIMIT ?
                """,
                (source, limit),
            ).fetchall()
            return [{
                'media_type': row[0], 'canonical_id': row[1], 'title': row[2],
                'poster': row[3], 'background': row[4], 'clearlogo': row[5],
                'year': row[6], 'plot': row[7], 'source': row[8],
                'sources': [row[8]], 'added_at': row[9],
            } for row in rows]

        rows = conn.execute(
            """
            SELECT media_type, canonical_id, title, poster, background, clearlogo,
                   year, plot, source, added_at
            FROM favorites
            ORDER BY added_at DESC, CASE WHEN source='local' THEN 0 ELSE 1 END
            """
        ).fetchall()
    finally:
        conn.close()

    out = []
    seen = {}
    for row in rows:
        media_type, canonical_id = row[0], row[1]
        key = (media_type, canonical_id)
        source_name = row[8] or 'local'
        payload = {
            'media_type': media_type,
            'canonical_id': canonical_id,
            'title': row[2],
            'poster': row[3],
            'background': row[4],
            'clearlogo': row[5],
            'year': row[6],
            'plot': row[7],
            'source': source_name,
            'sources': [source_name],
            'added_at': row[9],
        }
        existing = seen.get(key)
        if not existing:
            seen[key] = payload
            out.append(payload)
            continue
        sources = set(existing.get('sources') or [])
        sources.add(source_name)
        existing['sources'] = sorted(sources)
        if source_name != existing.get('source'):
            existing['source'] = 'mixed'
        for field in ('title', 'poster', 'background', 'clearlogo', 'year', 'plot'):
            if not existing.get(field) and payload.get(field):
                existing[field] = payload.get(field)
        existing['added_at'] = max(int(existing.get('added_at') or 0), int(payload.get('added_at') or 0))

    out.sort(key=lambda row: int(row.get('added_at') or 0), reverse=True)
    if limit:
        return out[: max(0, int(limit or 0))]
    return out


def replace_trakt_mirror(rows):
    """Replace ALL trakt-sourced rows with the latest snapshot from Trakt.

    `rows` is a list of dicts with keys matching `add()` parameters. Local
    rows are untouched; we only rewrite the trakt mirror so disabling Trakt
    or removing items from your Trakt watchlist is reflected in Nuvio Hub.
    """
    _ensure_db()
    conn = _connect()
    try:
        conn.execute("DELETE FROM favorites WHERE source='trakt'")
        for row in rows or []:
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO favorites (media_type, canonical_id, title,
                        poster, background, clearlogo, year, plot, source, added_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'trakt', ?)
                    """,
                    (
                        row.get('media_type') or 'movie',
                        row.get('canonical_id') or '',
                        row.get('title') or row.get('canonical_id') or '',
                        row.get('poster') or '',
                        row.get('background') or '',
                        row.get('clearlogo') or '',
                        int(row.get('year') or 0),
                        row.get('plot') or '',
                        int(row.get('added_at') or time.time()),
                    ),
                )
            except Exception:
                continue
        conn.commit()
    finally:
        conn.close()


def count(source=None):
    _ensure_db()
    conn = _connect()
    try:
        if source:
            n = conn.execute(
                'SELECT COUNT(*) FROM (SELECT 1 FROM favorites WHERE source=? GROUP BY media_type, canonical_id)',
                (source,),
            ).fetchone()[0]
        else:
            n = conn.execute(
                'SELECT COUNT(*) FROM (SELECT 1 FROM favorites GROUP BY media_type, canonical_id)'
            ).fetchone()[0]
    finally:
        conn.close()
    return int(n or 0)


def refresh_external_mirror(include_trakt=True):
    """Merge Trakt + Simkl (plan to watch) + MDBList watchlists into one
    mirror snapshot (v4.2.0). Lives here — not in plugin.py — because BOTH
    the plugin process and the background service write this mirror; when the
    service wrote a trakt-only snapshot it silently erased the other
    services' rows every sync cycle. Per-service failures are silent and
    independent; toggles: watchlist_merge_simkl / watchlist_merge_mdblist.
    """
    import xbmcaddon

    def _flag(key, default='true'):
        try:
            return (xbmcaddon.Addon('plugin.video.nuviohub').getSetting(key) or default).strip().lower() == 'true'
        except Exception:
            return default == 'true'

    combined, seen = [], set()

    def _extend(rows):
        for row in rows or []:
            key = (row.get('media_type'), row.get('canonical_id'))
            if not key[1] or key in seen:
                continue
            seen.add(key)
            combined.append(row)

    if include_trakt:
        try:
            from . import trakt as _trakt
            if _trakt.enabled():
                _extend(_trakt.fetch_watchlist(limit=200) or [])
        except Exception as exc:
            xbmc.log('[NuvioHub] watchlist mirror (trakt) failed: %s' % exc, xbmc.LOGDEBUG)
    try:
        from . import simkl as _simkl
        if _simkl.enabled() and _simkl.authorized() and _flag('watchlist_merge_simkl'):
            _extend(_simkl.watchlist_mirror_rows(limit=200))
    except Exception as exc:
        xbmc.log('[NuvioHub] watchlist mirror (simkl) failed: %s' % exc, xbmc.LOGDEBUG)
    try:
        from . import mdblist as _mdblist
        if _mdblist.configured() and _flag('watchlist_merge_mdblist'):
            _extend(_mdblist.watchlist_mirror_rows(limit=200))
    except Exception as exc:
        xbmc.log('[NuvioHub] watchlist mirror (mdblist) failed: %s' % exc, xbmc.LOGDEBUG)
    replace_trakt_mirror(combined)
    return len(combined)
