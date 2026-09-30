# -*- coding: utf-8 -*-
import json
import re
import sqlite3
from functools import lru_cache

import xbmcvfs

# Bug fix: previously every image (poster/fanart/logo) was fetched at
# /t/p/original — full-resolution 2000+px files (often 500KB-2MB each)
# downloaded just to be displayed in a 320x480 poster slot. Use TMDb's
# CDN-served sized variants to drop bandwidth ~95% with no visible
# quality loss for Kodi display sizes.
_TMDB_IMAGE_BASE_POSTER = 'https://image.tmdb.org/t/p/w500'
_TMDB_IMAGE_BASE_BACKDROP = 'https://image.tmdb.org/t/p/w1280'
_TMDB_IMAGE_BASE_LOGO = 'https://image.tmdb.org/t/p/w500'
# Backwards-compatible alias for any external caller that imports the old name.
_TMDB_IMAGE_BASE = _TMDB_IMAGE_BASE_POSTER
_DB_PATHS = [
    'special://userdata/addon_data/plugin.video.themoviedb.helper/database_10/ItemDetails.db',
    'special://userdata/addon_data/plugin.video.themoviedb.helper/database_09/ItemDetails.db',
    'special://userdata/addon_data/plugin.video.themoviedb.helper/database_08/ItemDetails.db',
    'special://userdata/addon_data/plugin.video.themoviedb.helper/database_07/ItemDetails.db',
    'special://userdata/addon_data/plugin.video.themoviedb.helper/database_06/ItemDetails.db',
    'special://userdata/addon_data/plugin.video.themoviedb.helper/database_05/ItemDetails.db',
]
_CACHE = {}
_CACHE_ORDER = []
_CACHE_MAX = 1024


def _cache_put(key, value):
    if key in _CACHE:
        return
    _CACHE[key] = value
    _CACHE_ORDER.append(key)
    if len(_CACHE_ORDER) > _CACHE_MAX:
        old = _CACHE_ORDER.pop(0)
        _CACHE.pop(old, None)


@lru_cache(maxsize=1)
def _active_db_path():
    """Return the first existing TMDb Helper DB path. Cached for the session
    since these paths don't change at runtime."""
    for db in _DB_PATHS:
        try:
            path = xbmcvfs.translatePath(db)
            if xbmcvfs.exists(path):
                return path
        except Exception:
            continue
    return ''


def _normalize_media_type(media_type):
    if media_type in ['tvshow', 'episode', 'season', 'series', 'show', 'tv']:
        return 'tv'
    return 'movie'


def _to_image_url(icon, kind='poster'):
    """Build a sized TMDb URL. `kind` ∈ {'poster','backdrop','logo'}."""
    icon = str(icon or '').strip()
    if icon and '](' in icon:
        icon = icon.split('](')[-1].replace(')', '')
    if not icon:
        return ''
    if icon.startswith('http'):
        return icon
    if kind == 'backdrop':
        return _TMDB_IMAGE_BASE_BACKDROP + icon
    if kind == 'logo':
        return _TMDB_IMAGE_BASE_LOGO + icon
    return _TMDB_IMAGE_BASE_POSTER + icon


# Map TMDb Helper db `art.type` values to our size kind.
_ART_TYPE_KIND = {
    'posters': 'poster', 'poster': 'poster', 'thumb': 'poster',
    'backdrops': 'backdrop', 'fanarts': 'backdrop', 'landscape': 'backdrop', 'stills': 'backdrop',
    'logos': 'logo', 'clearlogo': 'logo',
}


def _query_first_icon(conn, table, parent_id, art_type, order_sql=''):
    """Read one icon from TMDb Helper artwork tables defensively.

    TMDb Helper 5.x stores normal TMDb images in `art` using types like
    posters/backdrops/logos, while older NuvioHub code only queried fanarts/
    landscape. Some cached rows also live in `default_art`, `user_art`, or
    `fanart_tv`, so check them too.
    """
    try:
        cols = _table_columns(conn, table)
        if not cols or 'icon' not in cols or 'parent_id' not in cols or 'type' not in cols:
            return ''
        sql = "SELECT icon FROM %s WHERE type=? AND parent_id=?" % table
        if order_sql:
            sql += " ORDER BY " + order_sql
        sql += " LIMIT 1"
        cur = conn.cursor()
        cur.execute(sql, (art_type, parent_id))
        row = cur.fetchone()
        return str(row[0]).strip() if row and row[0] not in (None, '') else ''
    except Exception:
        return ''


