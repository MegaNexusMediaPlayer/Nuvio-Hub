# -*- coding: utf-8 -*-
"""Subtitle file handling — extracted from plugin.py (v3.9.264 decomposition).

Everything here deals with fetching, caching, naming, filtering and applying
subtitle files around playback. The functions are unchanged; only their home
moved. plugin.py re-exports every public name so existing callers and Kodi
routes keep working.

Heavy plugin functions (`season`, `streams`, `_jsonrpc_call`) are reached via
a late import to avoid a circular dependency at module load.
"""
import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from ..i18n import tr
from .. import plex_client

# --- nuviohub-401-patch ---
try:
    # This module lives one package below resources.lib.  The old relative
    # import used ``.settings_cache`` (playback.settings_cache), which does not
    # exist, so every playback invocation silently created another Addon()
    # object and bypassed the shared settings cache.
    from ..settings_cache import cached_addon as _dh_cached_addon
except Exception:
    try:
        from settings_cache import cached_addon as _dh_cached_addon
    except Exception:
        _dh_cached_addon = None
ADDON = _dh_cached_addon() if _dh_cached_addon else xbmcaddon.Addon('plugin.video.nuviohub')
ADDON_ID = ADDON.getAddonInfo('id')


def _plugin():
    """Late accessor for plugin.py (circular-safe)."""
    from .. import plugin as _p
    return _p


def _jsonrpc_call(method, params=None):
    return _plugin()._jsonrpc_call(method, params)

# v3.9.266: names this module references that live elsewhere. Constants come
# from context.py (their home); plugin-side helpers are reached lazily to keep
# the circular-safe boundary. This closes the extraction gap that raised
# NameError: _normalize_ascii at playback time.
from ..context import (  # noqa: E402
    COLOR_TAG_RE, STREAM_ICON_RE, REGIONAL_FLAG_RE, MULTI_WS_RE,
    WINDOW_ID, SUBS_DIR, LANG_MAP, build_url, notify, error, _get_int_setting,
)
from urllib.parse import parse_qsl  # noqa: E402
from .. import cache_store  # noqa: E402


def allow_automatic(*a, **k):
    from .subtitles import allow_automatic as _f
    return _f(*a, **k)


def _normalize_ascii(value):
    return _plugin()._normalize_ascii(value)


def _regional_flag_to_code(match):
    return _plugin()._regional_flag_to_code(match)



_SUBS_TMP_DIRNAME = 'nuviohub_subs'

_FILENAME_LANG_HINTS = [
    ('arabic',     'ar'), ('Arabic',     'ar'), ('Arabic',    'ar'), ('ara',  'ar'), ('.ar.', 'ar'), ('-ar-', 'ar'), ('_ar_', 'ar'),
    ('english',    'en'), ('eng',      'en'), ('.en.', 'en'), ('-en-', 'en'), ('_en_', 'en'),
    ('french',     'fr'), ('français', 'fr'), ('francais', 'fr'), ('fre',  'fr'), ('fra',  'fr'), ('.fr.', 'fr'),
    ('spanish',    'es'), ('español',  'es'), ('espanol',  'es'), ('spa',  'es'), ('.es.', 'es'),
    ('german',     'de'), ('deutsch',  'de'), ('ger',  'de'), ('deu',  'de'), ('.de.', 'de'),
    ('italian',    'it'), ('italiano', 'it'), ('ita',  'it'), ('.it.', 'it'),
    ('portuguese', 'pt'), ('portugues','pt'), ('por',  'pt'), ('.pt.', 'pt'),
    ('brazilian',  'pt-br'), ('portuguese-br','pt-br'), ('pob','pt-br'), ('pt-br','pt-br'), ('.pb.', 'pt-br'),
    ('turkish',    'tr'), ('turkce',   'tr'), ('türkçe',   'tr'), ('tur',  'tr'), ('.tr.', 'tr'),
    ('russian',    'ru'), ('russky',   'ru'), ('rus',  'ru'), ('.ru.', 'ru'),
    ('japanese',   'ja'), ('jpn',  'ja'), ('.ja.', 'ja'), ('.jp.', 'ja'),
    ('korean',     'ko'), ('kor',  'ko'), ('.ko.', 'ko'), ('.kr.', 'ko'),
    ('chinese',    'zh'), ('chi',  'zh'), ('zho',  'zh'), ('.zh.', 'zh'), ('.cn.', 'zh'),
    ('hindi',      'hi'), ('hin',  'hi'), ('.hi.', 'hi'),
    ('persian',    'fa'), ('farsi','fa'), ('fas',  'fa'), ('per',  'fa'), ('.fa.', 'fa'),
]



# broker_search_subtitles lives in subtitle_broker; keep the same lazy shape
# plugin.py used so behaviour is identical.
def broker_search_subtitles(*args, **kwargs):
    from ..subtitle_broker import search_subtitles as _f
    return _f(*args, **kwargs)


def _subtitle_pick_mode_setting():
    try:
        raw = str(ADDON.getSetting('subtitle_search_mode') or '').strip().lower()
    except Exception:
        raw = ''
    if 'Play with subtitles' in raw or "\u062a\u0634\u063a\u064a\u0644 \u0645\u0639 \u0627\u0644\u062a\u0631\u062c\u0645\u0627\u062a" in raw or 'with subtitle' in raw or 'with subtitles' in raw or 'play_with_subtitles' in raw:
        return 'play_with_subtitles'
    if 'During playback' in raw or 'auto' in raw or 'playback' in raw:
        return 'play_with_subtitles'
    # No more runtime prompt. Any legacy/empty/"ask" value falls back to
    # normal playback and is controlled from settings only.
    return 'play'


def _subtitle_search_on_demand_only():
    return _subtitle_pick_mode_setting() != 'play_with_subtitles'


def _preferred_subtitle_lang_keys():
    try:
        raw = str(ADDON.getSetting('preferred_subtitle_langs') or 'en').strip()
    except Exception:
        raw = 'en'
    out = []
    for part in raw.split(','):
        key = _normalize_lang(part)
        if key and key not in out:
            out.append(key)
    return out or ['ar', 'en']


