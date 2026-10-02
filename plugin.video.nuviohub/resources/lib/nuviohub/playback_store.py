# -*- coding: utf-8 -*-
import os
import sqlite3
import threading
import time

from .common import profile_path, WATCHED_PERCENT

DB_PATH = os.path.join(profile_path(), 'playback.db')
_DB_READY = False
_DB_LOCK = threading.RLock()


_ID_COLUMNS = (
    ('tmdb_id', 'TEXT'),
    ('imdb_id', 'TEXT'),
    ('tvdb_id', 'TEXT'),
    # Episode rows normally carry the series TMDb id.  Keep it separately so
    # a TMDb Helper episode handoff can match even when a provider uses an
    # opaque id for both canonical_id and video_id.
    ('show_tmdb_id', 'TEXT'),
    # Native server identity lets Continue Watching reopen the exact Plex or
    # Emby object even when a translated show title has no usable external ID.
    ('native_server_id', 'TEXT'),
    ('native_item_id', 'TEXT'),
)


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
    except Exception:
        pass
    return conn


def _ensure_db():
    global _DB_READY
    if _DB_READY:
        return
    # Kodi can keep the plugin interpreter alive and invoke it from more than
    # one thread.  Serialising the one-time migration prevents concurrent
    # ALTER TABLE calls on slower CoreELEC/Android storage.
    with _DB_LOCK:
        if _DB_READY:
            return
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS playback (
                    media_type TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    title TEXT,
                    provider_name TEXT,
                    poster TEXT,
                    background TEXT,
                    clearlogo TEXT,
                    season INTEGER,
                    episode INTEGER,
                    position REAL,
                    duration REAL,
                    percent REAL,
                    stream_url TEXT,
                    event_type TEXT,
                    updated_at INTEGER,
                    tmdb_id TEXT,
                    imdb_id TEXT,
                    tvdb_id TEXT,
                    show_tmdb_id TEXT,
                    native_server_id TEXT,
                    native_item_id TEXT,
                    PRIMARY KEY (media_type, canonical_id, video_id)
                )
                """
            )
            # Existing installations already have the original table.  SQLite
            # migrations are additive, so no Continue Watching rows are lost.
            columns = set(row[1] for row in conn.execute('PRAGMA table_info(playback)').fetchall())
            for name, kind in _ID_COLUMNS:
                if name not in columns:
                    conn.execute('ALTER TABLE playback ADD COLUMN %s %s' % (name, kind))
            conn.execute('CREATE INDEX IF NOT EXISTS idx_playback_updated ON playback(updated_at DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_playback_percent ON playback(percent)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_playback_imdb ON playback(imdb_id, updated_at DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_playback_tmdb ON playback(tmdb_id, updated_at DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_playback_show_tmdb ON playback(show_tmdb_id, season, episode, updated_at DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_playback_tvdb ON playback(tvdb_id, updated_at DESC)')
            # Repair 6.0.9 cloud timestamps written as milliseconds into a seconds column.
            conn.execute('UPDATE playback SET updated_at=updated_at/1000.0 WHERE updated_at>=100000000000')
            from resources.lib.nuvio_progress import ensure
            ensure(conn)
            # Older cloud imports used 'tv' while local playback uses 'series'.
            cursor=conn.execute("SELECT * FROM playback WHERE media_type='tv'")
            names=[column[0] for column in cursor.description]
            for values in cursor.fetchall():
                row=dict(zip(names, values))
                old=(row['media_type'], row['canonical_id'], row['video_id'])
                row['media_type']='series';row['ext_updated_at']=row.get('updated_at')
                if row.get('duration') and row.get('event_type')=='account_sync':
                    row['percent']=min(100, max(0, 100*float(row.get('position') or 0)/float(row['duration'])))
                conn.execute(_UPSERT_SQL, _upsert_params(conn, row))
                conn.execute('DELETE FROM playback WHERE media_type=? AND canonical_id=? AND video_id=?',old)

            conn.commit()
            _DB_READY = True
        finally:
            conn.close()


_UPSERT_SQL = """
        INSERT INTO playback (
            media_type, canonical_id, video_id, title, provider_name, poster, background, clearlogo,
            season, episode, position, duration, percent, stream_url, event_type, updated_at,
            tmdb_id, imdb_id, tvdb_id, show_tmdb_id
            , native_server_id, native_item_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(media_type, canonical_id, video_id)
        DO UPDATE SET
            title=CASE WHEN lower(trim(excluded.title)) NOT IN ('', 'unknown', 'untitled') THEN excluded.title ELSE playback.title END,
            provider_name=CASE WHEN excluded.provider_name != '' THEN excluded.provider_name ELSE playback.provider_name END,
            poster=CASE WHEN excluded.poster != '' THEN excluded.poster ELSE playback.poster END,
            background=CASE WHEN excluded.background != '' THEN excluded.background ELSE playback.background END,
            clearlogo=CASE WHEN excluded.clearlogo != '' THEN excluded.clearlogo ELSE playback.clearlogo END,
            season=excluded.season,
            episode=excluded.episode,
            position=CASE WHEN excluded.duration<=0 AND playback.duration>0 THEN playback.duration*excluded.percent/100.0 ELSE excluded.position END,
            duration=CASE WHEN excluded.duration>0 THEN excluded.duration ELSE playback.duration END,
            percent=excluded.percent,
            stream_url=excluded.stream_url,
            event_type=excluded.event_type,
            updated_at=excluded.updated_at,
            tmdb_id=CASE WHEN excluded.tmdb_id != '' THEN excluded.tmdb_id ELSE playback.tmdb_id END,
            imdb_id=CASE WHEN excluded.imdb_id != '' THEN excluded.imdb_id ELSE playback.imdb_id END,
            tvdb_id=CASE WHEN excluded.tvdb_id != '' THEN excluded.tvdb_id ELSE playback.tvdb_id END,
            show_tmdb_id=CASE WHEN excluded.show_tmdb_id != '' THEN excluded.show_tmdb_id ELSE playback.show_tmdb_id END,
            native_server_id=CASE WHEN excluded.native_server_id != '' THEN excluded.native_server_id ELSE playback.native_server_id END,
            native_item_id=CASE WHEN excluded.native_item_id != '' THEN excluded.native_item_id ELSE playback.native_item_id END
        WHERE excluded.updated_at >= playback.updated_at
"""


def _mark_sync_dirty():
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty('nuviohub.sync_dirty', str(time.time_ns()))
    except Exception:
        pass


def _upsert_params(conn, row):
    media_type = row.get('media_type') or ''
    if media_type in ('tv', 'show', 'tvshow', 'episode'):media_type='series'
    canonical_id = row.get('canonical_id') or ''
    video_id = row.get('video_id') or ''
    ext_updated_at = row.get('ext_updated_at')
    try:
        from resources.lib.progress_model import timestamp
        ts = timestamp(ext_updated_at) if ext_updated_at is not None else time.time()
    except Exception:
        ts = time.time()
    # We avoid clobbering updated_at on no-op local updates: when the new
    # position and completion state are unchanged, keep the existing timestamp.
    # A 30-second tolerance froze recency forever with 15-second heartbeats.
    existing = None
    if ext_updated_at is None:
        existing = conn.execute(
            "SELECT position, updated_at, event_type FROM playback WHERE media_type=? AND canonical_id=? AND video_id=?",
            (media_type, canonical_id, video_id),
        ).fetchone()
    if existing:
        try:
            if abs(float(row.get('position') or 0.0) - float(existing[0] or 0.0)) < 0.01 and (row.get('event_type') or '') == existing[2]:
                ts = float(existing[1] or ts)
        except Exception:
            pass
    return (
        media_type, canonical_id, video_id, row.get('title') or '',
        row.get('provider_name') or '', row.get('poster') or '',
        row.get('background') or '', row.get('clearlogo') or '',
        row.get('season'), row.get('episode'), row.get('position') or 0.0,
        row.get('duration') or 0.0, row.get('percent') or 0.0,
        row.get('stream_url') or '', row.get('event_type') or '', ts,
        str(row.get('tmdb_id') or '').strip(),
        str(row.get('imdb_id') or '').strip().lower(),
        str(row.get('tvdb_id') or '').strip(),
        str(row.get('show_tmdb_id') or '').strip(),
        str(row.get('native_server_id') or '').strip(),
        str(row.get('native_item_id') or '').strip(),
    )


def upsert_entries(entries, mark_dirty=True):
    """Write many progress rows in one SQLite transaction.

    Remote account imports previously called :func:`upsert_entry` hundreds of
    times.  That meant one connection, WAL setup and commit per row and also
    raised ``sync_dirty`` for every row pulled from the cloud.  This bulk path
    performs one connection/commit and lets imports suppress the feedback
    flag while local playback writes retain event-driven sync.
    """
    rows = [dict(row) for row in (entries or []) if isinstance(row, dict)]
    if not rows:
        return 0
    _ensure_db()
    changed = 0
    from resources.lib import nuvio_progress
    account = nuvio_progress.scope() if mark_dirty else ''
    with _DB_LOCK:
        conn = _connect()
        try:
            for row in rows:
                if not (row.get('canonical_id') or row.get('video_id')):
                    continue
                values = _upsert_params(conn, row)
                cursor = conn.execute(_UPSERT_SQL, values)
                if mark_dirty and cursor.rowcount and account:
                    queued = dict(row, media_type=values[0], updated_at=values[15])
                    nuvio_progress.queue(conn, queued, account=account)
                try:
                    changed += max(0, int(cursor.rowcount or 0))
                except Exception:
                    changed += 1
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()
    if changed and mark_dirty:
        _mark_sync_dirty()
    return changed


def upsert_entry(media_type, canonical_id, video_id, title, provider_name,
                 poster, background, clearlogo, season, episode, position,
                 duration, percent, stream_url, event_type,
                 ext_updated_at=None, tmdb_id='', imdb_id='', tvdb_id='',
                 show_tmdb_id='', native_server_id='', native_item_id='',
                 mark_dirty=True):
    """Insert/update one row; local playback remains dirty-event driven."""
    return upsert_entries([{
        'media_type': media_type, 'canonical_id': canonical_id,
        'video_id': video_id, 'title': title,
        'provider_name': provider_name, 'poster': poster,
        'background': background, 'clearlogo': clearlogo,
        'season': season, 'episode': episode, 'position': position,
        'duration': duration, 'percent': percent, 'stream_url': stream_url,
        'event_type': event_type, 'ext_updated_at': ext_updated_at,
        'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': tvdb_id,
        'show_tmdb_id': show_tmdb_id,
        'native_server_id': native_server_id,
        'native_item_id': native_item_id,
    }], mark_dirty=mark_dirty)


def update_art(media_type, canonical_id, video_id, poster='', background='', clearlogo=''):
    """Update artwork only without touching updated_at so Continue Watching
    ordering stays stable until the user actually watches something new."""
    _ensure_db()
    conn = _connect()
    conn.execute(
        """
        UPDATE playback
        SET
            poster=CASE WHEN ? != '' THEN ? ELSE poster END,
            background=CASE WHEN ? != '' THEN ? ELSE background END,
            clearlogo=CASE WHEN ? != '' THEN ? ELSE clearlogo END
        WHERE media_type=? AND canonical_id=? AND video_id=?
        """,
        (
            poster or '', poster or '',
            background or '', background or '',
            clearlogo or '', clearlogo or '',
            media_type or '', canonical_id or '', video_id or '',
        ),
    )
    conn.commit()
    conn.close()


def update_metadata(media_type, canonical_id, video_id, title='', poster='', background='', clearlogo=''):
    """Repair display data only. Never reorder progress or mark it dirty for cloud sync."""
    _ensure_db()
    if str(title).strip().lower() in ('unknown','untitled','loading title…'):title=''
    with _DB_LOCK:
        conn=_connect()
        try:
            conn.execute('''UPDATE playback SET
                title=CASE WHEN ? != '' THEN ? ELSE title END,
                poster=CASE WHEN ? != '' THEN ? ELSE poster END,
                background=CASE WHEN ? != '' THEN ? ELSE background END,
                clearlogo=CASE WHEN ? != '' THEN ? ELSE clearlogo END
                WHERE media_type=? AND canonical_id=? AND video_id=?''',
                (title,title,poster,poster,background,background,clearlogo,clearlogo,media_type,canonical_id,video_id))
            conn.commit()
        finally:conn.close()


def list_continue_items(limit=50):
    # Pick the latest episode before filtering completion. Otherwise an older
    # unfinished episode resurfaces after a newer episode has been watched.
    out=[];seen=set()
    for row in list_recent_items(limit=max(200,int(limit)*8)):
        if not row.get('position') and row.get('event_type')!='watched' and float(row.get('percent') or 0)<=0:continue
        key=('movie' if row.get('media_type')=='movie' else 'series',row['canonical_id'])
        if key in seen:continue
        seen.add(key)
        if float(row.get('percent') or 0)>=WATCHED_PERCENT or row.get('event_type')=='watched':continue
        out.append(row)
        if len(out)>=limit:break
    return out


def list_recent_items(limit=200, media_types=None, include_watched=True):
    """Return recent playback rows without forcing the Continue Watching filter.

    Used by Next Up and diagnostics where fully watched episodes must remain
    visible as the base for finding the *next* episode.
    """
    _ensure_db()
    conn = _connect()
    where = []
    params = []
    if media_types:
        mts = [str(x or '').strip().lower() for x in media_types if str(x or '').strip()]
        if mts:
            where.append('media_type IN (%s)' % ','.join(['?'] * len(mts)))
            params.extend(mts)
    if not include_watched:
        where.append('percent < 95.0')
    sql = """
        SELECT media_type, canonical_id, video_id, title, provider_name, poster, background, clearlogo,
               season, episode, position, duration, percent, updated_at, event_type, stream_url,
               tmdb_id, imdb_id, tvdb_id, show_tmdb_id, native_server_id, native_item_id
        FROM playback
    """
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += " ORDER BY updated_at DESC, title COLLATE NOCASE ASC, canonical_id ASC, video_id ASC LIMIT ?"
    params.append(int(limit or 200))
    rows = conn.execute(sql, tuple(params)).fetchall()
    conn.close()
    out = []
    for row in rows:
        out.append({
            'media_type': row[0], 'canonical_id': row[1], 'video_id': row[2], 'title': row[3],
            'provider_name': row[4], 'poster': row[5], 'background': row[6], 'clearlogo': row[7],
            'season': row[8], 'episode': row[9], 'position': row[10], 'duration': row[11],
            'percent': row[12], 'updated_at': row[13], 'event_type': row[14], 'stream_url': row[15],
            'tmdb_id': row[16], 'imdb_id': row[17], 'tvdb_id': row[18], 'show_tmdb_id': row[19],
            'native_server_id': row[20], 'native_item_id': row[21],
        })
    return out


def _row_to_dict(row):
    return {
        'media_type': row[0], 'canonical_id': row[1], 'video_id': row[2], 'title': row[3],
        'provider_name': row[4], 'poster': row[5], 'background': row[6], 'clearlogo': row[7],
        'season': row[8], 'episode': row[9], 'position': row[10], 'duration': row[11],
        'percent': row[12], 'updated_at': row[13], 'tmdb_id': row[14], 'imdb_id': row[15],
        'tvdb_id': row[16], 'show_tmdb_id': row[17],
        'native_server_id': row[18], 'native_item_id': row[19],
    }


def find_resume_entry(media_type='movie', canonical_id='', tmdb_id='', imdb_id='', tvdb_id='', season=None, episode=None):
    """Return the best unfinished row for a TMDb Helper playback request.

    The priority is deliberate: IMDb is globally stable, then TMDb (the show
    id is also checked for episodes), then TVDb, then Nuvio Hub's legacy
    provider/canonical ids.  Each query is indexed and only asks SQLite for a
    single row, avoiding the old full scan of the latest 500 records.
    """
    _ensure_db()
    mt = str(media_type or 'movie').strip().lower()
    is_episode = mt in ('series', 'anime', 'show', 'tv') or (season not in (None, '', 0, '0') and episode not in (None, '', 0, '0'))
    try:
        season_i = int(season or 0)
        episode_i = int(episode or 0)
    except Exception:
        season_i, episode_i = 0, 0
    base = ['percent < 95.0', '(position > 30.0 OR percent > 1.0)']
    params = []
    if is_episode:
        base.extend(['season=?', 'episode=?'])
        params.extend([season_i, episode_i])
    else:
        base.append("media_type IN ('movie', 'movies', '')")
    select = """
        SELECT media_type, canonical_id, video_id, title, provider_name, poster, background, clearlogo,
               season, episode, position, duration, percent, updated_at,
               tmdb_id, imdb_id, tvdb_id, show_tmdb_id, native_server_id, native_item_id
        FROM playback WHERE %s AND %%s
        ORDER BY updated_at DESC LIMIT 1
    """ % ' AND '.join(base)
    matches = []
    imdb = str(imdb_id or '').strip().lower()
    if imdb.lower().startswith('imdb:'):
        imdb = imdb.split(':', 1)[1].strip()
    if imdb.isdigit():
        imdb = 'tt%s' % imdb
    if imdb:
        matches.append(('LOWER(imdb_id)=?', [imdb]))
    tmdb = str(tmdb_id or '').strip()
    if tmdb:
        matches.append(('(tmdb_id=? OR show_tmdb_id=?)', [tmdb, tmdb]))
    tvdb = str(tvdb_id or '').strip()
    if tvdb:
        matches.append(('tvdb_id=?', [tvdb]))
    canonical = str(canonical_id or '').strip()
    if canonical:
        matches.append(('(canonical_id=? OR video_id=?)', [canonical, canonical]))
    if not matches:
        return None
    conn = _connect()
    try:
        for clause, values in matches:
            row = conn.execute(select % clause, tuple(params + values)).fetchone()
            if row:
                return _row_to_dict(row)
    finally:
        conn.close()
    return None


def _mutate_progress(media_type, canonical_id, video_id, operation, mark_dirty=True):
    from resources.lib import nuvio_progress
    import json
    _ensure_db()
    account = nuvio_progress.scope() if mark_dirty else ''
    conn = _connect()
    changed = False
    try:
        cursor = conn.execute('SELECT * FROM playback WHERE media_type=? AND canonical_id=? AND video_id=?',
                              (media_type or '', canonical_id or '', video_id or ''))
        names = [item[0] for item in cursor.description]
        values = cursor.fetchone()
        if values:
            row = dict(zip(names, values))
            row['updated_at'] = time.time()
            if operation == 'delete':
                conn.execute('DELETE FROM playback WHERE media_type=? AND canonical_id=? AND video_id=?', (media_type, canonical_id, video_id))
            else:
                row.update(percent=100.0, position=row.get('duration') or row.get('position') or 0, event_type='watched')
                conn.execute("UPDATE playback SET percent=100.0, position=CASE WHEN duration>0 THEN duration ELSE position END, event_type='watched', updated_at=? WHERE media_type=? AND canonical_id=? AND video_id=?", (row['updated_at'], media_type, canonical_id, video_id))
            if mark_dirty:
                nuvio_progress.queue(conn, row, operation=operation, account=account)
                exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nuvio_continue'").fetchone()
                if exists:
                    for key, raw in conn.execute('SELECT identity,payload FROM nuvio_continue').fetchall():
                        local = json.loads(raw)
                        if local.get('canonical_id') == canonical_id and local.get('video_id') == video_id:
                            local.update(percent=100, event_type='removed' if operation=='delete' else 'watched', updated_at=row['updated_at'])
                            conn.execute('UPDATE nuvio_continue SET updated=?,payload=? WHERE identity=?', (row['updated_at'], json.dumps(local), key))
            changed = True
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if changed and mark_dirty:
        _mark_sync_dirty()
        from resources.lib.simkl_watched import _invalidate_view
        _invalidate_view()
    return changed


def delete_entry(media_type, canonical_id, video_id, mark_dirty=True):
    return _mutate_progress(media_type, canonical_id, video_id, 'delete', mark_dirty)


def mark_watched(media_type, canonical_id, video_id, mark_dirty=True):
    return _mutate_progress(media_type, canonical_id, video_id, 'upsert', mark_dirty)


_WATCHED_MEM={}
def watched_snapshot():
    """Account-independent local completion, cached until SQLite changes."""
    _ensure_db()
    def stamp(path):
        try:return os.stat(path).st_mtime_ns
        except OSError:return 0
    stamp_key=(DB_PATH,stamp(DB_PATH),stamp(DB_PATH+'-wal'))
    if _WATCHED_MEM.get('key')==stamp_key:return _WATCHED_MEM['items']
    conn=_connect()
    try:rows=conn.execute("SELECT media_type,canonical_id,season,episode,imdb_id,tmdb_id,tvdb_id FROM playback WHERE percent>=? OR event_type='watched'",(WATCHED_PERCENT,)).fetchall()
    finally:conn.close()
    items={}
    for media,mid,season,episode,imdb,tmdb,tvdb in rows:
        movie=media=='movie';prefix='movie|' if movie else 'series|'
        mids={mid}
        if imdb:mids.add(imdb if str(imdb).startswith('tt') else 'tt'+str(imdb))
        if tmdb:mids.add('tmdb:'+str(tmdb))
        if tvdb:mids.add('tvdb:'+str(tvdb))
        for identity in mids:
            entry=items.setdefault(prefix+str(identity),{'watched':False,'seasons':[],'episodes':[]})
            if movie:entry['watched']=True
            elif season is not None and episode is not None:
                marker='%s:%s'%(season,episode)
                if marker not in entry['episodes']:entry['episodes'].append(marker)
    _WATCHED_MEM.update(key=stamp_key,items=items)
    return items
