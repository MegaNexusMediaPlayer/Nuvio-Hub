"""Durable per-account/profile progress mutations; no upload of unrelated history."""
import hashlib
import json
import time
import uuid
from . import progress_model

FIELDS = ('media_type', 'canonical_id', 'video_id', 'season', 'episode', 'position',
          'duration', 'percent', 'event_type', 'updated_at', 'imdb_id', 'tmdb_id')


def scope():
    from nuviohub.nuvio_stremio_sync import Nuvio
    token = Nuvio.token()
    user = token.get('user_id') or str(token.get('email') or '').casefold()
    profile = token.get('profile_index')
    if not token.get('access_token') or not user or not profile:
        return ''
    return hashlib.sha256(('%s|%s' % (user, profile)).encode('utf-8')).hexdigest()


def ensure(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS nuvio_progress_outbox (scope TEXT NOT NULL, identity TEXT NOT NULL, version TEXT NOT NULL, updated REAL NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(scope,identity))')


def queue(conn, row, operation='upsert', account=None):
    account = scope() if account is None else account
    if not account or not progress_model.canonical(row):
        return False
    value = {k: row[k] for k in FIELDS if k in row}
    value.update(_operation=operation)
    identity = json.dumps(progress_model.identity(value), ensure_ascii=False)
    ensure(conn)
    conn.execute('INSERT OR REPLACE INTO nuvio_progress_outbox VALUES(?,?,?,?,?)',
                 (account, identity, uuid.uuid4().hex, progress_model.timestamp(value.get('updated_at')) or time.time(), json.dumps(value, ensure_ascii=False)))
    return True


def pending(limit=200):
    account = scope()
    if not account:
        return []
    from nuviohub import playback_store
    playback_store._ensure_db()
    conn = playback_store._connect()
    try:
        ensure(conn)
        rows = conn.execute('SELECT identity,version,payload FROM nuvio_progress_outbox WHERE scope=? ORDER BY updated LIMIT ?', (account, max(1, min(1000, int(limit))))).fetchall()
        conn.commit()
        return [dict(json.loads(raw), _outbox_identity=identity, _outbox_version=version, _outbox_scope=account) for identity, version, raw in rows]
    finally:
        conn.close()


def acknowledge(rows, account):
    if not account or scope() != account:
        return
    from nuviohub import playback_store
    conn = playback_store._connect()
    try:
        ensure(conn)
        for row in rows:
            if row.get('_outbox_scope') != account:
                continue
            # A new heartbeat saved during HTTP must remain queued.
            conn.execute('DELETE FROM nuvio_progress_outbox WHERE scope=? AND identity=? AND version=?',
                         (account, row.get('_outbox_identity'), row.get('_outbox_version')))
        conn.commit()
    finally:
        conn.close()
