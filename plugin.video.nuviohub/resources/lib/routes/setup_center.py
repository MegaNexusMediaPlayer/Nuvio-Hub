# -*- coding: utf-8 -*-
"""Small, task-oriented setup front door for Nuvio Hub.

Kodi's native settings window remains available for advanced users, but it is
not a friendly first stop on a television.  This module groups the handful of
choices that materially change day-to-day use into short remote-friendly
dialogs.  It deliberately never enables automatic source playback without a
separate confirmation.
"""


def _setting(addon, key, default=''):
    try:
        value = addon.getSetting(key)
    except Exception:
        value = ''
    return str(value if value not in (None, '') else default)


def _set_many(addon, values):
    for key, value in values.items():
        addon.setSetting(str(key), str(value))


def _provider_count(api):
    try:
        return len(api.store.list_providers() or [])
    except Exception:
        return 0


def _manual_source_mode(addon):
    return _setting(
        addon, 'playback_open_mode', 'Choose from sources'
    ).strip().lower() != 'best quality automatically'


def status_text(api):
    """Return a compact, privacy-safe configuration summary."""
    addon = api.ADDON
    source_mode = (
        api.tr('Manual add-on choice') if _manual_source_mode(addon)
        else api.tr('Play best quality automatically')
    )
    subtitle_mode = _setting(addon, 'subtitle_search_mode', 'Play only')
    subtitle_label = (
        api.tr('On request') if subtitle_mode.strip().lower() == 'play only'
        else api.tr('During playback')
    )
    try:
        timeout = max(10, min(20, int(float(
            _setting(addon, 'subtitle_timeout', '15')))))
    except Exception:
        timeout = 15
    return api.tr('%d add-on(s) - %s - subtitles %s (%d seconds)') % (
        _provider_count(api), source_mode, subtitle_label, timeout)


def render(api):
    """Render the simple setup centre as a normal Kodi directory."""
    add = api.add_item
    url = api.build_url
    art = api.root_art

    add(api.tr('Status - %s') % status_text(api),
        url(action='setup_diagnostics'), is_folder=False,
        art=art('settings'),
        info={'title': api.tr('Setup status'),
              'plot': api.tr('A quick summary without exposing keys or private data.')})
    add(api.tr('Quick start'), url(action='first_run_wizard'),
        art=art('add'),
        info={'title': api.tr('Quick start'),
              'plot': api.tr('Choose only Nuvio, Stremio, or manual setup.')})
    add(api.tr('Add-ons'), url(action='providers'), art=art('providers'),
        info={'title': api.tr('Add-ons'),
              'plot': api.tr('Add and order add-ons, and manage linked accounts.')})
    add(api.tr('Playback method'), url(action='setup_playback'),
        is_folder=False, art=art('play'),
        info={'title': api.tr('Playback method'),
              'plot': api.tr('Manual choice is recommended. Automatic playback needs a separate confirmation.')})
    add(api.tr('Subtitles'), url(action='setup_subtitles'),
        is_folder=False, art=art('subtitles'),
        info={'title': api.tr('Subtitles'),
              'plot': api.tr('Subtitle mode and one shared 10 to 20 second search window.')})
    add(api.tr('Quality'), url(action='setup_quality'),
        is_folder=False, art=art('catalogs'),
        info={'title': api.tr('Quality'),
              'plot': api.tr('Ready profiles: balanced, best quality, or data saver.')})
    add(api.tr('Appearance'), url(action='theme_select'),
        is_folder=False, art=art('settings'),
        info={'title': api.tr('Appearance'),
              'plot': api.tr('Choose a quiet theme with a colour preview.')})
    add(api.tr('Accounts and libraries'), url(action='integrations_menu'),
        art=art('sync'),
        info={'title': api.tr('Accounts and libraries'),
              'plot': api.tr('Nuvio, Stremio, Trakt, Plex, Emby, and other integrations.')})
    add(api.tr('Stability for low-power devices'), url(action='setup_stability'),
        is_folder=False, art=art('settings'),
        info={'title': api.tr('Stability for low-power devices'),
              'plot': api.tr('Stops heavy background work and optional windows without deleting any add-on.')})
    add(api.tr('Advanced settings'), url(action='open_settings'),
        is_folder=False, art=art('settings'),
        info={'title': api.tr('Advanced settings'),
              'plot': api.tr('All detailed options in Kodi settings.')})
    return api.end_dir(content='files', cache=False)


