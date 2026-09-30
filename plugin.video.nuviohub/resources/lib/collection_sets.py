# -*- coding: utf-8 -*-
"""Collection sets — external JSON shortcuts à la Fusion Starter Kit.

A "collection set" is a JSON array where each entry defines a named shortcut
that points to either:
  - an addonCatalog (a specific catalog from a Stremio-compatible manifest)
  - a traktList    (a Trakt user list)

Shape (one entry):
{
  "name": "Paul Thomas Anderson",
  "id": "...",
  "layout": "Poster" | "Wide",
  "backgroundImageURL": "https://...",
  "hideTitle": false,
  "dataSource": {
    "kind": "traktList" | "addonCatalog",
    "payload": {...}
  }
}

We persist:
  - collection_sets.json       → [{id, name, source_url, entries:[...]}]
The entries are frozen at add-time and can be refreshed later.
"""
import hashlib
import json
import os
import uuid

from .dexhub.common import profile_path
from . import store as _store
from .client import validate_manifest

SETS_FILE = os.path.join(profile_path(), 'collection_sets.json')

# Known public Stremio manifests used by popular Nuvio/Fusion collection
# exports. Collection JSONs usually reference addons by manifest `id` only
# (addonId), so Nuvio Hub cannot discover the transport URL unless we keep a
# small resolver table. User-configured/provider-installed manifests always
# win over this table.
# Private Plexio/StreamBridge manifests must be added by the user from the
# public setup sites. Never bundle per-user instance URLs or tokens here.
DEXWORLD_PLEXIO_SITE = 'https://plexio.dexworld.cc/'
DEXWORLD_STREAMBRIDGE_SITE = 'https://sb.dexworld.cc/'

KNOWN_ADDON_MANIFESTS = {
    # Streaming Catalogs — used by Nuvio profiles for Netflix/HBO/Disney/etc.
    'pw.ers.netflix-catalog': 'https://7a82163c306e-stremio-netflix-catalog-addon.baby-beamup.club/manifest.json',
}

# Addons that are known to require a user-configured manifest. Do not silently
# register their public shell manifest because it may expose no catalogs until
# configured.
CONFIG_REQUIRED_ADDONS = {
    'com.stremio.plexio',
    'com.stremio.plexbridge',
    'plexio',
    'plexbridge',
    'streambridge',
    'dexbridge',
    'com.stremio.streambridge',
    'com.stremio.dexbridge',
}

_CACHE_ROWS = None
_CACHE_MTIME = None


def _file_mtime():
    try:
        return os.path.getmtime(SETS_FILE)
    except Exception:
        return None