def _query_art_for_parent(conn, parent_id, art_type):
    kind = _ART_TYPE_KIND.get(art_type, 'poster')
    order = "CASE WHEN iso_language='en' THEN 0 WHEN iso_language IS NULL THEN 1 ELSE 2 END, rating DESC"
    candidates = []

    # Primary TMDb Helper art table. Use the real TMDb Helper names.
    type_aliases = [art_type]
    if art_type in ('fanarts', 'landscape'):
        type_aliases.insert(0, 'backdrops')
    elif art_type == 'thumb':
        type_aliases.insert(0, 'posters')
    elif art_type == 'clearlogo':
        type_aliases.insert(0, 'logos')

    for t in type_aliases:
        candidates.append(_query_first_icon(conn, 'art', parent_id, t, order))

    # Default/user art rows are commonly present even when the full `art`
    # table has not been populated by browsing TMDb Helper directly.
    for t in type_aliases:
        candidates.append(_query_first_icon(conn, 'user_art', parent_id, t))
        candidates.append(_query_first_icon(conn, 'default_art', parent_id, t))

    # Fanart.tv cache stores logos/backdrops separately.
    if art_type in ('logos', 'clearlogo'):
        candidates.append(_query_first_icon(conn, 'fanart_tv', parent_id, 'logos', "CASE WHEN iso_language='en' THEN 0 WHEN iso_language IS NULL THEN 1 ELSE 2 END, likes DESC"))
    elif art_type in ('fanarts', 'landscape', 'backdrops'):
        candidates.append(_query_first_icon(conn, 'fanart_tv', parent_id, 'backdrops', "CASE WHEN iso_language='en' THEN 0 WHEN iso_language IS NULL THEN 1 ELSE 2 END, likes DESC"))

    for icon in candidates:
        if icon:
            return _to_image_url(icon, kind=kind)
    return ''


def _table_columns(conn, table):
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(%s)" % table)
        return [row[1] for row in cur.fetchall()]
    except Exception:
        return []


def _find_title_columns(cols):
    candidates = ['title', 'name', 'label', 'originaltitle', 'originalname', 'showname']
    return [c for c in candidates if c in cols]


def _find_tmdb_column(cols):
    for key in ('tmdb_id', 'tmdb'):
        if key in cols:
            return key
    return ''


def _find_media_type_column(cols):
    for key in ('media_type', 'mediatype', 'type'):
        if key in cols:
            return key
    return ''


def _find_year_column(cols):
    for key in ('year', 'release_year'):
        if key in cols:
            return key
    return ''


def _resolve_tmdb_from_imdb(conn, imdb_id, media_type):
    if not imdb_id:
        return ''
    mt = _normalize_media_type(media_type)
    table = 'tvshow' if mt == 'tv' else 'movie'
    queries = [
        # Old helper/legacy schemas
        ("SELECT tmdb_id FROM unique_ids WHERE imdb_id=? LIMIT 1", (imdb_id,)),
        ("SELECT tmdb FROM unique_ids WHERE imdb=? LIMIT 1", (imdb_id,)),
        ("SELECT tmdb_id FROM item_ids WHERE imdb_id=? LIMIT 1", (imdb_id,)),
        ("SELECT tmdb FROM item_ids WHERE imdb=? LIMIT 1", (imdb_id,)),
        ("SELECT tmdb_id FROM items WHERE imdb_id=? AND media_type=? LIMIT 1", (imdb_id, mt)),
        ("SELECT tmdb_id FROM items WHERE imdb_id=? LIMIT 1", (imdb_id,)),
        # Current TMDb Helper schema: unique_id(key,value,parent_id) + movie/tvshow(tmdb_id)
        ("SELECT %s.tmdb_id FROM unique_id JOIN %s ON %s.id=unique_id.parent_id WHERE unique_id.key='imdb_id' AND unique_id.value=? LIMIT 1" % (table, table, table), (imdb_id,)),
        ("SELECT %s.tmdb_id FROM unique_id JOIN %s ON %s.id=unique_id.parent_id WHERE unique_id.key='imdb' AND unique_id.value=? LIMIT 1" % (table, table, table), (imdb_id,)),
    ]
    for sql, params in queries:
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            value = str(row[0]) if row and row[0] not in (None, '') else ''
            if value and value.isdigit():
                return value
        except Exception:
            continue
    return ''


