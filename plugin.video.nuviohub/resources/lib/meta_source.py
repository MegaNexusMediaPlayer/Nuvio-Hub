# -*- coding: utf-8 -*-
"""Per-provider metadata source.

Each registered provider (Plex, Emby, Plexio, Jellyfin, Cinemeta, Torrentio,
etc.) can have its own metadata override target. The mapping is stored as a
single JSON blob in `provider_meta_map` setting:

    {
      "plexio_abc123":  "cinemeta_xyz",    # provider_id → meta source id
      "plex_def456":    "tmdb_helper",
      "anime_provider": "kitsu_mno"
    }

Values can be:
  - A provider_id of another registered Stremio meta-capable addon
  - "tmdb_helper" — TMDb Helper local database only (no Nuvio Hub TMDb API key required)
  - "auto"   (or missing key) — heuristic default. Plex/Emby get auto-replaced
             from the first available meta addon, every other addon stays native.
  - "native" — explicitly keep the provider's own metadata, no override.
               When set, the override layer is a no-op for both individual and
               batch calls; the consumer is expected to also respect it when
               picking artwork (see _resolve_meta_art in plugin.py).

`list_available_meta_sources()` populates the picker UI. We auto-register
EVERY addon that declares `meta` as a resource — the previous narrow whitelist
("only addons whose name contains cinemeta/tmdb/...") missed addons like
AIOMetadata, Anime Catalogs, MAL, anidb, etc.
"""
import json

import xbmc
import xbmcaddon

from .nuviohub import store as _store
from .nuviohub.client import fetch_meta
from .art import extract_ids

# --- nuviohub-401-patch ---
try:
    from .settings_cache import cached_addon as _dh_cached_addon
except Exception:
    try:
        from settings_cache import cached_addon as _dh_cached_addon
    except Exception:
        _dh_cached_addon = None
ADDON = _dh_cached_addon() if _dh_cached_addon else xbmcaddon.Addon('plugin.video.nuviohub')


# Module-level cache of the provider_meta_map setting.
# Was being re-parsed (getSetting + json.loads) on every meta lookup —
# 60-item catalogs paid for it 60 times. Now parsed once per invocation,
# invalidated whenever _save_map() runs (user changed the picker).
# (3.8.12)
_MAP_CACHE = None


def _invalidate_map_cache():
    global _MAP_CACHE
    _MAP_CACHE = None


def _load_map():
    global _MAP_CACHE
    if _MAP_CACHE is not None:
        return _MAP_CACHE
    try:
        raw = ADDON.getSetting('provider_meta_map') or '{}'
        data = json.loads(raw)
        _MAP_CACHE = data if isinstance(data, dict) else {}
    except Exception:
        _MAP_CACHE = {}
    return _MAP_CACHE


def _save_map(mapping):
    global _MAP_CACHE
    try:
        ADDON.setSetting('provider_meta_map', json.dumps(mapping or {}, ensure_ascii=False))
        _MAP_CACHE = dict(mapping or {})
    except Exception:
        _invalidate_map_cache()


def _default_source_id_from_setting():
    """Read the user's default meta source setting and translate the
    labelenum index into the internal id ('auto', 'tmdb_helper', 'native')."""
    try:
        raw = (ADDON.getSetting('default_meta_source') or '').strip()
    except Exception:
        raw = ''
    # Kodi labelenum returns the visible label by default; map it.
    low = raw.lower()
    if 'tmdb helper' in low or 'tmdb_helper' in low or low == '1':
        return 'tmdb_helper'
    if 'native' in low or "\u0627\u0644\u0623\u0635\u0644\u064a" in low or "\u0627\u0635\u0644\u064a" in low or low == '2':
        return 'native'
    return 'auto'


def get_meta_source_for(provider_id):
    """Return the configured meta source id for a given provider.

    Resolution order:
      1) per-bucket override for the currently-rendering bucket
         (set via the home bucket context menu in plugin.py)
      2) explicit per-provider mapping in `provider_meta_map`
      3) global default from the `default_meta_source` setting
      4) 'auto' if neither is set
    """
    # v3.9.48: consult per-bucket override first. This is read via a
    # callback into plugin.py to avoid an import cycle. The callback
    # returns '' when no bucket is currently active or no override is
    # set, in which case we fall through to the existing logic.
    try:
        from . import plugin as _plugin
        bucket = _plugin._get_active_bucket()
        if bucket:
            bucket_override = _plugin.get_bucket_meta_source(bucket)
            if bucket_override and bucket_override != 'auto':
                return bucket_override
    except Exception:
        pass
    explicit = (_load_map().get(provider_id or '') or '').strip()
    if explicit and explicit != 'auto':
        return explicit
    return _default_source_id_from_setting()