def _force_preferred_subtitle_on_player(player, show=False, attempts=4, delay_ms=400):
    """v3.9.105: after Kodi has loaded subtitle streams, scan them and force
    setSubtitleStream() to the FIRST one matching the user's preferred language
    list (default: en). Kodi otherwise tends to auto-select the last loaded
    subtitle regardless of language — so a Chinese or Spanish sub ends up being
    the default even when an Arabic one is present in the list.

    Retries a few times because Kodi populates the stream list asynchronously
    after playback starts; the first poll often returns an empty list. `show`
    controls whether we also flip showSubtitles(True) — pass True only when the
    user explicitly asked to play WITH subtitles."""
    try:
        prefs = _preferred_subtitle_lang_keys() or ['ar', 'en']
    except Exception:
        prefs = ['ar', 'en']
    pref_bases = [(p.split('-')[0] if p else '').lower() for p in prefs if p]
    if not pref_bases:
        return False

    def _lang_base(code):
        return (str(code or '').split('-')[0] or '').strip().lower()

    for _attempt in range(max(1, attempts)):
        try:
            streams = player.getAvailableSubtitleStreams() or []
        except Exception:
            streams = []
        if streams:
            # Find first stream whose base lang matches our highest-priority pref.
            chosen_idx = -1
            for pref in pref_bases:
                for idx, code in enumerate(streams):
                    if _lang_base(code) == pref:
                        chosen_idx = idx
                        break
                if chosen_idx >= 0:
                    break
            if chosen_idx >= 0:
                try:
                    player.setSubtitleStream(chosen_idx)
                    if show:
                        player.showSubtitles(True)
                    try:
                        xbmc.log('[NuvioHub] auto-selected subtitle stream #%d (%s) from %d available'
                                 % (chosen_idx, streams[chosen_idx], len(streams)), xbmc.LOGINFO)
                    except Exception:
                        pass
                    return True
                except Exception:
                    return False
            # Streams loaded but no Arabic/preferred match — accept Kodi's default.
            return False
        try:
            xbmc.sleep(delay_ms)
        except Exception:
            import time as _t
            _t.sleep(delay_ms / 1000.0)
    return False


def _pick_default_subtitle_index(subtitles, ctx=None):
    rows = list(subtitles or [])
    if not rows:
        return -1
    prefs = _preferred_subtitle_lang_keys()

    def _lang_rank(sub):
        key = _normalize_lang(sub.get('lang') or sub.get('languageCode') or sub.get('language') or 'und')
        base = (key.split('-')[0] if key else '').lower()
        for idx, pref in enumerate(prefs):
            pref_key = _normalize_lang(pref)
            pref_base = (pref_key.split('-')[0] if pref_key else '').lower()
            if key == pref_key or (base and base == pref_base):
                return idx
        return len(prefs) + 10

    best_idx = -1
    best_key = None
    for idx, sub in enumerate(rows):
        if not allow_automatic(sub):
            continue
        sort_key = (
            0 if (sub.get('selected') or sub.get('default')) else 1,
            _lang_rank(sub),
            1 if sub.get('forced') else 0,
            idx,
        )
        if best_key is None or sort_key < best_key:
            best_idx = idx
            best_key = sort_key
    return best_idx


def _filename_basename(value):
    text = _normalize_ascii(value)
    if not text:
        return ''
    text = re.sub(r'\.(mkv|mp4|avi|m2ts|ts|mov|wmv|flv|webm|srt|ass|ssa)$', '', text, flags=re.I)
    return text.strip()