def _resolve_tmdb_from_title(conn, title, media_type, year=''):
    title = str(title or '').strip()
    if not title:
        return ''
    mt = _normalize_media_type(media_type)
    norm = re.sub(r'\s+', ' ', title).strip().lower()
    # Current TMDb Helper uses movie/tvshow tables directly. Keep old tables
    # for compatibility with older helper builds.
    tables = ['tvshow' if mt == 'tv' else 'movie', 'items', 'item_ids', 'unique_ids']
    for table in tables:
        cols = _table_columns(conn, table)
        if not cols:
            continue
        title_cols = _find_title_columns(cols)
        tmdb_col = _find_tmdb_column(cols)
        if not title_cols or not tmdb_col:
            continue
        mt_col = _find_media_type_column(cols)
        year_col = _find_year_column(cols)
        for tc in title_cols:
            sql = "SELECT %s FROM %s WHERE lower(%s)=?" % (tmdb_col, table, tc)
            params = [norm]
            if mt_col:
                sql += " AND %s=?" % mt_col
                params.append('tvshow' if mt == 'tv' and table == 'tvshow' else mt)
            if year_col and str(year or '').isdigit():
                sql += " AND %s=?" % year_col
                params.append(int(year))
            sql += " LIMIT 1"
            try:
                cur = conn.cursor()
                cur.execute(sql, tuple(params))
                row = cur.fetchone()
                value = str(row[0]) if row and row[0] not in (None, '') else ''
                if value and value.isdigit():
                    return value
            except Exception:
                continue
    return ''




def _find_column(cols, *names):
    for name in names:
        if name in cols:
            return name
    return ''


def get_external_ids_from_db(tmdb_id='', media_type='movie', imdb_id='', tvdb_id='', title='', year=''):
    """Resolve IMDb/TMDb/TVDb ids from TMDb Helper's local database.

    This is intentionally read-only and API-free.  Stremio stream addons such
    as Torrentio/AIOStreams usually resolve best with IMDb `tt...` ids, while
    Kodi/TMDb Helper handoffs often start as `tmdb:123`.  Stremio itself sends
    the configured addon the canonical id that the Stremio catalogue has; Dex
    Hub must recreate that by enriching ids locally before calling /stream.
    """
    mt = _normalize_media_type(media_type)
    tmdb_id = str(tmdb_id or '').strip()
    imdb_id = str(imdb_id or '').strip()
    tvdb_id = str(tvdb_id or '').strip()
    cache_key = 'ids:%s:%s:%s:%s:%s:%s' % (mt, tmdb_id, imdb_id, tvdb_id, title or '', year or '')
    if cache_key in _CACHE:
        return dict(_CACHE[cache_key] or {})
    out = {'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': tvdb_id}
    path = _active_db_path()
    if not path:
        _cache_put(cache_key, dict(out))
        return out
    try:
        # Read-only DB — TMDb Helper writes from its own service. mode=ro
        # avoids taking a write lock and skips journal bookkeeping. (3.8.12)
        conn = sqlite3.connect('file:%s?mode=ro' % path, uri=True, timeout=2)
        try:
            # Prefer direct id tables.  Table/column names vary across TMDb
            # Helper versions, so discover columns and query defensively.
            for table in ('unique_ids', 'item_ids', 'items'):
                cols = _table_columns(conn, table)
                if not cols:
                    continue
                tmdb_col = _find_column(cols, 'tmdb_id', 'tmdb')
                imdb_col = _find_column(cols, 'imdb_id', 'imdb')
                tvdb_col = _find_column(cols, 'tvdb_id', 'tvdb')
                mt_col = _find_media_type_column(cols)
                select_cols = []
                for col in (tmdb_col, imdb_col, tvdb_col):
                    if col and col not in select_cols:
                        select_cols.append(col)
                if not select_cols:
                    continue

                where = []
                params = []
                if out.get('tmdb_id') and tmdb_col:
                    where.append('%s=?' % tmdb_col)
                    params.append(out['tmdb_id'])
                if out.get('imdb_id') and imdb_col:
                    where.append('%s=?' % imdb_col)
                    params.append(out['imdb_id'])
                if out.get('tvdb_id') and tvdb_col:
                    where.append('%s=?' % tvdb_col)
                    params.append(out['tvdb_id'])
                if not where:
                    continue
                sql = 'SELECT %s FROM %s WHERE (%s)' % (', '.join(select_cols), table, ' OR '.join(where))
                if mt_col:
                    sql += ' AND %s=?' % mt_col
                    params.append(mt)
                sql += ' LIMIT 1'
                try:
                    cur = conn.cursor()
                    cur.execute(sql, tuple(params))
                    row = cur.fetchone()
                except Exception:
                    row = None
                if not row:
                    continue
                values = dict(zip(select_cols, row))
                if tmdb_col and not out.get('tmdb_id'):
                    val = str(values.get(tmdb_col) or '').strip()
                    if val and val.isdigit():
                        out['tmdb_id'] = val
                if imdb_col and not out.get('imdb_id'):
                    val = str(values.get(imdb_col) or '').strip()
                    if val:
                        out['imdb_id'] = val if val.startswith('tt') else ('tt%s' % val if val.isdigit() else val)
                if tvdb_col and not out.get('tvdb_id'):
                    val = str(values.get(tvdb_col) or '').strip()
                    if val and val.isdigit():
                        out['tvdb_id'] = val
                if out.get('tmdb_id') and out.get('imdb_id'):
                    break

            # Title fallback for older databases that don't have populated id
            # columns in unique_ids/item_ids.
            if (not out.get('imdb_id') or not out.get('tmdb_id')) and title:
                norm = re.sub(r'\s+', ' ', str(title or '')).strip().lower()
                for table in ('items', 'item_ids', 'unique_ids'):
                    cols = _table_columns(conn, table)
                    if not cols:
                        continue
                    title_cols = _find_title_columns(cols)
                    if not title_cols:
                        continue
                    tmdb_col = _find_column(cols, 'tmdb_id', 'tmdb')
                    imdb_col = _find_column(cols, 'imdb_id', 'imdb')
                    tvdb_col = _find_column(cols, 'tvdb_id', 'tvdb')
                    mt_col = _find_media_type_column(cols)
                    year_col = _find_year_column(cols)
                    select_cols = [c for c in (tmdb_col, imdb_col, tvdb_col) if c]
                    if not select_cols:
                        continue
                    for tc in title_cols:
                        sql = 'SELECT %s FROM %s WHERE lower(%s)=?' % (', '.join(select_cols), table, tc)
                        params = [norm]
                        if mt_col:
                            sql += ' AND %s=?' % mt_col
                            params.append(mt)
                        if year_col and str(year or '').isdigit():
                            sql += ' AND %s=?' % year_col
                            params.append(int(year))
                        sql += ' LIMIT 1'
                        try:
                            cur = conn.cursor()
                            cur.execute(sql, tuple(params))
                            row = cur.fetchone()
                        except Exception:
                            row = None
                        if not row:
                            continue
                        values = dict(zip(select_cols, row))
                        if tmdb_col and not out.get('tmdb_id'):
                            val = str(values.get(tmdb_col) or '').strip()
                            if val and val.isdigit():
                                out['tmdb_id'] = val
                        if imdb_col and not out.get('imdb_id'):
                            val = str(values.get(imdb_col) or '').strip()
                            if val:
                                out['imdb_id'] = val if val.startswith('tt') else ('tt%s' % val if val.isdigit() else val)
                        if tvdb_col and not out.get('tvdb_id'):
                            val = str(values.get(tvdb_col) or '').strip()
                            if val and val.isdigit():
                                out['tvdb_id'] = val
                        if out.get('tmdb_id') and out.get('imdb_id'):
                            break
                    if out.get('tmdb_id') and out.get('imdb_id'):
                        break
        finally:
            conn.close()
    except Exception:
        pass
    _cache_put(cache_key, dict(out))
    return out


