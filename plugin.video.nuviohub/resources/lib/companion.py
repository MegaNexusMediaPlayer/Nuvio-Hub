# -*- coding: utf-8 -*-
import json
import urllib.error
import urllib.parse
import urllib.request
import threading
import time
import queue

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from .session_store import clear_session, load_session, save_session
from . import trakt, simkl, playback_store
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

_SOURCE_SWITCH_HANDOFF_PROP = 'nuviohub.source_switch_handoff.v2'

# v5.4.11: files that are NEVER NuvioHub playback, no matter what a (possibly
# stale) session file says. TMDb Helper resolves every play through a local
# dummy clip whose 100ms start/stop double mode-switches the AML display
# pipeline — the companion must be completely silent for it.
_FOREIGN_FILE_MARKERS = (
    'plugin.video.themoviedb.helper',
    'dummy.mp4',
)


def _source_switch_handoff_read():
    try:
        raw = xbmcgui.Window(10000).getProperty(_SOURCE_SWITCH_HANDOFF_PROP) or ''
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            return {}
        expires = float(data.get('expires_at') or 0.0)
        if expires and time.time() > expires:
            xbmcgui.Window(10000).clearProperty(_SOURCE_SWITCH_HANDOFF_PROP)
            return {}
        return data
    except Exception:
        return {}


def _source_switch_handoff_ack(data):
    try:
        payload = dict(data or {})
        if not payload.get('token'):
            return False
        payload['ack'] = True
        payload['ack_at'] = time.time()
        xbmcgui.Window(10000).setProperty(
            _SOURCE_SWITCH_HANDOFF_PROP,
            json.dumps(payload, separators=(',', ':')),
        )
        return True
    except Exception:
        return False


def _monitor_path():
    try:
        import xbmcvfs
        return xbmcvfs.translatePath('special://profile/addon_data/plugin.video.nuviohub/playback_monitor.log')
    except Exception:
        try:
            return xbmcvfs.translatePath('special://profile/addon_data/plugin.video.nuviohub/playback_monitor.log')
        except Exception:
            return ''


def _monitor(event, level=xbmc.LOGINFO, **payload):
    record = {'event': str(event or ''), 'ts': int(time.time())}
    for key, value in dict(payload or {}).items():
        if value in (None, '', [], {}, ()): 
            continue
        try:
            record[key] = value if isinstance(value, (dict, list)) else str(value)
        except Exception:
            continue
    try:
        xbmc.log('[NuvioHubMonitor] %s' % json.dumps(record, ensure_ascii=False, sort_keys=True), level)
    except Exception:
        pass
    try:
        path = _monitor_path()
        if path:
            import os
            folder = os.path.dirname(path)
            if folder and not os.path.exists(folder):
                os.makedirs(folder, exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > 262144:
                with open(path, 'rb') as fh:
                    data = fh.read()[-131072:]
                with open(path, 'wb') as fh:
                    fh.write(data)
            with open(path, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
    except Exception:
        pass


def _timeout():
    try:
        return max(3, int(ADDON.getSetting('timeout') or '20'))
    except Exception:
        return 20


def _interval_seconds():
    try:
        return max(2, int(ADDON.getSetting('companion_interval') or '5'))
    except Exception:
        return 5


def companion_enabled():
    try:
        return (ADDON.getSetting('enable_companion_sync') or 'true').lower() == 'true'
    except Exception:
        return True


def _json_post(url, payload, headers=None):
    data = json.dumps(payload or {}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=dict(headers or {}, **{'Content-Type': 'application/json', 'Accept': 'application/json'}), method='POST')
    with urllib.request.urlopen(req, timeout=_timeout()) as resp:
        return resp.read().decode('utf-8', 'ignore')


def _json_get(url, headers=None):
    req = urllib.request.Request(url, headers=dict(headers or {}, **{'Accept': 'application/json'}), method='GET')
    with urllib.request.urlopen(req, timeout=_timeout()) as resp:
        return json.loads(resp.read().decode('utf-8', 'ignore'))


def _absolute_url(base, maybe_url):
    value = str(maybe_url or '').strip()
    if not value:
        return ''
    if value.startswith('http://') or value.startswith('https://'):
        return value
    if value.startswith('/') and base:
        parsed = urllib.parse.urlparse(base)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}{value}"
    return value


def _session_owned_by(ctx):
    """True when the CURRENT stored session belongs to this playback.

    v3.9.152: onPlayBackStopped/Ended used to clear_session()
    unconditionally. When the user switches sources, the OLD stream's stop
    event can arrive AFTER the NEW playback already saved its session — the
    late clear then wipes the new session and switch_source reports
    "nothing to switch" while a video is clearly playing.  Identity is
    compared via stream_key (persisted since v3.9.152) with stream_url as
    fallback; when neither side is comparable we keep the old behaviour.
    """
    try:
        sess = load_session() or {}
    except Exception:
        return True
    mine_uid = (ctx or {}).get('playback_uid') or ''
    cur_uid = sess.get('playback_uid') or ''
    if mine_uid and cur_uid:
        return cur_uid == mine_uid
    mine = (ctx or {}).get('stream_key') or ''
    cur = sess.get('stream_key') or ''
    if not (mine and cur):
        mine = (ctx or {}).get('stream_url') or ''
        cur = sess.get('stream_url') or ''
        if not (mine and cur):
            return True
    return cur == mine


class BaseReporter(object):
    def started(self, ctx, position_ms=0):
        raise NotImplementedError
    def progress(self, ctx, position_ms):
        raise NotImplementedError
    def paused(self, ctx, position_ms):
        raise NotImplementedError
    def stopped(self, ctx, position_ms):
        raise NotImplementedError
    def ended(self, ctx, position_ms=0):
        raise NotImplementedError


class UrlCompanionReporter(BaseReporter):
    def _headers(self, ctx):
        headers = {}
        client_id = ctx.get('clientIdentifier') or ctx.get('client_id')
        if client_id:
            headers['X-Plex-Client-Identifier'] = client_id
        product = ctx.get('product') or 'Nuvio Hub'
        headers['X-Plex-Product'] = product
        headers['X-Plex-Platform'] = 'Kodi'
        headers['X-Plex-Device'] = 'Kodi'
        headers['X-Plex-Device-Name'] = ctx.get('deviceName') or 'Kodi'
        if ctx.get('token'):
            headers['X-Plex-Token'] = ctx.get('token')
        return headers

    def _bootstrap(self, ctx):
        if ctx.get('_bootstrapped'):
            return
        url = ctx.get('bootstrapUrl')
        if not url and ctx.get('companionUrl'):
            url = str(ctx['companionUrl']).replace('/companion/timeline/', '/companion/bootstrap/')
        if not url:
            ctx['_bootstrapped'] = True
            return
        try:
            data = _json_get(url, headers=self._headers(ctx))
            if isinstance(data, dict):
                for src, dst in [('timelineUrl','companionUrl'),('scrobbleUrl','companionScrobbleUrl'),('unscrobbleUrl','companionUnscrobbleUrl'),('sessionIdentifier','sessionIdentifier'),('playbackSessionId','playbackSessionId'),('clientIdentifier','clientIdentifier')]:
                    val = data.get(src)
                    val = _absolute_url(url, val)
                    if val:
                        ctx[dst] = val
                interval = data.get('intervalMs')
                if interval and not ctx.get('intervalSeconds'):
                    try:
                        ctx['intervalSeconds'] = max(2, int(float(interval) / 1000.0))
                    except Exception:
                        pass
                if data.get('duration') and not ctx.get('duration_ms'):
                    try:
                        ctx['duration_ms'] = int(data.get('duration'))
                    except Exception:
                        pass
        except Exception as exc:
            xbmc.log('[NuvioHub] companion bootstrap error: %s' % exc, xbmc.LOGWARNING)
        ctx['_bootstrapped'] = True

    def _payload(self, ctx, position_ms, state, mark_watched=None):
        payload = {
            'state': state,
            'time': int(position_ms or 0),
            'duration': int(ctx.get('duration_ms') or 0),
            'playbackTime': int(position_ms or 0),
            'sessionIdentifier': ctx.get('sessionIdentifier') or '',
            'playbackSessionId': ctx.get('playbackSessionId') or ctx.get('sessionIdentifier') or '',
            'deviceName': ctx.get('deviceName') or 'Kodi',
            'device': 'Kodi',
            'platform': 'Kodi',
            'product': ctx.get('product') or 'Nuvio Hub',
        }
        if mark_watched is not None:
            payload['markWatched'] = bool(mark_watched)
        return payload

    def _post(self, ctx, key, position_ms, state, mark_watched=None):
        self._bootstrap(ctx)
        url = ctx.get(key)
        if not url:
            return None
        return _json_post(url, self._payload(ctx, position_ms, state, mark_watched), headers=self._headers(ctx))

    def started(self, ctx, position_ms=0):
        return self._post(ctx, 'companionUrl', position_ms, 'playing')

    def progress(self, ctx, position_ms):
        return self._post(ctx, 'companionUrl', position_ms, 'playing')

    def paused(self, ctx, position_ms):
        return self._post(ctx, 'companionUrl', position_ms, 'paused')

    def stopped(self, ctx, position_ms):
        return self._post(ctx, 'companionUrl', position_ms, 'stopped')

    def ended(self, ctx, position_ms=0):
        if ctx.get('companionScrobbleUrl'):
            return self._post(ctx, 'companionScrobbleUrl', position_ms or int(ctx.get('duration_ms') or 0), 'stopped', mark_watched=True)
        return self._post(ctx, 'companionUrl', position_ms or int(ctx.get('duration_ms') or 0), 'stopped', mark_watched=True)


class PlexReporter(BaseReporter):
    def _headers(self, ctx):
        return {
            'X-Plex-Product': ctx.get('product', 'Nuvio Hub'),
            'X-Plex-Version': ctx.get('product_version', '2.6.0'),
            'X-Plex-Client-Identifier': ctx['client_id'],
            'X-Plex-Provides': 'player',
            'X-Plex-Device-Name': ctx.get('device_name', 'Kodi'),
            'X-Plex-Platform': 'Kodi',
            'X-Plex-Model': 'Kodi',
            'X-Plex-Device': ctx.get('device_name', 'Kodi'),
        }

    def _get(self, ctx, path, params):
        params = dict(params)
        params['X-Plex-Token'] = ctx['token']
        url = ctx['server_url'].rstrip('/') + path + '?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers(ctx), method='GET')
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            return resp.read()

    def _timeline(self, ctx, position_ms, state):
        rating_key = ctx['rating_key']
        duration_ms = int(ctx.get('duration_ms', 0))
        params = {
            'duration': duration_ms,
            'guid': 'com.plexapp.plugins.library',
            'key': f'/library/metadata/{rating_key}',
            'containerKey': f'/library/metadata/{rating_key}',
            'ratingKey': str(rating_key),
            'state': state,
            'time': int(position_ms),
        }
        return self._get(ctx, '/:/timeline', params)

    def _scrobble(self, ctx):
        return self._get(ctx, '/:/scrobble', {'key': str(ctx['rating_key']), 'identifier': 'com.plexapp.plugins.library'})

    def started(self, ctx, position_ms=0):
        return self._timeline(ctx, position_ms, 'playing')
    def progress(self, ctx, position_ms):
        return self._timeline(ctx, position_ms, 'playing')
    def paused(self, ctx, position_ms):
        return self._timeline(ctx, position_ms, 'paused')
    def stopped(self, ctx, position_ms):
        return self._timeline(ctx, position_ms, 'stopped')
    def ended(self, ctx, position_ms=0):
        self._timeline(ctx, position_ms or int(ctx.get('duration_ms', 0)), 'stopped')
        return self._scrobble(ctx)


class EmbyReporter(BaseReporter):
    """Jellyfin / Emby playback reports. 6.0.39: Jellyfin 12 accepts only the
    standard Authorization header (emby_client builds it per server flavor)."""
    def _flavor(self, ctx):
        from . import emby_client
        return ctx.get('server_flavor') or emby_client.flavor_of(emby_client.account())

    def _headers(self, ctx):
        from . import emby_client
        return emby_client._headers(ctx['token'], self._flavor(ctx))

    def _post(self, ctx, path, payload):
        from . import emby_client
        prefix = '/emby' if self._flavor(ctx) == emby_client.EMBY else ''
        url = ctx['server_url'].rstrip('/') + prefix + path
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=self._headers(ctx), method='POST')
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            return resp.read()

    def _payload(self, ctx, position_ms, paused=False):
        payload = {
            'ItemId': ctx['item_id'],
            'PositionTicks': int(position_ms) * 10000,
            'IsPaused': paused,
            'PlayMethod': 'DirectStream',
            'CanSeek': True,
            'SessionId': ctx.get('session_id') or ctx.get('device_id') or 'nuviohub',
        }
        # v3.9.241: Emby rejected /Sessions/Playing with HTTP 400 (53x in one
        # session log) — it ties reports to the PlaybackInfo session and wants
        # PlaySessionId (+ MediaSourceId) when the stream came from PlaybackInfo.
        if ctx.get('play_session_id'):
            payload['PlaySessionId'] = ctx['play_session_id']
        if ctx.get('media_source_id'):
            payload['MediaSourceId'] = ctx['media_source_id']
        return payload

    def started(self, ctx, position_ms=0):
        return self._post(ctx, '/Sessions/Playing', self._payload(ctx, position_ms, paused=False))
    def progress(self, ctx, position_ms):
        payload = self._payload(ctx, position_ms, paused=False); payload['EventName']='TimeUpdate'; return self._post(ctx, '/Sessions/Playing/Progress', payload)
    def paused(self, ctx, position_ms):
        payload = self._payload(ctx, position_ms, paused=True); payload['EventName']='Pause'; return self._post(ctx, '/Sessions/Playing/Progress', payload)
    def stopped(self, ctx, position_ms):
        payload = self._payload(ctx, position_ms, paused=False); payload['EventName']='Stop'; return self._post(ctx, '/Sessions/Playing/Stopped', payload)
    def ended(self, ctx, position_ms=0):
        payload = self._payload(ctx, position_ms or int(ctx.get('duration_ms', 0)), paused=False); payload['EventName']='Stop'; return self._post(ctx, '/Sessions/Playing/Stopped', payload)




