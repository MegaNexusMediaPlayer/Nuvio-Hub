# -*- coding: utf-8 -*-
"""Simkl account sync for Nuvio Hub (v4.1.0).

Mirrors the trakt.py architecture: device-PIN auth, watched-history sync at
playback end, and the user's Simkl lists (watching / plan-to-watch / completed
/ on-hold / dropped) exposed as browsable catalogs.

Simkl API notes (encoded from Simkl's public apiary docs — endpoints marked
[VERIFY-LIVE] should be confirmed against a live account on first run):
  * Base: https://api.simkl.com
  * Device auth:  GET /oauth/pin?client_id=X
                  -> {user_code, verification_url, expires_in, interval}
                  poll GET /oauth/pin/{user_code}?client_id=X
                  -> {"result":"KO"} until {"result":"OK","access_token":...}
  * Authed calls: headers  Authorization: Bearer <token>
                            simkl-api-key: <client_id>
  * Lists:   GET /sync/all-items/{movies|shows|anime}/{status}?extended=full
  * History: POST /sync/history  {"movies":[{"ids":{...}}],
                                  "shows":[{"ids":{...},"seasons":[
                                      {"number":S,"episodes":[{"number":E}]}]}]}

Local resume is immediate; an account-scoped queue syncs paused progress.
"""
import json
import re
import os
import time
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import xbmc
import xbmcaddon
import xbmcgui

from .nuviohub.common import profile_path
from . import playback_store
from .i18n import tr

try:
    from .settings_cache import cached_addon as _dh_cached_addon
except Exception:
    try:
        from settings_cache import cached_addon as _dh_cached_addon
    except Exception:
        _dh_cached_addon = None
ADDON = _dh_cached_addon() if _dh_cached_addon else xbmcaddon.Addon('plugin.video.nuviohub')

API = 'https://api.simkl.com'
TOKEN_PATH = os.path.join(profile_path(), 'simkl_token.json')
# Public Nuvio Hub AUTH V1 registration, app #8268945. No secret is embedded.
DEFAULT_CLIENT_ID = 'b22385a5a145d47e2713d73e3a843f6d73e0e9c45ccea961613060a72499b0a7'
# Existing tokens keep their issuing app until a replacement PIN is approved.
LEGACY_CLIENT_ID = '7c5c3e3c74fa28dd639ca8b09da8f5e48d46ee7c3ea86d284c56bee4a0a09643'
PIN_URL_FALLBACK = 'https://simkl.com/pin'

_PUBLIC_CACHE = {}
_PUBLIC_CACHE_TTL = 300
# One history POST per video per Kodi session — a stop at 96% followed by the
# natural "ended" event must not write the same episode twice.
_MARKED_THIS_SESSION = set()

# status keys per Simkl kind. Movies have no "watching"/"hold" shelf.
STATUSES_SHOWS = ('watching', 'plantowatch', 'hold', 'completed', 'dropped')
STATUSES_MOVIES = ('plantowatch', 'completed', 'dropped')
KINDS = ('movies', 'shows', 'anime')


def _setting(key, default=''):
    try:
        return ADDON.getSetting(key) or default
    except Exception:
        return default


def enabled():
    return (_setting('enable_simkl', 'true') or 'true').lower() == 'true'


def client_id():
    configured=_setting('simkl_client_id', '').strip()
    return (DEFAULT_CLIENT_ID if configured==LEGACY_CLIENT_ID else configured or DEFAULT_CLIENT_ID).strip()


def token_client_id(data=None):
    data=token_data() if data is None else data
    return str(data.get('client_id') or _setting('simkl_client_id','').strip() or LEGACY_CLIENT_ID)


def needs_app_relink():
    data=token_data()
    return bool(data.get('access_token') and token_client_id(data)==LEGACY_CLIENT_ID)


def credentials_configured():
    return bool(client_id())


def mark_watched_enabled():
    return (_setting('simkl_mark_watched', 'true') or 'true').lower() == 'true'


def watched_threshold_percent():
    try:
        value = float(_setting('simkl_watched_threshold', '85') or 85)
    except Exception:
        value = 85.0
    return max(50.0, min(99.0, value))


def ensure_enabled():
    try:
        if not enabled():
            ADDON.setSetting('enable_simkl', 'true')
    except Exception:
        pass


