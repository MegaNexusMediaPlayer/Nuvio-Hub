# -*- coding: utf-8 -*-
import os
import re
import time

import xbmc
import xbmcaddon

from . import store
from .client import fetch_subtitles, supports_resource, start_parallel_race

# --- dexhub-401-patch ---
try:
    from .settings_cache import cached_addon as _dh_cached_addon
except Exception:
    try:
        from settings_cache import cached_addon as _dh_cached_addon
    except Exception:
        _dh_cached_addon = None
ADDON = _dh_cached_addon() if _dh_cached_addon else xbmcaddon.Addon('plugin.video.nuviohub')


def _timeout_seconds():
    try:
        return max(10, min(20, int(ADDON.getSetting('subtitle_timeout') or '15')))
    except Exception:
        return 15


def enabled():
    """v3.9.108: subtitle search is OFF by default. Two equivalent ways to
    enable it:
      1. switch subtitle_search_mode to 'Play with subtitles'  (recommended)
      2. flip the dedicated 'enable_stremio_subtitle_broker' toggle on

    The mode-driven path means a user who picks 'Play with subtitles' never
    has to also hunt down a second toggle — picking that mode IS the intent.
    """
    try:
        explicit = (ADDON.getSetting('enable_stremio_subtitle_broker') or 'true').lower() == 'true'
        if explicit:
            return True
        try:
            mode = (ADDON.getSetting('subtitle_search_mode') or '').strip().lower()
            if 'subtitle' in mode or 'with sub' in mode:  # 'Play with subtitles'
                return True
        except Exception:
            pass
        return False
    except Exception:
        return False


def _normalize_lang(value):
    if isinstance(value, (list, tuple, set)):
        for item in value:
            key = _normalize_lang(item)
            if key and key != 'und':
                return key
        return 'und'
    if isinstance(value, dict):
        for k in ('lang', 'language', 'languageCode', 'iso639', 'code', 'name'):
            if value.get(k):
                key = _normalize_lang(value.get(k))
                if key and key != 'und':
                    return key
        return 'und'
    try:
        converted=xbmc.convertLanguage(str(value or ''),xbmc.ISO_639_1) or xbmc.convertLanguage(str(value or ''),xbmc.ISO_639_2)
        if converted:return converted.lower()
    except Exception:pass
    raw = str(value or 'und').strip().lower().replace('_', '-').replace(' ', '-')
    if not raw:
        return 'und'
    aliases = {
        'hrv':'hr','cro':'hr','croatian':'hr','hrvatski':'hr',
        'srp':'sr','ser':'sr','serbian':'sr','bos':'bs','bosnian':'bs','slv':'sl','slovenian':'sl',
        'ara': 'ar', 'arabic': 'ar', 'عربي': 'ar', 'عربية': 'ar', 'العربية': 'ar',
        'eng': 'en', 'english': 'en',
        'fre': 'fr', 'fra': 'fr', 'french': 'fr',
        'spa': 'es', 'spanish': 'es',
        'ger': 'de', 'deu': 'de', 'german': 'de',
        'por': 'pt', 'pob': 'pt-br', 'pb': 'pt-br', 'brazilian': 'pt-br',
        'tur': 'tr', 'turkish': 'tr',
        'rus': 'ru', 'russian': 'ru',
        'jpn': 'ja', 'japanese': 'ja',
        'kor': 'ko', 'korean': 'ko',
        'chi': 'zh', 'zho': 'zh', 'chinese': 'zh',
        'hin': 'hi', 'hindi': 'hi',
        'fas': 'fa', 'per': 'fa', 'persian': 'fa', 'farsi': 'fa',
    }
    return aliases.get(raw, aliases.get(raw.split('-')[0], raw))


def _display_name_from_url(url):
    """v3.9.105: extract a sensible display name from a subtitle URL when the
    Stremio addon doesn't provide one in metadata. Stops Kodi's subtitle list
    from being polluted with addon-brand names like 'Subtitio - Arabic.srt'
    when the URL itself carries the real release name."""
    if not url:
        return ''
    try:
        from urllib.parse import urlparse as _urlparse, unquote as _unquote
        path = _urlparse(str(url)).path or ''
        if not path:
            return ''
        # Take last path segment and strip any extension.
        leaf = _unquote(path.rsplit('/', 1)[-1])
        if not leaf:
            return ''
        for ext in ('.srt', '.vtt', '.ass', '.ssa', '.sub', '.sbv', '.idx',
                    '.zip', '.gz', '.7z'):
            if leaf.lower().endswith(ext):
                leaf = leaf[:-len(ext)]
                break
        # Skip if it's just a hash / id (no letters, no dots) — those carry no
        # useful info. Examples we DO want: "Top.Gun.Maverick.2022.ar".
        # Examples we DON'T want: "abc123def".
        if leaf and ('.' in leaf or ' ' in leaf or '-' in leaf or '_' in leaf):
            return leaf.strip()
        return ''
    except Exception:
        return ''


