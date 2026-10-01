# -*- coding: utf-8 -*-
import os
import sys
import threading
import time
import xbmc

addon_path = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(addon_path, 'resources', 'lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

import xbmcgui

if __name__ == '__main__':
    from resources.lib.fork_profile import ensure_profile
    ensure_profile()


# Trakt/Simkl and Nuvio/Stremio touch the same local playback state.  They
# must never run concurrently: apart from extra pressure, overlapping pulls
# can race over progress rows.  A non-blocking lock lets the later cycle defer
# cleanly instead of creating another waiting worker.
_SYNC_CYCLE_LOCK = threading.Lock()
# --- nuviohub-402-patch ---
try:
    from resources.lib.i18n import tr as tr
except Exception:
    try:
        from i18n import tr as tr
    except Exception:
        def tr(_s):
            return _s



def _purge_http_cache():
    """Delete cached HTTP responses older than twice their max TTL. Keeps the
    cache dir bounded on long-running installs.

    Also purges:
      * special://temp/nuviohub_subs/  → subtitle files older than 24h
      * addon_data/subtitle_cache/    → switched subtitle copies older than 7d
      * meta_cache.db expired rows
      * fanarttv_cache.db expired rows
    """
    import os as _os, time as _t
    try:
        from resources.lib.nuviohub.client import HTTP_CACHE_DIR, catalog_ttl, meta_ttl
        max_ttl = max(catalog_ttl(), meta_ttl(), 3600) * 2
        if _os.path.isdir(HTTP_CACHE_DIR):
            now = _t.time()
            removed = 0
            for name in _os.listdir(HTTP_CACHE_DIR):
                path = _os.path.join(HTTP_CACHE_DIR, name)
                try:
                    if _os.path.isfile(path) and (now - _os.path.getmtime(path)) > max_ttl:
                        _os.remove(path)
                        removed += 1
                except Exception:
                    continue
            if removed:
                xbmc.log('[NuvioHub] purged %d stale http-cache files' % removed, xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NuvioHub] http-cache purge failed: %s' % exc, xbmc.LOGWARNING)

    # Subtitle files dir — wasn't being touched in earlier versions.
    try:
        import xbmcvfs
        subs_dir = xbmcvfs.translatePath('special://temp/nuviohub_subs/')
        if _os.path.isdir(subs_dir):
            now = _t.time()
            cutoff = now - 86400  # 24h
            removed = 0
            for root, dirs, files in _os.walk(subs_dir):
                for fn in files:
                    fp = _os.path.join(root, fn)
                    try:
                        if _os.path.getmtime(fp) < cutoff:
                            _os.remove(fp)
                            removed += 1
                    except Exception:
                        continue
                # Drop empty subdirs left behind
                try:
                    if root != subs_dir and not _os.listdir(root):
                        _os.rmdir(root)
                except Exception:
                    pass
            if removed:
                xbmc.log('[NuvioHub] purged %d stale subtitle files' % removed, xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NuvioHub] subs purge failed: %s' % exc, xbmc.LOGWARNING)

    # Stable copies used only to preserve external subtitles across source
    # switches. Keep them for a week, then remove them so the cache stays
    # bounded even on devices that are rarely restarted.
    try:
        import xbmcvfs
        switch_subs_dir = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.nuviohub/subtitle_cache/')
        if _os.path.isdir(switch_subs_dir):
            cutoff = _t.time() - (7 * 86400)
            removed = 0
            for fn in _os.listdir(switch_subs_dir):
                fp = _os.path.join(switch_subs_dir, fn)
                try:
                    if _os.path.isfile(fp) and _os.path.getmtime(fp) < cutoff:
                        _os.remove(fp)
                        removed += 1
                except Exception:
                    continue
            if removed:
                xbmc.log('[NuvioHub] purged %d stale switched-subtitle files' % removed, xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NuvioHub] switched-subs purge failed: %s' % exc, xbmc.LOGWARNING)

    # SQLite caches — drop expired rows
    try:
        from resources.lib import meta_cache as _mc
        n = _mc.purge_expired()
        if n:
            xbmc.log('[NuvioHub] purged %d expired meta_cache rows' % n, xbmc.LOGINFO)
    except Exception:
        pass
    try:
        from resources.lib import fanarttv as _ft
        n = _ft.purge_expired()
        if n:
            xbmc.log('[NuvioHub] purged %d expired fanarttv rows' % n, xbmc.LOGINFO)
    except Exception:
        pass


def _win():
    try:
        return xbmcgui.Window(10000)
    except Exception:
        return None


def _interactive_busy(max_age=180.0):
    """True while playback or a source/search interaction has priority."""
    try:
        if xbmc.Player().isPlayingVideo():
            return True
    except Exception:
        pass
    try:
        win = _win()
        raw = win.getProperty('nuviohub.interactive_busy') if win else ''
        return bool(raw and (time.time() - float(raw)) < float(max_age))
    except Exception:
        return False



def _setting(key, default=''):
    try:
        import xbmcaddon
        return xbmcaddon.Addon('plugin.video.nuviohub').getSetting(key) or default
    except Exception:
        return default



def _primary_player_mode():
    raw = str(_setting('catalog_click_mode', 'TMDb Helper') or 'TMDb Helper').strip().lower()
    compact = raw.replace(' ', '').replace('_', '').replace('-', '')
    if compact in ('tmdbhelper', 'helper', '1') or 'tmdb' in compact:
        return 'tmdbhelper'
    if compact in ('ask', 'askeverytime', '2') or raw in ('Ask every time', "\u0627\u0644\u0633\u0624\u0627\u0644 \u0643\u0644 \u0645\u0631\u0629"):
        return 'ask'
    return 'nuviohub'



def _publish_badge_props():
    return  # No source badge UI exists in the backend build.


def _publish_core_props(last_sync=''):
    win = _win()
    if not win:
        return
    # Keep Kodi startup light: optional integrations are imported only when
    # this small status snapshot is actually published.
    try:
        from resources.lib import tmdbh_player
        tmdbh_available = '1' if tmdbh_player.has_tmdbhelper() else '0'
        tmdbh_installed = '1' if tmdbh_player.player_installed() else '0'
    except Exception:
        tmdbh_available = '0'
        tmdbh_installed = '0'
    tmdbh_primary = '1' if _primary_player_mode() == 'tmdbhelper' else '0'
    try:
        from resources.lib import trakt
        trakt_enabled = '1' if trakt.enabled() else '0'
        trakt_connected = '1' if trakt.authorized() else '0'
    except Exception:
        trakt_enabled = '0'
        trakt_connected = '0'
    payload = {
        'nuviohub.core.ready': '1',
        'nuviohub.core.tmdbh.available': tmdbh_available,
        'nuviohub.core.tmdbh.player_installed': tmdbh_installed,
        'nuviohub.core.tmdbh.primary': tmdbh_primary,
        'nuviohub.core.trakt.enabled': trakt_enabled,
        'nuviohub.core.trakt.connected': trakt_connected,
        'nuviohub.core.trakt.last_sync': str(last_sync or ''),
        'nuviohub.core.formatter.enabled': '1' if ((_setting('enable_source_formatter', 'true') or 'true').lower() == 'true') else '0',
    }
    for k, v in payload.items():
        try:
            win.setProperty(k, v)
        except Exception:
            pass



def _invalidate_ui_caches():
    win = _win()
    if not win:
        return
    for key in ('nuviohub.nextup_cache', 'nuviohub.nextup_cache_ts', 'nuviohub.fav_mirror_done'):
        try:
            win.clearProperty(key)
        except Exception:
            pass



def _sync_trakt_state(reason='manual'):
    # Trakt is optional and fairly heavy; do not import it during service
    # bootstrap on installations where it is never used.
    try:
        from resources.lib import trakt
    except Exception:
        _publish_core_props('')
        return False
    if not trakt.enabled():
        _publish_core_props('')
        return False
    try:
        if not trakt.authorized():
            _publish_core_props('')
            return False
    except Exception:
        _publish_core_props('')
        return False

    did_work = False
    try:
        if trakt.sync_enabled():
            trakt.import_progress(limit=100)
            did_work = True
    except Exception as exc:
        xbmc.log('[NuvioHub] trakt progress sync failed (%s): %s' % (reason, exc), xbmc.LOGWARNING)

    try:
        # v4.2.0: one merged snapshot (Trakt + Simkl + MDBList). Writing a
        # trakt-only snapshot here used to erase the other services' rows on
        # every service cycle.
        from resources.lib import favorites_store
        # v4.4.1: the merged mirror hits up to three external APIs; refreshing
        # it every service cycle is wasteful. 30-minute throttle via window
        # property (resets on Kodi restart) keeps sections fresh and light.
        import time as _t
        win = _win()
        last = 0.0
        try:
            last = float(win.getProperty('nuviohub.mirror.last') or 0) if win else 0.0
        except Exception:
            last = 0.0
        if _t.time() - last >= 30 * 60:
            include_trakt = (_setting('trakt_sync_watchlist', 'true') or 'true').lower() == 'true'
            favorites_store.refresh_external_mirror(include_trakt=include_trakt)
            if win:
                win.setProperty('nuviohub.mirror.last', str(int(_t.time())))
            did_work = True
    except Exception as exc:
        xbmc.log('[NuvioHub] watchlist mirror sync failed (%s): %s' % (reason, exc), xbmc.LOGWARNING)

    if did_work:
        try:
            trakt.invalidate_cache('next_up_v1')
            trakt.invalidate_cache('/sync/playback/')
        except Exception:
            pass
        _invalidate_ui_caches()
        _publish_core_props(str(int(__import__('time').time())))
    else:
        _publish_core_props('')
    return did_work



def _sync_simkl_state(reason='manual'):
    """v4.2.0: mirror Simkl into Continue Watching on the trakt cadence.

    The watching-list sync is one request per kind and runs every cycle; the
    full watched-history import walks every list so it runs at most once per
    6 hours (window-property timestamp, resets on Kodi restart)."""
    if (_setting('simkl_service_sync', 'true') or 'true').lower() != 'true':
        return False
    try:
        from resources.lib import simkl
    except Exception:
        return False
    try:
        if not (simkl.enabled() and simkl.authorized()):
            return False
    except Exception:
        return False
    did_work = False
    try:
        simkl.sync_continue_watching(limit=60)
        did_work = True
    except Exception as exc:
        xbmc.log('[NuvioHub] simkl continue sync failed (%s): %s' % (reason, exc), xbmc.LOGWARNING)
    try:
        import time as _t
        win = _win()
        last = 0.0
        try:
            last = float(win.getProperty('nuviohub.simkl.last_import') or 0) if win else 0.0
        except Exception:
            last = 0.0
        if _t.time() - last >= 6 * 3600:
            simkl.import_watched()
            if win:
                win.setProperty('nuviohub.simkl.last_import', str(int(_t.time())))
            did_work = True
    except Exception as exc:
        xbmc.log('[NuvioHub] simkl watched import failed (%s): %s' % (reason, exc), xbmc.LOGWARNING)
    if did_work:
        try:
            simkl.invalidate_cache()
        except Exception:
            pass
        _invalidate_ui_caches()
    return did_work


def _sync_interval_ms():
    try:
        minutes = int(_setting('trakt_service_sync_interval', '30') or '30')
    except Exception:
        minutes = 30
    # Keep the full set exposed by the simplified account screen.  Earlier
    # code silently collapsed the 120/240 minute choices back to 60 minutes.
    minutes = max(10, min(240, minutes))
    return minutes * 60 * 1000



def _background_sync_loop(monitor):
    # Do not race Kodi/TMDb Helper/database migrations during boot. Previous
    # builds launched this at 4s and a second Trakt startup sync at 5s, doing
    # the same account import twice while the home screen was still opening.
    if monitor.waitForAbort(60):
        return
    _last_health = time.time()
    _last_purge = time.time()
    while not monitor.abortRequested():
        deferred = _interactive_busy()
        acquired = False
        if not deferred:
            acquired = _SYNC_CYCLE_LOCK.acquire(False)
            deferred = not acquired
        if acquired:
            try:
                try:
                    _sync_trakt_state(reason='service')
                except Exception as exc:
                    xbmc.log('[NuvioHub] trakt background sync failed: %s' % exc, xbmc.LOGWARNING)
                try:
                    _sync_simkl_state(reason='service')
                except Exception as exc:
                    xbmc.log('[NuvioHub] simkl background sync failed: %s' % exc, xbmc.LOGWARNING)
            finally:
                _SYNC_CYCLE_LOCK.release()

        # Health check Plex/Emby endpoints every 5 minutes
        import time as _t
        now = _t.time()
        if not deferred and now - _last_health >= 300:
            try:
                from resources.lib import health_monitor
                checked = health_monitor.run_check_cycle()
                if checked:
                    xbmc.log('[NuvioHub] health checks: %d endpoints' % checked, xbmc.LOGDEBUG)
            except Exception as exc:
                xbmc.log('[NuvioHub] health check failed: %s' % exc, xbmc.LOGWARNING)
            _last_health = now

        # Cache cleanup every hour
        if not deferred and now - _last_purge >= 3600:
            try:
                _purge_http_cache()
            except Exception:
                pass
            _last_purge = now

        if not deferred:
            _publish_core_props(_win().getProperty('nuviohub.core.trakt.last_sync') if _win() else '')
        # If the user is browsing/playing or the cloud cycle owns the lock,
        # retry gently in one minute. A completed cycle follows the normal
        # account interval (30 minutes by default).
        wait_seconds = 60.0 if deferred else (_sync_interval_ms() / 1000.0)
        if monitor.waitForAbort(wait_seconds):
            break


def _autodetect_language_first_run():
    """Pin the Nuvio Hub interface to English on first start/update.

    Subtitle preferences are deliberately left untouched: removing the Arabic
    UI must not remove the user's ability to play media or subtitles in any
    language.
    """
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon('plugin.video.nuviohub')
        if (addon.getSetting('ui_language') or '').strip() != 'English':
            addon.setSetting('ui_language', 'English')
        addon.setSetting('ui_lang_autodetected', 'true')
        xbmc.log('[NuvioHub] English-only UI language applied', xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NuvioHub] English UI language migration failed: %s' % exc, xbmc.LOGWARNING)


def _migrate_performance_defaults():
    """Move untouched legacy timeouts to the faster 3.9.242 defaults.

    Explicit user choices are preserved.  Kodi stores defaults as literal
    values, so the old 35/12 pair is a reliable signal that the user did not
    customise them.  A sentinel makes this a one-time operation.
    """
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon('plugin.video.nuviohub')
        if (addon.getSetting('perf_defaults_39242') or '').strip() == '1':
            return
        ceiling = (addon.getSetting('search_ceiling_seconds') or '').strip()
        lookup = (addon.getSetting('server_lookup_seconds') or '').strip()
        if ceiling in ('', '35', '35.0'):
            addon.setSetting('search_ceiling_seconds', '12')
        if lookup in ('', '12', '12.0'):
            addon.setSetting('server_lookup_seconds', '7')
        addon.setSetting('perf_defaults_39242', '1')
        xbmc.log('[NuvioHub] migrated untouched search defaults to 12s/7s', xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NuvioHub] performance-default migration failed: %s' % exc,
                 xbmc.LOGDEBUG)