def _read():
    global _CACHE_ROWS, _CACHE_MTIME
    mtime = _file_mtime()
    if _CACHE_ROWS is not None and mtime == _CACHE_MTIME:
        return list(_CACHE_ROWS)
    try:
        with open(SETS_FILE, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
            if isinstance(data, list):
                _CACHE_ROWS = data
                _CACHE_MTIME = mtime
                return list(data)
    except Exception:
        pass
    _CACHE_ROWS = []
    _CACHE_MTIME = mtime
    return []


def _write(rows):
    # v3.9.17: atomic write so a crash mid-save doesn't lose all custom
    # collection sets. Caller invariant unchanged — rows are persisted
    # then memory cache is updated.
    from .dexhub.safe_io import write_json as _safe_write_json
    global _CACHE_ROWS, _CACHE_MTIME
    _safe_write_json(SETS_FILE, rows)
    _CACHE_ROWS = list(rows)
    _CACHE_MTIME = _file_mtime()


def _write_fast(rows):
    """Fast atomic save for tiny collection edits such as delete.

    The normal writer is intentionally very defensive: it copies a .bak file,
    pretty-prints the whole JSON and fsyncs the temp file.  On Android/TV boxes
    that can make a simple context-menu delete feel like opening the whole
    collection again.  For confirmed local edits we still keep the important
    guarantee (write to temp then atomic replace), but write compact JSON and do
    not block on fsync/backup snapshot.
    """
    global _CACHE_ROWS, _CACHE_MTIME
    os.makedirs(os.path.dirname(SETS_FILE), exist_ok=True)
    tmp_path = '%s.tmp.%d.fast' % (SETS_FILE, os.getpid())
    try:
        with open(tmp_path, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp_path, SETS_FILE)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass
        raise
    _CACHE_ROWS = list(rows)
    _CACHE_MTIME = _file_mtime()


# ── parsing ──────────────────────────────────────────────────────────────────


def manifest_url_from_collections_url(url):
    """Return the sibling manifest.json URL for a Plexio/collection JSON URL.

    Plexio exposes both URLs side-by-side:
      /<installation>/<key>/collections.json
      /<installation>/<key>/manifest.json

    Nuvio Hub accepts collections.json for import, but provider registration and
    playback must use manifest.json. Query strings/fragments are preserved.
    """
    url = str(url or '').strip()
    if not url.lower().startswith(('http://', 'https://')):
        return ''
    try:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        path = parsed.path or ''
        if path.lower().endswith('/collections.json'):
            new_path = path[:-len('collections.json')] + 'manifest.json'
            return urlunparse((parsed.scheme, parsed.netloc, new_path, parsed.params, parsed.query, parsed.fragment))
    except Exception:
        pass
    lower = url.lower()
    marker = '/collections.json'
    idx = lower.find(marker)
    if idx >= 0:
        return url[:idx] + '/manifest.json' + url[idx + len(marker):]
    return ''


def normalize_catalog_id_and_type(catalog_id, catalog_type='movie'):
    """Normalize Nuvio/Plexio collection catalog IDs.

    Plexio's collections.json may export catalogId as e.g.
    `movie::plex-col-1-XXXX` while its manifest catalog id is `plex-col-1-XXXX`.
    Kodi/Nuvio Hub must call /catalog/movie/plex-col-... rather than passing the
    prefixed id verbatim.
    """
    cid = str(catalog_id or '').strip()
    ctype = str(catalog_type or '').strip() or 'movie'
    if '::' in cid:
        head, tail = cid.split('::', 1)
        head_l = head.strip().lower()
        if head_l in ('movie', 'movies', 'series', 'show', 'tv', 'anime') and tail.strip():
            cid = tail.strip()
            if head_l in ('series', 'show', 'tv'):
                ctype = 'series'
            elif head_l == 'anime':
                ctype = 'anime'
            else:
                ctype = 'movie'
    ctype_l = ctype.lower()
    if ctype_l in ('tv', 'show', 'shows'):
        ctype = 'series'
    elif ctype_l in ('movies',):
        ctype = 'movie'
    elif ctype_l not in ('movie', 'series', 'anime'):
        ctype = ctype or 'movie'
    return cid, ctype


def _normalize_entry(raw):
    """Return a clean minimal dict for one collection entry, or None if unusable.

    Supports both old shape (single dataSource) and new shape (multiple
    catalogSources from share-URL exports). Multi-catalog entries are stored
    with kind='multiCatalog' and payload contains the list.
    """
    if not isinstance(raw, dict):
        return None

    # New shape: catalogSources[] (list of {addonId, type, catalogId})
    cs = raw.get('catalogSources') or raw.get('catalog_sources') or []
    if isinstance(cs, list) and cs:
        cleaned = []
        for src in cs:
            if not isinstance(src, dict):
                continue
            addon_id = (src.get('addonId') or src.get('addon_id') or '').strip()
            catalog_id = (src.get('catalogId') or src.get('catalog_id') or '').strip()
            ctype = (src.get('type') or src.get('catalogType') or 'movie').strip()
            catalog_id, ctype = normalize_catalog_id_and_type(catalog_id, ctype)
            if addon_id and catalog_id:
                cleaned.append({'addonId': addon_id, 'catalogId': catalog_id, 'catalogType': ctype, 'genre': src.get('genre') or '', 'extra': src.get('extra') or {}})
        if cleaned:
            entry = {
                'id': str(raw.get('id') or uuid.uuid4().hex[:12]),
                'name': str(raw.get('title') or raw.get('name') or 'Folder').strip() or 'Folder',
                'layout': 'Wide' if (raw.get('tileShape') or '').upper() == 'LANDSCAPE' else 'Poster',
                'background': str(raw.get('coverImageUrl') or raw.get('focusGifUrl') or raw.get('backgroundImageURL') or '').strip(),
                'clearlogo': str(raw.get('clearlogo') or raw.get('clearLogoUrl') or raw.get('clearLogoURL') or raw.get('titleLogoUrl') or raw.get('titleLogoURL') or raw.get('titleLogo') or raw.get('logo') or raw.get('logoURL') or raw.get('logoUrl') or '').strip(),
                'hide_title': bool(raw.get('hideTitle') or False),
                'kind': 'multiCatalog',
                'payload': {'sources': cleaned},
                # Catalog-source folders should open directly like skin widgets;
                # users can still switch to normal mode from the context menu.
                'open_mode': str(raw.get('open_mode') or raw.get('openMode') or 'skip').strip() or 'skip',
            }
            return entry

    # Old shape: dataSource / dataSources
    # v3.9.61: bug fix — the previous check was `if not isinstance(ds, dict)`
    # which was ALWAYS False because `raw.get('dataSource') or {}` always
    # returns a dict (an empty one when the key is missing). That meant the
    # fallback to the plural `dataSources` array — used by every Fusion
    # Widgets export — was never reached. As a result, Fusion configs
    # containing traktList items got rejected with "no valid items in file".
    # The fix: fall through whenever ds is empty OR not a dict, then pick the
    # first source from the plural array if present.
    ds = raw.get('dataSource') or {}
    if not ds or not isinstance(ds, dict):
        sources = raw.get('dataSources') or []
        ds = sources[0] if sources and isinstance(sources[0], dict) else {}
    kind = (ds.get('kind') or '').strip()
    payload = ds.get('payload') or {}
    if not kind or not isinstance(payload, dict):
        return None
    payload = dict(payload)
    if kind == 'addonCatalog':
        cid, ctype = normalize_catalog_id_and_type(
            payload.get('catalogId') or payload.get('catalog_id') or '',
            payload.get('catalogType') or payload.get('type') or 'movie',
        )
        if cid:
            payload['catalogId'] = cid
        if ctype:
            payload['catalogType'] = ctype

    # Fusion Widgets export uses imageURL + imageAspect instead of the
    # older poster/backgroundImageURL + layout/tileShape fields. Preserve that
    # aspect so imported section cards render as wide/landscape widgets instead
    # of blank or badly-cropped poster tiles in Kodi skins.
    image_aspect = str(raw.get('imageAspect') or raw.get('image_aspect') or '').strip().lower()
    tile_shape = str(raw.get('tileShape') or raw.get('tile_shape') or '').strip().lower()
    raw_layout = str(raw.get('layout') or '').strip()
    if raw_layout:
        layout = raw_layout
    elif image_aspect in ('wide', 'landscape', 'banner', '16:9', '16x9') or tile_shape in ('landscape', 'wide', 'banner'):
        layout = 'Wide'
    else:
        layout = 'Poster'

    image_url = str(raw.get('backgroundImageURL') or raw.get('coverImageUrl') or raw.get('imageURL') or raw.get('imageUrl') or '').strip()
    poster_url = str(raw.get('poster') or raw.get('posterURL') or raw.get('posterUrl') or '').strip()
    background_url = image_url or poster_url

    entry = {
        'id': str(raw.get('id') or uuid.uuid4().hex[:12]),
        'name': str(raw.get('name') or raw.get('title') or 'Collection').strip() or 'Collection',
        'layout': layout,
        'background': background_url,
        'image_aspect': image_aspect,
        'poster': poster_url,
        'clearlogo': str(raw.get('clearlogo') or raw.get('clearLogoUrl') or raw.get('clearLogoURL') or raw.get('titleLogoUrl') or raw.get('titleLogoURL') or raw.get('titleLogo') or raw.get('logo') or raw.get('logoURL') or raw.get('logoUrl') or '').strip(),
        'hide_title': bool(raw.get('hideTitle') or False),
        'kind': kind,
        'payload': payload,
    }
    return entry


def _expand_groups(data):
    """Walk top-level groups with `folders[]` and emit each folder as an entry.

    Supports the share-URL export format:
        [
          {"id": "...", "title": "خدمات البث", "folders": [
              {"id": "...", "title": "Netflix", "catalogSources": [...]},
              ...
          ]},
          ...
        ]
    """
    if not isinstance(data, list):
        return data
    expanded = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get('folders'), list):
            for folder in item['folders']:
                if isinstance(folder, dict):
                    # Carry the group title forward as a name prefix when the
                    # folder's own name is generic.
                    if folder.get('title') in (None, '', 'Folder', 'Collection'):
                        folder = dict(folder)
                        folder['title'] = item.get('title') or folder.get('title') or 'Folder'
                    expanded.append(folder)
        else:
            expanded.append(item)
    return expanded