def _coerce_subtitle(row):
    if not row:
        return None
    if isinstance(row, str):
        return {'id': row, 'url': row, 'lang': 'und'}
    if not isinstance(row, dict):
        return None
    url = row.get('url') or row.get('externalUrl') or row.get('key')
    if not url:
        return None
    out = dict(row)
    out['url'] = url
    out['lang'] = _normalize_lang(row.get('lang') or row.get('language') or row.get('languageCode') or row.get('iso639') or 'und')
    source_name = row.get('sourceName') or row.get('providerName') or row.get('provider') or row.get('addonName') or row.get('addon') or row.get('sourceAddon') or row.get('source')
    if source_name:
        out['sourceName'] = source_name
    source_type = row.get('sourceType') or row.get('origin')
    if source_type:
        out['sourceType'] = str(source_type)
    display_name = row.get('displayName') or row.get('label') or row.get('title') or row.get('name') or row.get('release') or row.get('filename') or row.get('fileName')
    # v3.9.105: when the addon metadata lacks any display_name, derive one from
    # the URL filename. Many Stremio sub addons (Subtitio, etc.) only return
    # url+lang, and without this fallback the user sees "AddonName - Arabic.srt"
    # in Kodi's subtitle list instead of the actual release name embedded in
    # the download URL.
    if not display_name:
        display_name = _display_name_from_url(url)
    if display_name:
        out['displayName'] = str(display_name)
    return out


def _dedupe(rows):
    out = []
    seen = set()
    for row in rows:
        norm = _coerce_subtitle(row)
        if not norm:
            continue
        key = (norm.get('url') or '', norm.get('lang') or 'und')
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


def _candidate_ids(ctx):
    """Return only valid Stremio subtitle IDs.

    Movies:   tt1234567 (preferred), then tmdb:123 / tvdb:123.
    Episodes: tt1234567:S:E, then tmdb:123:S:E / tvdb:123:S:E.

    Never emit ``imdb:tt...`` and never append S/E to an ID that already
    contains an episode suffix. Those malformed variants were accepted by
    some addons but interpreted literally by Dex subtitles, producing values
    such as ``imdb:tt1981558:1:1`` or ``tt...:1:1:1:1``.
    """
    def _imdb(value):
        text = str(value or '').strip().lower()
        if text.startswith('imdb:'):
            text = text.split(':', 1)[1]
        m = re.search(r'\btt\d{5,10}\b', text, re.I)
        return m.group(0).lower() if m else ''

    def _numeric(value, prefix):
        text = str(value or '').strip().lower()
        if text.startswith(prefix + ':'):
            text = text.split(':', 1)[1]
        # Strip accidental episode suffix before validating the base id.
        text = text.split(':', 1)[0]
        return text if text.isdigit() else ''

    imdb = _imdb(ctx.get('imdb_id'))
    tmdb = _numeric(ctx.get('tmdb_id'), 'tmdb')
    tvdb = _numeric(ctx.get('tvdb_id'), 'tvdb')

    # Recover clean IDs from canonical/video IDs without copying their suffix.
    for key in ('canonical_id', 'video_id'):
        raw = str(ctx.get(key) or '').strip()
        if not imdb:
            imdb = _imdb(raw)
        low = raw.lower()
        if not tmdb and low.startswith('tmdb:'):
            tmdb = _numeric(raw, 'tmdb')
        if not tvdb and low.startswith('tvdb:'):
            tvdb = _numeric(raw, 'tvdb')

    is_episode = str(ctx.get('media_type') or '').lower() in (
        'series', 'episode', 'show', 'tv', 'anime')
    season = episode = None
    if is_episode:
        try:
            season = int(ctx.get('season'))
            episode = int(ctx.get('episode'))
        except Exception:
            season = episode = None
        if season is None or episode is None or season < 0 or episode < 0:
            return []

    bases = []
    if imdb:
        bases.append(imdb)
    if tmdb:
        bases.append('tmdb:%s' % tmdb)
    if tvdb:
        bases.append('tvdb:%s' % tvdb)

    out = []
    for base in bases:
        item = '%s:%d:%d' % (base, season, episode) if is_episode else base
        if item not in out:
            out.append(item)
    return out


