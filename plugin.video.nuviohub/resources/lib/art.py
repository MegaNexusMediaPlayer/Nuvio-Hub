# -*- coding: utf-8 -*-
import os
import re
from .log import log

import xbmcaddon

from .tmdbhelper import get_art_bundle_from_db, get_clearlogo_from_db
from .tmdb_direct import art_for as get_tmdb_direct_art

# --- dexhub-401-patch ---
try:
    from .settings_cache import cached_addon as _dh_cached_addon
except Exception:
    try:
        from settings_cache import cached_addon as _dh_cached_addon
    except Exception:
        _dh_cached_addon = None
ADDON = _dh_cached_addon() if _dh_cached_addon else xbmcaddon.Addon('plugin.video.nuviohub')
ADDON_PATH = ADDON.getAddonInfo('path')
MEDIA = 'special://home/addons/script.nuvio/resources/media'


def _setting_text(key, default=''):
    try:
        value = ADDON.getSetting(key)
    except Exception:
        value = default
    return str(value or default).strip()


def poster_source_mode():
    return _setting_text('poster_source_mode', 'Local only')


def posters_prefer_local():
    """Should NuvioHub avoid hitting TMDb/remote sources for artwork?

    Before v3.9.1 this read from `poster_source_mode` directly. That setting
    was confusingly redundant with `default_meta_source` (both controlled
    "where do we get art from?"). We now derive the answer from
    `default_meta_source` first, falling back to the legacy
    `poster_source_mode` if a user had it set.

    Logic:
      default_meta_source = 'Native (addon)'         → True  (don't fetch remote)
      default_meta_source = 'TMDb Helper (...)'      → False (DO fetch remote)
      default_meta_source = 'Auto (smart)' or empty → consult legacy setting
                                                       (or False if unset = new install)
    """
    try:
        import xbmcaddon
        meta_choice = (xbmcaddon.Addon('plugin.video.nuviohub').getSetting('default_meta_source') or '').strip().lower()
    except Exception:
        meta_choice = ''
    if 'native' in meta_choice:
        return True
    if 'tmdb' in meta_choice or 'helper' in meta_choice:
        return False
    # Auto / not set — fall back to legacy setting for backward compatibility
    return str(poster_source_mode() or '').strip().lower() in ('محلي فقط', 'local only', 'local', '0')

ROOT_ICONS = {
    'add':            'root_add.png',
    'providers':      'root_sources.png',
    'search_movie':   'root_search_movie.png',
    'search_series':  'root_search_series.png',
    'continue':       'root_continue.png',
    'catalogs':       'root_catalogs.png',
    'plex':           'provider_plex.png',
    'emby':           'provider_emby.png',
    'jellyfin':       'provider_jellyfin.png',
    'emby_jellyfin':  'provider_emby_jellyfin.png',
    'trakt':          'trakt.png',
    'tmdb':           'tmdb.png',
    'mdblist':        'mdblist.png',
    'simkl':          'simkl.png',
    'stremio':        'stremio.png',
    'kodi':           'kodi.png',
    'settings':       'settings.png',
    'nextup':         'up-next.png',
    'favorites':      'cat_watchlist.png',
    'watchlist':      'cat_watchlist.png',
    'movies':         'cat_movies.png',
    'series':         'cat_series.png',
    'anime':          'cat_anime.png',
    'arabic':         'cat_arabic.png',
    'turkish':        'cat_series.png',
    'korean':         'cat_series.png',
    'live':           'cat_live.png',
    'accounts':       'root_accounts.png',
}

# Screens that get a richer background (used by root_art_with_bg below).
ROOT_BG = {
    'search_movie':  'nuvio_banner.png',
    'search_series': 'nuvio_banner.png',
}


def media_path(name):
    # Legacy backend callers share the new interface's neutral fallback artwork.
    if name not in ('black.png', 'white.png') and not name.startswith('nuvio_'):
        name = 'nuvio_mark.png'
    return os.path.join(MEDIA, name)


def addon_fanart():
    return media_path('nuvio_banner.png')


def neutral_fanart():
    return media_path('black.png')


def _default_poster(media_type='movie'):
    return media_path('default_series_poster.png' if media_type in ('series', 'anime', 'tv', 'show') else 'default_movie_poster.png')


def _clean_art_value(value):
    value = str(value or '').strip()
    if not value or value.lower() in ('none', 'null', 'n/a', '0'):
        return ''
    lower = value.lower()
    if 'manifest bridge' in lower:
        return ''
    # Absolute URL with a supported scheme → always accepted.
    supported = ('http://', 'https://', 'special://', 'image://', 'file://',
                 'plugin://', 'smb://', 'nfs://')
    if lower.startswith(supported):
        return value
    # Relative path beginning with '/' → caller must have a base URL;
    # we return it as-is and let Kodi or the caller prepend the origin.
    if value.startswith('/'):
        return value
    # Bare filename / special:// alias already stripped above.
    # Unknown scheme → reject so Kodi doesn't choke on it.
    if '://' in value:
        return ''
    return value


