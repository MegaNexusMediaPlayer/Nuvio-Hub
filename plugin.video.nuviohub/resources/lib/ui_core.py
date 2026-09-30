# -*- coding: utf-8 -*-
"""UI foundation layer — extracted from plugin.py (v3.9.264 decomposition).

The listing primitives every route builds on: directory item construction,
directory finalization, id-seed merging, small prompts. Functions unchanged;
plugin.py re-exports every name so all call sites keep working.
"""
import json
import os
import sys
import urllib.parse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from .i18n import tr

# --- dexhub-401-patch ---
try:
    from .settings_cache import cached_addon as _dh_cached_addon
except Exception:
    try:
        from settings_cache import cached_addon as _dh_cached_addon
    except Exception:
        _dh_cached_addon = None
ADDON = _dh_cached_addon() if _dh_cached_addon else xbmcaddon.Addon('plugin.video.nuviohub')
ADDON_ID = ADDON.getAddonInfo('id')
try:
    HANDLE = int(__import__('sys').argv[1]) if len(__import__('sys').argv) > 1 else -1
except Exception:
    HANDLE = -1


from .art import addon_fanart
from .context import WINDOW_ID, MULTI_WS_RE, _get_int_setting


def _plugin():
    """Late accessor for plugin.py (circular-safe)."""
    from . import plugin as _p
    return _p


def _apply_sort_methods(*a, **k):
    return _plugin()._apply_sort_methods(*a, **k)

def _apply_unique_ids(*a, **k):
    return _plugin()._apply_unique_ids(*a, **k)

def _favorite_properties(*a, **k):
    return _plugin()._favorite_properties(*a, **k)

def _flush_pending_items(*a, **k):
    return _plugin()._flush_pending_items(*a, **k)

def _normalize_kodi_item_art(*a, **k):
    return _plugin()._normalize_kodi_item_art(*a, **k)

def _videoinfotag_apply(*a, **k):
    return _plugin()._videoinfotag_apply(*a, **k)


def _profile_path():
    try:
        path = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    except Exception:
        path = ''
    if path:
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
    return path or xbmcvfs.translatePath('special://profile/addon_data/plugin.video.nuviohub/')


def _listing_page_size():
    return _get_int_setting('large_section_limit', 30, minimum=12, maximum=60)


def add_item(label, path, is_folder=True, info=None, art=None, properties=None, label2=None, ids=None, context_menu=None, is_favorite=None, cast=None):
    label = tr(label)
    label2 = tr(label2 or '') if label2 else ''
    item = xbmcgui.ListItem(label=label, label2=label2)
    art = _normalize_kodi_item_art(art)
    info = dict(info or {})
    for _k in ('title', 'plot', 'genre', 'tagline', 'status'):
        if isinstance(info.get(_k), str):
            info[_k] = tr(info.get(_k))
    # Pull cast out of info if caller stuffed it there (legacy callers do this).
    if cast is None and isinstance(info.get('cast'), list):
        cast = info.pop('cast')
    _apply_unique_ids(item, ids, info)
    used_videoinfotag = False
    if _plugin()._KODI_MAJOR >= 20 and info:
        used_videoinfotag = _videoinfotag_apply(item, info, ids=ids, cast=cast)
    if info and not used_videoinfotag:
        try:
            item.setInfo('video', info)
        except Exception:
            pass
    if art:
        try:
            item.setArt(art)
        except Exception:
            pass
        if _plugin()._KODI_MAJOR >= 20:
            try:
                item.getVideoInfoTag(offscreen=True).setArtwork({k: v for k, v in (art or {}).items() if v})
            except Exception:
                pass
    fanart_image = (art or {}).get('fanart') or (art or {}).get('landscape') or (art or {}).get('poster') or addon_fanart()
    props = {'fanart_image': fanart_image}
    if ids:
        try:
            if ids.get('tmdb_id'):
                props['tmdb_id'] = str(ids.get('tmdb_id'))
            if ids.get('imdb_id'):
                props['imdb_id'] = str(ids.get('imdb_id'))
                props['imdb'] = str(ids.get('imdb_id'))
                props['IMDBNumber'] = str(ids.get('imdb_id'))
            if ids.get('tvdb_id'):
                props['tvdb_id'] = str(ids.get('tvdb_id'))
            mt_info = str((info or {}).get('mediatype') or '').lower()
            props['tmdb_type'] = 'tv' if mt_info in ('tvshow', 'season', 'episode') else 'movie'
        except Exception:
            pass
    try:
        if (not is_folder) and 'action=play_item' in str(path or ''):
            props.setdefault('IsPlayable', 'true')
    except Exception:
        pass
    if art:
        for art_key in ('clearlogo', 'logo', 'tvshow.clearlogo', 'clearart', 'landscape', 'banner', 'poster', 'tvshow.poster', 'season.poster', 'thumb', 'icon', 'thumbnail', 'cover', 'image', 'tvshow.thumb', 'fanart'):
            if art.get(art_key):
                props[art_key] = art.get(art_key)
    props.update(_favorite_properties(is_favorite))
    if properties:
        props.update(properties)
    try:
        item.setProperties(props)
    except Exception:
        pass
    if context_menu:
        try:
            # replaceItems=True so we OWN the menu. Previously False appended
            # to Kodi's defaults, which on some skins (Aura, Arctic Fuse,
            # Estuary MOD) injects a built-in 'Add to favourites' that the
            # skin then renders as a persistent heart overlay on EVERY
            # poster — making the heart meaningless as a "this is favourited"
            # marker. Replacing the menu also gives us full control over
            # the available actions.
            item.addContextMenuItems([(tr(lbl), act) for (lbl, act) in list(context_menu)], replaceItems=True)
        except Exception:
            pass
    _plugin()._PENDING_ITEMS.append((path, item, is_folder))