def set_meta_source_for(provider_id, source_id):
    if not provider_id:
        return
    mapping = _load_map()
    if not source_id or source_id == 'auto':
        mapping.pop(provider_id, None)
    else:
        mapping[provider_id] = source_id
    _save_map(mapping)
    # Drop the on-disk + in-memory HTTP cache for /meta/ URLs so the very
    # next catalog/detail render actually reflects the new mapping. Without
    # this, the user would have to wait for the meta TTL to expire (often
    # 6h+) before the change took visible effect — what users perceived as
    # "the meta source picker doesn't work".
    try:
        from .nuviohub.client import purge_meta_cache as _purge
        _purge()
    except Exception:
        pass


def clear_meta_map():
    _save_map({})
    try:
        from .nuviohub.client import purge_meta_cache as _purge
        _purge()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────
# v3.9.30: per-bucket art priority.
#
# Sits next to the existing provider_meta_map (per-provider meta source).
# Where provider_meta_map answers "for items from Plex, fetch metadata
# from Cinemeta", this answers "for items in the Anime bucket, prefer
# poster art from Kitsu, then AniList, then fall back to default".
#
# Stored shape (in setting `bucket_art_map`):
#   {
#     "anime":  {"poster": ["kitsu_xxx", "anilist_yyy"],
#                "background": ["fanart_zzz"]},
#     "movies": {"poster": ["cinemeta_aaa"]}
#   }
#
# Art types supported: poster, background, clearlogo. Anything missing
# from the map → caller uses the existing _resolve_meta_art strategy.
# Empty list for an art type → also fall through.
#
# Why JSON-in-setting rather than a separate file: matches the rest of
# NuvioHub's hidden-state pattern (providers_json, catalog_state_json,
# provider_meta_map). Settings round-trip is reliable across Kodi
# restarts and survives addon updates.
# ─────────────────────────────────────────────────────────────────────

_BUCKET_ART_CACHE = None

ALLOWED_ART_TYPES = ('poster', 'background', 'clearlogo', 'landscape', 'banner', 'clearart')


def art_configuration_mode():
    """Return unified or custom artwork mode."""
    try:
        raw = (ADDON.getSetting('art_configuration_mode') or 'Unified').strip().lower()
    except Exception:
        raw = 'unified'
    return 'custom' if raw in ('custom', "\u062a\u062e\u0635\u064a\u0635") else 'unified'




# Global artwork source priorities. These apply to every item in Nuvio Hub,
# then a per-folder override may replace them. Stored separately from the
# per-folder map so exporting/importing settings remains predictable.
_GLOBAL_ART_CACHE = None

def _invalidate_global_art_cache():
    global _GLOBAL_ART_CACHE
    _GLOBAL_ART_CACHE = None

def _load_global_art_map():
    global _GLOBAL_ART_CACHE
    if _GLOBAL_ART_CACHE is not None:
        return _GLOBAL_ART_CACHE
    try:
        raw = ADDON.getSetting('global_art_map') or '{}'
        data = json.loads(raw)
        clean = {}
        if isinstance(data, dict):
            for art_type, pids in data.items():
                if art_type in ALLOWED_ART_TYPES and isinstance(pids, list):
                    clean[art_type] = [str(p) for p in pids if p]
        _GLOBAL_ART_CACHE = clean
    except Exception:
        _GLOBAL_ART_CACHE = {}
    return _GLOBAL_ART_CACHE

def _save_global_art_map(mapping):
    global _GLOBAL_ART_CACHE
    try:
        clean = {}
        for art_type, pids in (mapping or {}).items():
            if art_type in ALLOWED_ART_TYPES and isinstance(pids, list) and pids:
                clean[art_type] = [str(p) for p in pids if p]
        ADDON.setSetting('global_art_map', json.dumps(clean, ensure_ascii=False))
        _GLOBAL_ART_CACHE = clean
    except Exception:
        _invalidate_global_art_cache()

def get_global_art_priority(art_type):
    if art_type not in ALLOWED_ART_TYPES:
        return []
    return list(_load_global_art_map().get(art_type) or [])