def playback(api):
    labels = [
        api.tr('Choose a add-on every time (recommended)'),
        api.tr('Use the same add-on only'),
        api.tr('Choose through TMDb Helper'),
        api.tr('Play best quality automatically'),
    ]
    idx = api.xbmcgui.Dialog().select(api.tr('Playback method'), labels)
    if idx < 0:
        return False
    if idx == 3:
        confirmed = api.xbmcgui.Dialog().yesno(
            api.tr('Confirm automatic playback'),
            api.tr('The best source will start directly without a picker. Enable this?'),
        )
        if not confirmed:
            return False
        _set_many(api.ADDON, {
            'source_resolution_mode': 'NuvioHub picker',
            'playback_open_mode': 'Best quality automatically',
            'remember_last_source': 'false',
        })
    else:
        resolution = ('NuvioHub picker', 'Same source', 'TMDb Helper')[idx]
        _set_many(api.ADDON, {
            'source_resolution_mode': resolution,
            'playback_open_mode': 'Choose from sources',
            'remember_last_source': 'false',
        })
    api.notify(api.tr('Playback method saved'))
    return True


def subtitles(api):
    mode_labels = [
        api.tr('Play only; subtitles on request'),
        api.tr('Play with subtitles'),
    ]
    mode_idx = api.xbmcgui.Dialog().select(api.tr('Subtitle mode'), mode_labels)
    if mode_idx < 0:
        return False
    timeout_labels = [
        api.tr('10 seconds'), api.tr('15 seconds (recommended)'), api.tr('20 seconds')
    ]
    timeout_idx = api.xbmcgui.Dialog().select(
        api.tr('Shared search window'), timeout_labels)
    if timeout_idx < 0:
        return False
    _set_many(api.ADDON, {
        'subtitle_search_mode': (
            'Play only' if mode_idx == 0 else 'Play with subtitles'),
        'subtitle_timeout': ('10', '15', '20')[timeout_idx],
    })
    api.notify(api.tr('Subtitle setup saved'))
    return True


def quality(api):
    values = (
        'Balanced (recommended)', 'Best', 'Data saver', 'Custom'
    )
    labels = [
        api.tr('Balanced (recommended)'), api.tr('Best quality'),
        api.tr('Data saver'), api.tr('Custom'),
    ]
    idx = api.xbmcgui.Dialog().select(api.tr('Quality profile'), labels)
    if idx < 0:
        return False
    api.ADDON.setSetting('quality_profile', values[idx])
    api.notify(api.tr('Quality profile saved'))
    if idx == 3:
        api.open_settings_action()
    return True


def stability(api):
    confirmed = api.xbmcgui.Dialog().yesno(
        api.tr('Stability for low-power devices'),
        api.tr('Enable lightweight mode and turn off the wait window, next-episode pre-cache, and heavy parallel work?'),
    )
    if not confirmed:
        return False
    _set_many(api.ADDON, {
        'lightweight_mode': 'true',
        'show_playback_waiter': 'false',
        'pre_cache_next_episode': 'false',
        'streams_full_parallel_scan': 'false',
        'elite_badges_enabled': 'false',
        'verbose_logging': 'false',
    })
    api.notify(api.tr('Stability setup enabled'))
    return True


def diagnostics(api):
    try:
        from ..runtime_tasks import active_count
        optional_jobs = active_count()
    except Exception:
        optional_jobs = 0
    details = [
        api.tr('Version: %s') % api.ADDON.getAddonInfo('version'),
        api.tr('Add-ons: %d') % _provider_count(api),
        api.tr('Optional background jobs: %d') % int(optional_jobs),
        api.tr('Mode: manual choice') if _manual_source_mode(api.ADDON)
        else api.tr('Mode: automatic playback'),
        api.tr('Next-episode pre-cache: off')
        if _setting(api.ADDON, 'pre_cache_next_episode', 'false').lower() != 'true'
        else api.tr('Next-episode pre-cache: on'),
    ]
    api.xbmcgui.Dialog().ok(api.tr('Nuvio Hub status'), '\n'.join(details))
    return True