def _db_scalar(value):
    if value in (None, ''):
        return ''
    if isinstance(value, bytes):
        try:
            value = value.decode('utf-8', 'ignore')
        except Exception:
            return ''
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text:
        return ''
    if (text[:1] in ('{', '[')):
        try:
            parsed = json.loads(text)
            return parsed
        except Exception:
            return text
    return text


def _as_clean_list(value):
    value = _db_scalar(value)
    out = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                name = entry.get('name') or entry.get('title') or entry.get('value') or entry.get('label') or ''
                if name:
                    out.append(str(name).strip())
            elif entry not in (None, ''):
                out.append(str(entry).strip())
    elif isinstance(value, dict):
        for key in ('name', 'title', 'value', 'label'):
            if value.get(key):
                out.append(str(value.get(key)).strip())
                break
    else:
        text = str(value or '').strip()
        if text:
            # TMDb Helper DB fields vary between JSON strings and simple comma /
            # slash separated values depending on version and skin helper cache.
            if ',' in text or ' / ' in text or '|' in text:
                parts = re.split(r'\s*(?:,|/|\|)\s*', text)
                out.extend([x.strip() for x in parts if x.strip()])
            else:
                out.append(text)
    seen = set()
    clean = []
    for item in out:
        item = str(item or '').strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            clean.append(item)
    return clean


def _row_to_dict(cols, row):
    if not cols or row is None:
        return {}
    return {cols[i]: row[i] for i in range(min(len(cols), len(row)))}


def _first_field(row, *names):
    lowered = {str(k).lower(): k for k in (row or {}).keys()}
    for name in names:
        key = name if name in row else lowered.get(str(name).lower())
        if not key:
            continue
        val = _db_scalar(row.get(key))
        if val not in (None, '', [], {}):
            return val
    return ''


def _first_numeric(row, *names):
    val = _first_field(row, *names)
    if val in (None, '', [], {}):
        return ''
    try:
        if isinstance(val, str):
            m = re.search(r'\d+(?:\.\d+)?', val.replace(',', ''))
            return float(m.group(0)) if m else ''
        return float(val)
    except Exception:
        return ''