def set_global_art_priority(art_type, provider_ids):
    if art_type not in ALLOWED_ART_TYPES:
        return
    mapping = _load_global_art_map()
    if provider_ids:
        mapping[art_type] = [str(p) for p in provider_ids if p]
    else:
        mapping.pop(art_type, None)
    _save_global_art_map(mapping)
    try:
        from .nuviohub.client import purge_meta_cache as _purge
        _purge()
    except Exception:
        pass

def clear_global_art():
    _save_global_art_map({})
    try:
        from .nuviohub.client import purge_meta_cache as _purge
        _purge()
    except Exception:
        pass


def _invalidate_bucket_art_cache():
    global _BUCKET_ART_CACHE
    _BUCKET_ART_CACHE = None


def _load_bucket_art_map():
    global _BUCKET_ART_CACHE
    if _BUCKET_ART_CACHE is not None:
        return _BUCKET_ART_CACHE
    try:
        raw = ADDON.getSetting('bucket_art_map') or '{}'
        data = json.loads(raw)
        # Defensive: validate shape so a corrupted setting doesn't crash
        # callers downstream. Coerce non-list priorities into [] and drop
        # unknown art types.
        clean = {}
        if isinstance(data, dict):
            for bucket, types in data.items():
                if not isinstance(types, dict):
                    continue
                clean_types = {}
                for art_type, pids in types.items():
                    if art_type not in ALLOWED_ART_TYPES:
                        continue
                    if isinstance(pids, list):
                        clean_types[art_type] = [str(p) for p in pids if p]
                if clean_types:
                    clean[str(bucket)] = clean_types
        _BUCKET_ART_CACHE = clean
    except Exception:
        _BUCKET_ART_CACHE = {}
    return _BUCKET_ART_CACHE


def _save_bucket_art_map(mapping):
    global _BUCKET_ART_CACHE
    try:
        ADDON.setSetting('bucket_art_map',
                          json.dumps(mapping or {}, ensure_ascii=False))
        _BUCKET_ART_CACHE = dict(mapping or {})
    except Exception:
        _invalidate_bucket_art_cache()


def get_bucket_art_priority(bucket, art_type):
    """Return the ordered provider_id priority list for (bucket, art_type),
    or [] if no priority is configured. Empty list = caller should fall
    through to the default art-resolution strategy."""
    if not bucket or art_type not in ALLOWED_ART_TYPES:
        return []
    bucket_cfg = _load_bucket_art_map().get(str(bucket)) or {}
    return list(bucket_cfg.get(art_type) or [])


def set_bucket_art_priority(bucket, art_type, provider_ids):
    """Persist a new priority list for (bucket, art_type). An empty list
    clears the entry. Passing provider_ids=None also clears."""
    if not bucket or art_type not in ALLOWED_ART_TYPES:
        return
    mapping = _load_bucket_art_map()
    bucket_key = str(bucket)
    bucket_cfg = mapping.get(bucket_key) or {}
    if not provider_ids:
        bucket_cfg.pop(art_type, None)
        if not bucket_cfg:
            mapping.pop(bucket_key, None)
        else:
            mapping[bucket_key] = bucket_cfg
    else:
        bucket_cfg[art_type] = [str(p) for p in provider_ids if p]
        mapping[bucket_key] = bucket_cfg
    _save_bucket_art_map(mapping)
    # Purge meta cache so the next render uses the new priority.
    try:
        from .nuviohub.client import purge_meta_cache as _purge
        _purge()
    except Exception:
        pass


def clear_bucket_art_for(bucket):
    """Remove all priorities for one bucket (poster + background + clearlogo)."""
    if not bucket:
        return
    mapping = _load_bucket_art_map()
    if str(bucket) in mapping:
        mapping.pop(str(bucket), None)
        _save_bucket_art_map(mapping)
        try:
            from .nuviohub.client import purge_meta_cache as _purge
            _purge()
        except Exception:
            pass


def _provider_supports_meta(provider):
    manifest = (provider or {}).get('manifest') or {}
    for resource in manifest.get('resources', []):
        if resource == 'meta':
            return True
        if isinstance(resource, dict) and resource.get('name') == 'meta':
            return True
    return False