def _read_json(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_json(path, value):
    temporary = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=os.path.dirname(path), delete=False) as handle:
            temporary = handle.name
            json.dump(value, handle)
        try: os.chmod(temporary, 0o600)
        except OSError: pass
        os.replace(temporary, path)
        return True
    except Exception:
        return False
    finally:
        if temporary and os.path.exists(temporary):
            try: os.remove(temporary)
            except OSError: pass


def token_data():
    return _read_json(TOKEN_PATH, {})


def save_token(data):
    data=dict(data or {})
    if data.get('access_token'):data.setdefault('client_id',client_id())
    return _write_json(TOKEN_PATH, data)


def clear_token():
    try:
        if os.path.exists(TOKEN_PATH):
            os.remove(TOKEN_PATH)
    except Exception:
        pass


def authorized():
    return bool((token_data() or {}).get('access_token'))


def authorization_status():
    if authorized():
        return 'connected'
    return 'ready' if credentials_configured() else 'needs_api'


def _headers(auth=False):
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'NuvioHub/%s (Kodi)' % (ADDON.getAddonInfo('version') or '4.1.0'),
        'simkl-api-key': client_id(),
    }
    if auth:
        data=token_data() or {}
        token = data.get('access_token') or ''
        if not token:
            raise RuntimeError(tr('Simkl account is not linked'))
        headers['Authorization'] = 'Bearer %s' % token
        headers['simkl-api-key'] = token_client_id(data)
    return headers


def _request(path, payload=None, method='GET', auth=False, timeout=20):
    headers=_headers(auth=auth)
    parsed=urllib.parse.urlsplit(API+path)
    query=dict(urllib.parse.parse_qsl(parsed.query,keep_blank_values=True))
    query.update({'client_id':headers['simkl-api-key'],'app-name':'nuvio-hub','app-version':ADDON.getAddonInfo('version') or '6.0.5'})
    url=urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode('utf-8', 'ignore')
        return json.loads(body) if body else {}


def _cached_request(path, auth=True, timeout=20):
    now = time.time()
    hit = _PUBLIC_CACHE.get(path)
    if hit and (now - hit[0]) <= _PUBLIC_CACHE_TTL:
        return hit[1]
    data = _request(path, method='GET', auth=auth, timeout=timeout)
    _PUBLIC_CACHE[path] = (now, data)
    return data


def invalidate_cache(prefix=''):
    for key in list(_PUBLIC_CACHE.keys()):
        if not prefix or key.startswith(prefix):
            _PUBLIC_CACHE.pop(key, None)


def _build_pin_message(verify_url, user_code, remaining=None):
    """PIN first: Kodi's progress textbox only has room for a few lines.

    Keep this compact; progress updates can reset the skin's text autoscroll.
    Never put the actual pairing code below instructions or blank spacer lines.
    """
    lines = [
        '[B]PIN: %s[/B]' % user_code,
        'Open on your phone: %s' % verify_url,
    ]
    if remaining is not None:
        lines.append('Enter the PIN and approve. Time remaining: %ss' % max(0,int(remaining)))
    else:
        lines.append('Enter the PIN and approve the connection.')
    return '\n'.join(lines)