def _find_item_row(conn, media_type, tmdb_id='', imdb_id='', title='', year=''):
    mt = _normalize_media_type(media_type)
    resolved_tmdb = str(tmdb_id or '').strip()
    if not resolved_tmdb and imdb_id:
        resolved_tmdb = _resolve_tmdb_from_imdb(conn, imdb_id, mt)
    if not resolved_tmdb and title:
        resolved_tmdb = _resolve_tmdb_from_title(conn, title, mt, year)

    preferred = ['tvshow' if mt == 'tv' else 'movie', 'items']
    for table in preferred:
        cols = _table_columns(conn, table)
        if not cols:
            continue
        tmdb_col = _find_tmdb_column(cols)
        mt_col = _find_media_type_column(cols)
        title_cols = _find_title_columns(cols)
        row = None
        if resolved_tmdb and tmdb_col:
            sql = 'SELECT * FROM %s WHERE %s=?' % (table, tmdb_col)
            params = [resolved_tmdb]
            if table == 'items' and mt_col:
                sql += ' AND %s=?' % mt_col
                params.append(mt)
            sql += ' LIMIT 1'
            try:
                cur = conn.cursor()
                cur.execute(sql, tuple(params))
                row = cur.fetchone()
            except Exception:
                row = None
        if not row and title and title_cols:
            norm = re.sub(r'\s+', ' ', str(title or '')).strip().lower()
            for tc in title_cols:
                sql = 'SELECT * FROM %s WHERE lower(%s)=?' % (table, tc)
                params = [norm]
                if table == 'items' and mt_col:
                    sql += ' AND %s=?' % mt_col
                    params.append(mt)
                ycol = _find_year_column(cols)
                if ycol and str(year or '').isdigit():
                    sql += ' AND %s=?' % ycol
                    params.append(int(year))
                sql += ' LIMIT 1'
                try:
                    cur = conn.cursor()
                    cur.execute(sql, tuple(params))
                    row = cur.fetchone()
                except Exception:
                    row = None
                if row:
                    break
        if row:
            data = _row_to_dict(cols, row)
            if not resolved_tmdb and tmdb_col:
                val = str(data.get(tmdb_col) or '').strip()
                if val and val.isdigit():
                    resolved_tmdb = val
            return data, resolved_tmdb
    return {}, resolved_tmdb


def _parent_candidates(media_type, tmdb_id='', imdb_id='', tvdb_id='', internal_id=''):
    mt = _normalize_media_type(media_type)
    out = []
    def add(v):
        v = str(v or '').strip()
        if v and v not in out:
            out.append(v)
    if internal_id not in (None, ''):
        add(internal_id)
    if tmdb_id:
        add('%s.%s' % (mt, tmdb_id))
        if mt == 'tv':
            add('tvshow.%s' % tmdb_id)
            add('tv.%s' % tmdb_id)
        else:
            add('movie.%s' % tmdb_id)
        add(tmdb_id)
    if imdb_id:
        add('%s.%s' % (mt, imdb_id))
        add('%s.imdb:%s' % (mt, imdb_id))
        add(imdb_id)
    if tvdb_id:
        add('%s.tvdb:%s' % (mt, tvdb_id))
        add(tvdb_id)
    return out


def _query_related_values(conn, table_names, parent_ids, role_filter=None, limit=30):
    values = []
    for table in table_names:
        cols = _table_columns(conn, table)
        if not cols:
            continue
        parent_col = _find_column(cols, 'parent_id', 'item_id', 'media_id', 'dbid')
        name_col = _find_column(cols, 'name', 'title', 'value', 'label')
        if not parent_col or not name_col:
            continue
        role_col = _find_column(cols, 'role', 'job', 'department', 'type')
        order_col = _find_column(cols, 'order', 'sort_order', 'sortorder', 'ordering')
        sql = 'SELECT * FROM %s WHERE %s=?' % (table, parent_col)
        if order_col:
            sql += ' ORDER BY %s ASC' % order_col
        sql += ' LIMIT %d' % int(limit or 30)
        for pid in parent_ids or []:
            try:
                cur = conn.cursor()
                cur.execute(sql, (pid,))
                rows = cur.fetchall() or []
            except Exception:
                rows = []
            for row in rows:
                data = _row_to_dict(cols, row)
                if role_filter and role_col:
                    role_text = str(data.get(role_col) or '').lower()
                    if not any(x in role_text for x in role_filter):
                        continue
                name = str(_db_scalar(data.get(name_col)) or '').strip()
                if name:
                    values.append(name)
    seen = set()
    out = []
    for value in values:
        key = str(value).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(str(value).strip())
    return out[:limit]