# --- Stream-only detection (Plex/Emby/Plexio/Jellyfin/DexBridge) --------
# These providers have private-token poster URLs that Kodi can't reliably
# load, so 'auto' meta-source mode auto-replaces them with remote art.
_STREAM_ONLY_HINTS = ('plex', 'plexio', 'emby', 'jellyfin', 'dexbridge')

# Negative hints for meta-source picker — these addons CAN report meta but
# the user almost never wants them as the *primary* metadata source for
# OTHER addons. They still get listed if the user hasn't disabled them.
_META_PICKER_BLOCKLIST = ('torrentio', 'comet', 'mediafusion', 'watchhub',
                          'opensubtitles', 'orion', 'debrid', 'real-debrid',
                          'realdebrid', 'rd:', 'aiostreams')


def _provider_haystack(provider):
    manifest = (provider or {}).get('manifest') or {}
    return ' '.join([
        str((provider or {}).get('name') or ''),
        str((provider or {}).get('id') or ''),
        str((provider or {}).get('base_url') or ''),
        str((provider or {}).get('manifest_url') or ''),
        str(manifest.get('name') or ''),
        str(manifest.get('id') or ''),
        str(manifest.get('description') or ''),
    ]).lower()


def _provider_is_plexio(provider):
    haystack = _provider_haystack(provider)
    return any(hint in haystack for hint in (
        'plexio', 'plexbridge', 'com.stremio.plexio', 'com.stremio.plexbridge',
        'plexio.dexworld.cc'
    ))


def _provider_looks_like_meta_source(provider):
    """Permissive check: any provider that DECLARES `meta` is eligible for the
    picker, except the well-known stream-only providers and known stream
    aggregators. This is the fix for: 'when adding any tool that supports
    metadata it should auto-appear in the metadata picker'.
    """
    if not _provider_supports_meta(provider):
        return False
    haystack = _provider_haystack(provider)
    if any(hint in haystack for hint in _STREAM_ONLY_HINTS):
        return False
    if any(hint in haystack for hint in _META_PICKER_BLOCKLIST):
        return False
    return True


def provider_is_stream_only(provider):
    """True if provider is best known for streams/catalogs, unreliable meta."""
    return any(h in _provider_haystack(provider) for h in _STREAM_ONLY_HINTS)


def list_available_meta_sources():
    """Return the list of choosable meta sources for the picker."""
    sources = [
        {'id': 'auto', 'name': 'Automatic (smart)', 'kind': 'special'},
        {'id': 'native', 'name': "The addon's own metadata", 'kind': 'special'},
        {'id': 'tmdb_helper', 'name': 'TMDb Helper (no API needed)', 'kind': 'builtin'},
    ]
    seen = set()
    for row in _store.list_providers() or []:
        if not _provider_looks_like_meta_source(row):
            continue
        pid = row.get('id') or ''
        if not pid or pid in seen:
            continue
        seen.add(pid)
        sources.append({
            'id': pid,
            'name': row.get('name') or pid,
            'kind': 'stremio',
        })
    return sources


def source_display_name(source_id):
    """Human label for a source id, used in menus."""
    if not source_id or source_id == 'auto':
        return 'Automatic'
    if source_id == 'native':
        return 'Addon metadata'
    if source_id == 'tmdb_helper':
        return 'TMDb Helper'
    prov = _store.get_provider(source_id)
    if prov:
        return prov.get('name') or source_id
    return source_id


def _candidate_ids(ids):
    imdb = ids.get('imdb_id') or ''
    tmdb = ids.get('tmdb_id') or ''
    tvdb = ids.get('tvdb_id') or ''
    candidates = []
    if imdb:
        candidates.append(imdb if imdb.startswith('tt') else 'tt%s' % imdb)
    if tmdb:
        candidates.append('tmdb:%s' % tmdb)
    if tvdb:
        candidates.append('tvdb:%s' % tvdb)
    return candidates


def _fetch_from_stremio(meta_provider_id, media_type, ids):
    provider = _store.get_provider(meta_provider_id) if meta_provider_id else None
    if not provider:
        return None
    stremio_mt = 'series' if media_type in ('series', 'anime', 'tv', 'show') else 'movie'
    for item_id in _candidate_ids(ids):
        try:
            data = fetch_meta(provider, stremio_mt, item_id)
            meta = data.get('meta') or {}
            if meta and (meta.get('poster') or meta.get('background') or meta.get('description')):
                return meta
        except Exception as exc:
            xbmc.log('[NuvioHub] meta fetch %s:%s failed: %s' % (
                provider.get('name'), item_id, exc), xbmc.LOGDEBUG)
            continue
    return None


