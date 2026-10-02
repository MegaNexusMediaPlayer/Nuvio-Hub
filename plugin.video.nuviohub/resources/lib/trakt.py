# -*- coding: utf-8 -*-
import datetime
import json
import os
import time
import urllib.error
import urllib.request

import xbmc
import xbmcaddon
import xbmcgui

from .nuviohub.common import profile_path
from . import playback_store
from . import tmdbhelper as _tmdbhelper_art
from .art import posters_prefer_local
from . import tmdb_direct as _tmdb_direct_art
from .i18n import tr

# --- nuviohub-401-patch ---
try:
    from .settings_cache import cached_addon as _dh_cached_addon
except Exception:
    try:
        from settings_cache import cached_addon as _dh_cached_addon
    except Exception:
        _dh_cached_addon = None
ADDON = _dh_cached_addon() if _dh_cached_addon else xbmcaddon.Addon('plugin.video.nuviohub')
API = 'https://api.trakt.tv'
TOKEN_PATH = os.path.join(profile_path(), 'trakt_token.json')
DEFAULT_CLIENT_ID = '19abc9f8275ec0d9a8099f6edf809714184222778aa83ac50f997f3b02165001'
DEFAULT_CLIENT_SECRET = '039b60d14d91c7b948479f463e4c4bff7bd09035fc24d51a92e376cf39c47ae1'
_PUBLIC_CACHE = {}
_PUBLIC_CACHE_TTL = 300


def _setting(key, default=''):
    try:
        return ADDON.getSetting(key) or default
    except Exception:
        return default


def enabled():
    # v5.4.4: the fallback said 'false' while settings.xml defaults to
    # 'true', so a profile that never touched the key had Trakt silently
    # disabled while the settings screen showed it enabled.
    return (_setting('enable_trakt', 'true') or 'true').lower() == 'true'


def client_id():
    return (_setting('trakt_client_id', '').strip() or DEFAULT_CLIENT_ID).strip()


def client_secret():
    return (_setting('trakt_client_secret', '').strip() or DEFAULT_CLIENT_SECRET).strip()


def credentials_configured():
    return bool(client_id() and client_secret())


def ensure_enabled():
    try:
        if not enabled():
            ADDON.setSetting('enable_trakt', 'true')
    except Exception:
        pass


def authorization_status():
    if authorized():
        return 'connected'
    return 'ready' if credentials_configured() else 'needs_api'


def scrobble_enabled():
    return (_setting('trakt_scrobble', 'true') or 'true').lower() == 'true'


def sync_enabled():
    return (_setting('trakt_sync_progress', 'true') or 'true').lower() == 'true'


def _read_json(path, default):
    # v3.9.17: delegated to safe_io for crash-safe read with .bak recovery.
    from .nuviohub.safe_io import read_json as _safe_read_json
    return _safe_read_json(path, default)


def _write_json(path, value):
    # v3.9.17: delegated to safe_io for atomic write + .bak snapshot —
    # avoids losing your Trakt tokens to a half-written file on power loss.
    from .nuviohub.safe_io import write_json as _safe_write_json
    _safe_write_json(path, value)


def token_data():
    return _read_json(TOKEN_PATH, {})


def save_token(data):
    data = dict(data or {})
    data.setdefault('created_at', int(time.time()))
    _write_json(TOKEN_PATH, data)


def clear_token():
    # 6.0.39: the account's watched marks and unsent watches go with it.
    for path in (TOKEN_PATH, os.path.join(os.path.dirname(TOKEN_PATH), 'trakt_watched.json'),
                 os.path.join(os.path.dirname(TOKEN_PATH), 'trakt_outbox.json')):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def authorized():
    data = token_data()
    return bool(enabled() and credentials_configured() and data.get('access_token'))


def _headers(auth=False):
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'trakt-api-version': '2',
        'User-Agent': 'NuvioHub/%s (Kodi)' % (ADDON.getAddonInfo('version') or '3.7'),
    }
    cid = client_id()
    if cid:
        headers['trakt-api-key'] = cid
    if auth:
        data = token_data()
        token = data.get('access_token') or ''
        if token:
            headers['Authorization'] = 'Bearer %s' % token
    return headers