def _flatten_fusion_widgets(data):
    """Flatten Fusion Widgets exports into normal collection entries.

    Fusion config files often look like:
        {
          "exportType": "fusionWidgets",
          "widgets": [
            {
              "title": "Latest Shows",
              "dataSource": {
                "kind": "collection",
                "payload": {"items": [ ... real entries ... ]}
              }
            }
          ]
        }

    Nuvio Hub expects the real entries directly. This helper unwraps the
    intermediate widget shell and preserves the widget title as a fallback
    label for generic child items.
    """
    def _copy_with_defaults(child, parent):
        if not isinstance(child, dict):
            return child
        row = dict(child)
        for key in ('backgroundImageURL', 'coverImageUrl', 'imageURL', 'imageUrl', 'poster', 'posterURL', 'posterUrl'):
            if not row.get(key) and parent.get(key):
                row[key] = parent.get(key)
                break
        if row.get('title') in (None, '', 'Folder', 'Collection') and parent.get('title'):
            row['title'] = parent.get('title')
        if row.get('name') in (None, '', 'Folder', 'Collection') and parent.get('name'):
            row['name'] = parent.get('name')
        return row

    def _unwrap(item):
        if not isinstance(item, dict):
            return [item]
        ds = item.get('dataSource') or {}
        payload = ds.get('payload') or {}
        kind = str(ds.get('kind') or '').strip().lower()
        items = payload.get('items') if isinstance(payload, dict) else None
        if kind == 'collection' and isinstance(items, list) and items:
            out = []
            for child in items:
                if isinstance(child, dict):
                    out.append(_copy_with_defaults(child, item))
            if out:
                return out
        return [item]

    if isinstance(data, dict):
        export_type = str(data.get('exportType') or data.get('type') or '').strip().lower()
        widgets = data.get('widgets') if isinstance(data.get('widgets'), list) else None
        if widgets and export_type in ('fusionwidgets', 'fusion_widgets', 'fusion-widget-export'):
            flattened = []
            for widget in widgets:
                flattened.extend(_unwrap(widget))
            return flattened
        return data

    if isinstance(data, list):
        flattened = []
        for item in data:
            flattened.extend(_unwrap(item))
        return flattened

    return data