def _migrate_subtitle_broker_defaults():
    """Enable Stremio subtitle discovery once for existing installations.

    v3.9.243 separates subtitle discovery from auto-showing subtitles.  The
    broker may search all installed Stremio subtitle addons while Play only
    remains selected, so enabling discovery no longer forces a subtitle on.
    Users can still turn the broker off afterwards.
    """
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon('plugin.video.nuviohub')
        if (addon.getSetting('subtitle_defaults_39243') or '').strip() == '1':
            return
        addon.setSetting('enable_stremio_subtitle_broker', 'true')
        addon.setSetting('subtitle_defaults_39243', '1')
        xbmc.log('[NuvioHub] enabled parallel Stremio subtitle discovery', xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NuvioHub] subtitle-default migration failed: %s' % exc, xbmc.LOGDEBUG)


def _migrate_legacy_brand_settings():
    """Carry hidden migration sentinels forward from pre-rename profiles."""
    try:
        import xbmcaddon
        from resources.lib import legacy_names
        from resources.lib.nuviohub.common import profile_path
        legacy_names.carry_forward(xbmcaddon.Addon('plugin.video.nuviohub'), profile_path())
    except Exception as exc:
        xbmc.log('[NuvioHub] legacy brand-settings migration failed: %s' % exc, xbmc.LOGDEBUG)