def _normalize_lang(value):
    # Stremio subtitle addons are not consistent: lang/language may be a
    # string, list, dict, regional-flag emoji, or a human name. Normalize all
    # of them so the subtitle picker always gets the proper language flag.
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
    raw_text = str(value or 'und').strip()
    if not raw_text:
        return 'und'
    # Convert regional flag emoji to a country code hint before STREAM_ICON_RE
    # can strip it elsewhere. Arabic subtitles often come as 🇸🇦 / 🇦🇪 only.
    try:
        flag_hint = REGIONAL_FLAG_RE.sub(_regional_flag_to_code, raw_text)
        country = flag_hint.strip('[]').lower() if flag_hint.startswith('[') and flag_hint.endswith(']') else ''
        country_alias = {'sa': 'ar', 'ae': 'ar', 'eg': 'ar', 'us': 'en', 'gb': 'en', 'uk': 'en', 'br': 'pt-br'}
        if country in country_alias:
            return country_alias[country]
    except Exception:
        pass
    raw = raw_text.lower().replace('_', '-').replace(' ', '-')
    aliases = {
        'ara': 'ar', 'arabic': 'ar', 'Arabic': 'ar', 'Arabic': 'ar', 'Arabic': 'ar',
        'eng': 'en', 'english': 'en',
        'spa': 'es', 'spanish': 'es',
        'fre': 'fr', 'fra': 'fr', 'french': 'fr',
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
    raw = aliases.get(raw, raw)
    if raw in LANG_MAP:
        return raw
    raw2 = raw.split('-')[0]
    raw2 = aliases.get(raw2, raw2)
    if raw2 in LANG_MAP:
        return raw2
    return raw or 'und'


def _guess_lang_from_text(text):
    """Best-effort language detection from a filename/release/display string.

    Returns a normalized language code (e.g. 'ar', 'en', 'pt-br') or '' if
    no hint was found. This is the recovery path for issue #12: external
    Stremio subtitles (especially from SubSource/Wyzie) sometimes ship with
    `lang: 'und'` and put the language only in the filename — we used to
    drop them as 'Unknown', now we mine the filename for a hint.
    """
    if not text:
        return ''
    haystack = str(text).strip().lower()
    if not haystack:
        return ''
    # Pad with separators so .ar. style matches at the boundaries too.
    padded = '.' + haystack.replace(' ', '.').replace('_', '.').replace('-', '.') + '.'
    for token, code in _FILENAME_LANG_HINTS:
        if token in padded:
            return code
    return ''


GENERIC_SUBTITLE_NAMES = {
    'external', 'embedded', 'internal', 'subtitle', 'subtitles', 'sub', 'subs',
    'caption', 'captions', 'closed captions', 'cc', 'sdh'
}


def _clean_subtitle_text(value):
    text = _filename_basename(value)
    text = COLOR_TAG_RE.sub('', text)
    text = REGIONAL_FLAG_RE.sub(' ', text)
    text = STREAM_ICON_RE.sub(' ', text)
    text = re.sub(r'^[0-9a-f]{12,}[_\-\s]*', '', text, flags=re.I)
    text = re.sub(r'^\d{1,3}[._\-\s]+', '', text)
    text = text.replace('_', ' ')
    text = MULTI_WS_RE.sub(' ', text).strip(' -|_.')
    return text


def _subtitle_source_name(sub):
    raw = (sub.get('sourceName') or sub.get('providerName') or
           sub.get('addonName') or sub.get('sourceAddon') or sub.get('addonId') or
           sub.get('providerId') or sub.get('provider') or sub.get('addon') or
           sub.get('source') or sub.get('origin') or '')
    text = _clean_subtitle_text(raw)
    # Avoid showing generic type labels as addon names. The display line should
    # feel like Stremio: language + real addon/source name.
    if text.lower() in GENERIC_SUBTITLE_NAMES or text.lower() in ('addon', 'stream', 'manual', 'subtitle addon'):
        return ''
    return text


def _subtitle_language_info(sub):
    lang = sub.get('lang') or sub.get('language') or sub.get('languageCode') or sub.get('iso639') or 'und'
    lang_key = _normalize_lang(lang)
    if lang_key in ('und', '', None):
        for source_field in (sub.get('displayName'), sub.get('label'),
                             sub.get('title'), sub.get('name'),
                             sub.get('release'), sub.get('filename'),
                             sub.get('fileName'), sub.get('url'), sub.get('id')):
            guessed = _guess_lang_from_text(source_field)
            if guessed:
                lang_key = guessed
                break
    if lang_key in ('und', '', None):
        combined_hint = ' '.join(str(sub.get(k) or '') for k in (
            'sourceName', 'providerName', 'addonName', 'sourceAddon', 'addonId',
            'providerId', 'displayName', 'label', 'title', 'name', 'release',
            'filename', 'fileName', 'url', 'id'
        ))
        guessed = _guess_lang_from_text(combined_hint)
        if guessed:
            lang_key = guessed
    lang_key = lang_key or 'und'
    lang_info = LANG_MAP.get(lang_key, ('🏳️', str(lang).title() if lang else 'Unknown'))
    flag = lang_info[0] or ''
    label = lang_info[1] or (str(lang).title() if lang else 'Unknown')
    code = lang_key.split('-')[0].upper() if lang_key else 'UND'
    return lang_key, flag, label, code


def _subtitle_display_name(sub):
    source_name = _subtitle_source_name(sub)
    source_lc = source_name.lower()
    candidates = [
        sub.get('displayName'), sub.get('label'), sub.get('title'), sub.get('name'),
        sub.get('release'), sub.get('filename'), sub.get('fileName')
    ]
    for value in candidates:
        text = _clean_subtitle_text(value)
        if not text:
            continue
        lowered = text.lower()
        if lowered in GENERIC_SUBTITLE_NAMES:
            continue
        if source_lc and lowered == source_lc:
            continue
        if source_lc and lowered.startswith(source_lc + ' '):
            lowered_tail = lowered[len(source_lc):].strip(' -|_.')
            if lowered_tail in GENERIC_SUBTITLE_NAMES or not lowered_tail:
                continue
        return text
    return ''


def _subtitle_title(sub):
    lang_key, flag, label, code = _subtitle_language_info(sub)
    source_name = _subtitle_source_name(sub)
    display_name = _subtitle_display_name(sub)

    # Stremio-style subtitle label:
    #   🇸🇦 Arabic · [OpenSubtitles v3] · Release/File name
    # Source name is wrapped in brackets so the user can clearly see
    # which addon/provider produced each subtitle result. Avoid noisy
    # internal markers such as ADDON/STREAM unless there is no real
    # addon name to show.
    parts = []
    lang_part = ' '.join([part for part in (flag, label if label else code) if part]).strip()
    if lang_part:
        parts.append(lang_part)
    elif code:
        parts.append(code)

    if source_name:
        parts.append('[COLOR cyan]%s[/COLOR]' % source_name)
    else:
        source_type = str(sub.get('sourceType') or '').strip().lower()
        if source_type == 'stream':
            parts.append('[COLOR grey]Stream[/COLOR]')
        elif source_type == 'manual':
            parts.append('[COLOR grey]Manual[/COLOR]')
        elif source_type == 'addon':
            parts.append('[COLOR grey]Addon[/COLOR]')

    if display_name and (not source_name or display_name.lower() != source_name.lower()):
        parts.append(display_name)
    if sub.get('forced'):
        parts.append('Forced')
    if sub.get('hearingImpaired'):
        parts.append('SDH')
    return ' · '.join([part for part in parts if part]).strip()


def _subtitles_summary(subtitles):
    if not subtitles:
        return ''
    parts = []
    seen = set()
    for sub in subtitles[:4]:
        name = _subtitle_title(sub)
        if name not in seen:
            parts.append(name)
            seen.add(name)
    if len(subtitles) > 4:
        parts.append('+%d' % (len(subtitles) - 4))
    return ' | '.join(parts)


_SUB_PREFETCH = {}


_SUB_PREFETCH_LOCK = threading.Lock()


_SUB_PREFETCH_TTL = 300.0


_SUB_PREFETCH_MAX = 32


# Coordinator work is bounded independently of the three network workers.
# Rapidly opening several titles used to leave one raw daemon thread per
# subtitle search alive at once on CoreELEC.
_SUBTITLE_COORDINATOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix='NuvioHub-Subtitle')


def _subtitle_budget_seconds():
    """One end-to-end subtitle-search budget, measured from source scan.

    The setting is intentionally constrained: a corrupted/legacy value must
    not turn subtitle lookup into a long playback stall.  The UI exposes the
    same 10..20 second range and defaults to fifteen seconds.
    """
    try:
        value = float(_get_int_setting('subtitle_timeout', 15))
    except Exception:
        value = 15.0
    return max(10.0, min(20.0, value))


def _purge_sub_prefetch_locked(now_wall=None):
    """Keep the per-process cache small on long-running Kodi sessions."""
    now_wall = float(now_wall or time.time())
    stale = [
        key for key, state in _SUB_PREFETCH.items()
        if now_wall - float((state or {}).get('at') or 0.0) >= _SUB_PREFETCH_TTL
    ]
    for key in stale:
        _SUB_PREFETCH.pop(key, None)
    if len(_SUB_PREFETCH) <= _SUB_PREFETCH_MAX:
        return
    oldest = sorted(
        _SUB_PREFETCH,
        key=lambda key: float((_SUB_PREFETCH.get(key) or {}).get('at') or 0.0),
    )
    for key in oldest[:max(0, len(_SUB_PREFETCH) - _SUB_PREFETCH_MAX)]:
        state = _SUB_PREFETCH.get(key) or {}
        # Never evict the job that is currently serving a playback request.
        if state.get('running'):
            continue
        _SUB_PREFETCH.pop(key, None)


def _sub_prefetch_key(media_type, canonical_id, season=None, episode=None):
    return '%s|%s|%s|%s' % (media_type or '', canonical_id or '',
                            season or '', episode or '')


