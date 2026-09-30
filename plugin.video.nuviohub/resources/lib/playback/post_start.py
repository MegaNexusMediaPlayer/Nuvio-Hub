# -*- coding: utf-8 -*-
"""Post-start subtitle work, executed by the SERVICE — not the plugin.

v5.4.11. Until 5.4.10 the play dispatch spawned two threads that kept
running long after the plugin script returned:

  * ``NuvioHubSubtitleLifecycle`` — waited for AV, then ran the FULL broker
    discovery (15s budget) and downloaded every found subtitle file;
  * ``NuvioHubPlayPost``          — polled up to 25s for real media, then
    applied/selected the elected subtitle track.

Kodi's CPythonInvoker cannot finish while any thread of its interpreter is
alive (``CPythonInvoker(...): waiting on thread`` in the log — one line per
blocking thread, exactly what invokers 119 and 220 showed).  While it waits,
the invoker never reaches ``InvokerStateScriptDone``, so with
``reuselanguageinvoker=true`` the next dispatch cannot reuse it: Kodi
releases the stuck invoker asynchronously and builds a FRESH sub-interpreter
instead.  Every playback therefore left a zombie interpreter whose threads
kept calling Player APIs and downloading files — and stop → instant replay
put that churn exactly inside the Amlogic display-pipeline reset while the
new dispatch was being wired up.  That collision is the hard freeze.

The rule now: a plugin invocation exits with ZERO surviving threads.  The
dispatch only *publishes a job* (one Window-property write, done before
``Player.play``); the long-lived service companion consumes it on its own
``onPlayBackStarted`` and runs the exact same work on a service-interpreter
thread, where no invoker lifecycle exists to block.

The job travels over a Home-window property (same transport as the session
store): written by the plugin interpreter, read+cleared by the service.
"""
import json

import xbmc
import xbmcgui
import xbmcvfs

WINDOW_ID = 10000
PROP_JOB = 'dexhub.post_start_job_v1'

# Files that must never count as "our media has started": TMDb Helper opens
# a local dummy clip before every real play, and NuvioHub's own plugin:// nav
# URLs can flash through the player during handoff.
_FOREIGN_FILE_MARKERS = (
    'plugin.video.themoviedb.helper',
    'dummy.mp4',
)
_NAV_MARKERS = (
    'action=streams', 'action=episode_streams', 'action=item_open',
    'action=series_meta', 'action=play_item', 'action=cw_resume',
    'action=cw_play_from_start', 'action=play', 'action=tmdb_player',
    'action=kodi_route_browse',
)


def _window():
    return xbmcgui.Window(WINDOW_ID)


def publish_job(ctx, stream_key='play', subtitle_path='', subtitle_index=-1,
                force_subtitles=False, existing_paths=None, subtitle_rows=None,
                attach_rows=None, discovery=False):
    """Called by the play dispatch (plugin interpreter). Cheap and thread-free:
    serialises the post-start work and hands it to the service."""
    ctx = dict(ctx or {})
    uid = str(ctx.get('playback_uid') or '')
    existing_ids = []
    for row in (subtitle_rows or []):
        try:
            rid = str(row.get('id') or row.get('url') or row.get('path') or '')
        except Exception:
            rid = ''
        if rid:
            existing_ids.append(rid)
    apply_job = None
    try:
        idx = int(subtitle_index)
    except Exception:
        idx = -1
    if subtitle_path or idx >= 0 or force_subtitles:
        apply_job = {
            'path': str(subtitle_path or ''),
            'index': idx,
            'force': bool(force_subtitles),
        }
    job = {
        'v': 1,
        'uid': uid,
        'stream_key': str(stream_key or 'play'),
        'title': str(ctx.get('title') or ''),
        'provider': str(ctx.get('provider_name') or ctx.get('provider_id') or ''),
        'ctx': ctx,
        'apply': apply_job,
        'existing_paths': [str(p) for p in (existing_paths or []) if p],
        'existing_ids': existing_ids,
        'attach_rows': list(attach_rows or []),
        'discovery': bool(discovery),
    }
    _window().setProperty(PROP_JOB, json.dumps(job, ensure_ascii=False,
                                               default=str))
    return job


def clear_job():
    try:
        _window().clearProperty(PROP_JOB)
    except Exception:
        pass


def take_job(expected_uid):
    """Called by the service companion on playback start.  Returns the job
    for ``expected_uid`` and clears the property; a job left behind by an
    earlier playback (uid mismatch) is discarded so it can never run against
    the wrong stream."""
    raw = ''
    try:
        raw = _window().getProperty(PROP_JOB) or ''
    except Exception:
        raw = ''
    if not raw:
        return None
    clear_job()
    try:
        job = json.loads(raw)
    except Exception:
        return None
    if not isinstance(job, dict):
        return None
    uid = str(job.get('uid') or '')
    if not uid or uid != str(expected_uid or ''):
        return None
    if not (job.get('apply') or job.get('attach_rows') or job.get('discovery') or
            (job.get('ctx') or {}).get('nuvio_subtitle_language')):
        return None
    return job