def parse_collection_json(text):
    """Parse the raw text of a collection JSON into a list of normalized entries.

    Accepts:
      - Top-level array of entries (old format)
      - Top-level array of groups, each with `folders[]` (new share-URL format)
      - Top-level object with 'collections'/'widgets'/'entries' array
      - Fusion Widgets export files where real entries live under
        widgets[].dataSource.payload.items
    """
    try:
        data = json.loads(text)
    except Exception:
        try:
            data = json.loads(text.strip().lstrip('\ufeff'))
        except Exception:
            raise ValueError('JSON غير صالح')

    data = _flatten_fusion_widgets(data)

    if isinstance(data, dict):
        for key in ('collections', 'widgets', 'entries', 'items', 'folders'):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]

    data = _flatten_fusion_widgets(data)

    if not isinstance(data, list):
        raise ValueError('الملف لا يحتوي على قائمة عناصر')

    # Expand any top-level groups so each folder becomes its own entry.
    data = _expand_groups(data)

    out = []
    for raw in data:
        entry = _normalize_entry(raw)
        if entry:
            out.append(entry)
    if not out:
        raise ValueError('لم يتم العثور على عناصر صالحة في الملف')
    return out


# ── addon auto-registration ──────────────────────────────────────────────────


def _provider_for_manifest(manifest_url):
    wanted = _normalize_manifest_url(manifest_url)
    for row in _store.list_providers():
        if _normalize_manifest_url(row.get('manifest_url')) == wanted:
            return row
    return None


def find_provider_by_addon_id(addon_id):
    """Lookup a registered provider by its Stremio manifest id (e.g.
    'ar.stremiolab.collections') instead of by manifest URL.

    Used by share-URL collection imports where the JSON references addons
    by ID, not URL. Returns None if no installed provider matches. Plexio is
    intentionally fuzzy because configured servers may expose
    com.stremio.plexbridge while collection JSONs call it com.stremio.plexio.
    """
    if not addon_id:
        return None
    addon_id = str(addon_id).strip().lower()
    wants_plexio = 'plexio' in addon_id or addon_id in ('com.stremio.plexio', 'com.stremio.plexbridge', 'plexbridge') or 'plexbridge' in addon_id
    wants_streambridge = addon_id.startswith('streambridge') or addon_id in ('com.stremio.streambridge', 'com.stremio.dexbridge', 'dexbridge') or 'streambridge' in addon_id or 'dexbridge' in addon_id or addon_id.startswith('sb.')
    for row in _store.list_providers():
        manifest = row.get('manifest') or {}
        mid = str(manifest.get('id') or '').strip().lower()
        manifest_url = str(row.get('manifest_url') or '').strip().lower()
        name = str(row.get('name') or manifest.get('name') or '').strip().lower()
        if mid and mid == addon_id:
            return row
        if wants_plexio and (mid in ('com.stremio.plexbridge', 'com.stremio.plexio') or 'plexio' in manifest_url or 'plexio' in name or 'plexbridge' in name):
            return row
        if wants_streambridge and (mid in ('com.stremio.streambridge', 'com.stremio.dexbridge') or 'sb.dexworld.cc' in manifest_url or 'streambridge' in manifest_url or 'streambridge' in name or 'dexbridge' in name or 'emby' in name):
            return row
    return None


def _normalize_manifest_url(url):
    url = str(url or '').strip()
    if url.lower().endswith('/manifest.json/'):
        url = url[:-1]
    return url


def known_manifest_for_addon_id(addon_id):
    addon_id = str(addon_id or '').strip().lower()
    if not addon_id:
        return ''
    if addon_id in KNOWN_ADDON_MANIFESTS:
        return _normalize_manifest_url(KNOWN_ADDON_MANIFESTS.get(addon_id, ''))
    # Some Nuvio/Fusion exports use generated Plexio/StreamBridge ids or
    # URL-ish ids. They require the user's configured manifest, so do not map
    # them to a bundled private URL.
    return ''