class TraktReporter(BaseReporter):
    def started(self, ctx, position_ms=0):
        return trakt.scrobble('start', ctx, position_ms)

    def progress(self, ctx, position_ms):
        # Keep Trakt's playback position current during long sessions.  This
        # uses the same scrobble/start endpoint as playback start and is called
        # by Nuvio Hub's throttled heartbeat (once per minute), not every player
        # tick, so it stays lightweight.
        return trakt.scrobble('start', ctx, position_ms)

    def paused(self, ctx, position_ms):
        return trakt.scrobble('pause', ctx, position_ms)

    def stopped(self, ctx, position_ms):
        return trakt.scrobble('pause', ctx, position_ms)

    def ended(self, ctx, position_ms=0):
        return trakt.scrobble('stop', ctx, position_ms)


class SimklReporter(BaseReporter):
    # The local journal already queued the newest durable position. A delayed
    # reporter must only flush it, never replace it with an older callback.
    def started(self, ctx, position_ms=0):
        return simkl.flush_progress()
    def progress(self, ctx, position_ms):
        return simkl.flush_progress()
    def paused(self, ctx, position_ms):
        return simkl.flush_progress()
    def stopped(self, ctx, position_ms):
        return simkl.flush_progress()
    def ended(self, ctx, position_ms=0):
        return simkl.flush_progress()


class MultiReporter(BaseReporter):
    def __init__(self, reporters):
        self.reporters = [r for r in (reporters or []) if r]

    def _call(self, method_name, ctx, position_ms=0):
        results = []
        for reporter in self.reporters:
            try:
                results.append(getattr(reporter, method_name)(ctx, position_ms))
            except TypeError:
                results.append(getattr(reporter, method_name)(ctx))
            except Exception as exc:
                # v3.9.241: one line per playback, not 53 — the log showed the
                # same Emby 400 repeated every heartbeat for a whole session.
                if not getattr(self, '_report_err_logged', False):
                    self._report_err_logged = True
                    xbmc.log('[NuvioHub] reporter %s error (repeats suppressed): %s' % (method_name, exc), xbmc.LOGWARNING)
        return results

    def started(self, ctx, position_ms=0):
        return self._call('started', ctx, position_ms)

    def progress(self, ctx, position_ms):
        return self._call('progress', ctx, position_ms)

    def paused(self, ctx, position_ms):
        return self._call('paused', ctx, position_ms)

    def stopped(self, ctx, position_ms):
        return self._call('stopped', ctx, position_ms)

    def ended(self, ctx, position_ms=0):
        return self._call('ended', ctx, position_ms)