def _query_cast(conn, parent_ids, limit=25):
    cast = []
    for table in ('cast', 'actors', 'actor', 'credits_cast'):
        cols = _table_columns(conn, table)
        if not cols:
            continue
        parent_col = _find_column(cols, 'parent_id', 'item_id', 'media_id', 'dbid')
        name_col = _find_column(cols, 'name', 'title', 'value', 'label')
        if not parent_col or not name_col:
            continue
        role_col = _find_column(cols, 'character', 'role', 'castrole')
        thumb_col = _find_column(cols, 'thumbnail', 'thumb', 'profile_path', 'icon', 'image')
        order_col = _find_column(cols, 'order', 'sort_order', 'sortorder', 'ordering')
        sql = 'SELECT * FROM %s WHERE %s=?' % (table, parent_col)
        if order_col:
            sql += ' ORDER BY %s ASC' % order_col
        sql += ' LIMIT %d' % int(limit or 25)
        for pid in parent_ids or []:
            try:
                cur = conn.cursor()
                cur.execute(sql, (pid,))
                rows = cur.fetchall() or []
            except Exception:
                rows = []
            for row in rows:
                data = _row_to_dict(cols, row)
                name = str(_db_scalar(data.get(name_col)) or '').strip()
                if not name:
                    continue
                thumb = str(_db_scalar(data.get(thumb_col)) or '').strip() if thumb_col else ''
                # TMDb profile images are also stored as /abc.jpg paths in many helper DB builds.
                if thumb and thumb.startswith('/'):
                    thumb = _to_image_url(thumb, kind='poster')
                cast.append({
                    'name': name,
                    'role': str(_db_scalar(data.get(role_col)) or '').strip() if role_col else '',
                    'thumbnail': thumb,
                })
                if len(cast) >= limit:
                    return cast
    return cast