def device_auth():
    ensure_enabled()
    if not credentials_configured():
        raise RuntimeError(tr('Enter a Simkl Client ID in settings first (from simkl.com/settings/developer)'))

    # Step 1: request a user code.
    try:
        code = _request('/oauth/pin?client_id=%s' % urllib.parse.quote(client_id()), method='GET', auth=False)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', 'ignore')
        except Exception:
            body = ''
        raise RuntimeError(tr('Simkl code request failed (%s): %s') % (exc.code, body[:200]))
    except Exception as exc:
        raise RuntimeError(tr('Could not reach Simkl: %s') % exc)

    user_code = str((code or {}).get('user_code') or '').strip()
    verify = str((code or {}).get('verification_url') or PIN_URL_FALLBACK)
    interval = max(5, int((code or {}).get('interval') or 5))
    expires_in = max(60, int((code or {}).get('expires_in') or 900))
    if not user_code:
        raise RuntimeError(tr('Simkl did not return a valid pairing code'))

    # Step 2: show the PIN (dialog + sticky notification so it is never lost).
    try:
        xbmcgui.Dialog().ok(tr('Nuvio Hub • Link Simkl'), tr(_build_pin_message(verify, user_code)))
    except Exception as exc:
        xbmc.log('[NuvioHub] simkl Dialog.ok fallback: %s' % exc, xbmc.LOGWARNING)
    xbmc.executebuiltin('Notification(Nuvio Hub,Simkl code: %s,10000)' % user_code)

    # Step 3: poll until the user approves on simkl.com/pin.
    dlg = xbmcgui.DialogProgress()
    dlg.create(tr('Nuvio Hub • Link Simkl'), tr(_build_pin_message(verify, user_code, remaining=expires_in)))
    poll_path = '/oauth/pin/%s?client_id=%s' % (urllib.parse.quote(user_code), urllib.parse.quote(client_id()))
    start = time.time()
    try:
        while not dlg.iscanceled() and (time.time() - start) < expires_in:
            remaining = int(expires_in - (time.time() - start))
            pct = int(max(0, min(100, ((time.time() - start) / float(expires_in)) * 100)))
            dlg.update(pct, tr(_build_pin_message(verify, user_code, remaining=remaining)))
            try:
                token = _request(poll_path, method='GET', auth=False)
                if isinstance(token, dict) and token.get('access_token'):
                    save_token({'access_token': token.get('access_token'), 'created_at': int(time.time())})
                    dlg.close()
                    xbmcgui.Dialog().notification('Nuvio Hub', tr('Simkl linked successfully'), xbmcgui.NOTIFICATION_INFO, 3000)
                    invalidate_cache()
                    return True
                # {"result":"KO"} → pending; keep polling quietly.
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    interval = max(interval, 5) * 2
                elif exc.code in (400, 404):
                    pass  # pending / not-yet-entered — keep polling
                else:
                    xbmc.log('[NuvioHub] simkl poll http %s' % exc.code, xbmc.LOGWARNING)
            except Exception as exc:
                # Transient network hiccup — log and keep polling rather than die.
                xbmc.log('[NuvioHub] simkl poll transient error: %s' % exc, xbmc.LOGWARNING)
            xbmc.sleep(interval * 1000)
    finally:
        try:
            dlg.close()
        except Exception:
            pass
    return False


def logout():
    clear_token()
    invalidate_cache()
    _MARKED_THIS_SESSION.clear()
    return True


# ─── ids / payload helpers ──────────────────────────────────────────────────

def _ids_from_ctx(ctx):
    ids = {}
    imdb = str((ctx or {}).get('imdb_id') or '').strip()
    tmdb = str((ctx or {}).get('tmdb_id') or '').strip()
    tvdb = str((ctx or {}).get('tvdb_id') or '').strip()
    if imdb:
        ids['imdb'] = imdb if imdb.startswith('tt') else 'tt%s' % imdb
    if tmdb:
        ids['tmdb'] = tmdb
    if tvdb:
        ids['tvdb'] = tvdb
    return ids


def history_payload(ctx):
    """Build the POST /sync/history body for a playback ctx (movie or episode)."""
    ids = _ids_from_ctx(ctx)
    if not ids:
        return None
    media_type = str((ctx or {}).get('media_type') or 'movie').lower()
    if media_type in ('series', 'show', 'tv', 'anime', 'episode'):
        try:
            season = int(ctx.get('season'))
            episode = int(ctx.get('episode'))
        except Exception:
            return None
        if season <= 0 and episode <= 0:
            return None
        return {'shows': [{
            'title': ctx.get('show_title') or ctx.get('title') or '',
            'ids': ids,
            'seasons': [{'number': season, 'episodes': [{'number': episode}]}],
        }]}
    return {'movies': [{'title': ctx.get('title') or '', 'ids': ids}]}


def add_to_library(ctx):
    """Save a whole title to Simkl Plan to Watch; never mark episodes watched."""
    if not authorized():raise ValueError('Connect Simkl in HUB Settings first.')
    ids = _ids_from_ctx(ctx)
    if not ids:raise ValueError('This title has no IMDb, TMDb or TVDb ID for Simkl.')
    kind = 'shows' if ctx.get('media_type') in ('series','tv','show','tvshow','anime','episode') else 'movies'
    item = {'ids':ids, 'title':ctx.get('title') or '', 'to':'plantowatch'}
    response = _request('/sync/add-to-list', payload={kind:[item]}, method='POST', auth=True, timeout=8)
    if not isinstance(response, dict) or response.get('error') or any((response.get('not_found') or {}).values()):
        raise ValueError('Simkl could not match this title. Nothing was confirmed as saved.')
    added = response.get('added') or {}
    if not isinstance(added, dict) or not any(
            (isinstance(added.get(k), list) and bool(added[k])) or
            (isinstance(added.get(k), (int,float)) and added[k]>0) for k in (kind,'anime')):
        raise ValueError('Simkl did not confirm saving this title. Check your Plan to Watch list and retry.')
    invalidate_cache('/sync/all-items')
    return True