def _migrate_v510_light_defaults():
    """One-time production profile requested for speed and stability.

    The settings remain readable for backward compatibility, but costly
    experimental features are disabled and no longer exposed in the normal
    settings UI.  Account links, provider lists, quality choices and user data
    are untouched.
    """
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon('plugin.video.nuviohub')
        if (addon.getSetting('nuviohub_v510_defaults_applied') or '').strip().lower() == 'true':
            return
        try:
            revision = int((addon.getSetting('nuviohub_defaults_rev') or '0').strip())
        except Exception:
            revision = 0
        if revision >= 510:
            addon.setSetting('nuviohub_v510_defaults_applied', 'true')
            return
        # v5.4.1: this migration force-wrote every value below into existing
        # installs — including two the user had deliberately turned ON:
        # image badges (after several sessions spent getting community badge
        # sets working) and continuous sync. Silently reversing a choice the
        # user made is the same fault the clean_catalog_view migration had.
        # Performance defaults still apply to installs that never touched
        # them; anything the user has expressed an opinion on is left alone.
        values = {
            'lightweight_mode': 'true',
            'pre_cache_next_episode': 'false',
            'deep_meta_enrich': 'false',
            'fanarttv_enrich': 'false',
            'streams_full_parallel_scan': 'false',
            'show_playback_waiter': 'false',
            'safe_playback_handoff': 'true',
            'kodi22_minimal_item': 'true',
            'tmdbh_auto_play_first': 'false',
            'parallel_workers': '4',
            'trakt_service_sync_interval': '30',
            'http_gzip': 'true',
        }
        # Features the user opts into keep whatever they already are.
        for key, value in values.items():
            addon.setSetting(key, value)
        addon.setSetting('nuviohub_v510_defaults_applied', 'true')
        xbmc.log('[NuvioHub] applied v5.1 light production defaults', xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NuvioHub] v5.1 defaults migration failed: %s' % exc,
                 xbmc.LOGDEBUG)