def _first_art(*values):
    for value in values:
        cleaned = _clean_art_value(value)
        if cleaned:
            return cleaned
    return ''


def _image_dict_art(images, *keys):
    if not isinstance(images, dict):
        return ''
    for key in keys:
        node = images.get(key)
        if isinstance(node, dict):
            value = _first_art(
                node.get('full'), node.get('original'), node.get('large'),
                node.get('medium'), node.get('small'), node.get('thumb'), node.get('url')
            )
        else:
            value = _first_art(node)
        if value:
            return value
    return ''


def root_art(key):
    icon = ROOT_ICONS.get(key, 'provider.png')
    fanart = media_path(ROOT_BG.get(key, 'nuvio_banner.png'))
    logo = media_path(icon)
    # AF3 and other information-heavy skins look at landscape/banner and
    # clearlogo properties to decide which root-folder view to use. Populate
    # the complete artwork contract for every root row; the transparent icon
    # is a safe clearlogo fallback when no dedicated wide wordmark exists.
    return {
        'thumb': logo, 'icon': logo, 'poster': logo,
        'fanart': fanart, 'landscape': fanart, 'banner': fanart,
        'clearlogo': logo, 'tvshow.clearlogo': logo,
        'clearart': logo, 'logo': logo,
    }


def provider_art(name='', manifest=None, base_url=''):
    manifest = manifest or {}
    slug = normalize_name(name)
    fallback_map = (
        ('jellyfin', 'provider_jellyfin.png'),
        ('plex', 'provider_plex.png'),
        ('emby', 'provider_emby.png'),
        ('mdblist', 'mdblist.png'),
        ('simkl', 'simkl.png'),
        ('stremio', 'stremio.png'),
        ('tmdb', 'tmdb.png'),
        ('trakt', 'trakt.png'),
        ('kodi', 'kodi.png'),
    )
    fallback = next((asset for token, asset in fallback_map if token in slug), 'provider.png')
    raw_logo = _first_art(manifest.get('logo'), manifest.get('icon'))

    # CDN / PlexBridge servers sometimes return a relative path for logo
    # (e.g. '/logo.png'). Resolve it against the provider's base URL.
    if raw_logo and raw_logo.startswith('/') and base_url:
        try:
            from urllib.parse import urlparse
            p = urlparse(base_url)
            if p.scheme and p.netloc:
                raw_logo = '%s://%s%s' % (p.scheme, p.netloc, raw_logo)
        except Exception as _silent_exc:
            log.silent('ART', _silent_exc)
    provider_logo = raw_logo or ''
    background = _first_art(
        manifest.get('background'), manifest.get('fanart'), addon_fanart())
    icon = _first_art(provider_logo, media_path(fallback))
    # Pass URL through as-is — Kodi handles http/https icons natively.
    # Do NOT wrap in image:// here (requires full URL-encoding or it breaks icons).
    clearlogo = _first_art(manifest.get('clearlogo'), manifest.get('logo'), icon)
    art = {
        'thumb': icon, 'icon': icon, 'poster': icon, 'fanart': background,
        'landscape': background, 'banner': background,
        'clearlogo': clearlogo, 'tvshow.clearlogo': clearlogo,
        'clearart': clearlogo, 'logo': clearlogo,
    }
    return art


def catalog_art(name='', media_type='movie', manifest=None, catalog=None):
    manifest = manifest or {}
    catalog = catalog or {}
    slug = normalize_name(name)
    icon = _first_art(catalog.get('icon'), catalog.get('logo'))
    fanart = _first_art(catalog.get('background'), catalog.get('fanart'), manifest.get('background'), manifest.get('fanart'), addon_fanart())
    if not icon:
        icon_name = 'cat_series.png' if media_type in ('series', 'anime', 'tv', 'show') else 'cat_movies.png'
        mapping = [
            ('watchlist', 'cat_watchlist.png'),
            ('continue', 'cat_continue.png'),
            ('next up', 'cat_continue.png'),
            ('4k', 'cat_4k.png'),
            ('anime', 'cat_anime.png'),
            ('kids', 'cat_kids.png'),
            ('arabic', 'cat_arabic.png'),
            ('document', 'cat_doc.png'),
            ('doc', 'cat_doc.png'),
            ('collection', 'cat_collection.png'),
            ('search', 'cat_search.png'),
        ]
        for key, value in mapping:
            if key in slug:
                icon_name = value
                break
        icon = media_path(icon_name)
    art = {
        'thumb': icon, 'icon': icon, 'poster': icon, 'fanart': fanart,
        'landscape': fanart, 'banner': fanart,
    }
    # Same rule as provider_art(): keep generic catalog/addon logos as icons only.
    # Clearlogo should be reserved for explicit item-style logo artwork.
    real_clearlogo = _first_art(catalog.get('clearlogo'), manifest.get('clearlogo'))
    clearlogo = real_clearlogo or icon
    art['clearlogo'] = clearlogo
    art['tvshow.clearlogo'] = clearlogo
    art['clearart'] = clearlogo
    art['logo'] = clearlogo
    return art