def _resolve_imdb_for_subtitles(ctx, timeout_seconds=None):
    """Look up the IMDb id for this item, cheaply and only when needed.

    Uses the TMDb lookup NuvioHub already caches, so a repeat request for the
    same title costs nothing. Any failure returns '' and the broker simply
    proceeds with whatever ids it has.
    """
    tmdb_id = str((ctx or {}).get('tmdb_id') or '').strip()
    if not tmdb_id:
        raw = str((ctx or {}).get('canonical_id') or '').strip().lower()
        if raw.startswith('tmdb:'):
            tmdb_id = raw.split(':', 1)[1].split(':', 1)[0]
    if not tmdb_id:
        return ''
    media_type = str((ctx or {}).get('media_type') or 'movie').lower()
    kind = 'series' if media_type in ('series', 'show', 'tv', 'anime', 'episode') else 'movie'
    try:
        from . import tmdb_direct
        kwargs = {'media_type': kind}
        if timeout_seconds not in (None, ''):
            kwargs['timeout'] = max(1.0, float(timeout_seconds))
        return str(tmdb_direct.imdb_id_for(tmdb_id, **kwargs) or '').strip()
    except Exception:
        return ''


def _provider_order(ctx):
    rows = list(store.list_providers())
    preferred = str(ctx.get('provider_id') or '').strip()
    if not preferred:
        return rows
    front = [row for row in rows if row.get('id') == preferred]
    back = [row for row in rows if row.get('id') != preferred]
    return front + back


def _preferred_languages():
    raw = (ADDON.getSetting('preferred_subtitle_langs') or 'ar,en').strip()
    if not raw:
        return ['ar', 'en']
    return [x.strip().lower() for x in raw.split(',') if x.strip()]


def _lang_priority(lang, prefs):
    """Return sort priority — lower is better. Preferred langs rank by position."""
    lang = (lang or 'und').strip().lower().replace('_', '-')
    # Normalize common codes.
    alias = {'ara': 'ar', 'arabic': 'ar', 'eng': 'en', 'english': 'en'}
    lang_short = alias.get(lang, lang.split('-')[0])
    for i, pref in enumerate(prefs):
        if lang_short == pref:
            return i
    return 999 + len(lang_short)  # unpreferred — stable last


def _sort_by_lang_preference(rows):
    prefs = _preferred_languages()
    return sorted(rows, key=lambda r: (
        _lang_priority(r.get('lang'), prefs),
        # Stream-embedded subtitles first (most likely to match the file),
        # then addon results grouped by source name for readability.
        0 if r.get('sourceType') == 'stream' else 1,
        str(r.get('sourceName') or r.get('providerName') or 'zzz').lower(),
    ))


# Per-process subtitle result cache. Key = (canonical_id, season, episode).
# TTL is short — subtitle availability changes day-to-day — but within a
# single playback or back-and-forth session, hits are common.
_RESULT_CACHE = {}
_RESULT_CACHE_ORDER = []
_RESULT_CACHE_MAX = 64
_RESULT_TTL = 600  # 10 minutes


def _result_cache_get(key):
    entry = _RESULT_CACHE.get(key)
    if not entry:
        return None
    expires, value = entry
    if expires < time.monotonic():
        _RESULT_CACHE.pop(key, None)
        return None
    return value


def _result_cache_put(key, value):
    if key in _RESULT_CACHE:
        _RESULT_CACHE[key] = (time.monotonic() + _RESULT_TTL, value)
        return
    _RESULT_CACHE[key] = (time.monotonic() + _RESULT_TTL, value)
    _RESULT_CACHE_ORDER.append(key)
    if len(_RESULT_CACHE_ORDER) > _RESULT_CACHE_MAX:
        old = _RESULT_CACHE_ORDER.pop(0)
        _RESULT_CACHE.pop(old, None)