def get_reporter(ctx):
    if not ctx:
        return None
    reporters = []
    server_reporter = None
    if ctx.get('companionUrl') or ctx.get('companionScrobbleUrl'):
        server_reporter = UrlCompanionReporter()
    elif ctx.get('server_type') == 'plex' and ctx.get('server_url') and ctx.get('token') and ctx.get('rating_key'):
        server_reporter = PlexReporter()
    elif ctx.get('server_type') == 'emby' and ctx.get('server_url') and ctx.get('token') and ctx.get('item_id'):
        server_reporter = EmbyReporter()
    if server_reporter:
        reporters.append(server_reporter)
    ids_present = any(ctx.get(k) for k in ('imdb_id', 'tmdb_id', 'tvdb_id'))
    if trakt.enabled() and trakt.scrobble_enabled():
        if ids_present:
            reporters.append(TraktReporter())
    # Partial progress is independent of the optional watched-history setting.
    if simkl.enabled() and simkl.authorized():
        if ids_present:
            reporters.append(SimklReporter())
    if not reporters:
        return None
    if len(reporters) == 1:
        return reporters[0]
    return MultiReporter(reporters)


def should_mark_watched(position_ms, duration_ms, threshold=0.90):  # 6.0.35: as the Nuvio apps
    try:
        return duration_ms > 0 and (float(position_ms) / float(duration_ms)) >= threshold
    except Exception:
        return False


def _safe_int(value, default=0):
    try:
        return int(value or 0)
    except Exception:
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value or 0.0)
    except Exception:
        return default


def _local_percent(position_ms, duration_ms):
    try:
        if duration_ms and duration_ms > 0:
            return max(0.0, min(100.0, (float(position_ms) / float(duration_ms)) * 100.0))
    except Exception:
        pass
    return 0.0


def _save_local_progress(ctx, position_ms=0, duration_ms=0, finished=False):
    if not isinstance(ctx, dict) or not ctx:
        return
    media_type = (ctx.get('media_type') or '').lower()
    canonical_id = ctx.get('canonical_id') or ''
    if not canonical_id:
        return
    is_episode = media_type in ('series', 'anime', 'show', 'tv') or (ctx.get('season') not in (None, '', 0, '0') and ctx.get('episode') not in (None, '', 0, '0'))
    if not media_type:
        media_type = 'series' if is_episode else 'movie'
    video_id = ctx.get('video_id') or canonical_id
    season = _safe_int(ctx.get('season'), 0) if is_episode else None
    episode = _safe_int(ctx.get('episode'), 0) if is_episode else None
    title = ctx.get('show_title') or ctx.get('title') or canonical_id
    provider_name = ctx.get('provider_name') or 'Nuvio Hub'
    poster = ctx.get('poster') or ''
    background = ctx.get('background') or ''
    clearlogo = ctx.get('clearlogo') or ''
    duration_sec = _safe_float(duration_ms, 0.0) / 1000.0
    position_sec = _safe_float(position_ms, 0.0) / 1000.0
    finished = finished or bool(ctx.get('nuvio_completed_by_user')) or should_mark_watched(position_ms, duration_ms)
    percent = 100.0 if finished else _local_percent(position_ms, duration_ms)
    event_type = 'watched' if finished else 'progress'
    # Persist standard ids alongside Nuvio Hub's provider-specific ids.  The
    # latter are often opaque (for example a Stremio addon id), whereas TMDb
    # Helper launches with IMDb/TMDb/TVDb ids.  Keeping both makes a future
    # handoff resume the same row instead of starting from 0:00.
    external_ids = ctx.get('external_ids') or {}
    if not isinstance(external_ids, dict):
        external_ids = {}
    tmdb_id = str(ctx.get('tmdb_id') or external_ids.get('tmdb_id') or external_ids.get('tmdb') or '').strip()
    imdb_id = str(ctx.get('imdb_id') or external_ids.get('imdb_id') or external_ids.get('imdb') or '').strip()
    tvdb_id = str(ctx.get('tvdb_id') or external_ids.get('tvdb_id') or external_ids.get('tvdb') or '').strip()
    show_tmdb_id = str(ctx.get('show_tmdb_id') or (tmdb_id if is_episode else '')).strip()
    try:
        from . import continue_local
        continue_local.save(ctx, position_sec, duration_sec, finished)
    except Exception as exc:
        xbmc.log('[NuvioHub] local continue journal failed: %s' % exc, xbmc.LOGWARNING)
    try:
        playback_store.upsert_entry(
            media_type,
            canonical_id,
            video_id,
            title,
            provider_name,
            poster,
            background,
            clearlogo,
            season,
            episode,
            position_sec,
            duration_sec,
            percent,
            ctx.get('stream_url') or '',
            event_type,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            tvdb_id=tvdb_id,
            show_tmdb_id=show_tmdb_id,
            native_server_id=str(ctx.get('server_id') or '').strip(),
            native_item_id=str(ctx.get('rating_key') or ctx.get('item_id') or '').strip(),
        )
    except Exception as exc:
        xbmc.log('[NuvioHub] local progress save failed: %s' % exc, xbmc.LOGWARNING)
    else:
        _invalidate_nextup_cache()
        # Wake up the home / CW UI so the row reflects this save without
        # the user having to navigate away and back. Skipped when we're
        # mid-stream and only saving an interim progress tick — those
        # don't change the visible row order or membership.
        if finished or position_ms >= 1000:
            _refresh_cw_containers()


def _invalidate_nextup_cache():
    try:
        win = xbmcgui.Window(10000)
        for key in ('nuviohub.nextup_cache', 'nuviohub.nextup_cache_ts'):
            try:
                win.clearProperty(key)
            except Exception:
                pass
    except Exception:
        pass


# Paths whose visible content is driven by playback_store / favorites and
# therefore needs a Container.Refresh after each progress save. Matched as
# substrings against Container.FolderPath.
_CW_REFRESH_PATHS = (
    'plugin.video.nuviohub/?',     # root home page (CW row + nextup row)
    'plugin.video.nuviohub/',      # any NuvioHub container
    'action=continue',           # full Continue Watching list
    'action=favorites',          # favorites screen
    'action=nextup',             # next-up list
    'action=home',               # explicit home action
)


def _refresh_cw_containers():
    """Trigger Container.Refresh on the current container if it's CW-related,
    AND set a stale-flag on Window(10000) so that the next time the user
    opens a CW-displaying screen it rebuilds from fresh data even if Kodi
    served its directory cache.

    Why both:
      - Container.Refresh handles the "user is staring at CW right now"
        case (e.g. episode ended → Kodi auto-returned to the previous
        container which was the CW list).
      - The stale-flag handles "user finished playback then navigated
        elsewhere then came back to CW", where Container.Refresh isn't
        applicable because no NuvioHub container was visible.
    """
    # Always set the stale flag so the next CW-screen open rebuilds.
    try:
        win = xbmcgui.Window(10000)
        win.setProperty('nuviohub.cw_dirty', '1')
        win.setProperty('nuviohub.cw_dirty_ts', str(time.time_ns()))
        win.setProperty('nuvio.progress.revision', str(time.time_ns()))
    except Exception:
        pass

    # If a CW-affected NuvioHub container is the current container, refresh it.
    try:
        current = xbmc.getInfoLabel('Container.FolderPath') or ''
    except Exception:
        return
    if not current or 'plugin.video.nuviohub' not in current:
        return
    if not any(token in current for token in _CW_REFRESH_PATHS):
        return
    try:
        xbmc.executebuiltin('Container.Refresh')
    except Exception:
        pass


def _clear_tmdbh_handoff_flag():
    try:
        for win_id in (12005, 10000):
            try:
                win = xbmcgui.Window(win_id)
            except Exception:
                continue
            for key in ('nuviohub.invoked_by_tmdbh', 'nuviohub.tmdbh_seed_ids', 'nuviohub.tmdbh_seed_for', 'nuviohub.tmdbh_handoff_until'):
                try:
                    win.clearProperty(key)
                except Exception:
                    pass
    except Exception:
        pass


def _reopen_source_picker_url(sess, position_seconds=0.0):
    picker = (sess or {}).get('source_picker_url') or ''
    if not picker:
        return False
    try:
        parts = urllib.parse.urlsplit(picker)
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        if float(position_seconds or 0.0) > 1.0:
            query['resume_seconds'] = '%.1f' % float(position_seconds or 0.0)
        query['fresh_search'] = '1'
        picker = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))
    except Exception:
        pass
    try:
        _monitor('stop-reopen-sources', title=(sess or {}).get('title') or '', position_seconds='%.1f' % float(position_seconds or 0.0))
    except Exception:
        pass
    try:
        xbmc.executebuiltin('Container.Update(%s,replace)' % picker)
        return True
    except Exception as exc:
        xbmc.log('[NuvioHub] reopen source picker failed: %s' % exc, xbmc.LOGWARNING)
        return False