def _migrate_v520_search_defaults():
    """Move untouched v5.1 timing values to the v5.2 source/subtitle policy."""
    try:
        import xbmcaddon
        addon = xbmcaddon.Addon('plugin.video.nuviohub')
        if (addon.getSetting('nuviohub_v520_defaults_applied') or '').strip().lower() == 'true':
            return
        try:
            revision = int((addon.getSetting('nuviohub_defaults_rev') or '0').strip())
        except Exception:
            revision = 0
        if revision >= 520:
            addon.setSetting('nuviohub_v520_defaults_applied', 'true')
            return
        subtitle = (addon.getSetting('subtitle_timeout') or '').strip()
        # Every old supported value is outside the new safe range. Move it to
        # the requested midpoint; values already in 10..20 are user choices.
        try:
            subtitle_value = int(float(subtitle)) if subtitle else 0
        except Exception:
            subtitle_value = 0
        if subtitle_value < 10 or subtitle_value > 20:
            addon.setSetting('subtitle_timeout', '15')
        quick = (addon.getSetting('streams_quick_open_seconds') or '').strip()
        patient = (addon.getSetting('streams_enough_wait_seconds') or '').strip()
        if quick in ('', '0.8', '0.80'):
            addon.setSetting('streams_quick_open_seconds', '0.4')
        if patient in ('', '5', '5.0'):
            addon.setSetting('streams_enough_wait_seconds', '8')
        # This is a permanent safe default (see apply_clean_defaults_once).
        addon.setSetting('clean_catalog_view', 'false')
        addon.setSetting('nuviohub_v520_defaults_applied', 'true')
        xbmc.log('[NuvioHub] applied v5.2 source/subtitle timing defaults', xbmc.LOGINFO)
    except Exception as exc:
        xbmc.log('[NuvioHub] v5.2 defaults migration failed: %s' % exc,
                 xbmc.LOGDEBUG)