def get_meta_bundle_from_db(tmdb_id='', media_type='movie', imdb_id='', tvdb_id='', title='', year=''):
    """Return TMDb Helper-style metadata from the helper local DB.

    This is intentionally schema-tolerant: TMDb Helper has changed table/column
    names across releases, and skins can populate different caches.  We inspect
    available columns and copy every field Kodi skins normally use so a Nuvio Hub
    collection item can look like it came directly from TMDb Helper.
    """
    media_type = _normalize_media_type(media_type)
    cache_key = 'meta:%s:%s:%s:%s:%s:%s' % (media_type, tmdb_id or '', imdb_id or '', tvdb_id or '', title or '', year or '')
    if cache_key in _CACHE:
        return dict(_CACHE[cache_key])

    out = {}
    path = _active_db_path()
    if path:
        try:
            conn = sqlite3.connect('file:%s?mode=ro' % path, uri=True, timeout=2)
            try:
                row, resolved_tmdb = _find_item_row(conn, media_type, tmdb_id=tmdb_id, imdb_id=imdb_id, title=title, year=year)
                tmdb_final = str(tmdb_id or resolved_tmdb or '').strip()
                ids = get_external_ids_from_db(tmdb_id=tmdb_final, media_type=media_type, imdb_id=imdb_id, tvdb_id=tvdb_id, title=title, year=year) or {}
                tmdb_final = str(ids.get('tmdb_id') or tmdb_final or '').strip()
                imdb_final = str(ids.get('imdb_id') or imdb_id or '').strip()
                tvdb_final = str(ids.get('tvdb_id') or tvdb_id or '').strip()
                internal_id = _first_field(row, 'id', 'dbid', 'parent_id')
                parents = _parent_candidates(media_type, tmdb_id=tmdb_final, imdb_id=imdb_final, tvdb_id=tvdb_final, internal_id=internal_id)

                name = _first_field(row, 'title', 'name', 'label', 'showtitle') or title
                original = _first_field(row, 'originaltitle', 'original_title', 'originalname', 'original_name')
                plot = _first_field(row, 'plot', 'overview', 'description')
                tagline = _first_field(row, 'tagline')
                released = _first_field(row, 'premiered', 'released', 'release_date', 'firstaired', 'first_air_date', 'air_date', 'date')
                row_year = _first_field(row, 'year', 'release_year') or year
                if not row_year and released:
                    m = re.search(r'(\d{4})', str(released))
                    row_year = m.group(1) if m else ''
                runtime = _first_field(row, 'runtime', 'duration')
                rating = _first_numeric(row, 'rating', 'vote_average', 'userrating', 'user_rating', 'imdb_rating', 'score')
                votes = _first_numeric(row, 'votes', 'vote_count', 'imdb_votes')
                certification = _first_field(row, 'certification', 'mpaa', 'contentrating', 'content_rating', 'rated')
                trailer = _first_field(row, 'trailer')
                status = _first_field(row, 'status')

                genres = _as_clean_list(_first_field(row, 'genres', 'genre'))
                if not genres:
                    genres = _query_related_values(conn, ('genre', 'genres'), parents, limit=12)
                studios = _as_clean_list(_first_field(row, 'studio', 'studios', 'production_companies', 'productionCompanies', 'network', 'networks'))
                if not studios:
                    studios = _query_related_values(conn, ('studio', 'studios', 'production_company', 'production_companies', 'network', 'networks'), parents, limit=12)
                countries = _as_clean_list(_first_field(row, 'country', 'countries', 'origin_country'))
                if not countries:
                    countries = _query_related_values(conn, ('country', 'countries'), parents, limit=12)
                directors = _as_clean_list(_first_field(row, 'director', 'directors'))
                if not directors:
                    directors = _query_related_values(conn, ('director', 'directors', 'crew', 'credits_crew'), parents, role_filter=('director',), limit=12)
                writers = _as_clean_list(_first_field(row, 'writer', 'writers'))
                if not writers:
                    writers = _query_related_values(conn, ('writer', 'writers', 'crew', 'credits_crew'), parents, role_filter=('writer', 'screenplay'), limit=12)
                cast = _query_cast(conn, parents, limit=25)

                if name:
                    out['name'] = str(name)
                    out['title'] = str(name)
                if original:
                    out['originaltitle'] = str(original)
                if plot:
                    out['description'] = str(plot)
                    out['overview'] = str(plot)
                    out['plot'] = str(plot)
                if tagline:
                    out['tagline'] = str(tagline)
                if released:
                    out['released'] = str(released)
                    out['premiered'] = str(released)
                    out['releaseInfo'] = str(released)
                elif row_year:
                    out['releaseInfo'] = str(row_year)
                if row_year:
                    try:
                        out['year'] = int(float(row_year))
                    except Exception:
                        out['year'] = str(row_year)
                if runtime:
                    out['runtime'] = runtime
                if rating not in (None, ''):
                    out['imdbRating'] = rating
                    out['rating'] = rating
                if votes not in (None, ''):
                    try:
                        out['imdb_votes'] = int(votes)
                        out['votes'] = int(votes)
                    except Exception:
                        out['imdb_votes'] = votes
                        out['votes'] = votes
                if certification:
                    out['certification'] = str(certification)
                    out['mpaa'] = str(certification)
                if trailer:
                    out['trailer'] = str(trailer)
                if status:
                    out['status'] = str(status)
                if genres:
                    out['genres'] = genres
                    out['genre'] = genres
                if studios:
                    out['studios'] = studios
                    out['studio'] = studios
                if countries:
                    out['country'] = countries
                if directors:
                    out['director'] = directors
                if writers:
                    out['writer'] = writers
                if cast:
                    out['cast'] = cast

                if tmdb_final:
                    out['tmdb_id'] = tmdb_final
                    out.setdefault('id', 'tmdb:%s' % tmdb_final)
                if imdb_final:
                    out['imdb_id'] = imdb_final
                if tvdb_final:
                    out['tvdb_id'] = tvdb_final
                out['type'] = 'series' if media_type == 'tv' else 'movie'
            finally:
                conn.close()
        except Exception:
            out = {}

    # Always attach helper artwork through the existing well-tested resolver.
    art = get_art_bundle_from_db(tmdb_id=out.get('tmdb_id') or tmdb_id, media_type=media_type, imdb_id=out.get('imdb_id') or imdb_id, title=title, year=year) or {}
    poster = art.get('poster') or ''
    fanart = art.get('fanart') or art.get('landscape') or ''
    clearlogo = art.get('clearlogo') or ''
    if poster:
        out['poster'] = poster
        out['thumbnail'] = poster
        out['thumb'] = poster
    if fanart:
        out['background'] = fanart
        out['fanart'] = fanart
        out['landscape'] = art.get('landscape') or fanart
    if clearlogo:
        out['logo'] = clearlogo
        out['clearlogo'] = clearlogo
    if not out.get('landscape') and art.get('landscape'):
        out['landscape'] = art.get('landscape')

    _cache_put(cache_key, dict(out))
    return out