def normalize_name(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().lower())


def extract_ids(meta):
    raw_id = str(meta.get('id') or '')
    links = meta.get('links') or []
    behavior = meta.get('behaviorHints') or {}
    external = meta.get('externalIds') or {}
    candidates = [raw_id]
    for key in ('imdb_id', 'tmdb_id', 'tvdb_id', 'imdb', 'tmdb', 'tvdb', 'guid', 'external_id',
                'imdbId', 'tmdbId', 'tvdbId', 'anidbId'):  # camelCase (Plexio)
        val = meta.get(key)
        if val:
            candidates.append(str(val))
    if isinstance(external, dict):
        for val in external.values():
            if val:
                candidates.append(str(val))
    if isinstance(behavior, dict):
        for key in ('imdb_id', 'tmdb_id', 'tvdb_id', 'filename'):
            val = behavior.get(key)
            if val:
                candidates.append(str(val))
        ext2 = behavior.get('externalIds') or {}
        if isinstance(ext2, dict):
            for val in ext2.values():
                if val:
                    candidates.append(str(val))
    for link in links:
        if isinstance(link, dict):
            for key in ('name', 'category', 'url', 'externalUrl'):
                val = link.get(key)
                if val:
                    candidates.append(str(val))
        elif link:
            candidates.append(str(link))
    joined = ' '.join(candidates)
    tmdb_id = ''
    imdb_id = ''
    tvdb_id = ''
    raw_lower = raw_id.lower().strip()
    if raw_lower.startswith('tt'):
        imdb_id = raw_id.strip()
    elif raw_lower.startswith('imdb:tt'):
        imdb_id = raw_id.split(':', 1)[-1].strip()
    elif raw_lower.startswith('tmdb:'):
        tail = raw_id.split(':')[-1].strip()
        if tail.isdigit():
            tmdb_id = tail
    elif raw_lower.startswith('tvdb:'):
        tail = raw_id.split(':')[-1].strip()
        if tail.isdigit():
            tvdb_id = tail
    patterns = [
        (r'tmdb(?::(?:movie|series|show|tv))?:(\d+)', 'tmdb'),
        (r'themoviedb://(?:tv-)?(\d+)', 'tmdb'),
        (r'tmdb://(\d+)', 'tmdb'),
        (r'\btt\d{5,10}\b', 'imdb'),
        (r'imdb(?::|://)?(tt\d{5,10})', 'imdb'),
        (r'tvdb(?::|://)?(\d+)', 'tvdb'),
        (r'thetvdb://(\d+)', 'tvdb'),
    ]
    for pattern, kind in patterns:
        m = re.search(pattern, joined, re.I)
        if not m:
            continue
        value = m.group(1) if m.groups() else m.group(0)
        if kind == 'tmdb' and not tmdb_id:
            tmdb_id = value
        elif kind == 'imdb' and not imdb_id:
            imdb_id = value if str(value).startswith('tt') else m.group(0)
        elif kind == 'tvdb' and not tvdb_id:
            tvdb_id = value
    return {'tmdb_id': tmdb_id, 'imdb_id': imdb_id, 'tvdb_id': tvdb_id}


def _remote_art_bundles(meta, media_type='movie'):
    ids = extract_ids(meta)
    title = meta.get('name') or meta.get('title') or ''
    year = meta.get('releaseInfo') or meta.get('year') or ''
    tmdb_media_type = 'tv' if media_type in ('series', 'anime', 'tv', 'show') else 'movie'
    try:
        db_bundle = get_art_bundle_from_db(
            tmdb_id=ids.get('tmdb_id') or '',
            imdb_id=ids.get('imdb_id') or '',
            media_type=tmdb_media_type,
            title=title,
            year=year,
        ) or {}
    except Exception:
        db_bundle = {}
    direct_bundle = {}
    if not (db_bundle.get('poster') and db_bundle.get('fanart') and db_bundle.get('clearlogo')):
        try:
            direct_bundle = get_tmdb_direct_art(
                tmdb_id=ids.get('tmdb_id') or '',
                imdb_id=ids.get('imdb_id') or '',
                media_type=tmdb_media_type,
                title=title,
                year=year,
            ) or {}
        except Exception:
            direct_bundle = {}
    return ids, db_bundle, direct_bundle