def _session_key(ctx):
    base = str((ctx or {}).get('video_id') or (ctx or {}).get('canonical_id') or '')
    return base or json.dumps(_ids_from_ctx(ctx), sort_keys=True)


def should_mark_watched(position_ms, duration_ms, threshold=None):
    """Pure decision helper (unit-tested): watched iff progress ≥ threshold."""
    try:
        pos = float(position_ms or 0)
        dur = float(duration_ms or 0)
    except Exception:
        return False
    if dur <= 0:
        # No duration: only the explicit "ended" event (position 0 sentinel
        # from companion.ended when the player closed naturally) counts.
        return pos <= 0
    pct = (pos / dur) * 100.0
    return pct >= float(threshold if threshold is not None else watched_threshold_percent())


def mark_watched_from_ctx(ctx, position_ms=0, force=False):
    """Called by SimklReporter at stop/ended. POSTs /sync/history once per item.

    Returns True when a history write happened, False when skipped (below
    threshold, missing ids, disabled, or already written this session).
    """
    if not (enabled() and authorized() and mark_watched_enabled()):
        return False
    duration_ms = 0
    try:
        duration_ms = int(float((ctx or {}).get('duration_ms') or 0))
    except Exception:
        duration_ms = 0
    threshold = 95 if (ctx or {}).get('nuvio_request_id') else None
    if not force and not should_mark_watched(position_ms, duration_ms, threshold=threshold):
        return False
    key = _session_key(ctx)
    if key in _MARKED_THIS_SESSION:
        return False
    payload = history_payload(ctx)
    if not payload:
        return False
    try:
        response=_request('/sync/history', payload=payload, method='POST', auth=True)
        if isinstance(response,dict) and response.get('added') and not any((response.get('not_found') or {}).values()):
            from . import simkl_watched
            is_episode='shows' in payload
            simkl_watched.record(ctx,'episode' if is_episode else 'title',ctx.get('season'),ctx.get('episode'))
        _MARKED_THIS_SESSION.add(key)
        invalidate_cache('/sync/all-items')
        xbmc.log('[NuvioHub] simkl: marked watched %s' % key, xbmc.LOGINFO)
        return True
    except Exception as exc:
        xbmc.log('[NuvioHub] simkl mark-watched failed for %s: %s' % (key, exc), xbmc.LOGWARNING)
        return False


# ─── lists ──────────────────────────────────────────────────────────────────

def _node_from_row(row, kind):
    """The item node inside an all-items row: movies→'movie', shows/anime→'show'."""
    if not isinstance(row, dict):
        return {}
    if kind == 'movies':
        return row.get('movie') or {}
    return row.get('show') or {}


def normalize_all_items(data, kind):
    """Normalize a /sync/all-items response into mdblist-shaped rows.

    Output rows: {'_type': 'movie'|'show', 'title', 'year'/'release_year',
                  'overview', 'ids': {'imdb','tmdb','tvdb'}} — the exact shape
    plugin._render_idlist_rows() already consumes for MDBList catalogs.
    """
    rows = []
    if not isinstance(data, dict):
        return rows
    bucket = data.get(kind)
    if bucket is None and kind == 'anime':
        bucket = data.get('anime') or data.get('shows')
    for row in (bucket or []):
        node = _node_from_row(row, kind)
        if not node:
            continue
        ids_in = node.get('ids') or {}
        imdb = str(ids_in.get('imdb') or '').strip()
        tmdb = str(ids_in.get('tmdb') or '').strip()
        tvdb = str(ids_in.get('tvdb') or '').strip()
        if not (imdb or tmdb or tvdb):
            continue  # nothing Nuvio Hub can route on
        rows.append({
            '_type': 'movie' if kind == 'movies' else 'show',
            'title': node.get('title') or '',
            'year': node.get('year') or '',
            'release_year': node.get('year') or '',
            'overview': node.get('overview') or '',
            'ids': {'imdb': imdb, 'tmdb': tmdb, 'tvdb': tvdb},
            '_status': str(row.get('status') or ''),
            # v4.2.0: Simkl serves its own poster CDN slug — pass a full URL
            # through so the renderer never shows a bare file icon even when
            # the TMDb art pipeline has nothing for this title.
            'poster': poster_url(node.get('poster')),
            'last_watched': str(row.get('last_watched') or ''),
            'next_to_watch': str(row.get('next_to_watch') or ''),
            'watched_episodes_count': int(row.get('watched_episodes_count') or 0),
            'total_episodes_count': int(row.get('total_episodes_count') or 0),
            'last_watched_at': str(row.get('last_watched_at') or ''),
            'added_to_watchlist_at': str(row.get('added_to_watchlist_at') or ''),
        })
    return rows