def start_subtitle_prefetch(media_type, canonical_id, ids=None, title='',
                            season=None, episode=None):
    """Search subtitles WHILE the source scan runs, so they are ready first.

    v3.9.229 — the user's own idea, and a good one. Subtitles were only looked
    for after a source had been picked, so the spinner ran twice. The two are
    independent: the subtitle search only needs the item's ids, which are known
    the moment the title is opened. It now starts immediately, in the
    background, and the result is already in hand when a source is chosen.
    """
    # Do not create a coordinator thread when subtitle discovery is disabled.
    # ``search_subtitles`` performs the same check, but doing it here avoids a
    # needless thread on every source screen in Play-only installations.
    try:
        from ..subtitle_broker import enabled as _broker_enabled
        if not _broker_enabled():
            return None
    except Exception:
        return None

    key = _sub_prefetch_key(media_type, canonical_id, season, episode)
    started_mono = time.monotonic()
    budget = _subtitle_budget_seconds()
    with _SUB_PREFETCH_LOCK:
        _purge_sub_prefetch_locked()
        hit = _SUB_PREFETCH.get(key)
        if hit and time.time() - hit.get('at', 0) < _SUB_PREFETCH_TTL:
            return hit.get('event')
        ready = threading.Event()
        _SUB_PREFETCH[key] = {
            'rows': None, 'at': time.time(), 'event': ready, 'running': True,
            'started_mono': started_mono,
            'deadline_mono': started_mono + budget,
            'budget': budget,
        }

    def _work():
        rows = []
        try:
            rows = broker_search_subtitles({
                'media_type': media_type, 'canonical_id': canonical_id,
                'title': title, 'season': season, 'episode': episode,
                'imdb_id': (ids or {}).get('imdb_id') or '',
                'tmdb_id': (ids or {}).get('tmdb_id') or '',
                'tvdb_id': (ids or {}).get('tvdb_id') or '',
                'subtitle_deadline_mono': started_mono + budget,
            }, initial_subtitles=None, max_results=12) or []
        except Exception as exc:
            xbmc.log('[NuvioHub] subtitle prefetch failed: %s' % exc, xbmc.LOGDEBUG)
        with _SUB_PREFETCH_LOCK:
            state = _SUB_PREFETCH.get(key) or {}
            state.update({'rows': rows, 'at': time.time(), 'running': False,
                          'event': state.get('event') or ready})
            _SUB_PREFETCH[key] = state
            event = state.get('event')
        if event is not None:
            event.set()
        xbmc.log('[NuvioHub] subtitle prefetch ready: %d row(s)' % len(rows), xbmc.LOGINFO)

    try:
        _SUBTITLE_COORDINATOR.submit(_work)
    except Exception:
        with _SUB_PREFETCH_LOCK:
            # No job actually ran. Remove the marker so an explicit
            # Play-with-subtitles request may retry synchronously after the
            # stream lane has released its workers.
            _SUB_PREFETCH.pop(key, None)
        ready.set()
        return None
    return ready


def take_prefetched_subtitles(media_type, canonical_id, season=None, episode=None,
                              wait=0.0):
    """Return prefetched rows, waiting only while a real job is running.

    ``wait`` is a maximum budget, never a fixed delay. No cache entry returns
    immediately; a completed job returns immediately; an in-flight job wakes
    this call the instant it sets its Event.
    """
    key = _sub_prefetch_key(media_type, canonical_id, season, episode)
    with _SUB_PREFETCH_LOCK:
        state = _SUB_PREFETCH.get(key)
        if not state:
            return []
        rows = state.get('rows')
        event = state.get('event')
    if rows is not None:
        return list(rows)
    budget = max(0.0, float(wait or 0.0))
    # The timeout starts when source discovery starts, not when the user picks
    # a stream.  A source appearing at t=1s under a five-second policy leaves
    # at most four seconds; it never creates a second five-second wait.
    deadline = state.get('deadline_mono')
    if deadline not in (None, ''):
        try:
            budget = min(budget, max(0.0, float(deadline) - time.monotonic()))
        except Exception:
            pass
    if budget > 0.0 and event is not None:
        event.wait(budget)
    with _SUB_PREFETCH_LOCK:
        rows = (_SUB_PREFETCH.get(key) or {}).get('rows')
    return list(rows) if rows is not None else []


def subtitle_prefetch_status(media_type, canonical_id, season=None, episode=None):
    """Cheap status snapshot for the source picker and playback policy."""
    key = _sub_prefetch_key(media_type, canonical_id, season, episode)
    with _SUB_PREFETCH_LOCK:
        state = dict(_SUB_PREFETCH.get(key) or {})
    if not state:
        return {
            'exists': False, 'running': False, 'ready': False, 'count': 0,
            'budget': _subtitle_budget_seconds(), 'elapsed': 0.0,
            'remaining': 0.0,
        }
    now_mono = time.monotonic()
    rows = state.get('rows')
    started = float(state.get('started_mono') or now_mono)
    deadline = float(state.get('deadline_mono') or now_mono)
    return {
        'exists': True,
        'running': bool(state.get('running') and rows is None),
        'ready': rows is not None,
        'count': len(rows or []),
        'budget': float(state.get('budget') or _subtitle_budget_seconds()),
        'elapsed': max(0.0, now_mono - started),
        'remaining': max(0.0, deadline - now_mono),
    }


_BITMAP_SUB_CODECS = {
    'pgs', 'hdmv_pgs_subtitle', 'hdmv-pgs-subtitle', 'pgssub',
    'vobsub', 'dvd_subtitle', 'dvd-subtitle', 'dvdsub',
    'dvb_subtitle', 'dvb-subtitle', 'dvbsub', 'xsub',
}


def _is_bitmap_subtitle(sub):
    """True when the track is an image, not text — setSubtitles() cannot use it."""
    sub = sub or {}
    codec = str(sub.get('codec') or '').strip().lower()
    fmt = str(sub.get('format') or '').strip().lower()
    return codec in _BITMAP_SUB_CODECS or fmt in _BITMAP_SUB_CODECS


def _subs_tmp_dir():
    path = xbmcvfs.translatePath('special://temp/%s/' % _SUBS_TMP_DIRNAME)
    try:
        if not xbmcvfs.exists(path):
            xbmcvfs.mkdirs(path)
    except Exception:
        pass
    return path


def cleanup_cached_subtitles(max_age_days=7):
    """Best-effort sweep of the temp subtitle files. Silent on failure."""
    try:
        path = _subs_tmp_dir()
        if not xbmcvfs.exists(path):
            return
        cutoff = time.time() - (max_age_days * 86400)
        _dirs, files = xbmcvfs.listdir(path)
        for name in files:
            full = os.path.join(path, name)
            try:
                if xbmcvfs.Stat(full).st_mtime() < cutoff:
                    xbmcvfs.delete(full)
            except Exception:
                continue
    except Exception:
        pass


