"""Read-only segment lookup and playback controls, owned by the Nuvio Hub service."""
import json
import math
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui

_BACKOFF = 0.0


def query_params(context, duration):
    params = {}
    tid = str(context.get('tmdb_id') or '')
    imdb = str(context.get('imdb_id') or context.get('canonical_id') or '')
    if tid.isdigit() and int(tid) > 0:
        params['tmdb_id'] = tid
    elif re.fullmatch(r'tt\d+', imdb):
        params['imdb_id'] = imdb
    else:
        return None
    mt = context.get('media_type') or context.get('type')
    if mt not in ('movie', 'series', 'episode', 'tv', 'show', 'tvshow', 'anime'):
        return None
    if mt != 'movie':
        try:
            season, episode = int(context['season']), int(context['episode'])
        except (KeyError, ValueError, TypeError):
            return None
        if season < 1 or episode < 1: return None
        params.update(season=season, episode=episode)
    if not math.isfinite(duration) or duration <= 0: return None
    params['duration_ms'] = int(duration * 1000)
    return params


def normalize_segments(payload, duration):
    """Never trust API timestamps enough to seek outside the current media."""
    result = []
    if not isinstance(payload, dict) or not math.isfinite(duration) or duration <= 0:
        return result
    for kind in ('intro', 'recap', 'credits', 'preview'):
        candidates = []
        raw = payload.get(kind) or []
        if not isinstance(raw, list): continue
        for segment in raw:
            if not isinstance(segment, dict): continue
            try:
                if segment.get('start_ms') is None and kind in ('credits', 'preview'): continue
                start = float(segment.get('start_ms') or 0) / 1000
                end = segment.get('end_ms')
                if end is None and kind in ('intro', 'recap'): continue
                end = float(end) / 1000 if end is not None else duration - 0.75
                confidence = float(segment.get('confidence', 0.5))
                if not all(math.isfinite(n) for n in (start, end, confidence)): continue
                if start < 0 or end <= start or end > duration or start >= duration - 1: continue
                candidates.append((confidence, start, min(end, duration - 0.75)))
            except (ValueError, TypeError, OverflowError):
                continue
        if candidates:
            _, start, end = max(candidates)
            if end > start:
                result.append({'type': kind, 'start': start, 'end': end})
    return sorted(result, key=lambda row: row['start'])


def lookup(context, duration, key=''):
    global _BACKOFF
    params = query_params(context, duration)
    if not params or time.monotonic() < _BACKOFF:
        return []
    request = Request('https://api.theintrodb.org/v3/media?' + urlencode(params),
                      headers={'Accept': 'application/json', 'User-Agent': 'Nuvio Hub/' + xbmcaddon.Addon('plugin.video.nuviohub').getAddonInfo('version')})
    if key: request.add_header('Authorization', 'Bearer ' + key)
    try:
        with urlopen(request, timeout=4) as response:
            data = json.loads(response.read(1024 * 1024).decode('utf-8'))
        return normalize_segments(data, duration)
    except HTTPError as error:
        if error.code == 429:
            try: delay = min(3600, max(60, int(error.headers.get('Retry-After', '300'))))
            except (TypeError, ValueError): delay = 300
            _BACKOFF = time.monotonic() + delay
        return []
    except Exception:
        return []


def owns_playback(player, uid):
    if not uid or getattr(player, '_foreign_active', True): return False
    if uid != getattr(player, '_active_playback_uid', ''): return False
    if uid != (getattr(player, 'ctx', {}) or {}).get('playback_uid'): return False
    try:
        if not player.isPlayingVideo():return False
        return bool(player._last_started_file and player.getPlayingFile()==player._last_started_file)
    except Exception:
        return False


class SkipOverlay(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super(SkipOverlay, self).__init__(*args)
        self.player = kwargs['player']
        self.uid = kwargs['uid']
        self.segment = kwargs['segment']
        self.dismissed = False
        self.command = None

    def onInit(self):
        outro=self.segment['type'] in ('credits','preview')
        self.getControl(10).setLabel('Skip outro' if outro else 'Skip '+self.segment['type'])
        self.setProperty('nuvio.next_available','1' if outro and self.player.ctx.get('next_episode') else '')
        self.setFocusId(10)

    def onClick(self, control_id):
        if control_id in (10,11):self.command=control_id
        self.dismissed=True
        self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 92, 216):
            self.dismissed = True
            self.close()


def run(player, monitor):
    addon = xbmcaddon.Addon('plugin.video.nuviohub')
    uid, segments, handled, overlay = '', [], set(), None
    try:
        while not monitor.abortRequested():
            try:
                mode = addon.getSetting('nuvio_skip_mode') or 'Button'
                current_uid = getattr(player, '_active_playback_uid', '')
                active = mode != 'Off' and owns_playback(player, current_uid)
                if not active:
                    uid, segments, handled = '', [], set()
                    if overlay: overlay.close(); overlay = None
                else:
                    if current_uid != uid:
                        if overlay: overlay.close(); overlay = None
                        duration = player.getTotalTime()
                        if duration <= 0:
                            if monitor.waitForAbort(0.5): break
                            continue
                        uid, handled = current_uid, set()
                        segments = lookup(dict(player.ctx), duration, addon.getSetting('nuvio_introdb_key'))
                    # A lookup can finish after playback changed. Recheck before touching the player.
                    if owns_playback(player, uid):
                        position = player.getTime()
                        if overlay and overlay.dismissed:
                            if overlay.command:apply_skip(player,uid,overlay.segment,overlay.command==11)
                            handled.add((overlay.segment['type'], overlay.segment['start']))
                            overlay = None
                        segment = next((s for s in segments if s['start'] <= position < s['end']
                                        and (s['type'], s['start']) not in handled), None)
                        if not segment or xbmc.getCondVisibility('Player.Paused') or not xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'):
                            if overlay: overlay.close(); overlay = None
                        elif mode == 'Automatic':
                            if owns_playback(player, uid):
                                apply_skip(player,uid,segment,False)
                                handled.add((segment['type'], segment['start']))
                        elif overlay is None:
                            overlay = SkipOverlay('nuvio_skip.xml', xbmcaddon.Addon('script.nuvio').getAddonInfo('path'), 'Default', '1080i',
                                                  player=player, uid=uid, segment=segment)
                            overlay.show()
            except Exception:
                if overlay:
                    try: overlay.close()
                    except Exception: pass
                    overlay = None
            if monitor.waitForAbort(0.5): break
    finally:
        if overlay: overlay.close()


def apply_skip(player,uid,segment,next_episode=False):
    if not owns_playback(player,uid):return False
    position=player.getTime()
    if not segment['start']<=position<segment['end']:return False
    outro=segment['type'] in ('credits','preview')
    if outro:
        from .companion import _save_local_progress
        player.ctx['nuvio_completed_by_user']=True
        duration=player._duration_ms()
        _save_local_progress(player.ctx,player._position_ms(),duration,finished=True)
        player._report('ended',position_ms=duration)
    if next_episode and outro and player.ctx.get('next_episode'):
        request=dict(player.ctx['next_episode'],media_type='series')
        home=xbmcgui.Window(10000)
        home.setProperty('nuvio.next_episode',json.dumps(request))
        player.stop()
        if not home.getProperty('nuvio.frontend.running'):
            from . import cache_store
            key=cache_store.put('nuvio_open',dict(request,details_view='manual'))
            xbmc.executebuiltin('RunScript(script.nuvio,open,%s)'%key)
    else:player.seekTime(segment['end'])
    return True