_FAIL_LOG_MEMO = {}


def fetch_all_items(kind='shows', status='watching'):
    """User's Simkl list for one kind/status, normalized (see normalize_all_items)."""
    if not enabled():
        return []
    kind = kind if kind in KINDS else 'shows'
    valid = STATUSES_MOVIES if kind == 'movies' else STATUSES_SHOWS
    status = status if status in valid else valid[0]
    path = '/sync/all-items/%s/%s?extended=full' % (kind, status)
    try:
        data = _cached_request(path, auth=True)
    except Exception as exc:
        # v4.7.5: identical transient network errors (DNS/timeouts) repeated
        # 27 times in one session of the user's log. Report each failure
        # signature at most once an hour; the rest go to DEBUG.
        _sig = '%s|%s|%s' % (kind, status, str(exc)[:60])
        _now = time.time()
        if _now - float(_FAIL_LOG_MEMO.get(_sig) or 0.0) > 3600:
            _FAIL_LOG_MEMO[_sig] = _now
            xbmc.log('[NuvioHub] simkl fetch_all_items(%s,%s) failed: %s' % (kind, status, exc), xbmc.LOGWARNING)
        else:
            xbmc.log('[NuvioHub] simkl fetch_all_items(%s,%s) failed (repeat): %s' % (kind, status, exc), xbmc.LOGDEBUG)
        return []
    return normalize_all_items(data, kind)


def import_watched_movies(limit=500):
    """Pull completed movies from Simkl and mark them watched locally.

    v4.1.0 scope: movies only. Per-episode show history needs one request per
    show on Simkl's API; deferred until the batched endpoint is verified live.
    """
    if not (enabled() and authorized()):
        raise RuntimeError(tr('Simkl account is not linked'))
    rows = fetch_all_items('movies', 'completed')
    count = 0
    for row in rows[:max(1, int(limit))]:
        ids = row.get('ids') or {}
        imdb = ids.get('imdb') or ''
        tmdb = ids.get('tmdb') or ''
        canonical = imdb if imdb else ('tmdb:%s' % tmdb if tmdb else '')
        if not canonical:
            continue
        try:
            playback_store.mark_watched('movie', canonical, canonical, mark_dirty=False)
            count += 1
        except Exception:
            continue
    return count


# ── v4.2.0: art + full history import + Continue Watching sync ───────────

def poster_url(slug):
    """Simkl poster CDN. [VERIFY-LIVE] `_m` (medium) jpg variant."""
    slug = str(slug or '').strip()
    return ('https://simkl.in/posters/%s_m.jpg' % slug) if slug else ''


_EP_MARKER_RE = re.compile(r's\s*(\d+)\s*e\s*(\d+)', re.I)


def parse_episode_marker(value):
    """'S02E05' / 's2e5' → (2, 5); anything else → None."""
    match = _EP_MARKER_RE.search(str(value or ''))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _canonical_for(ids):
    imdb = str(ids.get('imdb') or '').strip()
    tmdb = str(ids.get('tmdb') or '').strip()
    tvdb = str(ids.get('tvdb') or '').strip()
    if imdb:
        return imdb if imdb.startswith('tt') else 'tt%s' % imdb
    if tmdb:
        return 'tmdb:%s' % tmdb
    if tvdb:
        return 'tvdb:%s' % tvdb
    return ''