def filter_playable_subtitles(rows):
    """Drop the tracks the player physically cannot render."""
    playable, dropped = [], []
    for row in (rows or []):
        if _is_bitmap_subtitle(row):
            dropped.append(str(row.get('lang') or row.get('title') or '?'))
            continue
        playable.append(row)
    if dropped:
        xbmc.log('[NuvioHub] dropped %d bitmap subtitle(s) the player cannot load: %s'
                 % (len(dropped), ', '.join(dropped[:5])), xbmc.LOGINFO)
    return playable


def _collect_playback_subtitles(ctx, manual=False, force_search=False, include_broker=True):
    initial = []
    # Try to get a meaningful source name from the stream context.
    # The provider_name is the best bet, but fall back to the stream's
    # addon name or source description so the user sees something useful.
    source_name = (
        ctx.get('provider_name') or
        ctx.get('stream_addon_name') or
        ctx.get('source_provider_name') or
        ctx.get('provider_id') or
        ctx.get('addon_name') or
        ''
    )
    # Clean up provider IDs that look like URLs or UUIDs — not user-friendly
    if source_name and ('/' in source_name or len(source_name) > 40):
        # Probably a manifest URL or UUID — extract a readable portion
        short = source_name.rsplit('/', 1)[-1].split('?')[0]
        if short and len(short) < 40:
            source_name = short
        else:
            source_name = ''
    selected = ctx.get('selected_subtitle')
    if selected:
        if isinstance(selected, dict):
            row = dict(selected)
        else:
            row = {'url': selected, 'id': selected, 'lang': 'und'}
        row.setdefault('sourceType', 'manual')
        row['user_selected'] = True
        row.setdefault('sourceName', source_name)
        initial.append(row)
        # Keep the user's selected subtitle first, but continue through the
        # Stremio subtitle broker so every installed subtitle addon can add
        # alternatives. Older builds returned here and hid all addon results.
    for sub in (ctx.get('subtitles') or []):
        if isinstance(sub, dict):
            row = dict(sub)
        else:
            row = {'url': sub, 'id': sub, 'lang': 'und'}
        row.setdefault('sourceType', 'stream')
        row.setdefault('sourceName', source_name)
        initial.append(row)
    # Native Plex/Emby sidecars are useful initial rows, but they must not
    # suppress Stremio subtitle addons. The broker now runs the same ID-based
    # subtitle query for native and Stremio playback; the server sidecars stay
    # first because they are the best file match.
    # "Play only" controls automatic subtitle visibility, not discovery.
    # When the broker is enabled we still collect addon results in the
    # background/list, matching Stremio's behavior; subtitles are only shown
    # automatically when the user selected Play with subtitles.
    try:
        # A Stremio stream's OWN subtitles come first: that addon serves the
        # file, so it knows which subtitle belongs to it.  Normal playback must
        # never wait for the cross-addon broker: attach source/native sidecars
        # now and discover the rest only after AVStarted.
        initial = filter_playable_subtitles(initial)
        if not include_broker:
            return initial or []

        # Play-with-subtitles is the deliberate blocking path. Reuse a warm
        # prefetch when available, otherwise perform the complete broker search
        # before handing the URL to Kodi.
        _prefetch_before = subtitle_prefetch_status(
            ctx.get('media_type'), ctx.get('canonical_id'),
            ctx.get('season'), ctx.get('episode'))
        _pre = take_prefetched_subtitles(
            ctx.get('media_type'), ctx.get('canonical_id'),
            ctx.get('season'), ctx.get('episode'),
            # Manual search may wait for the SAME remaining source-scan
            # budget; it never starts a fresh timeout window.
            wait=max(1.0, _subtitle_budget_seconds()))
        _pre = filter_playable_subtitles(_pre)
        _prefetch_after = subtitle_prefetch_status(
            ctx.get('media_type'), ctx.get('canonical_id'),
            ctx.get('season'), ctx.get('episode'))
        # A prefetch entry is authoritative even when it found zero rows or
        # reached its deadline. Starting the broker again here used to double
        # network traffic and create a second full timeout after stream pick.
        if _prefetch_before.get('exists') or _prefetch_after.get('exists'):
            xbmc.log('[NuvioHub] subtitles served from source-scan prefetch (%d, %.1fs elapsed)'
                     % (len(_pre), _prefetch_after.get('elapsed') or 0.0), xbmc.LOGINFO)
            return (initial or []) + [r for r in _pre if r not in (initial or [])]
        rows = broker_search_subtitles(ctx, initial_subtitles=initial, max_results=12)
    except Exception as exc:
        xbmc.log('[NuvioHub] subtitle broker failed: %s' % exc, xbmc.LOGWARNING)
        rows = initial
    return rows or []


def _publish_subtitle_addon_row():
    """Expose the addon-search entry to the player window (worker thread)."""
    try:
        if not kodi_subtitle_addons():
            return
        xbmcgui.Window(WINDOW_ID).setProperty(
            'nuviohub.subtitles.addon_search',
            build_url(action='subtitle_addons'))
    except Exception:
        pass


def kodi_subtitle_addons():
    """The subtitle addons the user has actually installed (a4kSubtitles, ...).

    v3.9.228 — Nuvio Hub only ever offered the subtitles that came with the
    stream, plus its own broker. Every subtitle addon the user had installed —
    the ones they chose, configured and rely on — was invisible during
    playback. They are Kodi's own resource type, so they can simply be asked.
    """
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.GetAddons',
               'params': {'type': 'xbmc.subtitle.module', 'enabled': True,
                          'properties': ['name', 'thumbnail']}}
    try:
        data = json.loads(xbmc.executeJSONRPC(json.dumps(payload)) or '{}')
    except Exception:
        return []
    rows = []
    for addon in ((data.get('result') or {}).get('addons') or []):
        addon_id = str(addon.get('addonid') or '')
        if addon_id:
            rows.append({'id': addon_id,
                         'name': str(addon.get('name') or addon_id),
                         'thumb': str(addon.get('thumbnail') or '')})
    return rows


def subtitle_addon_search():
    """Hand the currently playing item to Kodi's own subtitle search.

    Those addons read the playing item from Kodi's InfoLabels — which Nuvio Hub
    already publishes — so the native dialog drives every installed provider at
    once, with the user's own language settings, and drops the result straight
    onto the player.
    """
    try:
        if not xbmc.Player().isPlaying():
            notify(tr('Play something first'))
            return
    except Exception:
        pass
    addons = kodi_subtitle_addons()
    xbmc.log('[NuvioHub] subtitle addons available: %s'
             % (', '.join(a['id'] for a in addons) or 'none'), xbmc.LOGINFO)
    if not addons:
        notify(tr('No subtitle addons installed'))
        return
    xbmc.executebuiltin('ActivateWindow(SubtitleSearch)')