def addon_requires_configuration(addon_id):
    addon_id = str(addon_id or '').strip().lower()
    if addon_id in CONFIG_REQUIRED_ADDONS:
        return True
    return (
        'plexio' in addon_id or
        'plexbridge' in addon_id or
        'streambridge' in addon_id or
        'dexbridge' in addon_id or
        addon_id.startswith('sb.')
    )


def resolve_or_register_addon(addon_id, manifest_resolver=None, share_url=''):
    """Return a provider row for a Stremio addon id/manifest URL when possible.

    Priority:
      1. already registered provider whose manifest.id matches addon_id
      2. addon_id itself if it is a manifest URL
      3. built-in known manifest map for public catalog addons
      4. optional UI resolver callback (for Plexio/configured/private addons)
    """
    addon_id = str(addon_id or '').strip()
    if not addon_id:
        return None
    existing = find_provider_by_addon_id(addon_id)
    if existing:
        return existing
    if addon_id.startswith(('http://', 'https://')):
        try:
            return ensure_addon_registered(addon_id)
        except Exception:
            return None
    manifest_url = known_manifest_for_addon_id(addon_id)
    if manifest_url:
        try:
            return ensure_addon_registered(manifest_url)
        except Exception:
            pass
    # If no configured/known URL exists, configured-only addons should not fall
    # through to a public empty shell manifest. Let the caller ask the user.
    if addon_requires_configuration(addon_id) and not manifest_resolver:
        return None
    if manifest_resolver:
        try:
            resolved = manifest_resolver(addon_id, share_url)
            if resolved:
                return ensure_addon_registered(resolved)
        except Exception:
            return None
    return None


def ensure_addon_registered(manifest_url):
    """Make sure the given manifest is in the provider list. Returns the provider row.

    If a matching provider already exists, returns it. Otherwise fetches the
    manifest, validates it, and adds it to the store.
    """
    manifest_url = _normalize_manifest_url(manifest_url)
    existing = _provider_for_manifest(manifest_url)
    if existing:
        return existing
    manifest = validate_manifest(manifest_url)
    name = manifest.get('name') or 'Addon'
    return _store.add_provider(name, manifest_url, manifest)


# ── CRUD for saved sets ──────────────────────────────────────────────────────


def list_sets():
    return _read()


def get_set(set_id):
    for row in _read():
        if row.get('id') == set_id:
            return row
    return None


def collect_referenced_addon_ids(entries):
    """Return list of unique Stremio addon IDs referenced by the collection.

    Looks at both legacy `addonCatalog` (single source per entry) and
    new-format `multiCatalog` (many sources per entry). The IDs returned are
    NOT manifest URLs — they're Stremio addon `id` values like
    `ar.stremiolab.collections`.
    """
    seen = []
    seen_set = set()
    for entry in entries or []:
        kind = entry.get('kind')
        if kind == 'addonCatalog':
            aid = ((entry.get('payload') or {}).get('addonId') or '').strip()
            if aid and aid not in seen_set:
                seen_set.add(aid)
                seen.append(aid)
        elif kind == 'multiCatalog':
            for src in (entry.get('payload') or {}).get('sources') or []:
                aid = (src.get('addonId') or '').strip()
                if aid and aid not in seen_set:
                    seen_set.add(aid)
                    seen.append(aid)
    return seen


def derive_addon_manifest_url(share_url, addon_id):
    """Return a useful manifest hint for collection imports.

    Plexio/DexWorld collection URLs live next to the configured manifest, so
    /collections.json can be promoted to /manifest.json automatically. For
    Stremiolab/Nuvio collection hosts we still return the host prefix as a
    manual hint because their share token does not expose a manifest URL.
    """
    sibling = manifest_url_from_collections_url(share_url)
    if sibling:
        return sibling
    if not share_url:
        return ''
    try:
        from urllib.parse import urlparse
        parsed = urlparse(share_url)
        if parsed.netloc and 'collections' in parsed.netloc.lower():
            return '%s://%s/' % (parsed.scheme or 'https', parsed.netloc)
    except Exception:
        pass
    return ''