def _fetch_from_tmdb_helper(ids, meta, media_type):
    """Pull rich metadata from TMDb Helper.

    v3.9.122: choosing TMDb Helper as a collection/provider metadata source
    should make the *entire* item look like TMDb Helper, not just swap the
    poster. Read title/plot/year/genres/studios/cast/ratings/art from the
    helper local database when available, then use the existing TMDb fallback
    only to avoid blank artwork on uncached items.
    """
    is_tv = media_type in ('series', 'anime', 'show', 'tv')
    mt_norm = 'tv' if is_tv else 'movie'
    tmdb_id = str(ids.get('tmdb_id') or '').strip()
    imdb_id = str(ids.get('imdb_id') or '').strip()
    tvdb_id = str(ids.get('tvdb_id') or '').strip()
    title = str(meta.get('name') or meta.get('title') or '').strip()
    year = str(meta.get('releaseInfo') or meta.get('year') or '').strip()

    try:
        from . import tmdbhelper as _tmdbh
        db_meta = _tmdbh.get_meta_bundle_from_db(
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            tvdb_id=tvdb_id,
            media_type=mt_norm,
            title=title,
            year=year,
        ) or {}
    except Exception:
        db_meta = {}

    if db_meta and (db_meta.get('poster') or db_meta.get('background') or db_meta.get('description') or db_meta.get('genres') or db_meta.get('cast')):
        return db_meta

    # TMDb Helper DB had no cached row/art for this item. Fall back to the
    # direct TMDb artwork resolver as a visual safety net only; metadata fields
    # still come from the helper DB when it has them.
    try:
        from . import tmdb_direct as _td
        direct = _td.art_for(
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            media_type=mt_norm,
            title=title,
            year=year,
        ) or {}
    except Exception:
        direct = {}
    d_poster = direct.get('poster') or ''
    d_fanart = direct.get('fanart') or direct.get('landscape') or ''
    d_clearlogo = direct.get('clearlogo') or ''
    if not any([d_poster, d_fanart, d_clearlogo]):
        return None

    return {
        'poster': d_poster,
        'thumbnail': d_poster,
        'thumb': d_poster,
        'background': d_fanart,
        'fanart': d_fanart,
        'landscape': direct.get('landscape') or d_fanart,
        'logo': d_clearlogo,
        'clearlogo': d_clearlogo,
    }

def _meta_is_good_enough(meta):
    if not isinstance(meta, dict):
        return False
    if not (meta.get('poster') or meta.get('logo') or meta.get('clearlogo')):
        return False
    if meta.get('background') or meta.get('fanart') or meta.get('landscape'):
        return True
    desc = meta.get('description') or meta.get('overview') or ''
    return len(str(desc)) >= 80


_ART_OVERRIDE_KEYS = (
    'poster', 'posterUrl', 'posterURL', 'thumbnail', 'thumb', 'thumbUrl', 'thumbURL',
    'image', 'imageUrl', 'imageURL', 'background', 'fanart', 'landscape', 'banner',
    'backdrop', 'logo', 'clearlogo', 'clearart', 'plex_original_poster',
    'parentThumb', 'grandparentThumb'
)


def _drop_art_fields(meta):
    """Remove artwork from a base meta object before applying an explicit source.

    Without this, choosing a metadata source can still leak artwork from the
    previous/provider meta through nested `images` or `behaviorHints` fields.
    """
    out = dict(meta or {})
    for key in _ART_OVERRIDE_KEYS:
        out.pop(key, None)
    images = out.get('images')
    if isinstance(images, dict):
        new_images = dict(images)
        for key in list(new_images.keys()):
            if str(key).lower() in (
                'poster', 'thumb', 'thumbnail', 'cover', 'image', 'posterurl', 'poster_url',
                'background', 'fanart', 'backdrop', 'landscape', 'banner', 'art',
                'clearlogo', 'clearart', 'logo'
            ):
                new_images.pop(key, None)
        if new_images:
            out['images'] = new_images
        else:
            out.pop('images', None)
    behavior = out.get('behaviorHints')
    if isinstance(behavior, dict):
        new_behavior = dict(behavior)
        for key in _ART_OVERRIDE_KEYS:
            new_behavior.pop(key, None)
        if new_behavior:
            out['behaviorHints'] = new_behavior
        else:
            out.pop('behaviorHints', None)
    return out