def import_watched(limit=1000):
    """Mark Simkl completed movies + watched show episodes locally.

    Movies: every 'completed' movie → playback_store.mark_watched.
    Shows ('watching' + 'completed' + 'hold'): Simkl's all-items rows carry
    `last_watched` as an SxxEyy marker; episodes 1..Eyy of season Sxx are
    marked. Earlier seasons are intentionally NOT back-filled — real season
    lengths are unknown without one TMDb call per show, and Continue
    Watching correctness comes from sync_continue_watching() pointing at
    `next_to_watch` directly, not from the watched table. Anime rows ride
    the shows pipeline. Returns (movies_marked, episodes_marked).
    """
    if not (enabled() and authorized()):
        raise RuntimeError(tr('Simkl account is not linked'))
    from . import playback_store
    movies = 0
    for row in fetch_all_items('movies', 'completed')[:max(1, int(limit))]:
        canonical = _canonical_for(row.get('ids') or {})
        if not canonical:
            continue
        try:
            playback_store.mark_watched('movie', canonical, canonical, mark_dirty=False)
            movies += 1
        except Exception as exc:
            xbmc.log('[NuvioHub] simkl movie import failed for %s: %s' % (canonical, exc), xbmc.LOGDEBUG)
    episodes = 0
    for kind in ('shows', 'anime'):
        for status in ('watching', 'completed', 'hold'):
            for row in fetch_all_items(kind, status):
                canonical = _canonical_for(row.get('ids') or {})
                marker = parse_episode_marker(row.get('last_watched'))
                if not canonical or not marker:
                    continue
                season, episode = marker
                for e_num in range(1, episode + 1):
                    try:
                        playback_store.mark_watched('series', canonical, '%s:%s:%s' % (canonical, season, e_num), mark_dirty=False)
                        episodes += 1
                    except Exception:
                        pass
    return movies, episodes


def sync_continue_watching(limit=50):
    """Import actual paused playback, never fabricate a next episode at zero."""
    return sync_playback_progress(limit)


def watchlist_mirror_rows(limit=200):
    """'Plan to watch' movies+shows shaped for favorites_store mirror rows."""
    if not (enabled() and authorized()):
        return []
    out = []
    for kind, media_type in (('movies', 'movie'), ('shows', 'series'), ('anime', 'series')):
        for row in fetch_all_items(kind, 'plantowatch')[:limit]:
            canonical = _canonical_for(row.get('ids') or {})
            if not canonical:
                continue
            out.append({
                'media_type': media_type,
                'canonical_id': canonical,
                'title': row.get('title') or '',
                'poster': row.get('poster') or '',
                'background': '',
                'clearlogo': '',
                'year': row.get('year') or 0,
                'plot': row.get('overview') or '',
                'added_at': _epoch(row.get('added_to_watchlist_at')),   # Library calendar (6.0.35)
            })
    return out


def _epoch(value):
    from datetime import datetime
    try:
        return int(datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()) if value else 0
    except (ValueError, TypeError, OverflowError):
        return 0

# True playback progress (Simkl Scrobble API). All HTTP runs on the service
# reporter/idle worker; the durable, account-scoped queue survives restarts.
import hashlib
import threading
_SCROBBLE_LOCK = threading.Lock()
_SCROBBLE_RETRY_AT = 0.0


def _progress_account():
    token = (token_data() or {}).get('access_token') or ''
    return hashlib.sha256(token.encode('utf-8')).hexdigest() if token else ''


def progress_payload(ctx, position_ms):
    ids = _ids_from_ctx(ctx)
    duration = float(ctx.get('duration_ms') or 0)
    if not ids or duration <= 0:
        return None
    percent = 100 if ctx.get('nuvio_completed_by_user') else round(max(0, min(100, float(position_ms or 0) * 100 / duration)), 2)
    title = {'ids': ids, 'title': ctx.get('show_title') or ctx.get('title') or ''}
    data = {'progress': percent}
    if ctx.get('media_type') in ('series', 'show', 'tv', 'anime', 'episode'):
        try: season, episode = int(ctx.get('season')), int(ctx.get('episode'))
        except (ValueError, TypeError): return None
        if season < 0 or episode < 1: return None
        data['anime' if ctx.get('media_type') == 'anime' else 'show'] = title
        data['episode'] = {'season': season, 'number': episode}
    else:
        data['movie'] = title
    return data