def search_subtitles(ctx, initial_subtitles=None, max_results=12):
    """Query every installed Stremio subtitle addon in parallel.

    Older builds walked providers sequentially under one four-second deadline.
    A slow first addon starved every addon after it, so users saw server
    sidecars but none of their Stremio subtitle services. This mirrors the
    Stremio model: one independent request per subtitle addon, all racing under
    a shared deadline, then merge/dedupe/sort by preferred language.
    """
    rows = _dedupe(initial_subtitles or [])
    if not enabled() and not ctx.get('nuvio_subtitle_language'):
        return _sort_by_lang_preference(rows)[:max_results]
    # A selected/source-native subtitle is already matched to this exact file.
    # Do not hold playback open for unrelated addon providers once it exists;
    # the timeout is a ceiling for finding a subtitle, not a mandatory delay.
    if any((row or {}).get('user_selected') or
           str((row or {}).get('sourceType') or '').lower() in
           ('manual', 'stream', 'native', 'embedded', 'external')
           for row in rows):
        return _sort_by_lang_preference(rows)[:max_results]
    media_type = str(ctx.get('media_type') or 'movie').strip().lower() or 'movie'

    cache_key = (
        media_type,
        str(ctx.get('canonical_id') or ''),
        str(ctx.get('season') or ''),
        str(ctx.get('episode') or ''),
    )
    if cache_key[1]:
        cached = _result_cache_get(cache_key)
        if cached is not None:
            merged = _dedupe(rows + cached)
            return _sort_by_lang_preference(merged)[:max_results]

    timeout = float(_timeout_seconds())
    started = time.monotonic()
    deadline = started + timeout
    # Prefetch starts at the same instant as source discovery. Honour that
    # absolute deadline for ID resolution and provider requests alike.
    try:
        shared_deadline = float(ctx.get('subtitle_deadline_mono') or 0.0)
        if shared_deadline > 0.0:
            deadline = min(deadline, shared_deadline)
    except Exception:
        pass

    candidates = _candidate_ids(ctx)
    if not candidates or not any(c.startswith('tt') for c in candidates):
        # v4.8.8: resolve the IMDb id when we do not already have one.
        # Verified against the DexWorld subtitles engine (ai_subtitles.js):
        # its manifest declares idPrefixes ["tt"], so a request carrying only
        # tmdb:/tvdb: ids can never be answered — and NuvioHub has deferred
        # IMDb resolution since 4.5.0, which means the common case reached
        # this addon in a shape it does not serve. Most Stremio subtitle
        # addons (OpenSubtitles included) are IMDb-only for the same reason.
        resolution_budget = max(0.0, deadline - time.monotonic())
        resolved = (_resolve_imdb_for_subtitles(
            ctx, timeout_seconds=resolution_budget)
            if resolution_budget >= 1.0 else '')
        if resolved:
            ctx = dict(ctx)
            ctx['imdb_id'] = resolved
            candidates = _candidate_ids(ctx)
    if not candidates:
        return _sort_by_lang_preference(rows)[:max_results]
    # IMDb episode id variants are usually first and strongest. Keep enough
    # fallbacks for addons that only understand TMDb/TVDb, without spamming.
    candidates = candidates[:5]
    providers = list(_provider_order(ctx))
    if not providers:
        return _sort_by_lang_preference(rows)[:max_results]

    available = max(0.0, deadline - time.monotonic())
    if available <= 0.0:
        return _sort_by_lang_preference(rows)[:max_results]

    def _query_provider(provider):
        provider_rows = []
        for item_id in candidates:
            remain = deadline - time.monotonic()
            if remain <= 0:
                break
            try:
                if not supports_resource(provider, 'subtitles', media_type=media_type, item_id=item_id):
                    continue
                data = fetch_subtitles(
                    provider, media_type, item_id,
                    timeout_seconds=max(1, min(remain, timeout)),
                )
                subs = data.get('subtitles') or data.get('subs') or [] if isinstance(data, dict) else (data if isinstance(data, list) else [])
                if not subs:
                    continue
                for sub in subs:
                    row = dict(sub) if isinstance(sub, dict) else {'url': sub, 'id': sub, 'lang': 'und'}
                    row.setdefault('sourceType', 'addon')
                    row.setdefault('sourceName', provider.get('name') or provider.get('id') or 'Subtitle addon')
                    provider_rows.append(row)
                # One successful ID form is enough for this addon; querying its
                # aliases mostly returns duplicates and wastes the deadline.
                break
            except Exception as exc:
                xbmc.log('[NuvioHub] subtitle broker error for %s %s: %s' % (
                    provider.get('name'), item_id, exc), xbmc.LOGDEBUG)
        return provider_rows

    fetched_for_cache = []
    # Three workers are enough to keep Arabic providers parallel while
    # leaving headroom for the simultaneous stream scan on small CoreELEC
    # boxes.  The previous four-worker lane plus its coordinator thread could
    # overlap a six-worker stream lane and exhaust Kodi's native thread quota.
    workers = max(1, min(len(providers), 3))
    race = start_parallel_race(
        _query_provider, providers, workers=workers,
        timeout=max(0.1, available), lane='subtitles')
    try:
        while not race.done:
            completed = race.poll(0.05)
            for _provider, value in completed:
                found = [] if isinstance(value, Exception) else (value or [])
                if not found:
                    continue
                rows.extend(found)
                fetched_for_cache.extend(found)
    finally:
        race.cancel()

    if cache_key[1] and fetched_for_cache:
        _result_cache_put(cache_key, _dedupe(fetched_for_cache))

    result = _sort_by_lang_preference(_dedupe(rows))[:max_results]
    xbmc.log('[NuvioHub] Stremio subtitle broker: %d addon(s), %d result(s), %.1fs budget' % (
        len(providers), len(result), timeout), xbmc.LOGINFO)
    return result