def hybrid_meta_art(meta, media_type='movie', fallback_art=None):
    """Keep posters local, but allow remote fanart/clearlogo only when missing."""
    behavior = meta.get('behaviorHints') or {}
    images = meta.get('images') or {}
    fallback_art = fallback_art or {}
    art = native_meta_art(meta, media_type, fallback_art=fallback_art)
    raw_bg = _first_art(
        meta.get('background'), meta.get('fanart'), meta.get('landscape'), meta.get('banner'),
        _image_dict_art(images, 'background', 'fanart', 'backdrop', 'landscape', 'banner', 'art'),
        behavior.get('background') if isinstance(behavior, dict) else '',
        behavior.get('fanart') if isinstance(behavior, dict) else '',
    )
    local_clearlogo = _first_art(meta.get('clearlogo'), _image_dict_art(images, 'clearlogo', 'clearart'))
    if isinstance(behavior, dict):
        local_clearlogo = _first_art(local_clearlogo, behavior.get('clearlogo'))
    needs_remote = not raw_bg or not local_clearlogo
    ids = {'tmdb_id': '', 'imdb_id': ''}
    db_bundle = {}
    direct_bundle = {}
    if needs_remote:
        ids, db_bundle, direct_bundle = _remote_art_bundles(meta, media_type)
    fanart = _first_art(
        raw_bg,
        db_bundle.get('fanart'), db_bundle.get('landscape'),
        direct_bundle.get('fanart'), direct_bundle.get('landscape'),
        art.get('fanart'), fallback_art.get('fanart'), fallback_art.get('landscape'), addon_fanart()
    )
    landscape = _first_art(
        meta.get('landscape'), meta.get('banner'), raw_bg,
        db_bundle.get('landscape'), db_bundle.get('fanart'),
        direct_bundle.get('landscape'), direct_bundle.get('fanart'),
        art.get('landscape'), fanart
    )
    art['fanart'] = fanart
    art['landscape'] = landscape or fanart
    art['banner'] = _first_art(meta.get('banner'), raw_bg, db_bundle.get('landscape'), direct_bundle.get('landscape'), art.get('banner'), art.get('poster'))
    clearlogo = _first_art(
        local_clearlogo,
        db_bundle.get('clearlogo'),
        direct_bundle.get('clearlogo'),
        get_clearlogo_from_db(tmdb_id=ids.get('tmdb_id') or '', imdb_id=ids.get('imdb_id') or '', media_type=media_type) if needs_remote else ''
    )
    if clearlogo:
        art['clearlogo'] = clearlogo
        art['tvshow.clearlogo'] = clearlogo
        art['logo'] = clearlogo
        art['clearart'] = clearlogo
    return art