def _player_has_real_media(player):
    """Mirror of the plugin-side check the old workers used: video is up AND
    the playing file is neither NuvioHub navigation nor the TMDbH dummy."""
    has_video = False
    try:
        has_video = bool(player.isPlayingVideo())
    except Exception:
        has_video = False
    try:
        has_video = has_video or bool(xbmc.getCondVisibility('Player.HasVideo'))
    except Exception:
        pass
    if not has_video:
        return False
    playing_file = ''
    try:
        playing_file = player.getPlayingFile() or ''
    except Exception:
        playing_file = ''
    low = str(playing_file or '').lower()
    if low:
        if all(marker in low for marker in _FOREIGN_FILE_MARKERS):
            return False
        if low.startswith('plugin://plugin.video.nuviohub/') and any(
                marker in low for marker in _NAV_MARKERS):
            return False
    return True


def run_job(job, monitor=None):
    """Execute one published job on a service-interpreter thread.

    Nuvio waits for AV confirmation of its exact request (up to 60 seconds).
    Legacy callers keep the original sequence:
      1. wait up to 25s (250ms steps) for real media, then let it stabilise;
      2. apply the elected subtitle (stream index first, sidecar fallback)
         and re-assert the preferred-language stream;
      3. attach the deferred sidecars (non-playlist-handoff path);
      4. run background broker discovery and attach every new track.
    Every stage is bounded and abort-aware; the worker dies with playback.
    """
    job = dict(job or {})
    stream_key = str(job.get('stream_key') or 'play')
    title = str(job.get('title') or '')
    provider = str(job.get('provider') or '')

    def _emit(event, level=None, **fields):
        if monitor is None:
            return
        try:
            if level is not None:
                monitor(event, level=level, **fields)
            else:
                monitor(event, **fields)
        except Exception:
            pass

    kodi_monitor = xbmc.Monitor()
    player = xbmc.Player()
    apply_job = job.get('apply') or None
    ctx = job.get('ctx') or {}
    nuvio_auto = bool(ctx.get('nuvio_subtitle_language'))
    if nuvio_auto:
        from ..session_store import load_session
        _window().setProperty('nuvio.subtitle.status', 'Waiting for video')
    started = False
    try:
        # Stage 1 — wait for real media (the old NuvioHubPlayPost budget).
        for _ in range(240 if nuvio_auto else 100):
            if kodi_monitor.abortRequested():
                return
            if kodi_monitor.waitForAbort(.25):return
            if nuvio_auto:
                current_uid=(load_session() or {}).get('playback_uid')
                if current_uid and current_uid!=ctx.get('playback_uid'):return
                request=str(ctx.get('nuvio_request_id') or '')
                if request and (_window().getProperty('nuvio.cancelled.'+request) or _window().getProperty('nuvio.playback.finished')==request):return
                if _window().getProperty('nuvio.subtitle.manual')==ctx.get('nuvio_request_id'):return
                if _window().getProperty('nuvio.playback.started')!=ctx.get('nuvio_request_id'):continue
            try:
                if _player_has_real_media(player):
                    started = True
                    break
            except Exception:
                continue
        if not started:
            if nuvio_auto:_window().setProperty('nuvio.subtitle.status','Video start timed out')
            if apply_job:
                _emit('play-start-timeout', level=xbmc.LOGWARNING,
                      stream_key=stream_key, title=title, provider=provider)
            return
        if nuvio_auto:
            from ..nuvio_subtitles import auto_apply
            _window().setProperty('nuvio.subtitle.status','Searching')
            applied=auto_apply(ctx,player)
            if (load_session() or {}).get('playback_uid')==ctx.get('playback_uid'):
                _window().setProperty('nuvio.subtitle.status','Applied' if applied else 'No matching subtitle')
            _emit('nuvio-auto-subtitle',applied=applied,language=ctx.get('nuvio_subtitle_language'))
            return
        if apply_job:
            _emit('play-started', stream_key=stream_key, title=title,
                  provider=provider)
            # Plex/CDN streams need 1-3s past the first keyframe before a
            # seek/subtitle call sticks.
            xbmc.sleep(800)

        # Stage 2 — elected subtitle.
        if apply_job:
            _apply_selected_subtitle(player, apply_job, kodi_monitor)
            try:
                from .subtitle_files import _force_preferred_subtitle_on_player
                _force_preferred_subtitle_on_player(
                    player, show=bool(apply_job.get('force')),
                    attempts=4, delay_ms=400)
            except Exception:
                pass

        # Stage 3 — deferred sidecars (legacy non-playlist handoff only).
        attach_rows = job.get('attach_rows') or []
        if attach_rows and _player_has_real_media(player):
            _attach_remaining_rows(player, attach_rows,
                                   job.get('existing_paths') or [], stream_key)

        # Stage 4 — background broker discovery.
        if job.get('discovery') and not kodi_monitor.abortRequested() \
                and _player_has_real_media(player):
            _discover_and_attach(player, job, stream_key)
    except Exception as exc:
        if nuvio_auto and (load_session() or {}).get('playback_uid')==ctx.get('playback_uid'):
            _window().setProperty('nuvio.subtitle.status','Subtitle could not be loaded')
        _emit('play-post-start-error', level=xbmc.LOGWARNING, error=exc,
              stream_key=stream_key, title=title)
        try:
            xbmc.log('[NuvioHub] post-start chores failed: %s' % exc,
                     xbmc.LOGDEBUG)
        except Exception:
            pass