def add_set_from_url(url, name=None, manifest_resolver=None):
    """Fetch a collection JSON, parse it, and persist it.

    For each unique addonId referenced by the entries, attempt to register
    the addon. Plexio/DexWorld collections.json URLs are also registered as a
    normal provider by swapping /collections.json -> /manifest.json, so opening
    the imported collection can play immediately without asking for the same
    manifest URL again.

    v3.9.60: defensive — addon-resolution failures no longer abort the
    whole import. Entries are saved regardless; addon resolution is a
    convenience for catalog entries that need a provider, but trakt/
    mdblist/kodi-route entries don't depend on it, and saving them
    even when some resolution step fails gives the user something
    usable instead of nothing.
    """
    url = (url or '').strip()
    if not url:
        raise ValueError('رابط فارغ')
    text = _fetch_raw_text(url)
    entries = parse_collection_json(text)

    # Log a summary so kodi.log shows exactly what got parsed and saved.
    try:
        import xbmc as _xbmc
        kinds = {}
        for e in entries:
            k = e.get('kind') or '?'
            kinds[k] = kinds.get(k, 0) + 1
        _xbmc.log('[NuvioHub] add_set_from_url parsed %d entries: %s' % (
            len(entries), ', '.join('%s=%d' % (k, v) for k, v in kinds.items())),
            _xbmc.LOGINFO)
    except Exception:
        pass

    sibling_manifest = manifest_url_from_collections_url(url)
    if sibling_manifest:
        try:
            ensure_addon_registered(sibling_manifest)
        except Exception:
            # Keep collection import usable even if the source is temporarily
            # unreachable; individual entries can still resolve through their
            # explicit addonId or a later refresh.
            pass

    def _resolver(addon_id, share_url):
        if sibling_manifest:
            try:
                if addon_requires_configuration(addon_id) or 'plex' in str(addon_id or '').lower():
                    return sibling_manifest
            except Exception:
                return sibling_manifest
        if manifest_resolver:
            return manifest_resolver(addon_id, share_url)
        return ''

    # Collect all referenced addonIds from any kind of entry. Trakt/
    # MDBList/Kodi-route entries don't reference any addonId so this
    # returns an empty list for the user's Fusion config — no resolver
    # prompts and no auxiliary failures can block the save.
    try:
        referenced = collect_referenced_addon_ids(entries)
    except Exception:
        referenced = []

    seen_addons = {}
    for addon_id in referenced:
        if addon_id in seen_addons:
            continue
        try:
            seen_addons[addon_id] = resolve_or_register_addon(
                addon_id,
                manifest_resolver=_resolver,
                share_url=url,
            )
        except Exception as exc:
            # v3.9.60: a failed addon registration must NOT abort the
            # whole import. Log it and continue — the entry is still
            # persisted and will work if the addon gets installed later.
            try:
                import xbmc as _xbmc
                _xbmc.log('[NuvioHub] addon resolve failed for %s: %s — continuing' % (addon_id, exc), _xbmc.LOGWARNING)
            except Exception:
                pass

    set_row = {
        'id': hashlib.sha1(url.encode('utf-8')).hexdigest()[:12],
        'name': (name or _derive_set_name(url, entries)).strip(),
        'source_url': url,
        'entries': entries,
    }

    rows = _read()
    rows = [r for r in rows if r.get('id') != set_row['id']]
    rows.append(set_row)
    _write(rows)
    return set_row

def rename_set(set_id, new_name):
    new_name = (new_name or '').strip()
    if not new_name:
        raise ValueError('الاسم فارغ')
    rows = _read()
    changed = False
    for r in rows:
        if r.get('id') == set_id:
            r['name'] = new_name
            changed = True
            break
    if not changed:
        raise ValueError('المجموعة غير موجودة')
    _write(rows)


def update_entry(set_id, entry_id, updates):
    """Update fields of a single entry inside a set.

    `updates` is a dict that may include any of: name, background, layout,
    hide_title, or keys inside payload (prefixed with 'payload.') like
    'payload.username', 'payload.listSlug', 'payload.addonId'.
    """
    rows = _read()
    target_set = None
    for r in rows:
        if r.get('id') == set_id:
            target_set = r
            break
    if not target_set:
        raise ValueError('المجموعة غير موجودة')
    target_entry = None
    for e in (target_set.get('entries') or []):
        if e.get('id') == entry_id:
            target_entry = e
            break
    if not target_entry:
        raise ValueError('العنصر غير موجود')
    for k, v in (updates or {}).items():
        if k.startswith('payload.'):
            payload = target_entry.setdefault('payload', {})
            payload[k.split('.', 1)[1]] = v
        else:
            target_entry[k] = v
    _write(rows)
    return target_entry


def remove_entry(set_id, entry_id):
    rows = _read()
    for r in rows:
        if r.get('id') == set_id:
            before = len(r.get('entries') or [])
            r['entries'] = [e for e in (r.get('entries') or []) if e.get('id') != entry_id]
            if len(r['entries']) == before:
                raise ValueError('العنصر غير موجود')
            # Deleting one entry should be instant from the context menu.  Use
            # the compact atomic writer instead of the full backup+fsync path.
            _write_fast(rows)
            return True
    raise ValueError('المجموعة غير موجودة')