def composite_style_meta_art(meta, media_type='movie', fallback_art=None):
    """Composite-like artwork for Plexio/DexWorld items.

    - Poster/thumb/icon stay from the active metadata payload (native_meta_art).
    - Background/landscape use item-native artwork first, then TMDb Helper DB.
    - Clearlogo uses item-native logo first, then TMDb Helper DB/direct TMDb.
    """
    behavior = meta.get('behaviorHints') or {}
    images = meta.get('images') or {}
    fallback_art = fallback_art or {}
    art = native_meta_art(meta, media_type, fallback_art=fallback_art)

    ids = extract_ids(meta)
    title = meta.get('name') or meta.get('title') or ''
    year = meta.get('releaseInfo') or meta.get('year') or ''
    tmdb_media_type = 'tv' if media_type in ('series', 'anime', 'tv', 'show') else 'movie'

    try:
        db_bundle = get_art_bundle_from_db(
            tmdb_id=ids.get('tmdb_id') or '',
            imdb_id=ids.get('imdb_id') or '',
            media_type=tmdb_media_type,
            title=title,
            year=year,
        ) or {}
    except Exception:
        db_bundle = {}

    direct_bundle = {}
    if not (db_bundle.get('fanart') and db_bundle.get('clearlogo')):
        try:
            direct_bundle = get_tmdb_direct_art(
                tmdb_id=ids.get('tmdb_id') or '',
                imdb_id=ids.get('imdb_id') or '',
                media_type=tmdb_media_type,
                title=title,
                year=year,
            ) or {}
        except Exception:
            direct_bundle = {}

    raw_bg = _first_art(
        meta.get('background'), meta.get('fanart'), meta.get('backdrop'),
        meta.get('landscape'), meta.get('banner'),
        _image_dict_art(images, 'background', 'fanart', 'backdrop', 'landscape', 'banner', 'art'),
        behavior.get('background') if isinstance(behavior, dict) else '',
        behavior.get('fanart') if isinstance(behavior, dict) else '',
    )

    fanart = _first_art(
        raw_bg,
        db_bundle.get('fanart'), db_bundle.get('landscape'),
        direct_bundle.get('fanart'), direct_bundle.get('landscape'),
        art.get('fanart'), fallback_art.get('fanart'), fallback_art.get('landscape'),
        addon_fanart()
    )
    landscape = _first_art(
        meta.get('landscape'), meta.get('banner'), raw_bg,
        _image_dict_art(images, 'landscape', 'banner', 'fanart', 'backdrop'),
        db_bundle.get('landscape'), db_bundle.get('fanart'),
        direct_bundle.get('landscape'), direct_bundle.get('fanart'),
        art.get('landscape'), fanart
    )
    banner = _first_art(
        meta.get('banner'),
        _image_dict_art(images, 'banner', 'landscape', 'backdrop'),
        raw_bg, landscape, art.get('banner')
    )

    art['fanart'] = _wrap_tokenized_url(fanart) or fanart
    art['landscape'] = _wrap_tokenized_url(landscape) or landscape or art.get('fanart')
    if banner:
        art['banner'] = _wrap_tokenized_url(banner) or banner

    local_clearlogo = _first_art(
        meta.get('clearlogo'), meta.get('logo'), meta.get('clearart'),
        _image_dict_art(images, 'clearlogo', 'clearart', 'logo')
    )
    if isinstance(behavior, dict):
        local_clearlogo = _first_art(local_clearlogo, behavior.get('clearlogo'), behavior.get('logo'))

    clearlogo = _first_art(
        local_clearlogo,
        db_bundle.get('clearlogo'),
        direct_bundle.get('clearlogo'),
        get_clearlogo_from_db(
            tmdb_id=ids.get('tmdb_id') or '',
            imdb_id=ids.get('imdb_id') or '',
            media_type=tmdb_media_type,
        )
    )
    clearlogo = _wrap_tokenized_url(clearlogo) or clearlogo
    if clearlogo:
        art['clearlogo'] = clearlogo
        art['tvshow.clearlogo'] = clearlogo
        art['logo'] = clearlogo
        art['clearart'] = clearlogo

    return art


def _wrap_tokenized_url(url):
    """Wrap fragile remote artwork URLs in Kodi's image:// scheme.

    Plex/Plexio/Emby overlay/composite posters often depend on query params
    even when no obvious auth token is present. Kodi's texture loader may strip
    or normalize those params unless the URL is handed to it as opaque image://.
    """
    if not url:
        return url
    text = str(url).strip()
    if not text:
        return text
    lower = text.lower()
    if lower.startswith(('image://', 'special://', 'file://', 'plugin://', 'smb://', 'nfs://', '/')):
        return text
    if not lower.startswith(('http://', 'https://')):
        return text
    needs_wrap = False
    if '?' in text:
        fragile_tokens = (
            'x-plex-token', 'api_key=', 'token=', 'access_token=', 'apikey=',
            '/:/', 'plex', 'emby', 'jellyfin', 'plexio', 'overlay', 'composite',
            'transcode', 'thumb=', 'url=', 'minsize=', 'upscale=', 'width=', 'height=', 'format=',
            'dexworld', 'dexbridge', '/items/',
        )
        needs_wrap = any(token in lower for token in fragile_tokens)
    # Overlay/composite posters from Plexio/Plex hosts should always be
    # wrapped — their URLs contain path-based routing that Kodi's texture
    # cache may mangle even when no query string is present.
    if not needs_wrap:
        overlay_path_tokens = ('/:/transcode', '/composite', '/overlay', '/photo/', '/collection-image/')
        needs_wrap = any(token in lower for token in overlay_path_tokens)
    # Plexio/Plex/Emby host-based wrapping — any image URL from these hosts
    # should be wrapped regardless of path or query string, because their
    # image endpoints return dynamic content without a file extension that
    # Kodi's texture cache requires to work reliably.
    if not needs_wrap:
        fragile_hosts = ('plexio.', 'plex.tv', 'plexapp.com', 'dexworld.cc', 'emby.', 'jellyfin.')
        needs_wrap = any(token in lower for token in fragile_hosts)
    if len(text) > 250:
        needs_wrap = True
    if not needs_wrap:
        return text
    try:
        from urllib.parse import quote
        return 'image://%s/' % quote(text, safe='')
    except Exception:
        return text


