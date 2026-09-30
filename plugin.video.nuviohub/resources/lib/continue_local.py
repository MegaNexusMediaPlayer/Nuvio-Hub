"""The last 50 locally played titles, committed before any cloud request.

Separate from imported history: a stale watched snapshot cannot erase a new
local resume. Completed entries act as tombstones against older cloud progress.
"""
import json
import time
from dexhub import playback_store as db

_FIELDS = ('media_type', 'canonical_id', 'video_id', 'title', 'show_title',
           'season', 'episode', 'poster', 'background', 'clearlogo',
           'imdb_id', 'tmdb_id', 'tvdb_id', 'provider_name', 'plot', 'year')


def connect():
    db._ensure_db()
    conn = db._connect()
    conn.execute('CREATE TABLE IF NOT EXISTS nuvio_continue (identity TEXT PRIMARY KEY, updated REAL NOT NULL, payload TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS nuvio_simkl_outbox (account TEXT, identity TEXT, updated REAL, payload TEXT, PRIMARY KEY(account, identity))')
    return conn


def identity(ctx):
    kind = 'movie' if ctx.get('media_type') == 'movie' else 'series'
    return kind + '|' + str(ctx.get('canonical_id') or '')


def save(ctx, position, duration, finished=False):
    if not ctx.get('canonical_id') or position < 1:
        return
    value = {k: ctx[k] for k in _FIELDS if k in ctx}
    value.update(position=position, duration=duration,
                 percent=100 if finished else min(100, position * 100 / duration) if duration else 0,
                 event_type='watched' if finished else 'progress', updated_at=time.time())
    conn = connect()
    try:
        conn.execute('INSERT OR REPLACE INTO nuvio_continue VALUES (?, ?, ?)',
                     (identity(ctx), value['updated_at'], json.dumps(value)))
        conn.execute('DELETE FROM nuvio_continue WHERE identity NOT IN (SELECT identity FROM nuvio_continue ORDER BY updated DESC LIMIT 50)')
        conn.commit()
    finally:
        conn.close()
    # Queue only, never HTTP on the player/clock thread. No stream URLs/tokens stored.
    from . import simkl
    simkl.queue_progress(dict(value, duration_ms=duration * 1000), (duration if finished else position) * 1000, 'stop' if finished else 'pause')


def recent():
    conn = connect()
    try:
        return [json.loads(r[0]) for r in conn.execute('SELECT payload FROM nuvio_continue ORDER BY updated DESC LIMIT 50')]
    finally:
        conn.close()


def complete_matching(mids, media, scope='title', season=None, episode=None):
    """An explicit, confirmed Mark watched also removes the local resume."""
    from . import simkl
    conn=connect()
    try:
        for key,raw in conn.execute('SELECT identity,payload FROM nuvio_continue').fetchall():
            row=json.loads(raw)
            if row.get('canonical_id') not in mids:continue
            if ('movie' if row.get('media_type')=='movie' else 'series')!=media:continue
            if scope in ('season','episode') and str(row.get('season'))!=str(season):continue
            if scope=='episode' and str(row.get('episode'))!=str(episode):continue
            row.update(percent=100,event_type='watched',updated_at=time.time())
            conn.execute('UPDATE nuvio_continue SET updated=?,payload=? WHERE identity=?',(row['updated_at'],json.dumps(row),key))
            conn.execute('DELETE FROM nuvio_simkl_outbox WHERE account=? AND identity=?',(simkl._progress_account(),key))
            if media=='series':
                prefix=key+'|'
                if scope in ('season','episode'):prefix+=str(season)+':'
                if scope=='episode':
                    conn.execute('DELETE FROM nuvio_simkl_outbox WHERE account=? AND identity=?',(simkl._progress_account(),prefix+str(episode)))
                else:
                    conn.execute('DELETE FROM nuvio_simkl_outbox WHERE account=? AND substr(identity,1,?)=?',(simkl._progress_account(),len(prefix),prefix))
        conn.commit()
    finally:conn.close()