def _publish_playback_artwork(ctx):
    if not isinstance(ctx, dict) or not ctx:
        return
    try:
        logo = ctx.get('clearlogo') or ''
        poster = ctx.get('poster') or ''
        fanart = ctx.get('background') or poster or ''
        title = ctx.get('title') or ''
        plot = ctx.get('plot') or ''
        year = str(ctx.get('year') or '')
        for win_id in (10000,):
            try:
                win = xbmcgui.Window(win_id)
            except Exception:
                continue
            for key, value in (
                ('nuviohub.source.clearlogo', logo),
                ('nuviohub.source.poster', poster),
                ('nuviohub.source.thumb', poster),
                ('nuviohub.source.fanart', fanart),
                ('nuviohub.source.title', title),
                ('nuviohub.source.plot', plot),
                ('nuviohub.source.year', year),
                ('clearlogo', logo),
                ('logo', logo),
                ('tvshow.clearlogo', logo),
                ('poster', poster),
                ('thumb', poster),
                ('fanart', fanart),
                ('fanart_image', fanart),
            ):
                try:
                    win.setProperty(key, value)
                except Exception:
                    pass
    except Exception:
        pass


def _is_internal_navigation_path(path):
    value = str(path or '').strip()
    if not value.startswith('plugin://plugin.video.nuviohub/'):
        return False
    markers = (
        'action=streams', 'action=episode_streams', 'action=item_open',
        'action=series_meta', 'action=play_item', 'action=cw_resume',
        'action=cw_play_from_start', 'action=play'
    )
    return any(marker in value for marker in markers)


class CompanionPlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
        self.ctx = {}
        self.reporter = None
        self._report_queue = queue.Queue(maxsize=64)
        self._report_lock = threading.Lock()
        self._report_thread = None
        # Playback health tracking for fallback.
        self._play_start_time = 0.0
        self._had_error = False
        self._progress_seen_ms = 0
        self._fallback_chain = []
        self._next_episode = None
        self._started_reported = False
        self._started_probe_pending = False
        self._resume_applied = False
        self._resume_in_progress = False
        self._resume_generation = 0
        self._subtitle_restore_generation = 0
        self._subtitle_restored = False
        self._progress_heartbeat_token = 0
        self._progress_heartbeat_stop = threading.Event()
        self._active_playback_uid = ''
        self._last_started_file = ''
        self._last_started_at = 0.0
        self._last_position_ms = 0
        self._last_duration_ms = 0
        # Flag we set when we're the ones triggering the next play (avoid loops).
        self._own_trigger = False
        # v5.4.11: True while the CURRENT playback does not belong to NuvioHub
        # (TMDb Helper dummy, other addons, local files). While set, every
        # Player callback is a hard no-op: no Window-property writes, no
        # probe/heartbeat threads, no Player polling, no session or monitor
        # traffic. Kodi 22 on AML resets the display pipeline around every
        # playback start/stop, and running the companion machinery inside
        # that window (for a clip that was never ours) is what wedged the
        # box on stop → instant replay.
        self._foreign_active = False
        # v5.4.11: last playback_uid whose artwork was published to the home
        # window. Pause/resume used to republish the exact same 15 values.
        self._artwork_published_uid = ''
        # Delayed fallback timer for false-positive start/stop handoffs.
        self._fallback_pending = False
        self._started_reported = False
        self._started_probe_pending = False

    def _refresh_context(self):
        self.ctx = load_session() or {}
        base = self.ctx.get('provider_base_url') or self.ctx.get('server_url') or ''
        for key in ('bootstrapUrl', 'companionUrl', 'companionScrobbleUrl', 'companionUnscrobbleUrl'):
            if self.ctx.get(key):
                self.ctx[key] = _absolute_url(base, self.ctx.get(key))
        self.reporter = get_reporter(self.ctx)
        # v5.3: source choice is always user-owned.  Ignore and remove any
        # fallback chain left by an older session so a playback error cannot
        # silently start a different URL.
        self._fallback_chain = []
        self.ctx.pop('fallback_stream_keys', None)
        self._next_episode = self.ctx.get('next_episode') or None
        self._had_error = False
        self._progress_seen_ms = 0
        self._own_trigger = False
        self._last_position_ms = 0
        self._last_duration_ms = 0
        self._fallback_pending = False
        self._started_reported = False
        self._started_probe_pending = False
        self._resume_applied = False
        self._resume_in_progress = False
        self._resume_generation += 1
        self._subtitle_restore_generation += 1
        self._subtitle_restored = False
        self._progress_heartbeat_token += 1
        try:
            self._progress_heartbeat_stop.set()
        except Exception:
            pass
        self._active_playback_uid = str(self.ctx.get('playback_uid') or '')
        self._last_started_file = self._current_playing_file()
        import time as _t
        self._last_started_at = _t.time()
        self._play_start_time = self._last_started_at

    def _enter_foreign_playback(self, reason, playing_file=''):
        """Mark the current playback as not-ours and go fully idle.

        v5.4.11 root-cause fix for the hard AML freeze on stop → replay:
        the companion previously ran its FULL machinery for every playback
        in Kodi, including TMDb Helper's 100ms dummy.mp4 — ~17 Window(10000)
        property operations (each a GuiLock → LockFrameMoveGuard handshake
        with the app thread), Player polling at 4Hz from probe threads, and
        session/monitor traffic — synchronously on the announce pump, at
        the exact moment CVideoPlayer::CloseFile tears down the Amlogic
        codec and the windowing system re-inits GLES for the mode switch
        (kodi.log: 'GLES: Maximum texture width' between the dummy stop and
        the next tmdb_player resolution). Foreign playback now executes
        zero NuvioHub work inside that window."""
        self._foreign_active = True
        self._stop_progress_heartbeat()
        try:
            xbmc.log('[NuvioHub] companion idle: foreign playback (%s)%s'
                     % (reason, (' file=%s' % playing_file) if playing_file else ''),
                     xbmc.LOGDEBUG)
        except Exception:
            pass

    def _publish_artwork_async(self, ctx):
        """Publish playback artwork OFF the announce/callback path, once per
        playback_uid.

        _publish_playback_artwork performs ~15 Window(10000) property writes
        and each goes through Kodi's GuiLock, i.e. LockFrameMoveGuard — a
        synchronisation handshake with the app thread between frames. Doing
        that inline inside Player callbacks stalls the announce pump exactly
        while AML resets the display pipeline around playback start/stop.
        A short worker publishes instead, and identical republishes from
        pause/resume are coalesced away."""
        if not isinstance(ctx, dict) or not ctx:
            return
        uid = str(ctx.get('playback_uid') or '')
        if not uid:
            uid = 'file:%s' % (ctx.get('url') or ctx.get('title') or '')
        if uid == self._artwork_published_uid:
            return
        self._artwork_published_uid = uid
        snapshot = dict(ctx)

        def _job():
            _publish_playback_artwork(snapshot)

        try:
            threading.Thread(target=_job, name='NuvioHubArtPublish',
                             daemon=True).start()
        except RuntimeError:
            # Thread quota exhausted — publish inline rather than lose art.
            _publish_playback_artwork(snapshot)

    def _position_ms(self):
        try:
            if self._player_looks_active_for_clock():
                value = int(self.getTime() * 1000)
                if value >= 0:
                    self._last_position_ms = value
                    return value
        except Exception:
            pass
        return int(self._last_position_ms or 0)

    def _duration_ms(self):
        try:
            if self._player_looks_active_for_clock():
                total = int(self.getTotalTime() * 1000)
                if total > 0:
                    self._last_duration_ms = total
                    return total
        except Exception:
            pass
        return int(self._last_duration_ms or self.ctx.get('duration_ms', 0) or 0)

    def _player_looks_active_for_clock(self):
        try:
            return bool(self.isPlaying() or self.isPlayingVideo())
        except Exception:
            return False

    def _current_playing_file(self):
        try:
            return self.getPlayingFile() or ''
        except Exception:
            return ''

    def _player_looks_active(self, require_real_media=False):
        playing_file = self._current_playing_file()
        # Kodi may retain the plugin path after AV starts (adaptive streams).
        # A live video clock is authoritative, not the unresolved list path.
        try:
            if self.isPlayingVideo():
                return True
        except Exception:
            pass
        if playing_file and not _is_internal_navigation_path(playing_file):
            return True
        try:
            if xbmc.getCondVisibility('Player.HasVideo'):
                if not require_real_media:
                    return True
                return self._position_ms() > 0
        except Exception:
            pass
        return False

    def _restore_switched_subtitle_async(self):
        """Restore the exact external subtitle after a source replacement.

        Kodi treats a replacement URL as a new video. Subtitle-service dialogs
        can therefore rebuild the subtitle list *after* AV start. Restoring too
        early makes the saved track disappear when the user closes that dialog.
        Wait for the player, resume seek, and modal dialogs to settle, then
        verify the selected external path and retry a small bounded number of
        times.
        """
        if self._subtitle_restored:
            return
        path = str(self.ctx.get('switch_subtitle_path') or '').strip()
        if not path:
            self._subtitle_restored = True
            return
        enabled = bool(self.ctx.get('switch_subtitle_enabled', True))
        uid = str(self._active_playback_uid or self.ctx.get('playback_uid') or '')
        self._subtitle_restore_generation += 1
        generation = self._subtitle_restore_generation

        def _same_path(left, right):
            try:
                l = str(xbmcvfs.translatePath(left) or left).replace('\\', '/').lower()
                r = str(xbmcvfs.translatePath(right) or right).replace('\\', '/').lower()
                return bool(l and r and l == r)
            except Exception:
                return str(left or '') == str(right or '')

        def _dialog_active():
            # getCurrentWindowDialogId is available on Kodi 19+ and catches
            # subtitle-service pickers even when their skin XML name differs.
            try:
                return int(xbmcgui.getCurrentWindowDialogId() or 0) > 0
            except Exception:
                pass
            for cond in ('Window.IsActive(subtitlesearch)',
                         'Window.IsActive(subtitles)',
                         'Dialog.IsActive(subtitlesearch)'):
                try:
                    if xbmc.getCondVisibility(cond):
                        return True
                except Exception:
                    pass
            return False

        def _runner():
            try:
                # Wait up to 90s: the user may keep a subtitle picker open.
                # Require a quiet dialog-free window for ~1.25s before attach.
                quiet_ticks = 0
                for _ in range(360):
                    if generation != self._subtitle_restore_generation:
                        return
                    if uid and uid != str(self._active_playback_uid or ''):
                        return
                    ready = self._player_looks_active(require_real_media=True) and not self._resume_in_progress
                    if ready and not _dialog_active():
                        quiet_ticks += 1
                        if quiet_ticks >= 5:
                            break
                    else:
                        quiet_ticks = 0
                    xbmc.sleep(250)
                else:
                    return

                if not path.startswith(('http://', 'https://')):
                    try:
                        if not xbmcvfs.exists(path):
                            _monitor('subtitle-restore-missing', level=xbmc.LOGWARNING, path=path, playback_uid=uid)
                            return
                    except Exception:
                        pass

                # A subtitle service can mutate the list just after its dialog
                # closes. Re-attach at most three times, never an unbounded loop.
                restored = False
                for attempt in range(3):
                    if generation != self._subtitle_restore_generation:
                        return
                    if uid and uid != str(self._active_playback_uid or ''):
                        return
                    if _dialog_active():
                        xbmc.sleep(500)
                        continue
                    try:
                        self.setSubtitles(path)
                        xbmc.sleep(450)
                        self.showSubtitles(bool(enabled))
                    except Exception as exc:
                        _monitor('subtitle-restore-failed', level=xbmc.LOGWARNING, error=exc, path=path, playback_uid=uid, attempt=attempt + 1)
                        xbmc.sleep(600)
                        continue
                    try:
                        current = str(self.getSubtitles() or '').strip()
                    except Exception:
                        current = ''
                    if not current or _same_path(current, path):
                        restored = True
                        break
                    xbmc.sleep(700)

                if not restored:
                    _monitor('subtitle-restore-unverified', level=xbmc.LOGWARNING, path=path, playback_uid=uid)
                    return
                self._subtitle_restored = True
                self.ctx['switch_subtitle_restored'] = True
                self.ctx['source_switch_reuse_subtitle'] = False
                try:
                    save_session(self.ctx)
                except Exception:
                    pass
                _monitor('subtitle-restored-after-switch', path=path, enabled=enabled, playback_uid=uid)
            except Exception as exc:
                _monitor('subtitle-restore-error', level=xbmc.LOGWARNING, error=exc, playback_uid=uid)

        try:
            threading.Thread(target=_runner, name='NuvioHubSubtitleRestore', daemon=True).start()
        except Exception as exc:
            xbmc.log('[NuvioHub] subtitle restore thread failed: %s' % exc, xbmc.LOGWARNING)

    def _confirm_started_async(self):
        """Ensure the shared playback lifecycle worker is running.

        v5.2 spawned a short start-probe thread *and* a separate long-lived
        progress heartbeat for every playback.  The heartbeat now owns the
        bounded start probe too, so duplicate Kodi Started callbacks do not
        consume another native thread.
        """
        if self._started_probe_pending or self._started_reported:
            return
        self._start_progress_heartbeat()

    def _schedule_fallback(self, reason='', delay_ms=3200):
        """Automatic source fallback is intentionally disabled in v5.3."""
        self._fallback_pending = False
        return False

    def _report(self, method_name, position_ms=None):
        if not companion_enabled():
            return
        if not self.reporter:
            return
        # Network trackers must never delay the local playback clock or Stop.
        # Capture this session object; a later video replaces self.ctx entirely.
        event=(self.reporter,self.ctx,method_name,
               self._position_ms() if position_ms is None else position_ms)
        try:self._report_queue.put_nowait(event)
        except queue.Full:
            xbmc.log('[NuvioHub] Tracker queue is full; local progress remains saved.',xbmc.LOGWARNING)
            return
        with self._report_lock:
            if self._report_thread is None or not self._report_thread.is_alive():
                self._report_thread=threading.Thread(target=self._drain_reports,
                    name='NuvioTrackerReports',daemon=True)
                self._report_thread.start()

    def _drain_reports(self):
        while True:
            try:event=self._report_queue.get(timeout=1)
            except queue.Empty:
                with self._report_lock:
                    if self._report_queue.empty():
                        self._report_thread=None
                        return
                continue
            try:self._send_report(*event)
            finally:self._report_queue.task_done()

    @staticmethod
    def _send_report(reporter,ctx,method_name,position_ms):
        try:
            getattr(reporter, method_name)(ctx, position_ms)
        except TypeError:
            try:getattr(reporter, method_name)(ctx)
            except Exception:pass
        except urllib.error.HTTPError as exc:
            xbmc.log('[NuvioHub] companion %s HTTP %s' % (method_name, exc.code), xbmc.LOGWARNING)
        except Exception as exc:
            xbmc.log('[NuvioHub] companion %s error: %s' % (method_name, exc), xbmc.LOGWARNING)

    def _apply_resume_async(self):
        """Apply one coordinated resume seek for the current playback session.

        Older builds had two independent seek loops (plugin post-start chores
        and CompanionPlayer), each retrying several times.  That produced
        repeated Seeking overlays, stalls, and occasional jumps back to zero.
        CompanionPlayer is now the sole resume coordinator.  A generation
        token invalidates stale callbacks as soon as another item/source starts.
        """
        if self._resume_applied or self._resume_in_progress:
            return
        try:
            target = float(self.ctx.get('resume_seconds') or 0.0)
        except Exception:
            target = 0.0
        try:
            resume_pct = float(self.ctx.get('resume_percent') or 0.0)
        except Exception:
            resume_pct = 0.0
        # A 30s floor is right for an ORDINARY resume (ignore trivial offsets),
        # but WRONG for an explicit source switch: switch_source captures any
        # position > 1.0s, so switching early in a title (e.g. at 00:20) was
        # silently dropped here and the new source restarted from 00:00.
        # When a switch is pending, honour whatever was captured.
        switching = bool(self.ctx.get('source_switch_pending'))
        exact=bool(self.ctx.get('nuvio_resume_exact'))
        min_resume = 0.001 if exact else (1.0 if switching else 30.0)

        if target < min_resume and not (1.0 < resume_pct < 95.0):
            self._resume_applied = True
            return

        self._resume_in_progress = True
        self._resume_generation += 1
        generation = self._resume_generation

        def _runner():
            success = False
            try:
                stable_total = 0.0
                stable_count = 0
                # Wait for real media and a stable duration.  Do not seek while
                # Kodi is still opening/replacing the stream during source switch.
                for _ in range(50):
                    if generation != self._resume_generation:
                        return
                    xbmc.sleep(200)
                    if not self._player_looks_active(require_real_media=True):
                        continue
                    try:
                        total = float(self.getTotalTime() or 0.0)
                    except Exception:
                        total = 0.0
                    if total > (0.0 if exact else 60.0):
                        if abs(total - stable_total) < 1.0:
                            stable_count += 1
                        else:
                            stable_total = total
                            stable_count = 1
                        if stable_count >= 2:
                            break

                if generation != self._resume_generation or not self._player_looks_active(require_real_media=True):
                    return
                total = stable_total
                seek_to = target
                # Only derive from percent when there is no usable absolute
                # position; during a switch the captured seconds are authoritative.
                if seek_to < min_resume and 1.0 < resume_pct < 95.0 and total > 60.0:
                    seek_to = total * resume_pct / 100.0
                if total > 0.0:
                    seek_to = min(seek_to, max(0.0, total - (0.5 if exact else 90.0)))
                if seek_to < min_resume:
                    success = True
                    return

                try:
                    current = float(self.getTime() or 0.0)
                except Exception:
                    current = 0.0
                # Kodi/native player may already have resumed. Never seek again
                # when already close to or beyond the desired point.
                # The floor must not exceed the target: with a small switch
                # target (e.g. 20s) a hardcoded 15s floor could read the freshly
                # opened stream as "already resumed" and skip the seek entirely.
                already_at = max(0.0,seek_to-0.5) if exact else max(min(15.0, seek_to * 0.5), seek_to - 8.0)
                if current >= already_at:
                    success = True
                    _monitor('resume-already-applied', title=self.ctx.get('title') or '', target_seconds='%.1f' % seek_to, current_seconds='%.1f' % current)
                    return

                # One normal attempt plus one recovery attempt only.  Repeated
                # loops are intentionally avoided because each call shows Kodi's
                # Seeking overlay and can reset adaptive streams.
                for attempt in range(2):
                    if generation != self._resume_generation:
                        return
                    try:
                        self.seekTime(seek_to)
                    except Exception:
                        continue
                    xbmc.sleep(1200 if attempt == 0 else 1700)
                    if generation != self._resume_generation:
                        return
                    try:
                        current = float(self.getTime() or 0.0)
                    except Exception:
                        current = 0.0
                    if current >= already_at:
                        success = True
                        _monitor('resume-applied', title=self.ctx.get('title') or '', target_seconds='%.1f' % seek_to, current_seconds='%.1f' % current, attempt=attempt + 1)
                        return
                _monitor('resume-failed', level=xbmc.LOGWARNING, title=self.ctx.get('title') or '', target_seconds='%.1f' % seek_to, resume_percent='%.2f' % resume_pct)
            except Exception as exc:
                _monitor('resume-error', level=xbmc.LOGWARNING, error=exc, title=self.ctx.get('title') or '')
            finally:
                if generation == self._resume_generation:
                    self._resume_in_progress = False
                    self._resume_applied = True

        try:
            threading.Thread(target=_runner, name='NuvioHubResumeCoordinator', daemon=True).start()
        except Exception:
            self._resume_in_progress = False
            self._resume_applied = True

    def _start_progress_heartbeat(self):
        """Persist and sync progress while playback is active.

        Kodi does not emit a general progress callback. Previously a crash,
        power loss, or force-close could lose everything since the last pause.
        A single daemon heartbeat samples every second, saves locally after
        three seconds and every 15 seconds thereafter, and reports to
        connected companions/Trakt every 60 seconds. A generation token makes
        old playback threads exit immediately when a new item starts.
        """
        try:
            self._progress_heartbeat_stop.set()
        except Exception:
            pass
        self._progress_heartbeat_token += 1
        token = self._progress_heartbeat_token
        stop_event = threading.Event()
        self._progress_heartbeat_stop = stop_event
        self._started_probe_pending = True
        probe_uid = str(self._active_playback_uid or
                        self.ctx.get('playback_uid') or '')

        def _runner():
            try:
                started = False
                for _ in range(240):
                    if stop_event.is_set() or token != self._progress_heartbeat_token:
                        return
                    if probe_uid and probe_uid != str(self._active_playback_uid or ''):
                        return
                    if self._player_looks_active(require_real_media=True):
                        started = True
                        if not self._started_reported:
                            self._started_reported = True
                            _monitor(
                                'playback-started',
                                title=self.ctx.get('title') or '',
                                canonical_id=self.ctx.get('canonical_id') or '',
                                provider=(self.ctx.get('provider_name') or
                                          self.ctx.get('provider_id') or ''),
                                playing_file=self._current_playing_file(),
                            )
                            self._report('started')
                        break
                    if stop_event.wait(0.25):
                        return
                if not started:
                    _monitor(
                        'playback-start-timeout', level=xbmc.LOGWARNING,
                        title=self.ctx.get('title') or '',
                        canonical_id=self.ctx.get('canonical_id') or '',
                        provider=(self.ctx.get('provider_name') or
                                  self.ctx.get('provider_id') or ''),
                        playing_file=self._current_playing_file(),
                    )
                    return

                last_save = 0.0
                last_report = time.monotonic()
                while (token == self._progress_heartbeat_token and
                       not stop_event.wait(1.0)):
                    if not self._player_looks_active(require_real_media=True):
                        # Temporary buffering/decoder reconfiguration is not Stop.
                        continue
                    if self._resume_in_progress:
                        continue
                    pos = self._position_ms()
                    dur = self._duration_ms()
                    self._progress_seen_ms = max(
                        self._progress_seen_ms, int(pos or 0))
                    if dur > 0:
                        self.ctx['duration_ms'] = int(dur)
                    now = time.monotonic()
                    if pos >= 3000 and (not last_save or now - last_save >= 15):
                        _save_local_progress(self.ctx, pos, dur, finished=False)
                        last_save = now
                    if now - last_report >= 60:
                        self._report('progress', position_ms=pos)
                        last_report = now
            finally:
                if token == self._progress_heartbeat_token:
                    self._started_probe_pending = False

        try:
            threading.Thread(target=_runner, name='NuvioHubPlaybackLifecycle',
                             daemon=True).start()
        except Exception as exc:
            self._started_probe_pending = False
            xbmc.log('[NuvioHub] progress heartbeat failed: %s' % exc, xbmc.LOGWARNING)

    def _stop_progress_heartbeat(self):
        self._progress_heartbeat_token += 1
        self._started_probe_pending = False
        try:
            self._progress_heartbeat_stop.set()
        except Exception:
            pass

    def _run_post_start_async(self):
        """v5.4.11: run the plugin-published post-start subtitle job.

        The play dispatch used to spawn two threads inside ITS OWN invoker
        (subtitle lifecycle + post-start chores).  They kept the invoker in
        Kodi's waiting-on-thread loop long after the script ended, which
        broke reuselanguageinvoker and piled up zombie sub-interpreters —
        the second half of the stop → replay AML freeze.  The dispatch now
        only publishes a job property; this long-lived interpreter owns the
        actual work, keyed to the active playback_uid so a stale job can
        never touch the wrong stream."""
        uid = str(self._active_playback_uid or self.ctx.get('playback_uid') or '')
        if not uid:
            return
        try:
            from .playback import post_start
            job = post_start.take_job(uid)
        except Exception as exc:
            try:
                xbmc.log('[NuvioHub] post-start job pickup failed: %s' % exc,
                         xbmc.LOGWARNING)
            except Exception:
                pass
            return
        if not job:
            return

        def _runner():
            try:
                post_start.run_job(job, monitor=_monitor)
            except Exception as exc:
                _monitor('play-post-start-error', level=xbmc.LOGWARNING,
                         error=exc, title=self.ctx.get('title') or '')

        try:
            threading.Thread(target=_runner, name='NuvioHubPostStart',
                             daemon=True).start()
        except RuntimeError as exc:
            try:
                xbmc.log('[NuvioHub] post-start worker unavailable: %s' % exc,
                         xbmc.LOGWARNING)
            except Exception:
                pass

    def onPlayBackStarted(self):
        if xbmcgui.Window(10000).getProperty('nuvio.saver.cancelled'):
            from .saver_state import stop_cancelled_preview
            if stop_cancelled_preview(self):
                self._enter_foreign_playback('cancelled-screensaver')
                return
        # Adaptive/HLS players may emit Started more than once for the same
        # media item (manifest open, decoder re-open, quality change). Do not
        # reset the resume coordinator or spawn another heartbeat for those
        # duplicate callbacks.
        try:
            pending = load_session() or {}
        except Exception:
            pending = {}
        pending_uid = str(pending.get('playback_uid') or '')
        if xbmcgui.Window(10000).getProperty('nuvio.preview.active'):
            self._enter_foreign_playback('home-preview')
            return
        # v5.4.11 ownership gate — decide from the session file alone, BEFORE
        # touching the Player or any window property. No NuvioHub session and
        # no armed uid means this start is not ours (TMDb Helper dummy, other
        # addons, local files): go idle without a single Kodi API call.
        if not pending_uid and not self._active_playback_uid:
            self._enter_foreign_playback('no-session')
            return
        current_file = self._current_playing_file()
        _cf_low = (current_file or '').lower()
        if _cf_low and all(m in _cf_low for m in _FOREIGN_FILE_MARKERS):
            # A stale session must never let the TMDbH dummy arm the
            # companion — the real playback of that session comes next.
            self._enter_foreign_playback('tmdbh-dummy', current_file)
            return
        self._foreign_active = False
        import time as _t
        now = _t.time()
        same_uid = bool(pending_uid and pending_uid == self._active_playback_uid)
        same_file = bool(current_file and current_file == self._last_started_file)
        # A new source can resolve to the exact same URL/file. When both sides
        # have UIDs, identity is UID-only; using same_file here suppressed a
        # genuine replacement and left the old context/threads active.
        # After Stop, the old URL can still match while the active session is
        # empty. A fresh UID must always re-arm tracking, even on that same URL.
        duplicate_identity = same_uid if pending_uid else bool(self.ctx and same_file)
        if duplicate_identity and (now - float(self._last_started_at or 0.0)) < 12.0:
            _monitor('playback-started-duplicate-suppressed', title=self.ctx.get('title') or pending.get('title') or '', playback_uid=pending_uid, playing_file=current_file)
            self._publish_artwork_async(self.ctx or pending)
            self._confirm_started_async()
            return
        self._refresh_context()
        _clear_tmdbh_handoff_flag()
        self._publish_artwork_async(self.ctx)
        self._apply_resume_async()
        self._restore_switched_subtitle_async()
        self._run_post_start_async()
        self._start_progress_heartbeat()
        # v3.9.104: schedule pre-cache for the next episode while this one
        # plays. It is strictly opt-in and remains OFF by default so a small
        # CoreELEC box never pays for speculative network/thread work.
        try:
            self._schedule_next_episode_precache()
        except Exception as _pc_exc:
            try:
                xbmc.log('[NuvioHub] precache schedule failed: %s' % _pc_exc, xbmc.LOGDEBUG)
            except Exception:
                pass

    def onAVStarted(self):
        if xbmcgui.Window(10000).getProperty('nuvio.saver.cancelled'):
            from .saver_state import stop_cancelled_preview
            if stop_cancelled_preview(self):
                self._enter_foreign_playback('cancelled-screensaver')
                return
        # Started can precede actual A/V by many seconds on remote providers.
        # Recover even when the initial probe timed out or the service attached late.
        pending = load_session() or {}
        if not pending.get('playback_uid'):
            return
        if xbmcgui.Window(10000).getProperty('nuvio.preview.active'):
            return
        if self._foreign_active or self._active_playback_uid != pending.get('playback_uid'):
            self.onPlayBackStarted()
        if not self._foreign_active and not self._started_probe_pending:
            self._start_progress_heartbeat()
        if not self._foreign_active:
            self._last_started_file=self._current_playing_file() or self._last_started_file
            xbmcgui.Window(10000).setProperty('nuvio.playback.started', pending.get('nuvio_request_id') or '')
            self._run_post_start_async()

    def _schedule_next_episode_precache(self):
        """Fire-and-forget: read next_episode hint from session ctx and ask
        the addon to pre-scrape it in the background. Silently no-ops if the
        feature is disabled, if there's no next episode, or if the current
        item isn't a TV episode."""
        nxt = self._next_episode or {}
        if not nxt:
            return
        # Explicit opt-in only. A missing setting must behave as OFF too.
        try:
            from xbmcaddon import Addon as _Addon
            raw = (_Addon('plugin.video.nuviohub').getSetting('pre_cache_next_episode') or 'false').strip().lower()
            if raw not in ('true', '1', 'yes', 'on'):
                return
        except Exception:
            pass
        try:
            canonical_id = nxt.get('canonical_id') or nxt.get('canonical') or ''
            video_id = nxt.get('video_id') or ''
            season = nxt.get('season')
            episode = nxt.get('episode')
            title = nxt.get('title') or nxt.get('show_title') or ''
            media_type = nxt.get('media_type') or 'series'
        except Exception:
            return
        if not canonical_id or not season or not episode:
            return
        # Reach into plugin.py for the worker function (lazy import — keeps
        # the import graph clean, avoids circular dependency at module load).
        try:
            from . import plugin as _plg
            _plg._precache_episode_async(
                canonical_id=canonical_id,
                video_id=video_id,
                season=season,
                episode=episode,
                title=title,
                media_type=media_type,
                delay_seconds=60,
            )
        except Exception as exc:
            try:
                xbmc.log('[NuvioHub] precache dispatch failed: %s' % exc, xbmc.LOGWARNING)
            except Exception:
                pass

    def onPlayBackPaused(self):
        if self._foreign_active or not self.ctx:
            return
        if self._resume_in_progress:
            _monitor('playback-pause-during-resume-suppressed', title=self.ctx.get('title') or '')
            return
        self._publish_artwork_async(self.ctx)
        _monitor('playback-paused', title=self.ctx.get('title') or '', position_ms=self._position_ms())
        pos = self._position_ms()
        self._progress_seen_ms = max(self._progress_seen_ms, int(pos or 0))
        dur = self._duration_ms()
        _save_local_progress(self.ctx, pos, dur, finished=False)
        self._report('paused', position_ms=pos)

    def onPlayBackResumed(self):
        if self._foreign_active or not self.ctx:
            return
        if self._resume_in_progress:
            _monitor('playback-resume-during-resume-suppressed', title=self.ctx.get('title') or '')
            return
        self._publish_artwork_async(self.ctx)
        _monitor('playback-resumed', title=self.ctx.get('title') or '', position_ms=self._position_ms())
        pos = self._position_ms()
        self._progress_seen_ms = max(self._progress_seen_ms, int(pos or 0))
        _save_local_progress(self.ctx, pos, self._duration_ms(), finished=False)
        self._report('progress', position_ms=pos)

    def onPlayBackError(self):
        """Kodi 20+ fires this on format/codec/network failures."""
        if self._foreign_active:
            return
        _clear_tmdbh_handoff_flag()
        self._had_error = True
        _monitor('playback-error', level=xbmc.LOGWARNING, title=self.ctx.get('title') or '', canonical_id=self.ctx.get('canonical_id') or '', provider=self.ctx.get('provider_name') or self.ctx.get('provider_id') or '')
        if self._fallback_chain:
            xbmc.log('[NuvioHub] onPlayBackError — scheduling fallback grace', xbmc.LOGWARNING)
            self._schedule_fallback('playback-error', delay_ms=3200)
        else:
            xbmc.log('[NuvioHub] onPlayBackError — no fallback configured', xbmc.LOGWARNING)

    def _try_fallback(self):
        """Compatibility seam retained for callers; never changes source."""
        self._fallback_chain = []
        return False

    def onPlayBackStopped(self):
        self._stop_progress_heartbeat()
        self._resume_generation += 1
        self._resume_in_progress = False
        if self._foreign_active:
            # Foreign playback ended (e.g. the TMDbH dummy): reset the flag
            # and touch NOTHING else. No Window-property clears, no session
            # reads/writes, no monitor events — this callback lands inside
            # the AML display-mode-switch window. This also removes the
            # garbage 'playback-stopped' rows that reported the previous
            # movie's position for a 100ms dummy clip.
            self._foreign_active = False
            return
        _clear_tmdbh_handoff_flag()
        sess_for_reopen = load_session() or {}
        # Kodi has already detached the player by the time this callback runs
        # on several Kodi 22 builds. Never call getTime/getTotalTime after Stop;
        # use the last heartbeat or the exact source-switch snapshot instead.
        handoff = _source_switch_handoff_read()
        my_uid = str(self.ctx.get('playback_uid') or '')
        handoff_old_uid = str(handoff.get('old_uid') or '')
        handoff_matches = bool(handoff.get('token') and (not handoff_old_uid or handoff_old_uid == my_uid))
        switching = bool(sess_for_reopen.get('source_switch_pending'))
        same_uid = bool(my_uid and (my_uid == str(sess_for_reopen.get('playback_uid') or '')))
        if handoff_matches or (switching and same_uid):
            try:
                pos = int(float(sess_for_reopen.get('resume_seconds') or 0.0) * 1000)
            except Exception:
                pos = int(self._last_position_ms or self._progress_seen_ms or 0)
            try:
                dur = int(float(sess_for_reopen.get('duration') or 0.0) * 1000)
            except Exception:
                dur = int(self._last_duration_ms or self.ctx.get('duration_ms', 0) or 0)
            self._progress_seen_ms = max(self._progress_seen_ms, pos)
            if handoff_matches:
                _source_switch_handoff_ack(handoff)
            _monitor('source-switch-old-stop-suppressed', title=self.ctx.get('title') or '', playback_uid=self.ctx.get('playback_uid') or '', position_ms=pos, duration_ms=dur)
            # Do not report stopped/unscrobble, clear the session, or trigger
            # fallback. The replacement invocation owns the handoff now.
            self.ctx = {}
            self.reporter = None
            self._fallback_chain = []
            self._next_episode = None
            return
        pos = int(self._last_position_ms or self._progress_seen_ms or 0)
        dur = int(self._last_duration_ms or self.ctx.get('duration_ms', 0) or 0)
        self._progress_seen_ms = max(self._progress_seen_ms, int(pos or 0))
        watched = bool(self.ctx.get('nuvio_completed_by_user')) or should_mark_watched(pos, dur)
        # False-positive fallback fix: some hosts briefly stop/reopen the
        # player while the real stream continues. Only auto-fallback when
        # playback died almost immediately AND we never reached meaningful
        # progress, or Kodi explicitly reported a playback error.
        import time as _t
        elapsed = _t.time() - (self._play_start_time or 0)
        played_little = (pos < 3000)
        no_real_progress = (self._progress_seen_ms < 3000)
        # Do not auto-play another source when the user backs out or stops
        # early. Kodi reports those cases the same way as an early stop, so the
        # old no-progress fallback could re-enter the source search and start
        # the movie again.
        #
        # Tightened in 3.8.11: Kodi 20/21 fire onPlayBackError as a
        # false-positive on transient HLS hiccups, codec changes, and
        # Stop-after-Pause scenarios. `_had_error` alone is not a reliable
        # signal. Require ALL of:
        #   - had_error                  (Kodi-reported error)
        #   - elapsed < 60s wall-clock   (user couldn't have watched much)
        #   - progress_seen_ms < 30000   (player never advanced past 30s)
        # Anything else is a user-initiated stop — no auto-fallback.
        probably_failed = (
            bool(self._had_error)
            and elapsed < 60.0
            and self._progress_seen_ms < 30000
        )
        if probably_failed and self._fallback_chain:
            _monitor('stopped-probably-failed', level=xbmc.LOGWARNING, title=self.ctx.get('title') or '', elapsed='%.2f' % elapsed, position_ms=pos, duration_ms=dur, progress_seen_ms=self._progress_seen_ms, had_error=self._had_error, fallback_count=len(self._fallback_chain or []))
            self._schedule_fallback('stopped-early', delay_ms=3200)
            # Don't clear session yet — the fallback or recovered playback will reload it.
            return
        if self._had_error and not probably_failed:
            _monitor('stopped-error-but-user-progress', title=self.ctx.get('title') or '',
                     elapsed='%.2f' % elapsed, progress_seen_ms=self._progress_seen_ms,
                     position_ms=pos, note='auto-fallback suppressed')
        if watched:
            _monitor('playback-ended', title=self.ctx.get('title') or '', position_ms=dur or pos, duration_ms=dur, watched=True)
            _save_local_progress(self.ctx, dur or pos, dur or pos, finished=True)
        elif pos >= 1000:
            _monitor('playback-stopped', title=self.ctx.get('title') or '', position_ms=pos, duration_ms=dur, watched=False)
            _save_local_progress(self.ctx, pos, dur, finished=False)
        if self.ctx.get('nuvio_request_id'):
            xbmcgui.Window(10000).setProperty('nuvio.playback.finished',str(self.ctx['nuvio_request_id']))
        if self.reporter:
            if watched:
                self._report('ended', position_ms=dur or pos)
            else:
                self._report('stopped', position_ms=pos)
                if self.ctx.get('companionUnscrobbleUrl'):
                    try:
                        self.reporter._post(self.ctx, 'companionUnscrobbleUrl', pos, 'stopped', mark_watched=False)
                    except Exception as exc:
                        xbmc.log('[NuvioHub] companion unscrobble error: %s' % exc, xbmc.LOGWARNING)
        # User request: after Back/Stop, stay where Kodi returns naturally.
        # Do not reopen the source picker or trigger a fresh source search.
        try:
            _monitor('stop-reopen-sources-suppressed', title=self.ctx.get('title') or '', position_seconds='%.1f' % (float(pos or 0) / 1000.0))
        except Exception:
            pass
        if _session_owned_by(self.ctx):
            clear_session()
        self.ctx = {}
        self.reporter = None
        self._fallback_chain = []
        self._next_episode = None
        self._active_playback_uid = ''
        self._fallback_pending = False

    def onPlayBackEnded(self):
        self._stop_progress_heartbeat()
        self._resume_generation += 1
        self._active_playback_uid = ''
        self._fallback_pending = False
        self._resume_in_progress = False
        if self._foreign_active:
            # See onPlayBackStopped: foreign playback must end silently.
            self._foreign_active = False
            return
        _clear_tmdbh_handoff_flag()
        dur = self._duration_ms()
        _save_local_progress(self.ctx, dur or self._position_ms(), dur, finished=True)
        if self.ctx.get('nuvio_request_id'):
            xbmcgui.Window(10000).setProperty('nuvio.playback.finished',str(self.ctx['nuvio_request_id']))
        self._report('ended', position_ms=dur)
        next_ep = self._next_episode
        nuvio_owned = bool(self.ctx.get('nuvio_request_id'))
        if _session_owned_by(self.ctx):
            clear_session()
        self.ctx = {}
        self.reporter = None
        self._fallback_chain = []
        self._next_episode = None
        self._started_reported = False
        self._started_probe_pending = False
        # Auto-next episode prompt (if enabled and available).
        if next_ep and not nuvio_owned:
            self._maybe_play_next(next_ep)

    def _maybe_play_next(self, next_ep):
        try:
            auto = (ADDON.getSetting('auto_next_episode') or 'true').lower() == 'true'
        except Exception:
            auto = True
        if not auto:
            return
        try:
            countdown = max(3, int(ADDON.getSetting('auto_next_prompt_seconds') or '20'))
        except Exception:
            countdown = 20
        title = next_ep.get('title') or ''
        s = int(next_ep.get('season') or 0)
        e = int(next_ep.get('episode') or 0)
        dlg = xbmcgui.DialogProgress()
        try:
            dlg.create('Nuvio Hub', tr('Next episode: %s — S%02dE%02d') % (title, s, e))
            import time as _t
            start = _t.time()
            while not dlg.iscanceled() and (_t.time() - start) < countdown:
                remaining = int(countdown - (_t.time() - start))
                pct = int(max(0, min(100, ((_t.time() - start) / float(countdown)) * 100)))
                dlg.update(pct, tr('Next episode: %s — S%02dE%02d\nStarting in: %ss') % (title, s, e, remaining))
                xbmc.sleep(250)
        finally:
            try:
                dlg.close()
            except Exception:
                pass
        if dlg.iscanceled():
            return
        # Trigger the next episode via the plugin router — this re-enters the
        # whole streams/auto-pick pipeline with correct IDs and artwork.
        params = {
            'action': 'play_item',
            'media_type': 'series',
            'canonical_id': next_ep.get('canonical_id') or '',
            'video_id': next_ep.get('video_id') or '',
            'season': str(s),
            'episode': str(e),
            'title': next_ep.get('title') or '',
        }
        url = 'plugin://plugin.video.nuviohub/?' + urllib.parse.urlencode(params)
        xbmc.executebuiltin('RunPlugin(%s)' % url)


class ProgressLoop(object):
    def __init__(self, player):
        self.player = player
        self._back_reopen_until = 0.0
        self._back_seen_for = 0.0

    def _fullscreen_active(self):
        try:
            return bool(xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'))
        except Exception:
            return True

    def _maybe_stop_and_reopen_sources(self):
        # Keep playback alive when the user backs out of fullscreen. Kodi can
        # continue the video in the background / mini-player; the source picker
        # should only reopen after the user actually stops/closes playback.
        self._back_seen_for = 0.0
        return

    def _reopen_sources_after_stop(self, sess, position_seconds=0.0):
        # Disabled: stopping/backing out must not reopen source search or play again.
        return False


    def run(self):
        monitor = xbmc.Monitor()
        while not monitor.abortRequested():
            interval = _interval_seconds()
            # Heartbeat owns progress reports; this loop only retries saved sync.
            if not self.player.isPlayingVideo():
                try: simkl.flush_progress()
                except Exception: pass
            self._maybe_stop_and_reopen_sources()
            if monitor.waitForAbort(interval):
                break