def native_meta_art(meta, media_type='movie', fallback_art=None):
    """Fast path: use only artwork already provided by the addon/meta object.

    Intended for providers like Plex/Emby where artwork is already item-native and
    fetching TMDb/Helper art for every row makes browsing feel heavy.

    Plex/Plexio/Emby URLs get auto-wrapped with image:// so their auth tokens
    survive Kodi's image cache stripping (the most common cause of "Plexio
    posters don't show in Kodi" reports).
    """
    behavior = meta.get('behaviorHints') or {}
    images = meta.get('images') or {}
    fallback_art = fallback_art or {}
    raw_poster = _first_art(
        meta.get('poster'), meta.get('posterUrl'), meta.get('posterURL'),
        meta.get('thumbnail'), meta.get('thumb'), meta.get('thumbUrl'), meta.get('thumbURL'),
        meta.get('image'), meta.get('imageUrl'), meta.get('imageURL'),
        meta.get('plex_original_poster'), meta.get('parentThumb'), meta.get('grandparentThumb'),
        _image_dict_art(images, 'poster', 'thumb', 'thumbnail', 'cover', 'image', 'posterUrl', 'posterURL'),
        behavior.get('poster') if isinstance(behavior, dict) else '',
        behavior.get('thumbnail') if isinstance(behavior, dict) else '',
        behavior.get('plex_original_poster') if isinstance(behavior, dict) else '',
        fallback_art.get('poster'), fallback_art.get('thumb'),
        _default_poster(media_type)
    )
    raw_bg = _first_art(
        meta.get('background'), meta.get('fanart'), meta.get('landscape'), meta.get('banner'), meta.get('backdrop'),
        _image_dict_art(images, 'background', 'fanart', 'backdrop', 'landscape', 'banner', 'art'),
        behavior.get('background') if isinstance(behavior, dict) else '',
        behavior.get('fanart') if isinstance(behavior, dict) else '',
        ''
    )
    landscape = _first_art(
        meta.get('landscape'), meta.get('banner'), raw_bg,
        _image_dict_art(images, 'landscape', 'banner', 'fanart', 'backdrop'),
        raw_poster,
        fallback_art.get('landscape'), fallback_art.get('banner')
    )
    fanart = _first_art(
        raw_bg, landscape, raw_poster,
        fallback_art.get('fanart'), fallback_art.get('landscape'),
        addon_fanart()
    )
    thumb = _first_art(
        meta.get('plex_original_poster'), meta.get('thumbnail'), meta.get('thumb'),
        meta.get('thumbUrl'), meta.get('thumbURL'), meta.get('image'),
        _image_dict_art(images, 'thumb', 'thumbnail', 'poster', 'image'),
        raw_poster, fallback_art.get('thumb'), fallback_art.get('poster')
    )
    icon = _first_art(meta.get('plex_original_poster'), raw_poster, _image_dict_art(images, 'poster', 'thumb'), fallback_art.get('icon'), fallback_art.get('poster'), _default_poster(media_type))
    # Wrap tokenized Plex/Plexio/Emby URLs so Kodi can actually load them.
    poster_final = _wrap_tokenized_url(raw_poster) or raw_poster or fallback_art.get('poster') or fallback_art.get('thumb') or _default_poster(media_type)
    fanart_final = _wrap_tokenized_url(fanart) or fanart
    landscape_final = _wrap_tokenized_url(landscape) or landscape
    thumb_final = _wrap_tokenized_url(thumb) or thumb or raw_poster
    icon_final = _wrap_tokenized_url(icon) or icon
    banner_raw = _first_art(meta.get('banner'), _image_dict_art(images, 'banner', 'landscape', 'backdrop'), raw_bg, landscape, raw_poster, fallback_art.get('banner'))
    art = {
        'thumb': thumb_final,
        'poster': poster_final,
        'icon': icon_final,
        'fanart': fanart_final,
        'landscape': landscape_final or fanart_final,
        'banner': _wrap_tokenized_url(banner_raw) or banner_raw,
    }
    clearlogo = _first_art(meta.get('clearlogo'), _image_dict_art(images, 'clearlogo', 'clearart'))
    if isinstance(behavior, dict):
        clearlogo = _first_art(clearlogo, behavior.get('clearlogo'))
    clearlogo = _wrap_tokenized_url(clearlogo) or clearlogo
    if clearlogo:
        art['clearlogo'] = clearlogo
        art['tvshow.clearlogo'] = clearlogo
        art['logo'] = clearlogo
        art['clearart'] = clearlogo
    return art