def _apply_selected_subtitle(player, apply_job, kodi_monitor):
    path = str(apply_job.get('path') or '')
    try:
        index = int(apply_job.get('index'))
    except Exception:
        index = -1
    if path:
        low = path.lower()
        if not low.startswith(('http://', 'https://', 'smb://', 'nfs://')):
            # DPlex-style deferred sidecars may still be copying when AV
            # starts — wait for the file instead of silently losing it.
            for _ in range(40):
                try:
                    if xbmcvfs.exists(path):
                        break
                except Exception:
                    break
                if kodi_monitor.abortRequested():
                    return
                xbmc.sleep(250)
            else:
                return
    try:
        player.showSubtitles(False)
    except Exception:
        pass
    applied = False
    if index >= 0:
        try:
            player.setSubtitleStream(index)
            player.showSubtitles(True)
            applied = True
        except Exception:
            applied = False
    if not applied and path:
        try:
            player.setSubtitles(path)
            player.showSubtitles(True)
        except Exception:
            pass


def _attach_remaining_rows(player, rows, existing_paths, stream_key):
    try:
        from ..subtitle_policy import automatic_rows
        from .subtitle_files import _prepare_subtitle_files
        safe_rows = automatic_rows(list(rows))
        if not safe_rows:
            return
        prepared = _prepare_subtitle_files(
            safe_rows, stream_key, prefer_local_copy=True)
        extras = [r.get('path') for r in prepared if r.get('path')]
        if not extras:
            return
        # setSubtitles replaces the list wholesale on some Kodi builds —
        # replay the already-attached tracks first so none are lost.
        combined = list(existing_paths) + [p for p in extras
                                           if p not in existing_paths]
        try:
            player.setSubtitles(combined[0])
            for extra in combined[1:]:
                try:
                    player.setSubtitles(extra)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass


def _discover_and_attach(player, job, stream_key):
    try:
        from ..subtitle_policy import automatic_rows
        from .subtitle_files import (_collect_playback_subtitles,
                                     _prepare_subtitle_files)
        try:
            discovered = _collect_playback_subtitles(
                dict(job.get('ctx') or {}), manual=False, force_search=True,
                include_broker=True)
        except Exception as exc:
            xbmc.log('[NuvioHub] background subtitle discovery failed: %s' % exc,
                     xbmc.LOGWARNING)
            return
        existing_ids = set(str(i) for i in (job.get('existing_ids') or []))
        existing_paths = set(str(p) for p in (job.get('existing_paths') or []))
        extras = []
        for row in (discovered or []):
            rid = str(row.get('id') or row.get('url') or row.get('path') or '')
            if rid and rid in existing_ids:
                continue
            extras.append(row)
            if rid:
                existing_ids.add(rid)
        # AI rows stay manual-only: automatic preparation would trigger
        # generation and consume the user's DexWorld token.
        extras = automatic_rows(extras)
        if not extras:
            return
        prepared = _prepare_subtitle_files(
            extras, stream_key, prefer_local_copy=True)
        added = 0
        for row in prepared:
            path = row.get('path')
            if not path or path in existing_paths:
                continue
            if not _player_has_real_media(player):
                break
            try:
                player.setSubtitles(path)
                existing_paths.add(path)
                added += 1
            except Exception:
                pass
        xbmc.log('[NuvioHub] background subtitle discovery attached %d track(s)'
                 % added, xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NuvioHub] background subtitle attach failed: %s' % exc,
                 xbmc.LOGWARNING)