def queue_progress(ctx, position_ms, event='pause'):
    if not enabled(): return False
    account = _progress_account()
    payload = progress_payload(ctx, position_ms)
    if not account or not payload: return False
    # Simkl's stop threshold is 80%. Pause preserves 80–94.99% as resumable.
    from .nuviohub.common import SIMKL_WATCHED_PERCENT
    action = 'stop' if payload['progress'] >= SIMKL_WATCHED_PERCENT and mark_watched_enabled() else 'pause'
    if event == 'start' and payload['progress'] < 95: action = 'start'
    from . import continue_local
    key = continue_local.identity(ctx)
    # Each completed episode must survive starting the next episode offline.
    if payload.get('episode'):
        key += '|%s:%s' % (payload['episode']['season'],payload['episode']['number'])
    conn = continue_local.connect()
    try:
        conn.execute('INSERT OR REPLACE INTO nuvio_simkl_outbox VALUES (?, ?, ?, ?)',
                     (account, key, time.time(), json.dumps({'action': action, 'body': payload})))
        conn.execute('DELETE FROM nuvio_simkl_outbox WHERE account=? AND identity NOT IN (SELECT identity FROM nuvio_simkl_outbox WHERE account=? ORDER BY updated DESC LIMIT 50)', (account, account))
        conn.commit()
    finally: conn.close()
    return True


def report_progress(ctx, position_ms, event='pause'):
    if queue_progress(ctx, position_ms, event): return flush_progress()
    return 0


def flush_progress():
    global _SCROBBLE_RETRY_AT
    if not enabled() or time.monotonic() < _SCROBBLE_RETRY_AT: return 0
    account = _progress_account()
    if not account or not _SCROBBLE_LOCK.acquire(False): return 0
    count = 0
    try:
        from . import continue_local
        conn = continue_local.connect()
        try: rows = conn.execute('SELECT identity, updated, payload FROM nuvio_simkl_outbox WHERE account=? ORDER BY updated LIMIT 5', (account,)).fetchall()
        finally: conn.close()
        for key, stamp, raw in rows:
            if _progress_account() != account: break
            data = json.loads(raw)
            try:
                _request('/scrobble/' + data['action'], data['body'], method='POST', auth=True, timeout=6)
            except urllib.error.HTTPError as exc:
                if exc.code != 409:
                    try:delay=max(60,min(3600,float(exc.headers.get('Retry-After') or 60)))
                    except (ValueError,TypeError,AttributeError):delay=60
                    _SCROBBLE_RETRY_AT = time.monotonic() + delay
                    break
            except Exception:
                _SCROBBLE_RETRY_AT = time.monotonic() + 60
                break
            conn = continue_local.connect()
            try:
                # Never delete a newer event saved during the request.
                conn.execute('DELETE FROM nuvio_simkl_outbox WHERE account=? AND identity=? AND updated=?', (account, key, stamp))
                conn.commit()
            finally: conn.close()
            count += 1
        return count
    finally: _SCROBBLE_LOCK.release()


def sync_playback_progress(limit=50):
    if not (enabled() and authorized()): return 0
    from . import trakt
    account = _progress_account()
    data = _request('/sync/playback?limit=%d&hide_watched=true' % min(50, max(1, int(limit))), auth=True, timeout=8)
    if not isinstance(data, list) or account != _progress_account(): return 0
    rows = []
    for entry in data:
        if not isinstance(entry,dict):continue
        node = entry.get('movie') or entry.get('show') or entry.get('anime') or {}
        ids = node.get('ids') or {}; mid = _canonical_for(ids)
        try: percent = float(entry.get('progress') or 0)
        except (TypeError, ValueError): continue
        stamp = trakt._parse_trakt_ts(entry.get('paused_at'))
        if not mid or not 0 < percent < 95 or not stamp: continue
        episode = entry.get('episode') or {}
        series = bool(episode)
        season = episode.get('tvdb_season', episode.get('season'))
        number = episode.get('tvdb_number', episode.get('number', episode.get('episode')))
        if series and (season is None or number is None): continue
        rows.append(dict(media_type='series' if series else 'movie',canonical_id=mid,
            video_id='%s:%s:%s' % (mid, season, number) if series else mid,
            title=node.get('title') or 'Loading title…',provider_name='Simkl',
            poster=poster_url(node.get('poster')) if node.get('poster') else '',
            season=season,episode=number,position=0,duration=0,percent=percent,
            event_type='progress',ext_updated_at=stamp,imdb_id=ids.get('imdb') or '',
            tmdb_id=ids.get('tmdb') or '',tvdb_id=ids.get('tvdb') or ''))
    if account != _progress_account():return 0
    changed = playback_store.upsert_entries(rows, mark_dirty=False)
    if changed:
        from .simkl_watched import _invalidate_view
        _invalidate_view()
    return changed
