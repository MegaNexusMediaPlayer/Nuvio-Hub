# -*- coding: utf-8 -*-
"""O(1) dispatch for high-frequency routes.

The legacy dispatcher remains as a compatibility fallback. New routes should
be added here so plugin.py can shrink incrementally without changing Kodi URLs.
"""
_NOT_HANDLED = object()


def dispatch(action, params, api):
    p = params.get
    if action == 'search':
        return api.search(p('media_type', 'movie'), p('provider_id'), query=p('query', ''))
    if action == 'setup_center': return api.setup_center()
    if action == 'setup_playback': return api.setup_playback()
    if action == 'setup_subtitles': return api.setup_subtitles()
    if action == 'setup_quality': return api.setup_quality()
    if action == 'setup_stability': return api.setup_stability()
    if action == 'setup_diagnostics': return api.setup_diagnostics()
    if action == 'emby_menu': return api.emby_menu()
    if action == 'emby_login': return api.emby_login()
    if action == 'emby_logout': return api.emby_logout()
    if action == 'emby_continue': return api.emby_continue()
    if action == 'emby_library':
        return api.emby_library(p('key', ''), title=p('title', ''), library_type=p('library_type', ''), start=p('start', '0'), sort=p('sort', ''))
    if action == 'emby_children': return api.emby_children(p('key', ''), title=p('title', ''), start=p('start', '0'))
    if action == 'emby_play': return api.emby_play(p('item_id', ''))
    if action == 'plex_menu': return api.plex_menu()
    if action == 'plex_login': return api.plex_login()
    if action == 'plex_logout': return api.plex_logout()
    if action == 'plex_refresh': return api.plex_refresh()
    if action == 'plex_servers': return api.plex_servers()
    if action == 'plex_server': return api.plex_server(p('server_id', ''))
    if action == 'plex_continue': return api.plex_continue(p('server_id', ''))
    if action == 'plex_library':
        return api.plex_library(p('server_id', ''), p('key', ''), title=p('title', ''), library_type=p('library_type', ''), start=p('start', '0'), sort=p('sort', ''))
    if action == 'plex_children': return api.plex_children(p('server_id', ''), p('key', ''), title=p('title', ''), start=p('start', '0'))
    if action == 'plex_search': return api.plex_search(p('server_id', ''))
    if action == 'plex_play': return api.plex_play(p('server_id', ''), p('rating_key', ''))
    if action == 'switch_source': return api.switch_source()
    if action == 'nuvio_login': return api._cloud_login('nuvio')
    if action == 'nuvio_qr_login': return api._cloud_qr_login('nuvio')
    if action == 'stremio_qr_login': return api._cloud_qr_login('stremio')
    if action == 'nuvio_logout': return api._cloud_logout('nuvio')
    if action == 'stremio_login': return api._cloud_login('stremio')
    if action == 'stremio_logout': return api._cloud_logout('stremio')
    if action == 'cloud_sync_now': return api.cloud_sync_now()
    return _NOT_HANDLED