def _subtitle_picker_title(ctx):
    title = ctx.get('show_title') or ctx.get('title') or tr('Subtitles')
    season = ctx.get('season')
    episode = ctx.get('episode')
    if season not in (None, '') and episode not in (None, ''):
        try:
            return '%s — S%02dE%02d' % (title, int(season), int(episode))
        except Exception:
            return title
    return title


def _subtitle_pick_for_stream_key(stream_key, current=None):
    ctx = cache_store.get('stream', stream_key) or {}
    if not ctx:
        error(tr('The add-on data expired. Open it again.'))
        return None
    rows = _collect_playback_subtitles(ctx, manual=True)
    labels = ['No subtitles']
    for row in rows:
        labels.append(_subtitle_title(row))
    if len(labels) == 1:
        notify(tr('No subtitles available for this add-on'))
        return None
    idx = xbmcgui.Dialog().select(tr('Subtitles — %s') % _subtitle_picker_title(ctx), [tr(x) for x in labels])
    if idx < 0:
        return None
    if idx == 0:
        return {'__clear__': True, '_label': 'No subtitles'}
    chosen = dict(rows[idx - 1])
    chosen['_label'] = labels[idx]
    return chosen


def _publish_subtitle_bridge_properties(ctx, is_ep):
    """Publish content IDs for external subtitle services (fallback path).

    Extracted verbatim from _play_with_context. The subtitle service reads
    these Window(10000) properties before VideoPlayer.* infolabels are
    populated, so it always has the content IDs. Failures are swallowed
    exactly as before.
    """
    # ── External subtitle service bridge ────────────────────────────────
    # external subtitle services reads VideoPlayer.* infolabels. Kodi only
    # populates those AFTER the player starts, and only when setInfo() has
    # been processed. As an extra safety net we also write the IDs as
    # Window(10000) properties; the subtitle service reads these as fallback
    # so it always has the content IDs even before VideoPlayer is ready.
    try:
        _sub_home = xbmcgui.Window(10000)
        _sub_home.setProperty('nuviohub.sub.imdb_id',  ctx.get('imdb_id') or '')
        _sub_home.setProperty('nuviohub.sub.tmdb_id',  ctx.get('tmdb_id') or '')
        _sub_home.setProperty('nuviohub.sub.tvdb_id',  ctx.get('tvdb_id') or '')
        _sub_home.setProperty('nuviohub.sub.season',   str(int(ctx.get('season') or 0)) if is_ep else '')
        _sub_home.setProperty('nuviohub.sub.episode',  str(int(ctx.get('episode') or 0)) if is_ep else '')
        _sub_home.setProperty('nuviohub.sub.title',    ctx.get('title') or '')
        _sub_home.setProperty('nuviohub.sub.mediatype','episode' if is_ep else 'movie')
    except Exception:
        pass


def _safe_subtitle_filename_part(value, limit=48):
    text = _clean_subtitle_text(value)
    text = re.sub(r'[^\w\- ]+', ' ', text, flags=re.UNICODE)
    text = MULTI_WS_RE.sub(' ', text).strip(' -|_.')
    return text[:limit].strip()


def _subtitle_url_needs_local_copy(url):
    text = str(url or '').strip().lower()
    if not text:
        return False
    if text.startswith(('http://', 'https://', 'plugin://', 'ftp://', 'ftps://', 'smb://', 'nfs://', 'special://')):
        return False
    return True


_SUB_VALID_EXTS = ('srt', 'vtt', 'ass', 'ssa', 'sub', 'sbv', 'idx')


def _detect_subtitle_extension(sub, sub_url):
    """Pick a sensible extension. Prefer explicit format/codec; fall back to URL path."""
    raw = str(sub.get('format') or sub.get('codec') or '').lower().replace('/', '').strip('.').strip()
    if raw and raw in _SUB_VALID_EXTS:
        return raw
    try:
        from urllib.parse import urlparse as _urlparse
        path = _urlparse(str(sub_url or '')).path or ''
        url_ext = path.rsplit('.', 1)[-1].lower().strip() if '.' in path else ''
        if url_ext and url_ext in _SUB_VALID_EXTS:
            return url_ext
    except Exception:
        pass
    return raw or 'srt'


def _download_remote_subtitle(url, local_path):
    """Download a protected Plex/Emby sidecar when xbmcvfs.copy cannot.

    Kodi's VFS HTTP copy is inconsistent with authenticated URLs on some
    Android/CoreELEC builds. urllib handles the token query reliably and lets
    us reject HTML error pages before Kodi tries to parse them as subtitles.
    """
    raw_url = str(url or '').strip()
    if not raw_url.lower().startswith(('http://', 'https://')):
        return False
    headers = {
        'User-Agent': 'NuvioHub/%s (Kodi)' % (ADDON.getAddonInfo('version') or '3.9.212'),
        'Accept': 'text/plain,text/vtt,application/x-subrip,*/*;q=0.5',
    }
    # Kodi URL syntax may append request headers after a pipe.
    if '|' in raw_url:
        raw_url, raw_headers = raw_url.split('|', 1)
        try:
            for key, value in parse_qsl(raw_headers, keep_blank_values=True):
                if key:
                    headers[str(key)] = str(value)
        except Exception:
            pass
    try:
        # Use one controlled urllib attempt. Kodi's VFS may inherit global
        # curl retry settings and turn a failed subtitle into minutes of wait.
        timeout = min(12, max(2, _get_int_setting('subtitle_timeout', 15)))
        parsed = urlparse(raw_url)
        is_plex_sidecar = (str(parsed.hostname or '').lower().endswith('.plex.direct') or
                           'x-plex-token=' in str(parsed.query or '').lower())
        if is_plex_sidecar:
            # Reuse Plex Native's wrapped-TLS recovery. Calling urlopen here
            # directly reintroduced the same plex.direct CA failure that was
            # fixed for library/search requests, so the video played but its
            # external subtitle file never materialized.
            payload = plex_client._request(
                raw_url, headers=headers, timeout=timeout)[:(5 * 1024 * 1024) + 1]
        else:
            req = Request(raw_url, headers=headers)
            with urlopen(req, timeout=timeout) as response:
                payload = response.read((5 * 1024 * 1024) + 1)
        if not payload or len(payload) < 32 or len(payload) > 5 * 1024 * 1024:
            return False
        sniff = payload[:256].lstrip().lower()
        if sniff.startswith((b'<!doctype html', b'<html', b'<?xml')) and b'<tt ' not in sniff:
            return False
        fh = xbmcvfs.File(local_path, 'wb')
        try:
            written = fh.write(payload)
        finally:
            fh.close()
        return bool(written is None or int(written) > 0) and xbmcvfs.exists(local_path)
    except Exception:
        try:
            if xbmcvfs.exists(local_path):
                xbmcvfs.delete(local_path)
        except Exception:
            pass
        return False


