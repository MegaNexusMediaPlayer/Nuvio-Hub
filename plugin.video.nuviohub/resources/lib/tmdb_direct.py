# -*- coding: utf-8 -*-
import json
import os
import sqlite3
import time
import urllib.parse
# v5.4.7: urllib.request is imported inside _request(). This module is
# pulled eagerly via art.py on every render, and the top-level import
# dragged http.client onto every invoker cold start.

import xbmc
import xbmcaddon

from .nuviohub.common import profile_path

# --- nuviohub-401-patch ---
try:
    from .settings_cache import cached_addon as _dh_cached_addon
except Exception:
    try:
        from settings_cache import cached_addon as _dh_cached_addon
    except Exception:
        _dh_cached_addon = None
ADDON = _dh_cached_addon() if _dh_cached_addon else xbmcaddon.Addon('plugin.video.nuviohub')
API_BASE = 'https://api.themoviedb.org/3'
# Bug fix: previously every image (poster, fanart, clearlogo) was fetched at
# /t/p/original, returning 2000+px / 500KB-2MB files for thumbnail-sized
# display slots. The user reported: "tmdb posters downloaded with Plex full
# resolution — please make smaller". TMDb's CDN serves correctly-sized
# variants for free, so we now request appropriate widths per image kind.
# Reference sizes per TMDb docs: posters w185/w342/w500/w780, backdrops
# w300/w780/w1280, logos w92/w154/w300/w500.
IMAGE_BASE_POSTER = 'https://image.tmdb.org/t/p/w500'      # ~70 KB per item
IMAGE_BASE_BACKDROP = 'https://image.tmdb.org/t/p/w1280'   # ~200 KB per item
IMAGE_BASE_LOGO = 'https://image.tmdb.org/t/p/w500'        # logos are small
# Kept for backwards compatibility — used only if a caller passes raw paths
# without specifying a kind.
IMAGE_BASE = IMAGE_BASE_POSTER
CACHE_DB = os.path.join(profile_path(), 'tmdb_direct_cache.sqlite')
POSITIVE_TTL = 30 * 24 * 60 * 60
NEGATIVE_TTL = 6 * 60 * 60
DEFAULT_API_KEY = ''

# In-memory cache (per Python invocation) so a single catalog render doesn't
# reopen sqlite N times for the same items. Bounded to 512 entries with a
# simple FIFO eviction.
_MEM_CACHE = {}
_MEM_CACHE_ORDER = []
_MEM_CACHE_MAX = 512


def _mem_get(key):
    return _MEM_CACHE.get(key)


def _mem_put(key, value):
    if key in _MEM_CACHE:
        return
    _MEM_CACHE[key] = value
    _MEM_CACHE_ORDER.append(key)
    if len(_MEM_CACHE_ORDER) > _MEM_CACHE_MAX:
        old = _MEM_CACHE_ORDER.pop(0)
        _MEM_CACHE.pop(old, None)


def _setting(key, default=''):
    try:
        return ADDON.getSetting(key) or default
    except Exception:
        return default


def _api_key():
    return (_setting('tmdb_api_key', '').strip() or DEFAULT_API_KEY).strip()


def _timeout():
    try:
        return max(4, int(_setting('timeout', '20') or '20'))
    except Exception:
        return 12


def _normalize_media_type(media_type):
    value = str(media_type or 'movie').strip().lower()
    if value in ('tvshow', 'episode', 'season', 'series', 'show', 'tv', 'anime'):
        return 'tv'
    return 'movie'


def _preferred_image_languages():
    raw = (_setting('preferred_subtitle_langs', 'en') or 'en').strip()
    langs = [x.strip().lower().replace('_', '-') for x in raw.split(',') if x.strip()]
    out = []
    # Artwork looks cleaner and clearer in English more often than localized variants.
    # Prefer English assets first, then honor the user language list, then language-neutral.
    for lang in ['en'] + langs + ['null', '']:
        if lang not in out:
            out.append(lang)
    return out or ['en', 'null', '']