def _mark_source(meta, source_id='', provider_id='', strict_art=False, virtual_key=''):
    """Stamp meta so downstream artwork code can respect the user's picker.

    Kodi listing/detail/playback flows may re-score or re-cache metadata after
    the catalog page. These private fields let plugin.py know that the artwork
    already came from a selected source and must not be enriched/fallen back to
    another source later.
    """
    out = dict(meta or {})
    if source_id:
        out['_nuviohub_meta_source_id'] = str(source_id or '')
    if provider_id:
        out['_nuviohub_meta_provider_id'] = str(provider_id or '')
    if virtual_key:
        out['_nuviohub_meta_virtual_key'] = str(virtual_key or '')
    if strict_art:
        out['_nuviohub_art_strict'] = '1'
    return out


def _merge_meta(base_meta, replacement, strict_art=False, source_id='', provider_id='', virtual_key=''):
    if not replacement:
        merged = _drop_art_fields(base_meta) if strict_art else dict(base_meta or {})
        return _mark_source(merged, source_id=source_id, provider_id=provider_id, strict_art=strict_art, virtual_key=virtual_key)
    merged = _drop_art_fields(base_meta) if strict_art else dict(base_meta or {})
    for key in ('poster', 'posterUrl', 'posterURL', 'thumbnail', 'thumb', 'image', 'background', 'fanart', 'landscape', 'backdrop', 'banner',
                'logo', 'clearlogo', 'clearart', 'description', 'overview', 'plot', 'plotoutline', 'tagline',
                'genres', 'genre', 'releaseInfo', 'released', 'premiered', 'firstaired', 'date', 'year',
                'imdbRating', 'rating', 'voteAverage', 'score', 'imdb_votes', 'votes', 'userrating',
                'cast', 'credits_cast', 'director', 'writer', 'runtime', 'duration', 'country',
                'certification', 'mpaa', 'studio', 'studios', 'network', 'networks', 'production_companies',
                'originaltitle', 'trailer', 'status', 'type', 'tmdb_id', 'imdb_id', 'tvdb_id', 'id',
                'images', 'behaviorHints', 'name', 'title', 'videos', 'trailers', 'links'):
        val = replacement.get(key)
        if val not in (None, '', [], {}):
            # Clearlogo / logo: never overwrite a good existing value with
            # something empty — the user sees the clearlogo change every time
            # they switch meta sources, which feels broken. Only update it
            # if the replacement actually has a richer value.
            if key in ('clearlogo', 'logo') and merged.get(key) and not val:
                continue
            merged[key] = val
    return _mark_source(merged, source_id=source_id, provider_id=provider_id, strict_art=strict_art, virtual_key=virtual_key)


def is_native_for(provider_id):
    """Public helper: True iff the user explicitly asked for native meta."""
    return get_meta_source_for(provider_id) == 'native'


def override_virtual_meta(target_key, media_type, meta):
    """Apply a metadata override for non-provider targets (Continue Watching,
    Trakt collection entries) where there is no concrete Stremio provider row
    to attach the mapping to."""
    if not target_key:
        return meta
    meta = dict(meta or {})
    ids = extract_ids(meta)
    if not any(ids.values()):
        return meta

    source_id = get_meta_source_for(target_key)
    if source_id == 'native':
        return meta

    replacement = None
    if source_id in ('', 'auto'):
        replacement = _fetch_from_tmdb_helper(ids, meta, media_type)
        if not replacement:
            for src in list_available_meta_sources():
                if src.get('kind') == 'stremio':
                    replacement = _fetch_from_stremio(src.get('id') or '', media_type, ids)
                    if replacement:
                        break
    elif source_id == 'tmdb_helper':
        replacement = _fetch_from_tmdb_helper(ids, meta, media_type)
        if not replacement:
            # Do not erase the seed art for virtual Trakt/MDBList collection
            # entries when TMDb Helper has not cached the item yet and Nuvio Hub
            # has no API fallback. The previous strict merge turned useful
            # seed/local art into blank generic video icons.
            return _mark_source(meta, source_id=source_id, strict_art=False, virtual_key=target_key)
    else:
        # Explicit source means explicit source: do not silently fall back to
        # TMDb Helper/API when the selected meta add-on has no artwork.
        replacement = _fetch_from_stremio(source_id, media_type, ids)

    explicit = source_id not in ('', 'auto')
    return _merge_meta(meta, replacement, strict_art=explicit, source_id=source_id, virtual_key=target_key)