def _infer_content_type():
    """Infer Kodi content from the active route when a caller omitted it."""
    try:
        raw = sys.argv[2] if len(sys.argv) > 2 else ''
        params = dict(urllib.parse.parse_qsl(str(raw or '').lstrip('?'), keep_blank_values=True))
    except Exception:
        params = {}
    action = str(params.get('action') or '').strip().lower()
    media_type = str(params.get('media_type') or params.get('type') or '').strip().lower()
    bucket = str(params.get('bucket') or '').strip().lower()

    if action in {
            'episodes', 'nextup', 'next_up', 'calendar', 'plex_on_deck',
            'emby_nextup', 'emby_continue', 'simkl_continue'}:
        return 'episodes'
    if action in {'seasons', 'series_meta', 'show_seasons'}:
        return 'seasons'
    if action in {
            'continue', 'favorites', 'hub_search_menu', 'search_from_history',
            'people_search',
            'mdblist_watchlist_browse'}:
        return 'videos'

    if media_type in ('episode', 'episodes'):
        return 'episodes'
    if media_type in ('season', 'seasons'):
        return 'seasons'
    if media_type in ('series', 'show', 'shows', 'tv', 'tvshow', 'anime'):
        return 'tvshows'
    if media_type in ('movie', 'movies'):
        return 'movies'
    if media_type in ('video', 'videos', 'channel', 'channels', 'live', 'all', 'mixed'):
        return 'videos'

    if bucket in ('series', 'anime', 'turkish', 'korean'):
        return 'tvshows'
    if bucket == 'movies':
        return 'movies'
    if bucket in ('live', 'arabic'):
        return 'videos'
    return 'files'


def end_dir(content=None, cache=True, sortable=True):
    resolved_content = str(content or '').strip().lower() or _infer_content_type()
    xbmcplugin.setContent(HANDLE, resolved_content)
    _apply_sort_methods(resolved_content, sortable=sortable)
    _flush_pending_items()
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=cache)


def _merge_seed_ids(base_ids, seed_ids):
    """Non-empty seed IDs win over empty base IDs but never overwrite a resolved value."""
    base_ids = dict(base_ids or {})
    for k, v in (seed_ids or {}).items():
        if v and not base_ids.get(k):
            base_ids[k] = v
    return base_ids


def _get_tmdbh_seed_ids(canonical_id=None):
    """Return seed IDs only when the stash's canonical_id matches (or no canonical filter given)."""
    try:
        win = xbmcgui.Window(WINDOW_ID)
        raw = win.getProperty('dexhub.tmdbh_seed_ids') or ''
        scoped_for = win.getProperty('dexhub.tmdbh_seed_for') or ''
        if not raw:
            return {}
        # If caller specified a canonical_id and the stash was set for a different one, don't leak.
        if canonical_id and scoped_for and scoped_for != canonical_id:
            return {}
        return json.loads(raw) or {}
    except Exception:
        return {}


def _prompt_text(default_text, heading):
    kb = xbmc.Keyboard(default_text or '', tr(heading))
    kb.doModal()
    if not kb.isConfirmed():
        return None
    return (kb.getText() or '').strip()


def _derive_name_from_slug(slug):
    slug = str(slug or '').strip().strip('/')
    if not slug:
        return 'Collection'
    name = slug.replace('-', ' ').replace('_', ' ')
    return MULTI_WS_RE.sub(' ', name).strip().title() or 'Collection'