RATE_WAIT_MAX = 10      # s a 429 may hold one request before it gives up
_REFRESH_LOCK = __import__('threading').Lock()


def _send(path, payload, method, auth, timeout):
    url = API + path
    data = None
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=_headers(auth=auth), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode('utf-8', 'ignore')
        return json.loads(body) if body else {}


def _retry_after(exc):
    try:
        return max(1.0, float((exc.headers or {}).get('Retry-After') or 1))
    except (TypeError, ValueError, AttributeError):
        return 1.0


def _request(path, payload=None, method='GET', auth=False, timeout=20):
    """One Trakt call (6.0.39): a 401 refreshes the sign-in once and retries;
    a 429 waits as long as Trakt asks (up to RATE_WAIT_MAX) and retries once."""
    try:
        return _send(path, payload, method, auth, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 401 and auth and token_data().get('refresh_token'):
            _refresh_token_if_needed(force=True)
        elif exc.code == 429 and _retry_after(exc) <= RATE_WAIT_MAX:
            time.sleep(_retry_after(exc))
        else:
            raise
    return _send(path, payload, method, auth, timeout)


def _refresh_token_if_needed(force=False):
    with _REFRESH_LOCK:   # one refresh at a time: Trakt revokes a used refresh token
        return _refresh_locked(force)


def _refresh_locked(force=False):
    data = token_data()
    if not data.get('refresh_token'):
        return data
    created = int(data.get('created_at') or 0)
    expires_in = int(data.get('expires_in') or 0)
    if not force and data.get('access_token') and expires_in and (created + expires_in - 300) > int(time.time()):
        return data
    payload = {
        'refresh_token': data.get('refresh_token'),
        'client_id': client_id(),
        'client_secret': client_secret(),
        'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
        'grant_type': 'refresh_token',
    }
    try:
        refreshed = _send('/oauth/token', payload, 'POST', False, 20)
    except Exception:
        refreshed = None
    if isinstance(refreshed, dict) and refreshed.get('access_token'):
        refreshed['created_at'] = int(time.time())
        save_token(refreshed)
        return refreshed
    return data


def _ensure_auth():
    ensure_enabled()
    if not credentials_configured():
        raise RuntimeError('Trakt credentials are not bundled in this build')
    data = _refresh_token_if_needed(force=False)
    if not data.get('access_token'):
        raise RuntimeError('Trakt is not linked yet')
    return data


def _build_pin_message(verify_url, user_code, remaining=None):
    """Single-string message compatible with Kodi 20+ (Nexus/Omega) dialogs."""
    lines = [
        '[B]1) Open this link:[/B]',
        '[COLOR orange]%s[/COLOR]' % verify_url,
        '',
        '[B]2) Enter this code:[/B]',
        '[COLOR yellow][B]   %s   [/B][/COLOR]' % user_code,
    ]
    if remaining is not None:
        lines.append('')
        lines.append(tr('Remaining: %ss') % int(remaining))
    return '\n'.join(lines)


def device_auth():
    ensure_enabled()
    if not credentials_configured():
        raise RuntimeError('Trakt credentials are not bundled in this build')

    # Step 1: request a device code.
    try:
        code = _request('/oauth/device/code', payload={'client_id': client_id()}, method='POST', auth=False)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', 'ignore')
        except Exception:
            body = ''
        raise RuntimeError(tr('Trakt device-code request failed (%s): %s') % (exc.code, body[:200]))
    except Exception as exc:
        raise RuntimeError(tr('Trakt connection failed: %s') % exc)

    user_code = (code.get('user_code') or '').strip()
    device_code = (code.get('device_code') or '').strip()
    verify = code.get('verification_url') or 'https://trakt.tv/activate'
    interval = max(5, int(code.get('interval') or 5))
    expires_in = max(60, int(code.get('expires_in') or 600))

    if not user_code or not device_code:
        raise RuntimeError('Trakt did not return a valid device code')

    # Step 2: show the PIN to the user.
    # Kodi 20+ Dialog API: ok(heading, message) — old multi-line signature was removed.
    shown_ok = False
    try:
        xbmcgui.Dialog().ok(tr('Nuvio Hub • Trakt link'), tr(_build_pin_message(verify, user_code)))
        shown_ok = True
    except Exception as exc:
        xbmc.log('[NuvioHub] Dialog.ok fallback: %s' % exc, xbmc.LOGWARNING)

    # Fallback / reinforcement: sticky notification so the code is never lost.
    xbmc.executebuiltin('Notification(Nuvio Hub,Trakt code: %s,10000)' % user_code)

    # Step 3: polling dialog.
    dlg = xbmcgui.DialogProgress()
    # Kodi 20+ DialogProgress: create(heading, message).
    dlg.create(tr('Nuvio Hub • Trakt link'), tr(_build_pin_message(verify, user_code, remaining=expires_in)))

    start = time.time()
    try:
        while not dlg.iscanceled() and (time.time() - start) < expires_in:
            remaining = int(expires_in - (time.time() - start))
            pct = int(max(0, min(100, ((time.time() - start) / float(expires_in)) * 100)))
            # Kodi 20+ DialogProgress: update(percent, message).
            dlg.update(pct, tr(_build_pin_message(verify, user_code, remaining=remaining)))
            try:
                token = _send('/oauth/device/token', {   # its own 400/429 polling rules
                    'code': device_code,
                    'client_id': client_id(),
                    'client_secret': client_secret(),
                }, 'POST', False, 20)
                if isinstance(token, dict) and token.get('access_token'):
                    token['created_at'] = int(time.time())
                    save_token(token)
                    dlg.close()
                    xbmcgui.Dialog().notification('Nuvio Hub', tr('Trakt linked successfully'), xbmcgui.NOTIFICATION_INFO, 3000)
                    return True
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read().decode('utf-8', 'ignore')
                except Exception:
                    body = ''
                if exc.code == 400:
                    pass  # pending authorization — keep polling
                elif exc.code == 429:
                    interval = max(interval, 5) * 2
                elif exc.code == 404:
                    dlg.close()
                    raise RuntimeError('Invalid Trakt link code, please try again')
                elif exc.code == 409:
                    dlg.close()
                    raise RuntimeError('This Trakt code was already used. Start a new link flow')
                elif exc.code == 410:
                    dlg.close()
                    raise RuntimeError('The Trakt code expired. Please try again')
                elif exc.code == 418:
                    dlg.close()
                    raise RuntimeError('The Trakt link was denied on the activation page')
                else:
                    dlg.close()
                    raise RuntimeError(tr('Trakt link failed: %s %s') % (exc.code, body[:200]))
            except Exception as exc:
                # Transient network hiccup — log and keep polling rather than die.
                xbmc.log('[NuvioHub] trakt poll transient error: %s' % exc, xbmc.LOGWARNING)
            xbmc.sleep(interval * 1000)
    finally:
        try:
            dlg.close()
        except Exception:
            pass
    return False


def logout():
    data = token_data()
    token = data.get('access_token')
    if token and client_id() and client_secret():
        try:
            _request('/oauth/revoke', payload={
                'token': token,
                'client_id': client_id(),
                'client_secret': client_secret(),
            }, method='POST', auth=False)
        except Exception:
            pass
    clear_token()
    xbmcgui.Dialog().notification('Nuvio Hub', tr('Signed out from Trakt'), xbmcgui.NOTIFICATION_INFO, 2500)


def _ids_payload(ctx):
    ids = {}
    imdb = str(ctx.get('imdb_id') or '').strip()
    tmdb = str(ctx.get('tmdb_id') or '').strip()
    tvdb = str(ctx.get('tvdb_id') or '').strip()
    if imdb:
        ids['imdb'] = imdb if imdb.startswith('tt') else 'tt%s' % imdb
    if tmdb and tmdb.isdigit():
        ids['tmdb'] = int(tmdb)
    elif tmdb:
        try:
            ids['tmdb'] = int(float(tmdb))
        except Exception:
            pass
    if tvdb and tvdb.isdigit():
        ids['tvdb'] = int(tvdb)
    elif tvdb:
        try:
            ids['tvdb'] = int(float(tvdb))
        except Exception:
            pass
    return ids


def _progress(ctx, position_ms):
    duration = float(ctx.get('duration_ms') or 0)
    if duration <= 0:
        return 0.0
    return max(0.0, min(100.0, (float(position_ms or 0) / duration) * 100.0))


def _movie_payload(ctx, position_ms):
    payload = {
        'progress': round(_progress(ctx, position_ms), 2),
        'app_version': ADDON.getAddonInfo('version') or '3.7',
        'app_date': datetime.date.today().isoformat(),
        'movie': {
            'title': ctx.get('title') or '',
            'year': int(ctx.get('year') or 0) or None,
            'ids': _ids_payload(ctx),
        }
    }
    if payload['movie']['year'] is None:
        payload['movie'].pop('year', None)
    return payload


def _episode_payload(ctx, position_ms):
    payload = {
        'progress': round(_progress(ctx, position_ms), 2),
        'app_version': ADDON.getAddonInfo('version') or '3.7',
        'app_date': datetime.date.today().isoformat(),
        'show': {
            'title': ctx.get('show_title') or ctx.get('title') or '',
            'year': int(ctx.get('year') or 0) or None,
            'ids': _ids_payload(ctx),
        },
        'episode': {
            'season': int(ctx.get('season') or 0),
            'number': int(ctx.get('episode') or 0),
        }
    }
    if payload['show']['year'] is None:
        payload['show'].pop('year', None)
    return payload


def _scrobble_payload(ctx, position_ms):
    media_type = str(ctx.get('media_type') or 'movie').lower()
    if media_type in ('series', 'show', 'tv', 'anime') or ctx.get('season') or ctx.get('episode'):
        return _episode_payload(ctx, position_ms)
    return _movie_payload(ctx, position_ms)


def scrobble(action, ctx, position_ms=0):
    """Safe scrobble — never raises into the player."""
    if not (enabled() and scrobble_enabled()):
        return None
    try:
        data = _ensure_auth()
    except Exception as exc:
        xbmc.log('[NuvioHub] trakt scrobble skipped (not auth): %s' % exc, xbmc.LOGDEBUG)
        return None
    if not data.get('access_token'):
        return None
    try:
        progress = _progress(ctx or {}, position_ms)
        # Avoid Trakt 422 noise when playback fails before the first frame or
        # stops at 0%. NuvioHub already stores local progress separately.
        if str(action or '').lower() in ('stop', 'pause') and progress <= 0.5:
            return None
        payload = _scrobble_payload(ctx or {}, position_ms)
        ids = ((payload.get('movie') or payload.get('show') or {}).get('ids') or {})
        if not ids:
            return None
        try:
            return _request('/scrobble/%s' % action, payload=payload, method='POST', auth=True)
        except urllib.error.HTTPError as exc:
            if exc.code == 409:   # already scrobbled
                return None
            if exc.code < 500 and exc.code != 429:
                raise
            if str(action).lower() == 'stop':
                _queue_scrobble(payload)
            raise
        except (urllib.error.URLError, OSError):
            if str(action).lower() == 'stop':
                _queue_scrobble(payload)   # offline: the watch reaches Trakt later
            raise
    except Exception as exc:
        xbmc.log('[NuvioHub] trakt scrobble failed: %s' % exc, xbmc.LOGWARNING)
        return None


OUTBOX_PATH = os.path.join(profile_path(), 'trakt_outbox.json')
OUTBOX_MAX = 50
_OUTBOX_LOCK = __import__('threading').Lock()


def _queue_scrobble(payload):
    """A finished watch that could not reach Trakt (offline, Trakt down)."""
    with _OUTBOX_LOCK:
        rows = _read_json(OUTBOX_PATH, [])
        rows = (rows if isinstance(rows, list) else [])[-(OUTBOX_MAX - 1):]
        rows.append({'at': int(time.time()), 'payload': payload})
        _write_json(OUTBOX_PATH, rows)


def flush_outbox(limit=5):
    """Send queued finished watches as history (with their real watch time).

    /sync/history instead of a late /scrobble/stop: Trakt would otherwise log
    them at the moment of sending."""
    if not authorized():
        return 0
    with _OUTBOX_LOCK:
        rows = _read_json(OUTBOX_PATH, [])
        if not isinstance(rows, list) or not rows:
            return 0
        sent = 0
        for row in list(rows[:limit]):
            payload = row.get('payload') or {}
            when = datetime.datetime.utcfromtimestamp(int(row.get('at') or time.time())).strftime('%Y-%m-%dT%H:%M:%S.000Z')
            if payload.get('movie'):
                body = {'movies': [dict(payload['movie'], watched_at=when)]}
            elif payload.get('show') and payload.get('episode'):
                body = {'shows': [dict(payload['show'], seasons=[{'number': payload['episode']['season'],
                        'episodes': [{'number': payload['episode']['number'], 'watched_at': when}]}])]}
            else:
                body = None
            if body:
                try:
                    _request('/sync/history', payload=body, method='POST', auth=True, timeout=10)
                except urllib.error.HTTPError as exc:
                    if exc.code >= 500 or exc.code in (401, 429):
                        break   # keep it for the next round
                except Exception:
                    break
            rows.remove(row)
            sent += 1
        _write_json(OUTBOX_PATH, rows)
        return sent


def _canonical_from_ids(ids, fallback_title=''):
    ids = ids or {}
    if ids.get('tmdb'):
        return 'tmdb:%s' % ids.get('tmdb')
    if ids.get('imdb'):
        return ids.get('imdb')
    if ids.get('tvdb'):
        return 'tvdb:%s' % ids.get('tvdb')
    if ids.get('trakt'):
        return 'trakt:%s' % ids.get('trakt')
    return fallback_title or ''


def _fetch_art_setting():
    raw = (_setting('trakt_fetch_art', 'true') or 'true').lower()
    return raw not in ('false', '0', 'no')


def _art_bundle_for_ids(ids, media_type, title='', force_remote=False):
    """Resolve fanart/clearlogo, and only use remote posters when enabled.

    `force_remote=True` overrides the 'Local only' poster preference. Used by
    Next Up rows because they have no local provider context — the row is
    derived from a Trakt sync, so the only available poster source is remote.
    """
    if not _fetch_art_setting():
        return {'poster': '', 'fanart': '', 'clearlogo': ''}
    ids = ids or {}
    tmdb_id = str(ids.get('tmdb') or '').strip()
    imdb_id = str(ids.get('imdb') or '').strip()
    prefer_local_poster = posters_prefer_local() and not force_remote
    try:
        bundle = _tmdbhelper_art.get_art_bundle_from_db(
            tmdb_id=tmdb_id,
            media_type='tv' if media_type == 'series' else 'movie',
            imdb_id=imdb_id,
            title=title or '',
        ) or {}
    except Exception:
        bundle = {}
    need_direct = not (bundle.get('fanart') and bundle.get('clearlogo') and (prefer_local_poster or bundle.get('poster')))
    if need_direct:
        try:
            direct = _tmdb_direct_art.art_for(
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
                media_type='tv' if media_type == 'series' else 'movie',
                title=title or '',
            ) or {}
        except Exception:
            direct = {}
    else:
        direct = {}
    return {
        'poster': '' if prefer_local_poster else (bundle.get('poster') or direct.get('poster') or ''),
        'fanart': bundle.get('fanart') or bundle.get('landscape') or direct.get('fanart') or direct.get('landscape') or '',
        'clearlogo': bundle.get('clearlogo') or direct.get('clearlogo') or '',
    }



def _cached_public_request(path, timeout=20):
    now = time.time()
    cached = _PUBLIC_CACHE.get(path)
    if cached and (now - cached[0]) <= _PUBLIC_CACHE_TTL:
        return cached[1]
    data = _request(path, method='GET', auth=False, timeout=timeout)
    _PUBLIC_CACHE[path] = (now, data)
    return data


def invalidate_cache(prefix=''):
    """Drop entries from the public-request cache.

    With no prefix → clears ALL cached Trakt responses.
    With a prefix → clears every entry whose key starts with or equals it.

    Service-side sync calls this with 'next_up_v1' and '/sync/playback/' so the
    Next Up widget reflects the freshest data immediately after sync, instead
    of waiting for the natural TTL (10min/6h) to expire.
    """
    if not prefix:
        _PUBLIC_CACHE.clear()
        return
    prefix = str(prefix)
    for key in [k for k in list(_PUBLIC_CACHE.keys()) if str(k).startswith(prefix) or k == prefix]:
        _PUBLIC_CACHE.pop(key, None)


def import_progress(limit=100):
    if not (enabled() and sync_enabled()):
        raise RuntimeError('Enable Trakt sync from settings')
    _ensure_auth()
    pending = []
    for path, media_type in (('/sync/playback/movies?extended=full', 'movie'), ('/sync/playback/episodes?extended=full', 'series')):
        try:
            rows = _request(path, method='GET', auth=True) or []
        except Exception:
            rows = []
        for row in rows[:limit]:
            try:
                # Trakt gives `paused_at` (ISO 8601) — use it as the row's
                # updated_at so Continue Watching ordering stays stable across
                # imports. Falling back to time.time() reshuffled the row on
                # every sync (the original 3.7.5 bug).
                paused_at = _parse_trakt_ts(row.get('paused_at') or row.get('last_watched_at'))
                if media_type == 'movie':
                    movie = row.get('movie') or {}
                    ids = movie.get('ids') or {}
                    title = movie.get('title') or 'Unknown'
                    runtime = float(movie.get('runtime') or 0) * 60.0
                    duration = runtime if runtime > 0 else 0.0
                    progress = float(row.get('progress') or 0.0)
                    position = (duration * progress / 100.0) if duration > 0 else 0.0
                    canonical = _canonical_from_ids(ids, title)
                    art = _art_bundle_for_ids(ids, 'movie', title=title)
                    pending.append({
                        'media_type': 'movie', 'canonical_id': canonical,
                        'video_id': canonical, 'title': title,
                        'provider_name': 'Trakt', 'poster': art['poster'],
                        'background': art['fanart'], 'clearlogo': art['clearlogo'],
                        'season': None, 'episode': None, 'position': position,
                        'duration': duration, 'percent': progress,
                        'stream_url': '', 'event_type': 'progress',
                        'ext_updated_at': paused_at,
                        'tmdb_id': str(ids.get('tmdb') or ''),
                        'imdb_id': str(ids.get('imdb') or ''),
                        'tvdb_id': str(ids.get('tvdb') or ''),
                    })
                else:
                    episode = row.get('episode') or {}
                    show = row.get('show') or {}
                    ids = show.get('ids') or {}
                    title = show.get('title') or 'Unknown'
                    runtime = float(episode.get('runtime') or show.get('runtime') or 0) * 60.0
                    duration = runtime if runtime > 0 else 0.0
                    progress = float(row.get('progress') or 0.0)
                    position = (duration * progress / 100.0) if duration > 0 else 0.0
                    canonical = _canonical_from_ids(ids, title)
                    video_id = '%s:%s:%s' % (canonical, int(episode.get('season') or 0), int(episode.get('number') or 0))
                    art = _art_bundle_for_ids(ids, 'series', title=title)
                    pending.append({
                        'media_type': 'series', 'canonical_id': canonical,
                        'video_id': video_id, 'title': title,
                        'provider_name': 'Trakt', 'poster': art['poster'],
                        'background': art['fanart'], 'clearlogo': art['clearlogo'],
                        'season': int(episode.get('season') or 0),
                        'episode': int(episode.get('number') or 0),
                        'position': position, 'duration': duration,
                        'percent': progress, 'stream_url': '',
                        'event_type': 'progress', 'ext_updated_at': paused_at,
                        'tmdb_id': str(ids.get('tmdb') or ''),
                        'show_tmdb_id': str(ids.get('tmdb') or ''),
                        'imdb_id': str(ids.get('imdb') or ''),
                        'tvdb_id': str(ids.get('tvdb') or ''),
                    })
            except Exception:
                continue
    if not pending:
        return 0
    return int(playback_store.upsert_entries(pending, mark_dirty=False) or 0)


def _parse_trakt_ts(value):
    """Parse a Trakt ISO 8601 timestamp into epoch seconds, or None."""
    if not value:
        return None
    try:
        s = str(value).strip()
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        return int(datetime.datetime.fromisoformat(s).timestamp())
    except Exception:
        try:
            return int(time.mktime(time.strptime(str(value)[:19], '%Y-%m-%dT%H:%M:%S')))
        except Exception:
            return None


def fetch_watchlist(limit=100):
    """Return movies + shows on the user's Trakt watchlist."""
    if not enabled():
        return []
    try:
        _ensure_auth()
    except Exception:
        return []
    out = []
    for path, media_type in (('/users/me/watchlist/movies', 'movie'),
                             ('/users/me/watchlist/shows', 'series')):
        try:
            rows = _request(path, method='GET', auth=True) or []
        except Exception:
            rows = []
        for row in rows[:limit]:
            try:
                node = row.get('movie') if media_type == 'movie' else row.get('show')
                if not node:
                    continue
                ids = node.get('ids') or {}
                title = node.get('title') or ''
                year = int(node.get('year') or 0)
                # 6.0.35: IMDb first, like Simkl and the Stremio add-ons - with
                # TMDb first the same title got two Library cards (Trakt +
                # Simkl) and no poster (posters are found by IMDb ID).
                imdb = str(ids.get('imdb') or '').strip()
                canonical = (imdb if imdb.startswith('tt') else 'tt' + imdb) if imdb else _canonical_from_ids(ids, title)
                art = _art_bundle_for_ids(ids, media_type, title=title) if (_setting('trakt_fetch_art', 'true') == 'true') else {'poster':'', 'fanart':'', 'clearlogo':''}
                out.append({
                    'media_type': media_type,
                    'canonical_id': canonical,
                    'title': title,
                    'year': year,
                    'plot': node.get('overview') or '',
                    'poster': art.get('poster') or '',
                    'background': art.get('fanart') or '',
                    'clearlogo': art.get('clearlogo') or '',
                    'added_at': _parse_trakt_ts(row.get('listed_at')) or int(time.time()),
                })
            except Exception:
                continue
    return out


def fetch_next_up(limit=40):
    """Return the next unwatched episode for every show the user has started.

    Uses Trakt's `/sync/watched/shows` to find started shows, then
    `/shows/{id}/progress/watched` to get the next episode for each.
    Cached results are returned from a 10-minute in-memory cache to keep
    the home screen snappy.
    """
    cache_key = 'next_up_v1'
    cached = _PUBLIC_CACHE.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]
    if not enabled():
        return []
    try:
        _ensure_auth()
    except Exception:
        return []
    out = []
    try:
        watched = _request('/sync/watched/shows', method='GET', auth=True) or []
    except Exception:
        watched = []
    # Sort by last_watched_at descending so the home row leads with the most
    # recently active shows.
    def _key(row):
        return _parse_trakt_ts((row.get('last_watched_at') or '')) or 0
    watched = sorted(watched, key=_key, reverse=True)[:limit]
    for row in watched:
        try:
            show = row.get('show') or {}
            ids = show.get('ids') or {}
            slug = ids.get('slug') or ids.get('trakt')
            if not slug:
                continue
            try:
                progress = _request('/shows/%s/progress/watched?hidden=false&specials=false' % slug,
                                    method='GET', auth=True) or {}
            except Exception:
                continue
            nxt = (progress or {}).get('next_episode') or {}
            if not nxt:
                continue
            title = show.get('title') or 'Unknown'
            canonical = _canonical_from_ids(ids, title)
            art = _art_bundle_for_ids(ids, 'series', title=title, force_remote=True) if (_setting('trakt_fetch_art', 'true') == 'true') else {'poster':'', 'fanart':'', 'clearlogo':''}
            season_n = int(nxt.get('season') or 0)
            episode_n = int(nxt.get('number') or 0)
            out.append({
                'media_type': 'series',
                'canonical_id': canonical,
                'video_id': '%s:%s:%s' % (canonical, season_n, episode_n),
                'title': title,
                'episode_title': nxt.get('title') or '',
                'season': season_n,
                'episode': episode_n,
                'plot': nxt.get('overview') or show.get('overview') or '',
                'poster': art.get('poster') or '',
                'background': art.get('fanart') or '',
                'clearlogo': art.get('clearlogo') or '',
                'last_watched_at': _parse_trakt_ts(row.get('last_watched_at')) or int(time.time()),
            })
        except Exception:
            continue
    _PUBLIC_CACHE[cache_key] = (time.time() + 600, out)  # 10-minute cache
    return out