def override_meta(provider, media_type, meta):
    "Apply per-provider metadata override.\n\n    'native' is treated as a STRICT no-op — the provider's own meta is\n    returned untouched, even if it looks sparse. This is what '\u0627\u062d\u062a\u0631\u0627\u0645\n    \u0627\u062e\u062a\u064a\u0627\u0631 \u0627\u0644\u0645\u0633\u062a\u062e\u062f\u0645' means for users that explicitly prefer Plexio/DexBridge\n    meta because their setup already has rich local artwork.\n    "
    if not provider:
        return meta
    source_id = get_meta_source_for(provider.get('id'))
    if source_id == 'native' or (source_id == 'auto' and _provider_is_plexio(provider)):
        # Plexio already behaves like a Stremio metadata provider and carries
        # tokenized Plex artwork in its catalog/meta payload. In auto/native
        # mode, never replace it with TMDb/Cinemeta. Explicit selections below
        # still override 100%.
        return _mark_source(meta, source_id='native', provider_id=(provider.get('id') or ''), strict_art=False)

    ids = extract_ids(meta)
    if not any(ids.values()):
        return meta

    # 'auto' → replace only for Plex/Emby (unreliable meta), leave others native.
    if source_id == 'auto':
        if not provider_is_stream_only(provider):
            return meta
        replacement = None
        for src in list_available_meta_sources():
            if src['kind'] == 'stremio':
                replacement = _fetch_from_stremio(src['id'], media_type, ids)
                if replacement:
                    break
        if not replacement:
            replacement = _fetch_from_tmdb_helper(ids, meta, media_type)
    elif source_id == 'tmdb_helper':
        replacement = _fetch_from_tmdb_helper(ids, meta, media_type)
    else:
        # Explicit source means explicit source: do not silently fall back to
        # TMDb Helper/API when the selected meta add-on has no artwork.
        replacement = _fetch_from_stremio(source_id, media_type, ids)

    explicit = source_id not in ('', 'auto')
    if not replacement and explicit:
        # The user's explicitly-selected source had no art for this item.
        # As a last resort, try tmdb_direct API so the user sees SOME poster
        # instead of a blue default square. This only fires for explicit
        # picks (not auto), so it doesn't re-enrich native/auto artwork.
        replacement = _fetch_from_tmdb_helper(ids, meta, media_type)
    if not replacement:
        # Explicit source means strict source: if the selected source has no
        # artwork/meta for this item, do not leak the provider's old poster.
        return _merge_meta(meta, None, strict_art=explicit, source_id=source_id, provider_id=provider.get('id') or '')
    return _merge_meta(meta, replacement, strict_art=explicit, source_id=source_id, provider_id=provider.get('id') or '')


def override_metas_batch(provider, media_type, metas):
    if not provider or not metas:
        return metas
    source_id = get_meta_source_for(provider.get('id'))
    # Short-circuit: native = strict no-op. Plexio is also native in auto
    # because its configured Stremio manifest is already the authoritative
    # metadata/art source (same as Stremio).
    if source_id == 'native' or (source_id == 'auto' and _provider_is_plexio(provider)):
        return [_mark_source(m, source_id='native', provider_id=(provider.get('id') or ''), strict_art=False) for m in (metas or [])]
    if source_id == 'auto' and not provider_is_stream_only(provider):
        return metas

    from .nuviohub.client import run_parallel

    # When the user picks an EXPLICIT source (tmdb_helper or a specific
    # Stremio meta addon), every item must go through override_meta —
    # short-circuiting on _meta_is_good_enough makes the picker silently
    # do nothing for items whose original meta already had a poster +
    # description (the typical Plex/Plexio case). The "good_enough" skip
    # is only an optimisation valid for `auto` mode, where the goal is to
    # avoid redundant lookups; with an explicit pick the user is asking
    # us to replace the meta regardless.
    skip_good_enough = (source_id == 'auto')

    def _one(m):
        try:
            if skip_good_enough and _meta_is_good_enough(m):
                return m
            return override_meta(provider, media_type, m)
        except Exception:
            return m

    results = run_parallel(_one, metas)
    return [r if not isinstance(r, Exception) else original
            for original, r in results]