def enrich_meta_art(meta, media_type='movie', fallback_art=None):
    ids, db_bundle, direct_bundle = _remote_art_bundles(meta, media_type)
    behavior = meta.get('behaviorHints') or {}
    images = meta.get('images') or {}
    fallback_art = fallback_art or {}
    raw_poster = _first_art(
        meta.get('poster'), meta.get('posterUrl'), meta.get('posterURL'),
        meta.get('thumbnail'), meta.get('thumb'), meta.get('thumbUrl'), meta.get('thumbURL'),
        meta.get('image'), meta.get('imageUrl'), meta.get('imageURL'),
        meta.get('plex_original_poster'), meta.get('parentThumb'), meta.get('grandparentThumb'),
        _image_dict_art(images, 'poster', 'thumb', 'thumbnail', 'cover', 'image', 'posterUrl', 'posterURL')
    )
    # Prefer TMDb Helper art when IDs are known because some addon poster URLs are unsupported by Kodi on some devices.
    poster = _first_art(
        db_bundle.get('poster'),
        direct_bundle.get('poster'),
        raw_poster,
        behavior.get('poster') if isinstance(behavior, dict) else '',
        fallback_art.get('poster'), fallback_art.get('thumb'), fallback_art.get('icon'),
        _default_poster(media_type)
    )
    # Prefer item-specific artwork and TMDb Helper artwork. Avoid falling back to the addon/provider
    # fanart here because that makes content screens show the addon background instead of the movie/show.
    fanart = _first_art(
        db_bundle.get('fanart'),
        direct_bundle.get('fanart'),
        meta.get('background'), meta.get('fanart'), meta.get('backdrop'),
        _image_dict_art(images, 'background', 'fanart', 'backdrop', 'landscape', 'banner', 'art'),
        behavior.get('background') if isinstance(behavior, dict) else '',
        db_bundle.get('landscape'),
        direct_bundle.get('landscape'),
        behavior.get('poster') if isinstance(behavior, dict) else '',
        raw_poster,
        fallback_art.get('fanart'), fallback_art.get('landscape'),
        fallback_art.get('poster'), fallback_art.get('thumb'),
        addon_fanart()
    )
    landscape = _first_art(
        db_bundle.get('landscape'),
        direct_bundle.get('landscape'),
        db_bundle.get('fanart'),
        direct_bundle.get('fanart'),
        meta.get('background'), meta.get('fanart'), meta.get('backdrop'),
        _image_dict_art(images, 'background', 'fanart', 'backdrop', 'landscape', 'banner', 'art'),
        behavior.get('background') if isinstance(behavior, dict) else '',
        raw_poster,
        fallback_art.get('poster'), fallback_art.get('thumb'),
        fanart
    )
    banner = _first_art(meta.get('banner'), _image_dict_art(images, 'banner', 'landscape', 'backdrop'), meta.get('background'), raw_poster, fallback_art.get('banner'))
    thumb = _first_art(meta.get('thumbnail'), meta.get('thumb'), _image_dict_art(images, 'thumb', 'thumbnail', 'poster'), raw_poster, poster, fallback_art.get('thumb'), fallback_art.get('poster'))
    icon = _first_art(raw_poster, _image_dict_art(images, 'poster', 'thumb'), poster, fallback_art.get('icon'), fallback_art.get('poster'), _default_poster(media_type))
    # Same wrapping as native_meta_art: Plexio/Plex/Emby poster URLs often
    # contain X-Plex-Token or long transcode paths. Stremio can display them
    # directly, but Kodi's texture cache is safer when they are passed as opaque
    # image:// URLs. Normal TMDb/Cinemeta URLs are returned unchanged.
    poster_final = _wrap_tokenized_url(poster or fallback_art.get('poster') or fallback_art.get('thumb') or _default_poster(media_type))
    thumb_final = _wrap_tokenized_url(thumb or poster_final)
    icon_final = _wrap_tokenized_url(icon)
    fanart_final = _wrap_tokenized_url(fanart)
    landscape_final = _wrap_tokenized_url(landscape)
    banner_final = _wrap_tokenized_url(banner)
    art = {
        'thumb': thumb_final,
        'poster': poster_final,
        'icon': icon_final,
        'fanart': fanart_final,
        'landscape': landscape_final,
        'banner': banner_final,
    }
    clearlogo = _first_art(meta.get('clearlogo'), _image_dict_art(images, 'clearlogo', 'clearart'))
    if isinstance(behavior, dict):
        clearlogo = _first_art(clearlogo, behavior.get('clearlogo'))
    tmdb_id = ids.get('tmdb_id')
    imdb_id = ids.get('imdb_id')
    if not clearlogo:
        clearlogo = _first_art(
            db_bundle.get('clearlogo'),
            direct_bundle.get('clearlogo'),
            get_clearlogo_from_db(tmdb_id=tmdb_id, imdb_id=imdb_id, media_type=media_type)
        )
    # Do not fall back to the provider/addon logo here. When there is no real item clearlogo,
    # most skins display the title text more cleanly than the addon logo.
    if clearlogo:
        art['clearlogo'] = clearlogo
        art['tvshow.clearlogo'] = clearlogo
        art['logo'] = clearlogo
        art['clearart'] = clearlogo
    return art