def _db_conn():
    os.makedirs(os.path.dirname(CACHE_DB), exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS art_cache ('
        ' cache_key TEXT PRIMARY KEY,'
        ' expires_at INTEGER NOT NULL,'
        ' payload TEXT NOT NULL'
        ')'
    )
    return conn


def _cache_get(cache_key):
    # In-memory first (fast path; avoids opening sqlite for repeated items in
    # the same render).
    cached = _mem_get(cache_key)
    if cached is not None:
        return cached
    try:
        conn = _db_conn()
        row = conn.execute('SELECT expires_at, payload FROM art_cache WHERE cache_key=?', (cache_key,)).fetchone()
        if not row:
            conn.close()
            return None
        expires_at, payload = row
        if int(expires_at or 0) < int(time.time()):
            conn.execute('DELETE FROM art_cache WHERE cache_key=?', (cache_key,))
            conn.commit()
            conn.close()
            return None
        conn.close()
        result = json.loads(payload or '{}')
        _mem_put(cache_key, result)
        return result
    except Exception:
        return None


def _cache_set(cache_key, payload, ttl):
    _mem_put(cache_key, payload or {})
    try:
        conn = _db_conn()
        conn.execute(
            'INSERT OR REPLACE INTO art_cache(cache_key, expires_at, payload) VALUES (?, ?, ?)',
            (cache_key, int(time.time() + max(60, int(ttl or NEGATIVE_TTL))), json.dumps(payload or {}, ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _request(path, params=None, timeout=None):
    import urllib.request  # lazy: keeps http.client off the render import path
    api_key = _api_key()
    if not api_key:
        return {}
    query = dict(params or {})
    query['api_key'] = api_key
    url = API_BASE + path + ('?' + urllib.parse.urlencode(query) if query else '')
    req = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'User-Agent': 'NuvioHub/%s (Kodi)' % (ADDON.getAddonInfo('version') or '3.8.9'),
    })
    request_timeout = _timeout() if timeout is None else max(1.0, float(timeout))
    with urllib.request.urlopen(req, timeout=request_timeout) as resp:
        body = resp.read().decode('utf-8', 'ignore')
        return json.loads(body) if body else {}


def _image_url(file_path, kind='poster'):
    """Build a TMDb image URL with the appropriate size for `kind`.

    `kind` is one of: 'poster', 'backdrop', 'logo'. We pick a size that's
    large enough for any reasonable display slot in Kodi while keeping
    bandwidth (and the user's Plex download path through Kodi's image
    cache) modest.
    """
    file_path = str(file_path or '').strip()
    if not file_path:
        return ''
    if file_path.startswith('http://') or file_path.startswith('https://'):
        return file_path
    if kind == 'backdrop':
        return IMAGE_BASE_BACKDROP + file_path
    if kind == 'logo':
        return IMAGE_BASE_LOGO + file_path
    return IMAGE_BASE_POSTER + file_path


def _best_image(rows, langs):
    rows = rows or []
    langs = langs or ['en', 'null', '']

    def _lang_rank(row):
        iso = str((row or {}).get('iso_639_1') or '').strip().lower()
        iso_short = iso.split('-')[0] if iso else ''
        for idx, lang in enumerate(langs):
            target = str(lang or '').strip().lower()
            target_short = target.split('-')[0] if target else ''
            if iso == target or (iso_short and target_short and iso_short == target_short):
                return idx
        if not iso:
            return len(langs) + 1
        return len(langs) + 10

    ranked = sorted(
        rows,
        key=lambda row: (
            _lang_rank(row),
            -float((row or {}).get('vote_average') or 0.0),
            -int((row or {}).get('width') or 0),
            -int((row or {}).get('height') or 0),
            -float((row or {}).get('vote_count') or 0.0),
        )
    )
    return ranked[0] if ranked else {}


def _resolve_tmdb_from_imdb(imdb_id, media_type):
    imdb_id = str(imdb_id or '').strip()
    if not imdb_id:
        return ''
    try:
        data = _request('/find/%s' % urllib.parse.quote(imdb_id), {'external_source': 'imdb_id'}) or {}
    except Exception as exc:
        xbmc.log('[NuvioHub] tmdb_direct imdb lookup failed: %s' % exc, xbmc.LOGDEBUG)
        return ''
    mt = _normalize_media_type(media_type)
    bucket = 'tv_results' if mt == 'tv' else 'movie_results'
    rows = data.get(bucket) or []
    if rows:
        return str(rows[0].get('id') or '')
    return ''


def _resolve_tmdb_from_search(title, year, media_type):
    title = str(title or '').strip()
    if not title:
        return ''
    mt = _normalize_media_type(media_type)
    params = {'query': title}
    year = str(year or '').strip()
    if year.isdigit():
        if mt == 'movie':
            params['year'] = year
        else:
            params['first_air_date_year'] = year
    try:
        data = _request('/search/%s' % mt, params) or {}
    except Exception as exc:
        xbmc.log('[NuvioHub] tmdb_direct search failed: %s' % exc, xbmc.LOGDEBUG)
        return ''
    rows = data.get('results') or []
    if not rows:
        return ''
    return str(rows[0].get('id') or '')


def _resolve_tmdb_id(tmdb_id='', imdb_id='', media_type='movie', title='', year=''):
    tmdb_id = str(tmdb_id or '').strip()
    if tmdb_id.isdigit():
        return tmdb_id
    imdb_id = str(imdb_id or '').strip()
    if imdb_id:
        resolved = _resolve_tmdb_from_imdb(imdb_id, media_type)
        if resolved:
            return resolved
    return _resolve_tmdb_from_search(title, year, media_type)


# v3.9.48: public search function returning full meta records for the
# in-app TMDb search experience. Uses /search/multi so a single query
# returns movies, TV shows, and people interleaved by relevance — same
# as TMDb Helper's behaviour, but rendered inline within NuvioHub rather
# than requiring a redirect.
def search_multi(query, limit=40):
    """Search TMDb across movies and TV simultaneously. Returns a list
    of normalised result dicts ready for rendering, each containing
    media_type, tmdb_id, title, year, poster, backdrop, overview, and
    rating."""
    query = str(query or '').strip()
    if not query or not _api_key():
        return []
    language = 'ar-SA' if any("\u0600" <= ch <= "\u06ff" for ch in query) else 'en-US'
    cache_key = 'search_multi:%s:%s' % (language, query.casefold())
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached or []
    try:
        data = _request('/search/multi', {
            'query': query, 'include_adult': 'false', 'language': language,
        }, timeout=min(float(_timeout()), 6.0)) or {}
    except Exception as exc:
        xbmc.log('[NuvioHub] tmdb_direct search_multi failed: %s' % exc, xbmc.LOGDEBUG)
        return []
    raw_results = data.get('results') or []
    results = []
    for row in raw_results[:max(1, int(limit))]:
        mt = row.get('media_type') or ''
        if mt not in ('movie', 'tv'):
            continue
        title = row.get('title') if mt == 'movie' else row.get('name')
        release_raw = row.get('release_date') if mt == 'movie' else row.get('first_air_date')
        year = ''
        if release_raw and len(release_raw) >= 4 and release_raw[:4].isdigit():
            year = release_raw[:4]
        poster_path = row.get('poster_path')
        backdrop_path = row.get('backdrop_path')
        results.append({
            'media_type': 'series' if mt == 'tv' else 'movie',
            'tmdb_id': str(row.get('id') or ''),
            'title': title or '',
            'original_title': (row.get('original_title') if mt == 'movie'
                               else row.get('original_name')) or '',
            'year': year,
            'overview': row.get('overview') or '',
            'poster': _image_url(poster_path, kind='poster') if poster_path else '',
            'backdrop': _image_url(backdrop_path, kind='backdrop') if backdrop_path else '',
            'rating': row.get('vote_average') or 0.0,
        })
    _cache_set(cache_key, results, ttl=NEGATIVE_TTL if not results else POSITIVE_TTL // 4)
    return results


def search_metas(query, limit=40):
    """Return lightweight Stremio-shaped metas for the unified search."""
    metas = []
    for row in search_multi(query, limit=limit) or []:
        tmdb_id = str(row.get('tmdb_id') or '').strip()
        if not tmdb_id:
            continue
        media_kind = row.get('media_type') or 'movie'
        backdrop = row.get('backdrop') or ''
        metas.append({
            'id': 'tmdb:%s' % tmdb_id, 'type': media_kind,
            'name': row.get('title') or '',
            'original_title': row.get('original_title') or '',
            'moviedb_id': tmdb_id, 'year': row.get('year') or '',
            'releaseInfo': row.get('year') or '',
            'description': row.get('overview') or '',
            'poster': row.get('poster') or '', 'background': backdrop,
            'fanart': backdrop, 'imdbRating': row.get('rating') or 0.0,
            '_backend': 'tmdb',
        })
    return metas


# ── v4.7.9: ready-made collection sets ───────────────────────────────────
# TMDb-native endpoints only, so every row already carries a TMDb id and a
# poster: no id conversion, no per-item lookup, and the existing click path
# opens them like any other catalog row.
READY_SETS = (
    ('trending_movie', 'Trending now - Movies',      '/trending/movie/week',   'movie'),
    ('trending_tv',    'Trending now - Series',   '/trending/tv/week',      'series'),
    ('popular_movie',  'Most popular - Movies',   '/movie/popular',         'movie'),
    ('popular_tv',     'Most popular - Series', '/tv/popular',           'series'),
    ('top_movie',      'Top rated - Movies',  '/movie/top_rated',      'movie'),
    ('top_tv',         'Top rated - Series', '/tv/top_rated',        'series'),
    ('now_playing',    'Now playing',        '/movie/now_playing',     'movie'),
    ('upcoming',       'Coming soon',                 '/movie/upcoming',        'movie'),
    ('airing_today',   'Airing today',            '/tv/airing_today',       'series'),
)


def ready_set_def(set_id):
    for row in READY_SETS:
        if row[0] == str(set_id or ''):
            return row
    return None


def _row_from_tmdb(row, media_type):
    title = row.get('title') or row.get('name') or ''
    release_raw = row.get('release_date') or row.get('first_air_date') or ''
    year = release_raw[:4] if len(str(release_raw)) >= 4 and str(release_raw)[:4].isdigit() else ''
    poster_path = row.get('poster_path')
    backdrop_path = row.get('backdrop_path')
    return {
        'media_type': media_type,
        'tmdb_id': str(row.get('id') or ''),
        'title': title,
        'year': year,
        'overview': row.get('overview') or '',
        'poster': _image_url(poster_path, kind='poster') if poster_path else '',
        'backdrop': _image_url(backdrop_path, kind='backdrop') if backdrop_path else '',
        'rating': row.get('vote_average') or 0.0,
    }


def ready_set_items(set_id, page=1, limit=40):
    """Fetch one ready-made set. Cached like every other TMDb call."""
    row_def = ready_set_def(set_id)
    if not row_def or not _api_key():
        return []
    _sid, _label, path, media_type = row_def
    page = max(1, int(page or 1))
    cache_key = 'ready_set:%s:%d' % (set_id, page)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached or []
    try:
        data = _request(path, {'page': str(page)}) or {}
    except Exception as exc:
        xbmc.log('[NuvioHub] tmdb ready_set(%s) failed: %s' % (set_id, exc), xbmc.LOGWARNING)
        return []
    out = []
    for raw in (data.get('results') or [])[:max(1, int(limit))]:
        item = _row_from_tmdb(raw, media_type)
        if item['tmdb_id'] and item['title']:
            out.append(item)
    _cache_set(cache_key, out, ttl=NEGATIVE_TTL if not out else POSITIVE_TTL // 8)
    return out


def imdb_id_for(tmdb_id, media_type='movie', timeout=None):
    """Fetch the IMDb id for a given TMDb id when NuvioHub's playback path
    needs to feed an imdb identifier to a Stremio provider. Cached."""
    tmdb_id = str(tmdb_id or '').strip()
    if not tmdb_id.isdigit() or not _api_key():
        return ''
    mt = _normalize_media_type(media_type)
    cache_key = 'imdb_for:%s:%s' % (mt, tmdb_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached or ''
    try:
        data = _request('/%s/%s/external_ids' % (mt, tmdb_id),
                        timeout=timeout) or {}
        imdb = (data.get('imdb_id') or '').strip()
    except Exception:
        imdb = ''
    _cache_set(cache_key, imdb, ttl=POSITIVE_TTL if imdb else NEGATIVE_TTL)
    return imdb


def english_titles_for(tmdb_id, media_type='movie'):
    "The ENGLISH and ORIGINAL titles of an item — cached.\n\n    v3.9.215 — the reason Plex kept answering \"no match\".\n\n    Nuvio Hub searched the user's Plex libraries with the title it had, which for\n    an Arabic user is the ARABIC one (\"\u0628\u0631\u0634\u0627\u0645\u0629\") — while the library catalogues\n    the film under its English name (\"Cheat Sheet\"). For episodes it was worse:\n    the title passed was literally \"\u0627\u0644\u062d\u0644\u0642\u0629 16\" (Episode 16), so Plex was asked\n    for a show by that name and, truthfully, found nothing.\n    "
    tmdb_id = str(tmdb_id or '').strip()
    mt = _normalize_media_type(media_type)
    if not tmdb_id.isdigit() or not _api_key():
        return []
    cache_key = 'en_titles:%s:%s' % (mt, tmdb_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached or [])
    titles = []
    try:
        data = _request('/%s/%s' % (mt, tmdb_id), params={'language': 'en-US'}) or {}
        for key in ('title', 'name', 'original_title', 'original_name'):
            value = str(data.get(key) or '').strip()
            if value and value.casefold() not in [t.casefold() for t in titles]:
                titles.append(value)
    except Exception:
        titles = []
    _cache_set(cache_key, titles, ttl=POSITIVE_TTL if titles else NEGATIVE_TTL)
    return list(titles)


def titles_for_imdb(imdb_id, media_type='movie'):
    """English + original titles for an IMDb id — one call, cached.

    v3.9.219 — the last gap, straight from the log:

        plex lookup: ids=imdb_id=tt33076347 titles=1 -> 0 item(s)

    Only ONE title (the Arabic one) was ever sent to Plex, because the English
    title was fetched from /movie/<tmdb_id> — and this item has NO tmdb_id.
    TMDb's /find endpoint resolves an IMDb id directly, and returns the item in
    English, so Plex can finally be asked using the name its library actually
    uses.
    """
    imdb_id = str(imdb_id or '').strip()
    if not imdb_id.startswith('tt') or not _api_key():
        return []
    mt = _normalize_media_type(media_type)
    cache_key = 'find_titles:%s:%s' % (mt, imdb_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return list(cached or [])

    titles = []
    try:
        data = _request('/find/%s' % imdb_id,
                        params={'external_source': 'imdb_id',
                                'language': 'en-US'}) or {}
        bucket = ('tv_results' if mt == 'tv' else 'movie_results')
        rows = list(data.get(bucket) or [])
        if not rows:
            # An episode id resolves to tv_episode_results; the SHOW name is
            # what Plex needs, and it rides along there.
            rows = list(data.get('tv_episode_results') or []) + \
                   list(data.get('tv_results') or []) + \
                   list(data.get('movie_results') or [])
        for row in rows[:2]:
            for key in ('title', 'name', 'original_title', 'original_name',
                        'show_name'):
                value = str(row.get(key) or '').strip()
                if value and value.casefold() not in [t.casefold() for t in titles]:
                    titles.append(value)
    except Exception:
        titles = []
    _cache_set(cache_key, titles, ttl=POSITIVE_TTL if titles else NEGATIVE_TTL)
    return list(titles)


def art_cached_only(tmdb_id='', imdb_id='', media_type='movie', title='', year=''):
    """Return TMDb art ONLY if it is already cached — never touches the network.

    Used on the Plex/Emby render path: a listing must never wait on TMDb. On a
    miss the caller keeps the server art for this pass and warms TMDb off-thread
    so the next visit is an instant cache hit.
    """
    mt = _normalize_media_type(media_type)
    cache_key = 'art:%s:%s:%s:%s:%s' % (mt, tmdb_id or '', imdb_id or '', title or '', year or '')
    cached = _cache_get(cache_key)
    return cached if isinstance(cached, dict) else {}


def art_for(tmdb_id='', imdb_id='', media_type='movie', title='', year=''):
    mt = _normalize_media_type(media_type)
    cache_key = 'art:%s:%s:%s:%s:%s' % (mt, tmdb_id or '', imdb_id or '', title or '', year or '')
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if not _api_key():
        return {}

    resolved_tmdb = _resolve_tmdb_id(tmdb_id=tmdb_id, imdb_id=imdb_id, media_type=mt, title=title, year=year)
    if not resolved_tmdb:
        out = {}
        _cache_set(cache_key, out, NEGATIVE_TTL)
        return out

    langs = _preferred_image_languages()
    try:
        images = _request('/%s/%s/images' % (mt, resolved_tmdb), {
            'include_image_language': ','.join([x for x in langs if x and x != 'null'] + ['null'])
        }) or {}
    except Exception as exc:
        xbmc.log('[NuvioHub] tmdb_direct images failed: %s' % exc, xbmc.LOGDEBUG)
        images = {}

    try:
        ext = _request('/%s/%s/external_ids' % (mt, resolved_tmdb)) or {}
    except Exception:
        ext = {}

    poster = _best_image(images.get('posters') or [], langs)
    backdrop = _best_image(images.get('backdrops') or [], langs)
    logo = _best_image(images.get('logos') or [], langs)
    out = {
        'tmdb_id': resolved_tmdb,
        'imdb_id': str(ext.get('imdb_id') or imdb_id or '').strip(),
        'poster': _image_url((poster or {}).get('file_path') or '', kind='poster'),
        'fanart': _image_url((backdrop or {}).get('file_path') or '', kind='backdrop'),
        'landscape': _image_url((backdrop or {}).get('file_path') or '', kind='backdrop'),
        'clearlogo': _image_url((logo or {}).get('file_path') or '', kind='logo'),
    }
    ttl = POSITIVE_TTL if any(out.get(k) for k in ('poster', 'fanart', 'clearlogo')) else NEGATIVE_TTL
    _cache_set(cache_key, out, ttl)
    return out


def _localized_overview(detail, langs):
    """Pick the best overview: try the user's language list via translations,
    then fall back to the default-language overview from the detail call.
    """
    base = str((detail or {}).get('overview') or '').strip()
    translations = ((detail or {}).get('translations') or {}).get('translations') or []
    by_lang = {}
    for tr_row in translations:
        iso = str(tr_row.get('iso_639_1') or '').strip().lower()
        data = tr_row.get('data') or {}
        text = str(data.get('overview') or '').strip()
        if iso and text and iso not in by_lang:
            by_lang[iso] = text
    for lang in (langs or []):
        short = str(lang or '').strip().lower().split('-')[0]
        if short and short in by_lang:
            return by_lang[short]
    if base:
        return base
    return by_lang.get('en', '')


def meta_for(tmdb_id='', imdb_id='', media_type='movie', title='', year=''):
    """Full TMDb metadata in ONE network round-trip.

    v3.9.144: extends the TMDb-first art policy to TEXT. Appends
    credits + images + external_ids + translations to the detail call so a
    single request returns plot, year, genres, rating, runtime, studios,
    cast AND artwork. Normalized to NuvioHub's existing meta keys. Returns {}
    when no API key / resolution / HTTP fails (callers keep addon meta).
    """
    mt = _normalize_media_type(media_type)
    cache_key = 'meta:%s:%s:%s:%s:%s' % (mt, tmdb_id or '', imdb_id or '', title or '', year or '')
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    if not _api_key():
        return {}

    resolved_tmdb = _resolve_tmdb_id(tmdb_id=tmdb_id, imdb_id=imdb_id, media_type=mt, title=title, year=year)
    if not resolved_tmdb:
        out = {}
        _cache_set(cache_key, out, NEGATIVE_TTL)
        return out

    langs = _preferred_image_languages()
    detail_lang = next((x for x in langs if x and x != 'null'), 'en')
    try:
        detail = _request('/%s/%s' % (mt, resolved_tmdb), {
            'language': detail_lang,
            'append_to_response': 'credits,images,external_ids,translations',
            'include_image_language': ','.join([x for x in langs if x and x != 'null'] + ['null']),
        }) or {}
    except Exception as exc:
        xbmc.log('[NuvioHub] tmdb_direct meta_for failed: %s' % exc, xbmc.LOGDEBUG)
        out = {}
        _cache_set(cache_key, out, NEGATIVE_TTL)
        return out

    if not detail:
        out = {}
        _cache_set(cache_key, out, NEGATIVE_TTL)
        return out

    images = detail.get('images') or {}
    poster = _best_image(images.get('posters') or [], langs)
    backdrop = _best_image(images.get('backdrops') or [], langs)
    logo = _best_image(images.get('logos') or [], langs)
    ext = detail.get('external_ids') or {}

    if mt == 'tv':
        name = str(detail.get('name') or detail.get('original_name') or title or '').strip()
        date = str(detail.get('first_air_date') or '').strip()
    else:
        name = str(detail.get('title') or detail.get('original_title') or title or '').strip()
        date = str(detail.get('release_date') or '').strip()
    year_val = date[:4] if date[:4].isdigit() else (str(year or '').strip())

    genres = [str(g.get('name')).strip() for g in (detail.get('genres') or []) if g.get('name')]

    try:
        rating = round(float(detail.get('vote_average') or 0.0), 1)
    except Exception:
        rating = 0.0
    try:
        votes = int(detail.get('vote_count') or 0)
    except Exception:
        votes = 0

    runtime_min = 0
    if mt == 'tv':
        ert = detail.get('episode_run_time') or []
        if isinstance(ert, list) and ert:
            try:
                runtime_min = int(ert[0] or 0)
            except Exception:
                runtime_min = 0
    else:
        try:
            runtime_min = int(detail.get('runtime') or 0)
        except Exception:
            runtime_min = 0

    if mt == 'tv':
        studios = [str(s.get('name')).strip() for s in (detail.get('networks') or []) if s.get('name')]
    else:
        studios = [str(s.get('name')).strip() for s in (detail.get('production_companies') or []) if s.get('name')]

    cast = []
    for member in ((detail.get('credits') or {}).get('cast') or [])[:15]:
        nm = str(member.get('name') or '').strip()
        if not nm:
            continue
        cast.append({
            'name': nm,
            'role': str(member.get('character') or '').strip(),
            'thumbnail': _image_url(member.get('profile_path') or '', kind='logo'),
        })

    director = ''
    writers = []
    for member in ((detail.get('credits') or {}).get('crew') or []):
        job = str(member.get('job') or '').strip()
        nm = str(member.get('name') or '').strip()
        if not nm:
            continue
        if job == 'Director' and not director:
            director = nm
        elif job in ('Writer', 'Screenplay', 'Author'):
            if nm not in writers:
                writers.append(nm)

    overview = _localized_overview(detail, langs)
    country = ''
    countries = detail.get('production_countries') or detail.get('origin_country') or []
    if isinstance(countries, list) and countries:
        first = countries[0]
        country = str(first.get('name') if isinstance(first, dict) else first or '').strip()

    out = {
        'tmdb_id': str(resolved_tmdb),
        'imdb_id': str(ext.get('imdb_id') or imdb_id or '').strip(),
        'tvdb_id': str(ext.get('tvdb_id') or '').strip(),
        'name': name,
        'title': name,
        'year': year_val,
        'description': overview,
        'overview': overview,
        'genres': genres,
        'imdbRating': ('%.1f' % rating) if rating else '',
        'rating': rating,
        'vote_count': votes,
        'runtime': runtime_min,
        'studio': studios,
        'country': country,
        'director': director,
        'writer': writers,
        'cast': cast,
        'tagline': str(detail.get('tagline') or '').strip(),
        'status': str(detail.get('status') or '').strip(),
        'poster': _image_url((poster or {}).get('file_path') or '', kind='poster'),
        'fanart': _image_url((backdrop or {}).get('file_path') or '', kind='backdrop'),
        'landscape': _image_url((backdrop or {}).get('file_path') or '', kind='backdrop'),
        'clearlogo': _image_url((logo or {}).get('file_path') or '', kind='logo'),
    }
    has_payload = bool(out.get('description') or out.get('poster') or out.get('genres') or out.get('cast'))
    _cache_set(cache_key, out, POSITIVE_TTL if has_payload else NEGATIVE_TTL)
    return out


def merge_into_meta(addon_meta, tmdb_meta, prefer_tmdb_text=False):
    """Fill gaps in addon_meta from tmdb_meta without destroying good data.

    Mirrors the poster policy: TMDb fills/corrects, addon stays the base.
      - Text: addon wins when present; TMDb fills blanks (prefer_tmdb_text
        flips this for streaming-only providers with junk descriptions).
      - Lists (genres/cast/studio/writer): whichever is non-empty, addon first.
      - IDs: only fill blanks, never overwrite.
    """
    if not isinstance(addon_meta, dict):
        addon_meta = {}
    if not isinstance(tmdb_meta, dict) or not tmdb_meta:
        return addon_meta
    out = dict(addon_meta)

    text_keys = ('description', 'overview', 'name', 'title', 'year',
                 'imdbRating', 'runtime', 'tagline', 'director', 'country', 'status')
    for key in text_keys:
        tval = tmdb_meta.get(key)
        if not tval:
            continue
        aval = out.get(key)
        if prefer_tmdb_text or not aval:
            out[key] = tval

    for key in ('genres', 'cast', 'studio', 'writer'):
        tval = tmdb_meta.get(key) or []
        aval = out.get(key) or []
        if prefer_tmdb_text:
            out[key] = tval or aval
        else:
            out[key] = aval or tval

    for key in ('imdb_id', 'tmdb_id', 'tvdb_id'):
        if not out.get(key) and tmdb_meta.get(key):
            out[key] = tmdb_meta.get(key)

    return out