def add_custom_entry(set_id, name, kind, payload, background='', open_mode='normal'):
    """Manually add a new entry to a set (for users who want to build
    collections by hand instead of importing JSON)."""
    import uuid as _uuid
    rows = _read()
    for r in rows:
        if r.get('id') == set_id:
            entry = {
                'id': _uuid.uuid4().hex[:12],
                'name': (name or 'Collection').strip(),
                'layout': 'Poster',
                'background': (background or '').strip(),
                'hide_title': False,
                'open_mode': (open_mode or 'normal').strip() or 'normal',
                'kind': kind,
                'payload': dict(payload or {}),
            }
            r.setdefault('entries', []).append(entry)
            _write(rows)
            return entry
    raise ValueError('المجموعة غير موجودة')


def create_empty_set(name):
    """Create a new empty set the user can populate manually."""
    import uuid as _uuid, time as _t
    rows = _read()
    new_id = _uuid.uuid4().hex[:12]
    while any(r.get('id') == new_id for r in rows):
        new_id = _uuid.uuid4().hex[:12]
    set_row = {
        'id': new_id,
        'name': (name or 'مجموعة جديدة').strip() or 'مجموعة جديدة',
        'source_url': '',
        'entries': [],
        'created_at': int(_t.time()),
    }
    rows.append(set_row)
    _write(rows)
    return set_row


def add_set_from_text(text, source_label='مُدخل يدويًا', manifest_resolver=None):
    """Parse raw JSON text (paste) and persist as a new set.

    Mirrors `add_set_from_url`: collects unique addonIds across all entry
    kinds, auto-registers what we can, and falls back to `manifest_resolver`
    (caller-provided UI prompt) for missing ones.
    """
    entries = parse_collection_json(text)

    referenced = collect_referenced_addon_ids(entries)
    seen_addons = {}
    for addon_id in referenced:
        if addon_id in seen_addons:
            continue
        seen_addons[addon_id] = resolve_or_register_addon(
            addon_id,
            manifest_resolver=manifest_resolver,
            share_url='',
        )

    set_row = {
        'id': hashlib.sha1(text.encode('utf-8')).hexdigest()[:12],
        'name': source_label or 'Collection Set',
        'source_url': '',
        'entries': entries,
    }
    rows = _read()
    rows = [r for r in rows if r.get('id') != set_row['id']]
    rows.append(set_row)
    _write(rows)
    return set_row


def remove_set(set_id):
    rows = [r for r in _read() if r.get('id') != set_id]
    _write(rows)


def refresh_set(set_id, manifest_resolver=None):
    row = get_set(set_id)
    if not row or not row.get('source_url'):
        raise ValueError('لا يمكن تحديث مجموعة بدون رابط مصدر')
    return add_set_from_url(row['source_url'], name=row.get('name') or None, manifest_resolver=manifest_resolver)


# ── helpers ──────────────────────────────────────────────────────────────────


def _decode_share_token(token):
    """Decode a stremiolabar.com /api/share/<token> payload.

    Token is URL-safe base64 of gzip-compressed JSON. Returns the decoded
    JSON text on success, or None on any decoding failure (caller falls
    back to a normal HTTP fetch).
    """
    if not token:
        return None
    import base64 as _b64, gzip as _gzip
    try:
        # URL-safe base64 (uses - and _ instead of + and /). Pad to multiple of 4.
        padded = token + ('=' * ((4 - len(token) % 4) % 4))
        try:
            raw = _b64.urlsafe_b64decode(padded)
        except Exception:
            # Fallback: standard b64 with manual char swap.
            fixed = token.replace('-', '+').replace('_', '/')
            fixed += '=' * ((4 - len(fixed) % 4) % 4)
            raw = _b64.b64decode(fixed)
        # Try gzip decompress (most common case).
        try:
            decompressed = _gzip.decompress(raw)
        except Exception:
            # Token may be plain base64 of JSON without gzip.
            decompressed = raw
        return decompressed.decode('utf-8', 'replace')
    except Exception as exc:
        import xbmc
        xbmc.log('[NuvioHub] share token decode failed: %s' % exc, xbmc.LOGDEBUG)
        return None


def fetch_raw_text(url):
    """Public: fetch raw text from a URL with gzip support. Raises on HTTP errors.

    Special-cases stremiolabar.com share URLs: extracts the token after
    /api/share/ and decodes it locally instead of hitting the server.
    """
    return _fetch_raw_text(url)