def _download_subtitle_jobs_async(jobs):
    """Materialize protected Plex/Emby subtitles without blocking playback.

    DPlex deliberately hands Kodi the expected local paths first and performs
    network I/O in a daemon thread.  Doing the downloads synchronously before
    setResolvedUrl/Player.play can exceed Kodi's resolver timeout and produce
    the misleading "Playback failed" dialog even though the video later
    starts.  Native Plex and Emby now use the same proven handoff.
    """
    jobs = list(jobs or [])
    if not jobs:
        return

    def _worker():
        for sub_url, local_path in jobs:
            try:
                if xbmcvfs.exists(local_path):
                    continue
                lower = str(sub_url or '').lower()
                if lower.startswith(('http://', 'https://')):
                    _download_remote_subtitle(sub_url, local_path)
                else:
                    xbmcvfs.copy(sub_url, local_path)
            except Exception as exc:
                try:
                    xbmc.log('[NuvioHub] subtitle background download failed: %s' % exc,
                             xbmc.LOGDEBUG)
                except Exception:
                    pass

    try:
        _SUBTITLE_COORDINATOR.submit(_worker)
    except Exception:
        pass


def _prepare_subtitle_files(subtitles, stream_key, prefer_local_copy=False,
                            defer_download=False):
    """Materialize subtitle URLs as local files when needed.

    Behavior change in 3.8.14:
    * `prefer_local_copy` is now actually honored. When False, only HTTP/HTTPS
      URLs are downloaded (Kodi can stream those poorly), other paths pass
      through directly.
    * Extension is sniffed from the URL when `format`/`codec` is missing — this
      stops .vtt/.ass subs from being saved as .srt and mis-parsed by Kodi.
    * Successful xbmcvfs.copy is validated by file size (32B – 5MB), so HTML
      404 pages no longer become fake subtitle files.
    * `defer_download` mirrors DPlex: return expected local paths immediately
      and fetch them in the background, keeping Kodi's playback handoff fast.
    """
    if not subtitles:
        return []
    try:
        if not xbmcvfs.exists(SUBS_DIR):
            xbmcvfs.mkdirs(SUBS_DIR)
    except Exception:
        pass
    safe_stream_dir = re.sub(r'[^\w\-]+', '_', str(stream_key or 'play')).strip('_') or 'play'
    playback_dir = os.path.join(SUBS_DIR, safe_stream_dir[:80])
    try:
        if not xbmcvfs.exists(playback_dir):
            xbmcvfs.mkdirs(playback_dir)
    except Exception:
        playback_dir = SUBS_DIR
    out = []
    download_jobs = []
    used_filenames = set()
    for idx, sub in enumerate(subtitles, start=1):
        sub_url = sub.get('url') or sub.get('key')
        if not sub_url:
            continue
        lang_key, flag, label, code = _subtitle_language_info(sub)
        fmt = _detect_subtitle_extension(sub, sub_url)
        source_name = _subtitle_source_name(sub)
        display_name = _subtitle_display_name(sub)
        display_code = code or (lang_key.split('-')[0].upper() if lang_key else 'UND')

        # v3.9.105: subtitle filename rebuilt to lead with the ACTUAL subtitle
        # name (release/filename) instead of the addon name. Kodi's player UI
        # truncates long subtitle entries, so whatever appears first wins eye
        # time. Pattern now:
        #     Format: <DisplayName> - <Language> [- <Source>].<ext>
        # The source/addon name is appended as a small attribution at the end,
        # only kept if it actually differs from the display name. When the
        # subtitle row has no real release name we fall back to the old
        # source-first layout so the user still sees something meaningful.
        lang_label = (label if label and label.lower() != 'unknown' else display_code)
        lang_part = lang_label  # Plain text filenames also work with Kodi fonts without flag emoji.
        lang_part = re.sub(r'[<>:"/\\|?*]+', ' ', lang_part).strip() or display_code
        safe_source = _safe_subtitle_filename_part(source_name, 36) if source_name else ''
        safe_display = _safe_subtitle_filename_part(display_name, 60) if display_name else ''

        filename_parts = []
        if safe_display:
            # Display name first — this is the actual release/filename users
            # recognize (e.g. "GOAT.2026.WEBDL.2160p-BYNDR").
            filename_parts.append(safe_display)
            filename_parts.append(lang_part)
            if safe_source and safe_source.lower() != safe_display.lower():
                # Light attribution at end so user can still identify the addon.
                filename_parts.append('[%s]' % safe_source)
        elif safe_source:
            # v3.9.105: prefer the WORK's own title over the addon brand name.
            # The user requested that subtitle filenames never lead with the
            # provider/addon name — even if the addon didn't fill display_name,
            # show the movie/episode title at least, then language, then the
            # addon as a small attribution tag at the end.
            work_title = ''
            try:
                # Source-of-truth for the work title comes through the calling
                # site as part of the per-playback context. We don't have it
                # directly here, so peek at the most recently-set transient
                # property (set by the source picker before play).
                work_title = (xbmcgui.Window(WINDOW_ID).getProperty('nuviohub.source.title') or '').strip()
            except Exception:
                work_title = ''
            safe_work_title = _safe_subtitle_filename_part(work_title, 60) if work_title else ''
            if safe_work_title:
                filename_parts.append(safe_work_title)
                filename_parts.append(lang_part)
                if safe_source and safe_source.lower() != safe_work_title.lower():
                    filename_parts.append('[%s]' % safe_source)
            else:
                # Truly nothing available — last-resort fall back to source name.
                filename_parts.append(safe_source)
                filename_parts.append(lang_part)
        else:
            # No source, no display — fall back to source type at least.
            source_type = str(sub.get('sourceType') or '').strip().lower()
            if source_type == 'stream':
                filename_parts.append('Stream')
            elif source_type:
                filename_parts.append(source_type.title())
            filename_parts.append(lang_part)

        base_name = ' - '.join([part for part in filename_parts if part])
        # Ensure unique filename — append (N) on collision
        candidate = base_name
        collision_counter = 1
        while candidate.lower() in used_filenames:
            collision_counter += 1
            candidate = '%s (%d)' % (base_name, collision_counter)
        used_filenames.add(candidate.lower())
        filename = '%s.%s' % (candidate, fmt)

        local_path = os.path.join(playback_dir, filename)
        final_path = sub_url

        # Decide whether to copy. We always copy http(s) so Kodi can show the
        # nice flag/source filename in its subtitle list. Other schemes
        # (smb://, special://, local paths) just pass through unless the
        # caller explicitly asked for a local copy.
        url_lower = str(sub_url or '').lower()
        is_remote_http = url_lower.startswith(('http://', 'https://'))
        should_copy = is_remote_http or bool(prefer_local_copy)

        if should_copy and defer_download:
            final_path = local_path
            if not xbmcvfs.exists(local_path):
                download_jobs.append((sub_url, local_path))
        elif should_copy:
            try:
                if not xbmcvfs.exists(local_path):
                    if is_remote_http:
                        _download_remote_subtitle(sub_url, local_path)
                    else:
                        xbmcvfs.copy(sub_url, local_path)
                if xbmcvfs.exists(local_path):
                    # Validate: a real subtitle is between 32B (tiny vtt cue)
                    # and 5MB (very long episode .ass). Anything outside is
                    # almost always an HTML 404 page or a broken response.
                    size_ok = True
                    try:
                        with xbmcvfs.File(local_path) as fh:
                            sz = fh.size()
                        if sz < 32 or sz > 5 * 1024 * 1024:
                            size_ok = False
                    except Exception:
                        size_ok = True  # if we can't stat, assume OK
                    if size_ok:
                        final_path = local_path
                    else:
                        try:
                            xbmcvfs.delete(local_path)
                        except Exception:
                            pass
                        # VFS sometimes stores an HTML auth response. Retry
                        # through urllib before giving up on local materialize.
                        if is_remote_http and _download_remote_subtitle(sub_url, local_path):
                            final_path = local_path
                        else:
                            final_path = sub_url
            except Exception:
                if is_remote_http and _download_remote_subtitle(sub_url, local_path):
                    final_path = local_path
                else:
                    final_path = sub_url
        out.append({'path': final_path, 'subtitle': sub, 'lang_key': lang_key})
    if download_jobs:
        _download_subtitle_jobs_async(download_jobs)
    return out