def fetch_user_list_summary(username, slug):
    """Fetch public metadata about a Trakt list itself (description, counts, etc)."""
    username = (username or '').strip()
    slug = (slug or '').strip()
    if not username or not slug:
        return {}
    path = '/users/%s/lists/%s?extended=full' % (username, slug)
    try:
        data = _cached_public_request(path)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            try:
                data = _request(path, method='GET', auth=True)
            except Exception:
                return {}
        else:
            return {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def fetch_user_list(username, slug, list_type='movies,shows', limit=None):
    """Fetch a public Trakt list's items.

    Does NOT require auth for public lists. Returns the raw list rows from
    Trakt (each row has either a 'movie' or 'show' sub-object with ids).
    """
    username = (username or '').strip()
    slug = (slug or '').strip()
    if not username or not slug:
        return []
    path = '/users/%s/lists/%s/items?type=%s&extended=full' % (username, slug, list_type)
    if limit:
        try:
            path += '&limit=%d' % max(1, int(limit))
        except Exception:
            pass
    try:
        data = _cached_public_request(path)
    except urllib.error.HTTPError as exc:
        # 401 means the list is private; try with auth.
        if exc.code in (401, 403):
            try:
                data = _request(path, method='GET', auth=True)
            except Exception:
                return []
        else:
            return []
    except Exception:
        return []
    return data if isinstance(data, list) else []


_PROGRESS_LOOKUP_CACHE = {}
_PROGRESS_LOOKUP_TTL = 90

def find_playback_progress(media_type='movie', tmdb_id='', imdb_id='', tvdb_id='', season=None, episode=None):
    """Return the matching unfinished Trakt playback item on demand.

    Background sync remains the normal path. This targeted fallback is used
    only when a TMDb Helper handoff has no usable local/live resume point, so a
    recent Trakt pause is available immediately instead of after the next
    service interval. Results are cached briefly to avoid repeated API calls.
    """
    if not (enabled() and sync_enabled() and authorized()):
        return {}
    mt = str(media_type or 'movie').lower()
    is_ep = mt in ('series','show','tv','episode','anime') or (season not in (None,'',0,'0') and episode not in (None,'',0,'0'))
    try:
        wanted_s, wanted_e = int(season or 0), int(episode or 0)
    except Exception:
        wanted_s, wanted_e = 0, 0
    imdb = str(imdb_id or '').lower().replace('imdb:', '').strip()
    if imdb.isdigit(): imdb = 'tt'+imdb
    key = ('ep' if is_ep else 'movie', str(tmdb_id or ''), imdb, str(tvdb_id or ''), wanted_s, wanted_e)
    now = time.time()
    cached = _PROGRESS_LOOKUP_CACHE.get(key)
    if cached and now-cached[0] <= _PROGRESS_LOOKUP_TTL:
        return dict(cached[1])
    path = '/sync/playback/episodes?extended=full' if is_ep else '/sync/playback/movies?extended=full'
    try:
        rows = _request(path, method='GET', auth=True, timeout=12) or []
    except Exception as exc:
        xbmc.log('[NuvioHub] trakt direct progress lookup failed: %s' % exc, xbmc.LOGWARNING)
        return {}
    best = {}
    for row in rows:
        try:
            item = (row.get('show') or {}) if is_ep else (row.get('movie') or {})
            ids = item.get('ids') or {}
            matched = False
            if tmdb_id and str(ids.get('tmdb') or '') == str(tmdb_id): matched = True
            if not matched and imdb and str(ids.get('imdb') or '').lower() == imdb: matched = True
            if not matched and tvdb_id and str(ids.get('tvdb') or '') == str(tvdb_id): matched = True
            if not matched: continue
            ep = row.get('episode') or {}
            if is_ep and (int(ep.get('season') or 0) != wanted_s or int(ep.get('number') or 0) != wanted_e):
                continue
            progress = float(row.get('progress') or 0.0)
            if not (1.0 < progress < 95.0): continue
            runtime_min = float((ep.get('runtime') if is_ep else item.get('runtime')) or item.get('runtime') or 0.0)
            duration = runtime_min * 60.0 if runtime_min > 0 else 0.0
            position = duration * progress / 100.0 if duration > 0 else 0.0
            updated = _parse_trakt_ts(row.get('paused_at') or row.get('last_watched_at')) or 0
            candidate = {'resume_seconds': position, 'resume_percent': progress, 'duration': duration, 'updated_at': updated, 'source': 'trakt'}
            if not best or updated > int(best.get('updated_at') or 0): best = candidate
        except Exception:
            continue
    _PROGRESS_LOOKUP_CACHE[key] = (now, dict(best))
    return best