def get_art_bundle_from_db(tmdb_id='', media_type='movie', imdb_id='', title='', year=''):
    media_type = _normalize_media_type(media_type)
    cache_key = 'bundle:%s:%s:%s:%s:%s' % (media_type, tmdb_id or '', imdb_id or '', title or '', year or '')
    if cache_key in _CACHE:
        return dict(_CACHE[cache_key])

    bundle = {'poster': '', 'fanart': '', 'landscape': '', 'clearlogo': ''}
    path = _active_db_path()
    if path:
        try:
            # Read-only DB — see note in get_external_ids_from_db. (3.8.12)
            conn = sqlite3.connect('file:%s?mode=ro' % path, uri=True, timeout=2)
            try:
                resolved_tmdb = tmdb_id or _resolve_tmdb_from_imdb(conn, imdb_id, media_type) or _resolve_tmdb_from_title(conn, title, media_type, year)
                parent_ids = []
                if resolved_tmdb:
                    parent_ids.append('%s.%s' % (media_type, resolved_tmdb))
                    if media_type == 'tv':
                        parent_ids.append('tv.%s' % resolved_tmdb)
                        parent_ids.append('tvshow.%s' % resolved_tmdb)
                    else:
                        parent_ids.append('movie.%s' % resolved_tmdb)
                if imdb_id:
                    parent_ids.extend([
                        '%s.%s' % (media_type, imdb_id),
                        '%s.imdb:%s' % (media_type, imdb_id),
                        imdb_id,
                    ])
                for parent_id in parent_ids:
                    if not bundle['poster']:
                        bundle['poster'] = _query_art_for_parent(conn, parent_id, 'posters') or _query_art_for_parent(conn, parent_id, 'thumb')
                    if not bundle['fanart']:
                        bundle['fanart'] = _query_art_for_parent(conn, parent_id, 'backdrops') or _query_art_for_parent(conn, parent_id, 'fanarts')
                    if not bundle['landscape']:
                        bundle['landscape'] = _query_art_for_parent(conn, parent_id, 'landscape') or _query_art_for_parent(conn, parent_id, 'backdrops')
                    if not bundle['clearlogo']:
                        bundle['clearlogo'] = _query_art_for_parent(conn, parent_id, 'logos')
                    if bundle['poster'] and bundle['fanart'] and bundle['clearlogo']:
                        break
            finally:
                conn.close()
        except Exception:
            pass
    if not bundle['landscape']:
        bundle['landscape'] = bundle['fanart']
    _cache_put(cache_key, dict(bundle))
    return bundle


def get_clearlogo_from_db(tmdb_id='', media_type='movie', imdb_id=''):
    return (get_art_bundle_from_db(tmdb_id=tmdb_id, media_type=media_type, imdb_id=imdb_id) or {}).get('clearlogo', '')


def _query_title_for_parent(conn, media_type, tmdb_id='', imdb_id='', title='', year=''):
    resolved_tmdb = str(tmdb_id or '').strip() or _resolve_tmdb_from_imdb(conn, imdb_id, media_type) or _resolve_tmdb_from_title(conn, title, media_type, year)
    candidates = []
    if resolved_tmdb:
        candidates.append((resolved_tmdb, _normalize_media_type(media_type)))
    cols = _table_columns(conn, 'items')
    if not cols:
        return ''
    title_cols = [c for c in ('originaltitle', 'originalname', 'title', 'name', 'label', 'showname') if c in cols]
    if not title_cols:
        return ''
    tmdb_col = _find_tmdb_column(cols)
    mt_col = _find_media_type_column(cols)
    if tmdb_col and candidates:
        for tmdb_val, mt in candidates:
            for tc in title_cols:
                sql = "SELECT %s FROM items WHERE %s=?" % (tc, tmdb_col)
                params = [tmdb_val]
                if mt_col:
                    sql += " AND %s=?" % mt_col
                    params.append(mt)
                sql += " LIMIT 1"
                try:
                    cur = conn.cursor()
                    cur.execute(sql, tuple(params))
                    row = cur.fetchone()
                    value = str(row[0]).strip() if row and row[0] not in (None, '') else ''
                    if value:
                        return value
                except Exception:
                    continue
    # Last resort: title-based lookup, prefer originaltitle/originalname when present.
    norm = re.sub(r'\s+', ' ', str(title or '')).strip().lower()
    if norm:
        for tc_match in [c for c in ('title', 'name', 'label', 'showname') if c in cols]:
            for tc_out in title_cols:
                sql = "SELECT %s FROM items WHERE lower(%s)=?" % (tc_out, tc_match)
                params = [norm]
                if mt_col:
                    sql += " AND %s=?" % mt_col
                    params.append(_normalize_media_type(media_type))
                sql += " LIMIT 1"
                try:
                    cur = conn.cursor()
                    cur.execute(sql, tuple(params))
                    row = cur.fetchone()
                    value = str(row[0]).strip() if row and row[0] not in (None, '') else ''
                    if value:
                        return value
                except Exception:
                    continue
    return ''


def get_title_from_db(tmdb_id='', media_type='movie', imdb_id='', title='', year=''):
    cache_key = 'title:%s:%s:%s:%s:%s' % (_normalize_media_type(media_type), tmdb_id or '', imdb_id or '', title or '', year or '')
    if cache_key in _CACHE:
        return _CACHE[cache_key] or ''
    value = ''
    path = _active_db_path()
    if path:
        try:
            # Read-only DB — see note in get_external_ids_from_db. (3.8.12)
            conn = sqlite3.connect('file:%s?mode=ro' % path, uri=True, timeout=2)
            try:
                value = _query_title_for_parent(conn, media_type, tmdb_id=tmdb_id, imdb_id=imdb_id, title=title, year=year)
            finally:
                conn.close()
        except Exception:
            value = ''
    _cache_put(cache_key, value or '')
    return value or ''