if __name__ == '__main__':
    xbmc.log('[NuvioHub] companion service started', xbmc.LOGINFO)
    _migrate_legacy_brand_settings()
    try:
        import xbmcaddon as _xa_trailers
        from resources.lib.imdb_trailers import migrate_defaults as _trailer_defaults
        _trailer_defaults(_xa_trailers.Addon('plugin.video.nuviohub'))  # 6.0.27: IMDb, trailers on
    except Exception as exc:
        xbmc.log('[NuvioHub] trailer default migration skipped: %s' % exc, xbmc.LOGDEBUG)
    # v3.9.71: log Kodi version on startup so platform-specific issues
    # (e.g. deprecated API native crashes on Kodi 22 alpha) are easy to
    # correlate with bug reports.
    try:
        xbmc.log('[NuvioHub] platform: Kodi %s' % (xbmc.getInfoLabel('System.BuildVersion') or '?'),
                 xbmc.LOGINFO)
    except Exception:
        pass

    # New profiles use resources/settings.xml defaults. Existing profiles retain
    # every saved choice; upstream baseline migrations must not reset an update.
    # English initialization is handled once by ensure_profile above.

    # Publish the skin-aware theme palette early so every NuvioHub dialog
    # (sources, loading, wait, select) inherits the active skin's accent
    # the moment it opens, regardless of open order.
    pass  # Presentation is owned by the independent Nuvio skin.

    try:
        from resources.lib import tmdbh_player
        tmdbh_player.ensure_installed_once()
    except Exception as exc:
        xbmc.log('[NuvioHub] tmdbh player auto-install failed: %s' % exc, xbmc.LOGWARNING)

    _publish_core_props('')
    _publish_badge_props()
    from resources.lib import art_cache
    art_cache.start()

    # v3.9.24: launch the local poster proxy. Inspired by Plexio's
    # /proxy/{token} pattern, this gives us a single-URL handle to every
    # poster image that transparently falls back from decorated → clean
    # if the upstream decoration service is slow/dead. Critically it
    # works on skins that don't honour Kodi's poster→thumb fallback
    # chain (Estuary, Confluence, much of the community-skin field).
    _lightweight = (_setting('lightweight_mode', 'true') or 'true').strip().lower() in ('true', '1', 'yes', 'on')
    if not _lightweight:
        try:
            from resources.lib import poster_proxy as _poster_proxy
            _poster_proxy.start()
        except Exception as exc:
            xbmc.log('[NuvioHub] poster-proxy not started: %s' % exc, xbmc.LOGWARNING)
    else:
        xbmc.log('[NuvioHub] Lightweight Mode — poster proxy skipped', xbmc.LOGINFO)

    # v3.9.27: launch the library-index sync scheduler. Runs the first
    # sync 30s after Kodi boot, then every `index_sync_interval_hours`.
    # Activated only when the user has enabled hybrid/fast mode — in
    # 'live' mode the sync still runs to keep the index warm in case
    # the user toggles modes later, but we skip the first-boot sync to
    # avoid wasting bandwidth on someone who isn't using the feature.
    #
    # v3.9.37: Lightweight Mode disables the index scheduler entirely.
    # The user opted out of aggregated buckets, so there is nothing to
    # index — running the scheduler would only waste CPU and bandwidth.
    if _lightweight:
        xbmc.log('[NuvioHub] Lightweight Mode enabled — index scheduler skipped', xbmc.LOGINFO)
    else:
        try:
            from resources.lib import index_render as _idx_render
            from resources.lib.nuviohub import sync_engine as _sync_eng
            _idx_db = _idx_render.get_db()

            def _pinned_provider():
                # Late-import plugin (heavy module) only when actually needed.
                try:
                    from resources.lib import plugin as _plg
                    return _plg._hub_catalog_entries(bucket=None) or []
                except Exception as exc:
                    xbmc.log('[NuvioHub] sync pinned-provider failed: %s' % exc,
                             xbmc.LOGWARNING)
                    return []

            # v3.9.29: toast progress so the user knows the initial 5-15min
            # library sync is actually doing something. Throttled — only
            # fires on start/done and every 5 catalogs in between, never
            # spamming. Stays silent during scheduled background syncs (the
            # 4-hour periodic run) so it doesn't interrupt watching.
            _sync_progress_state = {'last_toast_at': 0, 'total': 0,
                                     'started_at': 0}

            def _on_sync_progress(stage, info):
                try:
                    import xbmcgui as _xg
                    now = time.time()
                    if stage == 'start':
                        _sync_progress_state['total'] = info.get('total') or 0
                        _sync_progress_state['started_at'] = now
                        _sync_progress_state['last_toast_at'] = now
                        if (info.get('total') or 0) > 0:
                            _xg.Dialog().notification(
                                'Nuvio Hub',
                                tr('Starting library sync (%d catalogs)') % info['total'],
                                _xg.NOTIFICATION_INFO, 2500, sound=False,
                            )
                    elif stage == 'catalog':
                        idx = info.get('index') or 0
                        total = info.get('total') or 0
                        # Throttle: every 5 catalogs, OR at least 4s since
                        # last toast — whichever is less frequent.
                        if total > 0 and (idx % 5 == 0 or idx == total) \
                           and (now - _sync_progress_state['last_toast_at']) >= 4:
                            _sync_progress_state['last_toast_at'] = now
                            _xg.Dialog().notification(
                                'Nuvio Hub',
                                '%d / %d  •  %s' % (
                                    idx, total,
                                    info.get('catalog') or info.get('bucket') or ''),
                                _xg.NOTIFICATION_INFO, 2000, sound=False,
                            )
                    elif stage == 'done':
                        elapsed = info.get('duration') or 0
                        ok = info.get('ok') or 0
                        if (info.get('total') or 0) > 0:
                            _xg.Dialog().notification(
                                'Nuvio Hub',
                                tr('Sync finished: %d succeeded in %.0f s') % (ok, elapsed),
                                _xg.NOTIFICATION_INFO, 3500, sound=False,
                            )
                except Exception as exc:
                    xbmc.log('[NuvioHub] sync progress toast failed: %s' % exc,
                             xbmc.LOGDEBUG)

            _idx_engine = _sync_eng.SyncEngine(
                _idx_db,
                pinned_entries_provider=_pinned_provider,
                on_progress=_on_sync_progress,
            )

            def _interval_hours():
                try:
                    raw = _setting('index_sync_interval_hours', '4') or '4'
                    return int(float(raw))
                except Exception:
                    return 4

            import threading as _thr
            _thr.Thread(
                target=_sync_eng.run_scheduler,
                args=(_idx_engine, xbmc.Monitor()),
                kwargs={'get_interval_hours': _interval_hours},
                name='NuvioHub-index-scheduler', daemon=True,
            ).start()
            xbmc.log('[NuvioHub] library index scheduler started', xbmc.LOGINFO)
        except Exception as exc:
            xbmc.log('[NuvioHub] index scheduler not started: %s' % exc, xbmc.LOGWARNING)

    # Playback monitor is the largest service dependency; load it only after
    # lightweight startup work and optional schedulers are ready.
    from resources.lib.companion import CompanionPlayer, ProgressLoop
    player = CompanionPlayer()
    from resources.lib.seek_profile import restore as restore_seek
    try:restore_seek()
    except Exception:xbmc.log('[Nuvio] Kodi seek migration will retry at next launch',xbmc.LOGWARNING)

    def _stop_owned_preview():
        """Stop a Nuvio trailer preview / screensaver video before the box sleeps.
        A windowed video kept across suspend is a known way to come back with a
        frozen picture on Amlogic boxes; user-started playback is never touched."""
        try:
            home=xbmcgui.Window(10000);token=home.getProperty('nuvio.preview.active')
            player=xbmc.Player()
            if token and player.isPlayingVideo() and player.getPlayingItem().getProperty('nuvio.preview')==token:
                xbmc.executebuiltin('PlayerControl(Stop)')
        except Exception as exc:
            xbmc.log('[NuvioHub] sleep preview stop skipped: %s' % exc, xbmc.LOGDEBUG)

    class _NuvioHubMonitor(xbmc.Monitor):
        def onNotification(self,sender,method,data):
            if sender=='nuvio' and 'artcache.' in method:art_cache.notify(method)
            elif method=='System.OnSleep':_stop_owned_preview()
        def onSettingsChanged(self):
            from resources.lib import settings_cache
            settings_cache.invalidate()

    monitor = _NuvioHubMonitor()

    SYNC_DIRTY_PROP = 'nuviohub.sync_dirty'

    def _cloud_sync_loop(mon):
        """Infrequent, idle-only configuration/library work; progress has its own loop."""
        from resources.lib.nuviohub import nuvio_stremio_sync as sync
        if mon.waitForAbort(30):return
        next_run = time.monotonic()
        while not mon.abortRequested():
            try:interval=max(0, int(float(_setting('cloud_sync_interval_min', '30') or 30)))
            except (ValueError, TypeError):interval=30
            if interval and time.monotonic()>=next_run and not _interactive_busy() and sync.enabled_targets():
                if _SYNC_CYCLE_LOCK.acquire(False):
                    try:
                        sections=sync._sections_for('nuvio')
                        # Home collection replacements always go through explicit validation/import.
                        sections.update(progress=False, collections=False)
                        if sections.get('addons') or sections.get('library'):
                            sync.run_sync(targets=['nuvio'], sections=sections)
                    except Exception:
                        pass
                    finally:
                        next_run=time.monotonic()+max(300, interval*60)
                        _SYNC_CYCLE_LOCK.release()
            if mon.waitForAbort(15):return


    def _bytecode_warm_job():
        # v5.4.7: pre-compile the addon tree to __pycache__ so the user's
        # first click after install/update pays warm-import cost only
        # (~0.5s ARM32) instead of full byte-compilation (~4-6s ARM32).
        # 20s boot delay keeps us out of Kodi's own startup CPU window;
        # after the first pass this is a stat-only sweep in milliseconds.
        try:
            if monitor.waitForAbort(20):
                return
            from bytecode_warm import warm
            addon_root = os.path.dirname(os.path.abspath(__file__))
            checked, compiled = warm(addon_root, monitor=monitor)
            if compiled:
                xbmc.log('[NuvioHub] bytecode warm: compiled %d/%d files'
                         % (compiled, checked), xbmc.LOGDEBUG)
        except Exception as exc:
            xbmc.log('[NuvioHub] bytecode warm skipped: %s' % exc, xbmc.LOGDEBUG)

    def _update_loop(mon):
        """GitHub release check every 12 h; installs when automatic updates are ON."""
        from resources.lib import updater
        updater.boot_token()  # this Kodi session; a pending restart from an older one is cleared
        if mon.waitForAbort(90):return
        while not mon.abortRequested():
            try:
                import xbmcaddon as _xa
                _addon = _xa.Addon('plugin.video.nuviohub')
                if updater.due(_addon) and not _interactive_busy():
                    status, info = updater.check_and_update(_addon)
                    if status == 'installed':
                        # Ask "restart now?" only when no video plays and Nuvio is
                        # closed; "Later" reminds again at the next Nuvio entry.
                        if updater.prompt_when_safe(_addon, mon):return
                    elif status == 'available':
                        xbmcgui.Dialog().notification('Nuvio Hub', '%s is available: Settings > Maintenance.' % info['version'], time=8000)
            except Exception as exc:
                xbmc.log('[NuvioHub] update check skipped: %s' % exc, xbmc.LOGDEBUG)
            if mon.waitForAbort(600):return

    def _component_sync(mon):
        # 6.0.23: no manual "Install or repair" after an update.
        try:
            from resources.lib.bundle_installer import auto_install
            auto_install(mon, busy=_interactive_busy)
        except Exception as exc:
            xbmc.log('[NuvioHub] automatic component install skipped: %s' % exc, xbmc.LOGWARNING)
        # 6.0.33: Kodi started without the MegaNexus skin the user chose.
        try:
            from resources.lib.skin_activation import restore_on_start
            restore_on_start(mon, busy=_interactive_busy)
        except Exception as exc:
            xbmc.log('[NuvioHub] skin check skipped: %s' % exc, xbmc.LOGWARNING)

    try:
        import threading as _thr_upd
        _thr_upd.Thread(target=_component_sync, args=(monitor,), name='NuvioHubComponents', daemon=True).start()
        _thr_upd.Thread(target=_update_loop, args=(monitor,), name='NuvioHubUpdates', daemon=True).start()
    except Exception as exc:
        xbmc.log('[NuvioHub] update checks not started: %s' % exc, xbmc.LOGWARNING)

    try:
        import threading as _thr
        _thr.Thread(target=_background_sync_loop, args=(monitor,), name='NuvioHubCoreLoop', daemon=True).start()
        _thr.Thread(target=_cloud_sync_loop, args=(monitor,), name='NuvioHubCloudLoop', daemon=True).start()

        from resources.lib.progress_sync import run as _progress_sync_run
        _thr.Thread(target=_progress_sync_run, args=(monitor, _SYNC_CYCLE_LOCK), name='NuvioProgressSync', daemon=True).start()
        _thr.Thread(target=_bytecode_warm_job, name='NuvioHubBytecodeWarm', daemon=True).start()
        from resources.lib.skip_service import run as _skip_run
        _thr.Thread(target=_skip_run, args=(player, monitor), name='NuvioHubSkip', daemon=True).start()
    except Exception as exc:
        xbmc.log('[NuvioHub] could not spawn core sync thread: %s' % exc, xbmc.LOGWARNING)
    try:
        from resources.lib.presentation_settings import sync as sync_appearance
        sync_appearance()
    except Exception:
        xbmc.log('[Nuvio] Appearance preference will be restored when the interface opens.', xbmc.LOGWARNING)
    try:
        ProgressLoop(player).run()
    finally:
        art_cache.stop()
        # Clean shutdown of the poster proxy thread when Kodi tears the
        # service down. Errors here are non-fatal — daemon threads die
        # with the process anyway, but explicit cleanup is hygienic.
        try:
            from resources.lib import poster_proxy as _poster_proxy
            _poster_proxy.stop()
        except Exception:
            pass