def stream_art(meta):
    art = enrich_meta_art(meta, meta.get('type') or 'movie')
    art['thumb'] = art.get('thumb') or media_path('play.png')
    art['icon'] = art.get('icon') or media_path('play.png')
    return art


# ─────────────────────────────────────────────────────────────────────
# v3.9.89: Poster resolution helpers — moved here from plugin.py so the
# source picker, loading dialog, player overlay, and any future caller
# all share ONE poster-sourcing policy. Previously this logic lived in
# plugin.py and only the playback handoff used it; the source_browser
# and sources_loading windows took the raw addon URL, which is why
# addons returning their own logo as "poster" showed up in the picker.
# ─────────────────────────────────────────────────────────────────────

METAHUB_POSTER_URL = 'https://images.metahub.space/poster/large/%s/img'


def is_suspect_logo_poster(url):
    """True when the URL looks like an addon icon/logo rather than a real
    movie/TV poster. Allow-lists known reliable poster CDNs (TMDb,
    MetaHub, Fanart.tv, Amazon Images, Imgur) and rejects paths ending
    in /icon.png, /logo.png, /favicon.*, etc.
    """
    if not url or not isinstance(url, str):
        return False
    url_low = url.lower()
    safe_hosts = (
        'image.tmdb.org', 'images.metahub.space', 'media-amazon.com',
        'm.media-amazon.com', 'img.youtube.com', 'i.imgur.com',
        'fanart.tv', 'assets.fanart.tv', 'static.metahub.space',
        'image.com', 'imgcdn', 'imageapi',
    )
    for h in safe_hosts:
        if h in url_low:
            return False
    suspect_endings = (
        '/icon.png', '/icon.jpg', '/icon.jpeg', '/icon.webp',
        '/logo.png', '/logo.jpg', '/logo.jpeg', '/logo.webp',
        '/addon.png', '/addon.jpg',
        '/favicon.png', '/favicon.ico', '/favicon.jpg',
        '/poster.png', '/poster.jpg',
        '/banner.png', '/banner.jpg',
    )
    for ending in suspect_endings:
        if url_low.endswith(ending):
            return True
    for seg in ('/logo/', '/icon/', '/icons/', '/branding/', '/brand/', '/assets/icon'):
        if seg in url_low:
            return True
    return False


def clean_poster(meta, media_type='movie'):
    """Pick the best poster URL for an item, in priority order:

      1. TMDb Helper's local SQLite artwork when available.
      2. The addon-provided URL when it passes the logo-suspect check —
         catches niche addons whose items aren't on TMDb but do have a
         genuine portrait poster.
      3. A deterministic MetaHub poster URL when only an IMDb id is known.
      4. The local default portrait placeholder
         (default_movie_poster.png / default_series_poster.png) so the
         portrait card never falls back to a landscape fanart/thumb
         which renders as a banner stuck at the top of an empty card.

    `meta` may be a Stremio-style meta dict (with 'poster', 'imdb_id',
    optionally 'tmdb_id', 'media_type'). Pass the resolved media_type
    explicitly when known — the function uses it only for the local
    placeholder fallback.
    """
    if not isinstance(meta, dict):
        meta = {}
    raw_poster = str(meta.get('poster') or '').strip()
    ids = extract_ids(meta)
    imdb_id = str(ids.get('imdb_id') or '').strip()
    tmdb_id = str(ids.get('tmdb_id') or '').strip()
    tmdb_media_type = 'tv' if media_type in ('series', 'anime', 'tv', 'show', 'tvshow', 'episode') else 'movie'
    try:
        local = get_art_bundle_from_db(
            tmdb_id=tmdb_id, imdb_id=imdb_id,
            media_type=tmdb_media_type,
            title=meta.get('title') or meta.get('name') or '',
            year=meta.get('year') or meta.get('releaseInfo') or '',
        ) or {}
        local_poster = str(local.get('poster') or '').strip()
        if local_poster and not is_suspect_logo_poster(local_poster):
            return local_poster
    except Exception:
        pass
    # Tier 2: addon URL when it's clearly not a logo.
    if raw_poster and not is_suspect_logo_poster(raw_poster):
        return raw_poster
    # Tier 3: a clean, predictable fallback when the local DB has no row.
    if imdb_id:
        return METAHUB_POSTER_URL % imdb_id
    # Tier 4: local placeholder — correctly proportioned 2:3.
    try:
        return _default_poster(media_type)
    except Exception:
        return ''