def _current_subtitle_enabled():
    """Return Kodi's current subtitle visibility without assuming player id."""
    players = _jsonrpc_call('Player.GetActivePlayers') or []
    for row in players if isinstance(players, list) else []:
        if str(row.get('type') or '') != 'video':
            continue
        try:
            pid = int(row.get('playerid'))
        except Exception:
            continue
        props = _jsonrpc_call('Player.GetProperties', {
            'playerid': pid,
            'properties': ['subtitleenabled'],
        }) or {}
        if isinstance(props, dict) and 'subtitleenabled' in props:
            return bool(props.get('subtitleenabled'))
    try:
        return bool(xbmc.getCondVisibility('VideoPlayer.HasSubtitles'))
    except Exception:
        return True


def _subtitle_cache_folder():
    folder = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.nuviohub/subtitle_cache')
    try:
        if not xbmcvfs.exists(folder):
            xbmcvfs.mkdirs(folder)
    except Exception:
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception:
            pass
    return folder


def _capture_external_subtitle_for_switch(player):
    """Capture the selected external subtitle before stopping the old source.

    Kodi's subtitle stream index is intentionally not stored because stream
    ordering changes between Plex/Emby/Jellyfin/direct sources. getSubtitles()
    returns the active external subtitle file; temporary files are copied into
    Nuvio Hub's own cache so Player.stop() or another addon cannot remove them.
    Internal subtitle streams normally return an empty path and are ignored.
    """
    try:
        raw_path = str(player.getSubtitles() or '').strip()
    except Exception:
        raw_path = ''
    if not raw_path:
        return {}
    low = raw_path.lower().split('?', 1)[0]
    valid_ext = ('.srt', '.ass', '.ssa', '.vtt', '.sub', '.idx', '.smi')
    if not (low.endswith(valid_ext) or raw_path.startswith(('http://', 'https://', 'special://'))):
        return {}
    enabled = _current_subtitle_enabled()
    final_path = raw_path
    name = os.path.basename(low.replace('\\', '/')) or 'subtitle.srt'
    # Cache local/special files. Remote URLs are retained as-is because Kodi
    # can reopen them and copying would add a blocking network request here.
    if not raw_path.startswith(('http://', 'https://')):
        try:
            source = xbmcvfs.translatePath(raw_path)
        except Exception:
            source = raw_path
        try:
            exists = bool(xbmcvfs.exists(source) or os.path.exists(source))
        except Exception:
            exists = False
        if exists:
            import hashlib
            ext = os.path.splitext(name)[1].lower() or '.srt'
            digest = hashlib.sha1((source + str(time.time_ns())).encode('utf-8', 'ignore')).hexdigest()[:16]
            destination = os.path.join(_subtitle_cache_folder(), 'switch_%s%s' % (digest, ext))
            try:
                copied = bool(xbmcvfs.copy(source, destination))
            except Exception:
                copied = False
            if not copied:
                try:
                    with open(source, 'rb') as src, open(destination, 'wb') as dst:
                        dst.write(src.read())
                    copied = True
                except Exception:
                    copied = False
            if copied:
                final_path = destination
                # VobSub is a PAIR: the .idx is the index, the .sub holds the
                # bitmap data — Kodi needs BOTH next to each other with the
                # same basename. getSubtitles() returns only one path, so
                # copying just that file silently broke the subtitle after the
                # switch. Bring the sibling along under the same digest name.
                if ext in ('.idx', '.sub'):
                    _sib_ext = '.sub' if ext == '.idx' else '.idx'
                    _sib_src = os.path.splitext(source)[0] + _sib_ext
                    try:
                        _sib_exists = bool(xbmcvfs.exists(_sib_src) or os.path.exists(_sib_src))
                    except Exception:
                        _sib_exists = False
                    if _sib_exists:
                        _sib_dst = os.path.splitext(destination)[0] + _sib_ext
                        try:
                            if not xbmcvfs.copy(_sib_src, _sib_dst):
                                with open(_sib_src, 'rb') as _s, open(_sib_dst, 'wb') as _d:
                                    _d.write(_s.read())
                        except Exception:
                            pass
    return {
        'switch_subtitle_path': final_path,
        'switch_subtitle_enabled': bool(enabled),
        'switch_subtitle_name': name,
        'switch_subtitle_captured_at': int(time.time()),
    }