def _fetch_raw_text(url):
    """Fetch raw text; supports inline share-token decoding and normal HTTP.

    v3.9.60: hardened with multiple fallbacks. If the standard urllib
    request fails for network or SSL reasons, we retry with:
      1. SSL verification disabled (some CoreELEC builds ship with a
         truncated CA store that rejects valid Let's Encrypt and
         Cloudflare R2 certs)
      2. urllib3 if available
      3. requests if available
    Each fallback is logged so kodi.log shows exactly which path
    succeeded — useful for diagnosing future issues.
    """
    import gzip as _gzip, io as _io, ssl as _ssl
    from urllib.request import Request, urlopen

    # Inline share token: most stremiolabar.com share URLs encode the
    # entire collection in the URL itself — no server call needed.
    if '/api/share/' in (url or ''):
        token = url.rsplit('/api/share/', 1)[-1].split('?', 1)[0].split('#', 1)[0]
        decoded = _decode_share_token(token)
        if decoded:
            return decoded
        # Fall through to HTTP if decode fails (server may still return JSON).

    # v3.9.62: bug fix — ADDON was never imported in this module, so
    # the User-Agent line raised NameError as soon as a URL was fetched.
    # The bug existed in the v3.9.58 baseline too but was masked by the
    # generic error handling. Resolve it now via a local defensive lookup
    # that survives if xbmcaddon isn't available.
    try:
        import xbmcaddon as _xa
        _ver = _xa.Addon().getAddonInfo('version') or '3.8.9'
    except Exception:
        _ver = '3.8.9'

    headers = {
        'Accept': 'application/json, text/plain, */*',
        'Accept-Encoding': 'gzip',
        'User-Agent': 'NuvioHub/%s (Kodi)' % _ver,
    }

    def _read_body(resp):
        body = resp.read()
        enc = (resp.headers.get('Content-Encoding') or '').lower()
        if 'gzip' in enc:
            try:
                body = _gzip.GzipFile(fileobj=_io.BytesIO(body)).read()
            except Exception:
                pass
        return body.decode('utf-8', 'replace')

    last_err = None
    # Attempt 1: standard urlopen with default SSL verification.
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=20) as resp:
            return _read_body(resp)
    except Exception as exc:
        last_err = exc
        try:
            import xbmc as _xbmc
            _xbmc.log('[NuvioHub] fetch_raw_text default fetch failed: %s — trying unverified SSL' % exc, _xbmc.LOGINFO)
        except Exception:
            pass

    # Attempt 2: unverified SSL context — covers stale CA stores.
    try:
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        req = Request(url, headers=headers)
        with urlopen(req, timeout=20, context=ctx) as resp:
            try:
                import xbmc as _xbmc
                _xbmc.log('[NuvioHub] fetch_raw_text succeeded with unverified SSL', _xbmc.LOGINFO)
            except Exception:
                pass
            return _read_body(resp)
    except Exception as exc:
        last_err = exc
        try:
            import xbmc as _xbmc
            _xbmc.log('[NuvioHub] fetch_raw_text unverified SSL failed: %s' % exc, _xbmc.LOGINFO)
        except Exception:
            pass

    # Attempt 3: third-party requests library if available.
    try:
        import requests as _requests  # type: ignore
        # --- dexhub-401-patch --- verify TLS; this is a public https endpoint
        resp = _requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        try:
            import xbmc as _xbmc
            _xbmc.log('[NuvioHub] fetch_raw_text succeeded via requests library', _xbmc.LOGINFO)
        except Exception:
            pass
        return resp.text
    except ImportError:
        pass
    except Exception as exc:
        last_err = exc

    # All attempts failed — raise the most recent error with context.
    raise last_err if last_err else IOError('Unknown fetch failure')


def _derive_set_name(url, entries):
    try:
        tail = url.rsplit('/', 1)[-1]
        if tail:
            base = tail.rsplit('.', 1)[0]
            if base:
                return base.replace('-', ' ').replace('_', ' ').title()
    except Exception:
        pass
    if entries:
        return '%d collection%s' % (len(entries), 's' if len(entries) > 1 else '')
    return 'Collection Set'


def import_sets(rows):
    """Merge backup rows into collection_sets.json and return count imported.

    The backup format is intentionally plain JSON so users can share it. Existing
    IDs are replaced, which lets a shared backup update the same collection cleanly.
    """
    incoming = []
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        entries = row.get('entries') or []
        if not isinstance(entries, list):
            continue
        rid = str(row.get('id') or '').strip() or hashlib.sha1(json.dumps(entries, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:12]
        incoming.append({
            'id': rid,
            'name': str(row.get('name') or row.get('title') or 'Shared Collection').strip(),
            'source_url': str(row.get('source_url') or row.get('source') or '').strip(),
            'entries': entries,
        })
    if not incoming:
        return 0
    current = _read()
    incoming_ids = {r.get('id') for r in incoming}
    merged = [r for r in current if r.get('id') not in incoming_ids]
    merged.extend(incoming)
    _write(merged)
    return len(incoming)
