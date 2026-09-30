# -*- coding: utf-8 -*-
import html
import json
import os
import re
import threading
import time
import unicodedata
try:
    from urllib.request import Request, urlopen
except Exception:  # pragma: no cover - Kodi runtime fallback
    Request = None
    urlopen = None
from .log import log

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from . import cache_store, source_session
from . import tmdbhelper as _tmdb_art_db
from .i18n import tr


def _provider_color_index(name):
    """v4.6.0: stable 1..8 identity-colour slot for a provider name.
    Shared with the loading dashboard and the chips strip so one provider
    is one colour everywhere. Falls back to slot 1 in stub environments."""
    try:
        from . import skin_theme
        return skin_theme.provider_color_index(name)
    except Exception:  # pragma: no cover
        return 1

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

ACTION_SELECT = {7, 100}
ACTION_INFO = {11}
ACTION_BACK = {9, 10, 92, 216, 247, 257, 275, 61467, 61448}
ACTION_CONTEXT = {117}
ACTION_LEFT = {1}
ACTION_RIGHT = {2}
ACTION_MOVE = {3, 4, 5, 6}  # up/down + page up/down

MODE_ASK = 'ask'
MODE_PLAY = 'play'
MODE_PLAY_SUBS = 'play_with_subtitles'

QUALITY_FILTERS = [
    ('Q:2160P', 'QUALITY • 4K / 2160P', ('2160P', '2160', '4K', 'UHD')),
    ('Q:1080P', 'QUALITY • 1080P', ('1080P', '1080', 'FHD')),
    ('Q:720P',  'QUALITY • 720P',  ('720P', '720', 'HD')),
    ('Q:480P',  'QUALITY • 480P / SD', ('480P', '480', 'SD')),
    ('Q:HDR',   'QUALITY • HDR', ('HDR', 'HDR10', 'HDR10+')),
    ('Q:DV',    'QUALITY • Dolby Vision', ('DV', 'DOVI', 'DOLBY VISION')),
    ('Q:REMUX', 'QUALITY • REMUX', ('REMUX', 'BDREMUX')),
]

# Built once per interpreter, not once per rendered source row.  The picker can
# receive hundreds of AIOStreams results and v5.2 rebuilt this palette list for
# every ListItem crossing Kodi's Python/C++ bridge.
_NATIVE_TAGS = (
    ('2160P', 'FF1A1E2A', 'FF8AC5DC'), ('4K', 'FF1A1E2A', 'FF8AC5DC'),
    ('1080P', 'FF1A1B2A', 'FF9AAEDC'), ('720P', 'FF18201E', 'FF8AC8B4'),
    ('DV', 'FF1E1A2A', 'FFBBA6D6'),
    ('HDR10+', 'FF221C14', 'FFD8B488'), ('HDR10', 'FF221C14', 'FFD8B488'),
    ('HDR', 'FF221C14', 'FFD8B488'),
    ('HEVC', 'FF181F1A', 'FF96C2A6'), ('AV1', 'FF181F1C', 'FF8CC0AE'),
    ('H264', 'FF1B1E18', 'FFAEC596'),
    ('ATMOS', 'FF1C1828', 'FFC2AEDA'),
    ('TRUEHD', 'FF1C1828', 'FFB6A8D6'),
    ('DTS-HD', 'FF181C26', 'FF9CB4D6'), ('DTS-X', 'FF181C26', 'FF9CB4D6'),
    ('DTS', 'FF181C26', 'FF9CB4D6'), ('DD+', 'FF1A1B24', 'FFA6AECE'),
    ('DD-EX', 'FF1A1B24', 'FFA6AECE'), ('7.1', 'FF1A1B22', 'FFAEB2C6'),
    ('5.1', 'FF1A1B22', 'FFAEB2C6'),
    ('REMUX', 'FF231819', 'FFD69C9C'),
    ('BLURAY', 'FF181C26', 'FF9CB0D6'),
    ('WEB-DL', 'FF181F1C', 'FF9EC2A8'), ('WEBDL', 'FF181F1C', 'FF9EC2A8'),
    ('WEBRIP', 'FF1A1F18', 'FFAEC596'),
    ('DUBBED', 'FF211F16', 'FFD4CC9A'),
    ('MULTI', 'FF182022', 'FF9AC6C6'), ('SUBS', 'FF182022', 'FF9AC6C6'),
)

# Kodi on Android/TV skins commonly ships with fonts that cover Latin/Arabic
# but not CJK/Hangul/emoji/private-use glyphs. When Stremio/Plexio metadata
# returns original Korean/Japanese/Chinese text, Kodi renders it as empty
# square boxes. Keep Arabic/Latin intact, but strip scripts that are very
# likely to render as boxes in the bundled source-picker skin.
_UNSUPPORTED_KODI_FONT_RE = re.compile(
    r'[\u1100-\u11FF\u2E80-\u2EFF\u2F00-\u2FDF\u3040-\u30FF'
    r'\u3100-\u312F\u31A0-\u31BF\u3400-\u4DBF\u4E00-\u9FFF'
    r'\uA960-\uA97F\uAC00-\uD7AF\uF900-\uFAFF\U0001F300-\U0001FAFF\uE000-\uF8FF]'
)
_VISIBLE_RE = re.compile(r'\S')
_MARKUP_RE = re.compile(r'\[/?(?:COLOR|B|I|UPPERCASE|LOWERCASE|LIGHT)\b[^\]]*\]', re.I)


def _kodi_safe_text(value, fallback=''):
    """Return text that the bundled Kodi skin is likely able to render.

    This is intentionally UI-only; it never changes the playable stream URL or
    cached metadata. It removes unsupported CJK/Hangul/emoji glyphs that show
    up as □□□ boxes in Kodi fonts, then falls back to a clean title when the
    remaining text would be mostly empty.
    """
    raw = html.unescape(str(value or ''))
    raw = _MARKUP_RE.sub(' ', raw)
    raw = raw.replace('\u200f', ' ').replace('\u200e', ' ').replace('\xa0', ' ')
    raw = ''.join(ch for ch in unicodedata.normalize('NFKC', raw) if ch == '\n' or ch == '\t' or ord(ch) >= 32)
    visible = len(_VISIBLE_RE.findall(raw))
    if not raw or not visible:
        return str(fallback or '')
    unsupported = len(_UNSUPPORTED_KODI_FONT_RE.findall(raw)) + raw.count('□') + raw.count('�')
    cleaned = _UNSUPPORTED_KODI_FONT_RE.sub(' ', raw)
    cleaned = cleaned.replace('□', ' ').replace('�', ' ')
    cleaned = re.sub(r'[\u25A0-\u25FF]+', ' ', cleaned)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n\s*\n+', '\n', cleaned).strip(' -|_/\\\n\t')
    if unsupported and (not cleaned or len(_VISIBLE_RE.findall(cleaned)) < max(4, int(visible * 0.35))):
        return str(fallback or '')
    return cleaned



_PLOT_NAN_RE = re.compile(r'(?:^|[\s•|·])(?:NaN|null|undefined|0(?:\.0)?)\s*(?:Mbps|Kbps|fps|bps)\b', re.I)
_PLOT_CH_RE = re.compile(r'\b([1-9])\s+1\b')
_PLOT_SEP_RE = re.compile(r'(?:\s*[•|·]\s*){2,}')
_PLOT_RELEASE_RE = re.compile(
    r'\b(?:2160p|1440p|1080p|720p|480p|WEB-?DL|WEB-?RIP|BLU-?RAY|BDRIP|HDTV|'
    r'REMUX|HEVC|AVC|X26[45]|H\.?26[45]|AAC|EAC-?3|DDP?[57]|ATMOS|TRUEHD|'
    r'\bMKV\b|\bMP4\b|\bSCOPE\b|HDR10?\+?|\bDV\b|FRAMESTOR|\d+(?:\.\d+)?\s*[GM]B)\b', re.I)
_PLOT_SENTENCE_RE = re.compile(r'[.!؟?…،]\s')


def _clean_header_plot(text):
    """v4.3.0: the hero 'plot' slot only ever shows a real overview.

    Search rows built from provider streams used to carry the release
    filename ('… [WEBDL-2160p HEVC 8-bit EAC3 Atmos 5 1]-SCOPE') or the
    aggregator tech line ('EAC3 • 5 1 • NaN Mbps • NaN fps') in their
    description — that junk rendered where the movie overview belongs.
    Real overviews pass through untouched (minus NaN-token cleanup).
    """
    text = str(text or '').strip()
    if not text:
        return ''
    text = _PLOT_NAN_RE.sub('', text)
    text = _PLOT_CH_RE.sub(r'\1.1', text)
    text = _PLOT_SEP_RE.sub('  •  ', text).strip(' •|·-\t')
    if not text:
        return ''
    tech_hits = len(_PLOT_RELEASE_RE.findall(text))
    looks_like_sentence = bool(_PLOT_SENTENCE_RE.search(text)) and len(text) > 80
    if tech_hits >= 2 and not looks_like_sentence:
        return ''
    return text


_RTL_STRONG_RE = re.compile(r'[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]')
_LTR_STRONG_RE = re.compile(r'[A-Za-z]')


def _bidi_anchor(text):
    """v4.3.1: pin LTR strings to LTR base direction under the Arabic UI.

    Kodi picks the paragraph direction from the first strong character; a
    release name like '3840X2160_ALQ…' starts with digits (direction-weak),
    so the Arabic UI rendered it RTL-based — visually clipping the START of
    long names ('3840' → '340'). One leading LRM fixes the base direction.
    Arabic-leading text is left untouched so Arabic labels still ellipsize
    on their natural side.
    """
    text = str(text or '')
    if not text:
        return text
    ltr = _LTR_STRONG_RE.search(text)
    rtl = _RTL_STRONG_RE.search(text)
    if ltr and (not rtl or ltr.start() < rtl.start()):
        return '\u200e' + text
    return text


def _fit_label(text, max_chars=52):
    """v4.3.2: pre-truncate long UI strings in code, keeping the START.

    Kodi clips overflowing label text on the paragraph-start side under the
    Arabic UI — long release names lost their beginning ('MULTI' → 'IULTI',
    'WEB' → 'B') with no ellipsis. Direction marks did not change the clip
    side in practice, so the row property itself is now guaranteed to fit:
    the unfocused layout binds this fitted value, while the focused layout
    keeps the full name and scrolls it.
    """
    text = str(text or '')
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1].rstrip() + '…'

def _kodi_safe_meta_text(value, fallback=''):
    text = _kodi_safe_text(value, fallback='')
    if text:
        return text
    return _kodi_safe_text(fallback, fallback='')



def _row_quality_blob(row):
    bits = []
    for key in ('quality', 'highlight', 'badges', 'video_bits', 'audio_bits',
                'extraInfo', 'extraInfo2', 'name', 'label2'):
        value = (row or {}).get(key)
        if isinstance(value, (list, tuple)):
            bits.extend([str(v) for v in value if v])
        elif value:
            bits.append(str(value))
    return ' '.join(bits).upper()


# Elite-style image badges for the custom Nuvio Hub source results XML.
# These are lightweight URL properties only; Kodi's texture cache handles
# fetching/caching them and the text-chip fallback remains active if a badge
# image cannot be resolved.
# v4.8.0: community badge sets the user asked to be supported, offered as
# one-tap presets so nobody has to type a long URL on a TV remote. They are
# plain URLs — the loader treats them exactly like any pasted link.
# Each preset is (name, url, preview) — the preview is one representative
# badge from that set, so the picker can show what the set LOOKS like
# under its name instead of asking the user to guess from a URL.
ELITE_BADGE_PRESETS = (
    ('Sterzeck — Colorful & Concise',
     'https://raw.githubusercontent.com/danielsdian/ColorfulAndConcise/refs/heads/main/Sterzeck_badge.json',
     'https://raw.githubusercontent.com/kingsizew/badges/main/badge-images/resolution/4k.png'),
    ('Nosvasedis — Transparent',
     'https://gist.githubusercontent.com/nosvasedis/63b769d205bddbbef79faf8beef53c28/raw/transparent-nosvasedis-badges-nuvio',
     ''),
    ('Nosvasedis — Mono',
     'https://gist.githubusercontent.com/nosvasedis/1858e332fef11d136f76c697ea6c7439/raw/mono-nosvasedis-badges-nuvio',
     ''),
    ('Nosvasedis — Solid',
     'https://gist.githubusercontent.com/nosvasedis/7abd79424bb8981b511838524c52f097/raw/solid-nosvasedis-badges-nuvio',
     ''),
    ('Nosvasedis — Classic',
     'https://gist.githubusercontent.com/nosvasedis/7abd79424bb8981b511838524c52f097/raw/76c519d05f6518f0ed186ba802847c625ba730fa/nosvasedis-badges-nuvio',
     ''),
    ('BetterFormatter — Mono BGB',
     'https://raw.githubusercontent.com/9mousaa/BetterFormatter/main/presets/mono-bgb-sep-nodv.json',
     'https://raw.githubusercontent.com/9mousaa/BetterFormatter/main/images/mono-best-remux.png'),
)

_ELITE_BADGE_DEFAULT_JSON_URL = 'https://raw.githubusercontent.com/9mousaa/BetterFormatter/main/presets/mono-bgb-sep-nodv.json'
_ELITE_BADGE_BASE = 'https://raw.githubusercontent.com/leonevz/Elite-Badges/main/Badges/'
_ELITE_BADGE_RULE_CACHE = {'url': '', 'ts': 0.0, 'rules': None}
_ELITE_BADGE_REFRESH_LOCK = threading.Lock()
_ELITE_GROUP_LIMITS = {
    'source': 1,
    'resolution': 1,
    'video-tech': 2,
    'video-codec': 1,
    'bit-depth': 1,
    'audio-tech': 2,
    'audio-channels': 1,
}
_ELITE_BADGE_RULES = [
    ('source', r'\bremux\b', 'remux.png'),
    ('source', r'\b(blu[\s._-]?ray|bluray|bdrip|bdremux)\b', 'blu_ray_disc.png'),
    ('source', r'\b(web[\s._-]?dl|webdl)\b', 'WEBDL_transparent_4x.png'),
    ('source', r'\b(web[\s._-]?rip|webrip)\b', 'WEBRip_transparent_4x.png'),
    ('source', r'\bhdtv\b', 'HDTV_transparent_4x.png'),
    ('source', r'\b(dvd[\s._-]?rip|dvdrip)\b', 'DVD_RIP_transparent_4x.png'),
    ('resolution', r'\b(4k|2160p|uhd|ultra\s*hd)\b', '4k_ultra_hd.png'),
    ('resolution', r'\b(1080p|fhd|full\s*hd)\b', '1080p_full_hd.png'),
    ('resolution', r'\b720p\b', '720p_hd.png'),
    ('resolution', r'\b480p\b', '480p_sd.png'),
    ('video-tech', r'\b(imax[\s._-]*enhanced)\b', 'imax_enhanced.png'),
    ('video-tech', r'\b(imax)\b(?![\s._-]*enhanced)', 'imax.png'),
    ('video-tech', r'\b(dolby\s*vision|dovi|dv)\b', 'dolby_vision.png'),
    ('video-tech', r'\b(hdr10\+|hdr10\s*plus\b|hdr\s*10\s*\+)', 'hdr10_plus.png'),
    ('video-tech', r'\b(hdr10|hdr\s*10)\b(?!\s*\+|\s*plus)', 'hdr10.png'),
    ('video-tech', r'\bhdr\b', 'hdr.png'),
    ('video-tech', r'\bsdr\b', 'SDR_transparent_4x.png'),
    ('video-codec', r'\b(hevc|h[\s._-]?265|x265)\b', 'HEVC_transparent_4x.png'),
    ('video-codec', r'\b(avc|h[\s._-]?264|x264)\b', 'AVC_transparent_4x.png'),
    ('bit-depth', r'\b(10[\s._-]?bit|10b|hi10p)\b', '10Bit_transparent_4x.png'),
    ('bit-depth', r'\b(8[\s._-]?bit|8b)\b', '8Bit_transparent_4x.png'),
    ('audio-tech', r'\b(dolby\s*atmos|atmos)\b', 'dolby_atmos.png'),
    ('audio-tech', r'\b(truehd|true\s*hd|dolby\s*truehd)\b', 'truehd.png'),
    ('audio-tech', r'\b(ddp[\s._-]*[0-9][\s._-]*[0-9]|ddp|dd\+|dolby[\s._-]*digital[\s._-]*plus|e-?ac-?3)(?![a-z])', 'dolby_digital_plus.png'),
    ('audio-tech', r'\b(dd[\s._-]*[0-9][\s._-]*[0-9]|dd|dolby[\s._-]*digital|ac-?3)(?![\s._-]*plus|\+|p|[a-z])', 'dolby_digital.png'),
    ('audio-tech', r'\b(dts[:\s._-]*x)\b', 'dts_x.png'),
    ('audio-tech', r'\b(dts[\s._-]*hd[\s._-]*ma|dtshd\s*ma|dts[\s._-]*hd[\s._-]*master)\b', 'dts_hd_master_audio.png'),
    ('audio-tech', r'\b(dts[\s._-]*hd|dtshd)(?![\s._-]*(ma|master)|ma)\b', 'dts_hd.png'),
    ('audio-tech', r'\bdts\b(?![\s._:-]*(x|hd))', 'dts.png'),
    ('audio-channels', r'\b(7\.1|7-1|8ch|8\s*channel)\b', '7_1_audio.png'),
    ('audio-channels', r'\b(5\.1|5-1|6ch|6\s*channel)\b', '5_1_audio.png'),
]
_ELITE_COMPILED_BADGE_RULES = tuple(
    (group, re.compile(pattern, re.I), _ELITE_BADGE_BASE + filename)
    for group, pattern, filename in _ELITE_BADGE_RULES
)


def _elite_badge_blob(row, tags=None):
    bits = []
    # v4.7.3: the raw formatter text FIRST — custom badges.json patterns
    # (\u265b-gated quality rules and friends) target the AIOStreams
    # formatted output, not the cleaned display name.
    for value in (row.get('badge_blob_raw'),
                  row.get('name'), row.get('label2'), row.get('provider'), row.get('addon'), row.get('source_site'),
                  row.get('badges'), row.get('extraInfo'), row.get('extraInfo2')):
        if value:
            bits.append(str(value))
    for seq_key in ('video_bits', 'audio_bits'):
        for item in (row.get(seq_key) or []):
            if item:
                bits.append(str(item))
    for tag in (tags or []):
        if isinstance(tag, dict) and tag.get('text'):
            bits.append(str(tag.get('text')))
    return ' '.join(bits)


def _elite_builtin_badge_rules():
    return _ELITE_COMPILED_BADGE_RULES






def elite_preset_preview(url, fallback=''):
    """First badge image of a set, for the picker's preview.

    Uses the last-good disk copy when there is one so the picker never
    blocks on a network fetch; otherwise the hardcoded fallback.
    """
    try:
        rules = _elite_rules_from_disk(url)
        if rules:
            return rules[0][2]
    except Exception:
        pass
    return fallback


def _elite_url_provenance():
    """Which layer answered — ends the guessing in the next log."""
    if _elite_url_override_read() is not None:
        return 'dexhub-file'
    if _settings_file_value('elite_badges_json_url') is not None:
        return 'settings.xml'
    try:
        if (xbmcgui.Window(10000).getProperty('dexhub.badges.url') or '').strip():
            return 'window-prop'
    except Exception:
        pass
    return 'getSetting'


def _elite_url_override_path():
    try:
        profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
        return os.path.join(profile, 'elite_badges_url.txt')
    except Exception:
        return ''


def _elite_url_override_read():
    """The NuvioHub-owned badges URL, or None when unset.

    v4.7.8: on the reporting device the Kodi settings route kept returning
    the default URL through EVERY layer that was tried — the reused
    interpreter's copy, a published window property, and finally the
    profile settings.xml itself. Rather than keep guessing which layer
    reverts it, NuvioHub now owns a file it writes and reads directly.
    An empty file means "use the built-in set"; no file means "fall back
    to the Kodi setting".
    """
    try:
        path = _elite_url_override_path()
        if path and os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as handle:
                return handle.read().strip()
    except Exception as exc:
        log.silent('ELITE_BADGES_OVERRIDE', exc)
    return None


def _elite_url_override_write(url):
    """Persist (or clear) the addon-owned badges URL and drop cached rules."""
    path = _elite_url_override_path()
    if not path:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if url is None:
            if os.path.isfile(path):
                os.remove(path)
        else:
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(str(url).strip())
        _ELITE_BADGE_RULE_CACHE.clear()
        _SETTINGS_FILE_MEMO.update({'sig': None, 'values': {}})
        return True
    except Exception as exc:
        log.silent('ELITE_BADGES_OVERRIDE', exc)
        return False


# ── v5.4.4: live settings reads moved to resources/lib/live_settings.py ──
# One implementation for the whole addon: profile settings.xml first, then
# the value the service publishes, then this interpreter's copy — with a
# single default shared by all three, which is what the badges toggle
# needed. The old names stay as aliases so nothing else had to move.
from . import live_settings as _live   # noqa: E402

_SETTINGS_FILE_MEMO = _live._SETTINGS_FILE_MEMO
_settings_file_value = _live._settings_file_value


def _elite_badge_setting_url():
    """v4.7.5: read the LIVE value, not this interpreter's stale copy.

    With reuselanguageinvoker=true the plugin runs in a long-lived Python
    process whose addon-settings copy is loaded once. The settings dialog
    saves in Kodi's MAIN process, so the reused interpreter keeps handing
    back the value it started with — pasting a new badges URL changed
    nothing and the previously saved set kept rendering ("it reverts to
    the saved link and its images"). The service publishes the live value
    to a window property on every settings change (window properties are
    global and never stale); getSetting stays as the fallback.
    """
    # 0) a URL set from inside NuvioHub — an addon-owned file that no Kodi
    #    settings layer can revert. This exists because the settings dialog
    #    route kept handing back the default on the user's box no matter
    #    what was pasted into it.
    override = _elite_url_override_read()
    if override is not None:
        return override
    # 1) the file Kodi wrote when the dialog was confirmed
    disk = _settings_file_value('elite_badges_json_url')
    if disk is not None:
        return disk.strip()
    # 2) the value the service published on the last settings change
    try:
        live = (xbmcgui.Window(10000).getProperty('dexhub.badges.url') or '').strip()
    except Exception:
        live = ''
    if live:
        return '' if live == '-' else live
    # 3) this interpreter's own copy
    try:
        return (xbmcaddon.Addon('plugin.video.nuviohub').getSetting('elite_badges_json_url') or '').strip()
    except Exception:
        return ''


def _elite_badges_enabled():
    """Image badges: ON by default, resolved from the freshest source.

    v5.4.3: the toggle is read from the profile's settings.xml first (the
    file Kodi writes when the dialog is confirmed), then the value the
    service publishes, then this interpreter's own copy. Every one of those
    three now defaults to ON — a disagreement between them was exactly why
    ticking the box appeared to do nothing: the service published 'false'
    for an unwritten key and that beat the setting.

    Kodi caches remote textures per URL, so the cost is a one-time warm-up
    on the first big list; the local text chips remain the zero-network
    fallback for anyone who turns this off.
    """
    # v4.7.5: same staleness applies to the toggle — prefer the live value.
    return _live.live_bool('elite_badges_enabled',
                           'dexhub.badges.enabled', default=True)


def _elite_rule_entry(item, inherited_group=''):
    """One rule from a single entry, tolerant of key naming.

    v4.7.4: badge-set authors use different vocabularies — pattern/regex/
    match/expr for the test, and imageURL/imageUrl/image/icon/url/badge for
    the art. Accepting only ('pattern', 'imageURL') meant EVERY set built
    to another convention parsed to nothing and silently fell back to the
    built-in rules, which is exactly the "the first set is forced" report.
    """
    if not isinstance(item, dict):
        return None
    if item.get('isEnabled') is False or item.get('enabled') is False:
        return None
    group = str(item.get('groupId') or item.get('group') or item.get('category')
                or inherited_group or 'other').strip() or 'other'
    pattern = ''
    for key in ('pattern', 'regex', 'match', 'expr', 'expression'):
        if item.get(key):
            pattern = str(item.get(key)).strip()
            break
    image = ''
    for key in ('imageURL', 'imageUrl', 'image_url', 'image', 'icon',
                'iconURL', 'url', 'badge', 'src'):
        if item.get(key):
            image = str(item.get(key)).strip()
            break
    if not pattern or not image:
        return None
    return (group, pattern, image)


def _elite_iter_rule_entries(data, inherited_group=''):
    """Walk any of the shapes badge sets ship in: a top-level list, a
    {'filters': [...]} or {'badges'/'rules'/'items': [...]} object, those
    collections as dicts keyed by rule id, and groups that nest their own
    filters."""
    if isinstance(data, list):
        for item in data:
            for rule in _elite_iter_rule_entries(item, inherited_group):
                yield rule
        return
    if not isinstance(data, dict):
        return
    collections = []
    for key in ('filters', 'badges', 'rules', 'items'):
        if data.get(key) is not None:
            collections.append(data.get(key))
    groups = data.get('groups')
    if isinstance(groups, (list, dict)):
        group_items = groups.values() if isinstance(groups, dict) else groups
        for grp in group_items:
            if not isinstance(grp, dict):
                continue
            gid = str(grp.get('id') or grp.get('groupId') or grp.get('name') or '').strip()
            for key in ('filters', 'badges', 'rules', 'items'):
                if grp.get(key) is not None:
                    for rule in _elite_iter_rule_entries(grp.get(key), gid):
                        yield rule
    if not collections:
        # a bare rule object, or a dict keyed by rule id
        direct = _elite_rule_entry(data, inherited_group)
        if direct:
            yield direct
            return
        for value in data.values():
            if isinstance(value, dict):
                rule = _elite_rule_entry(value, inherited_group)
                if rule:
                    yield rule
        return
    for coll in collections:
        entries = coll.values() if isinstance(coll, dict) else coll
        if not isinstance(entries, (list, tuple)) and not hasattr(entries, '__iter__'):
            continue
        for item in entries:
            rule = _elite_rule_entry(item, inherited_group)
            if rule:
                yield rule


def _strip_variable_lookbehind(pattern):
    """Drop lookbehind groups Python's `re` cannot compile.

    v4.8.0: community badge sets are authored against JavaScript regex,
    which allows VARIABLE-LENGTH lookbehind — `(?<!e[-_. ]?)ac3` and
    friends. Python only accepts fixed-width lookbehind, so those rules
    raised at compile time and were dropped: on the Sterzeck set that
    silently cost the DD/AC3, AAC and Opus audio badges.

    Removing the lookbehind makes a rule slightly more permissive (an
    'eac3' release can now also match the 'ac3' badge). A marginally
    eager badge is a far better outcome than a missing one, and the
    substitution is logged so it is never a mystery.
    """
    out = []
    i = 0
    text = str(pattern or '')
    while i < len(text):
        if text.startswith('(?<!', i) or text.startswith('(?<=', i):
            depth = 0
            j = i
            while j < len(text):
                ch = text[j]
                if ch == '\\':
                    j += 2
                    continue
                if ch == '[':                       # skip character classes
                    j += 1
                    while j < len(text) and text[j] != ']':
                        j += 2 if text[j] == '\\' else 1
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            i = j                                   # skip the whole group
            continue
        out.append(text[i])
        i += 1
    return ''.join(out)


def _elite_compile_rules(rules):
    """v4.7.7: pre-compile every rule pattern once per load.

    A big AIOStreams list is hundreds of rows and a set like the user's is
    63 rules, so matching went through re.search(str, ...) tens of
    thousands of times per screen. Compiling up front turns each of those
    into a direct call, and a pattern that will never compile is dropped
    here instead of raising per row.
    """
    out, salvaged, dropped = [], 0, 0
    for group, pattern, image in rules or []:
        compiled = None
        for attempt, candidate in enumerate((
                pattern,
                str(pattern or '').replace('(?i)', ''),
                _strip_variable_lookbehind(pattern),
                _strip_variable_lookbehind(str(pattern or '').replace('(?i)', '')))):
            try:
                compiled = re.compile(candidate, re.I)
                if attempt >= 2:
                    salvaged += 1
                break
            except Exception:
                continue
        if compiled is None:
            dropped += 1
            continue
        out.append((group, compiled, image))
    if salvaged or dropped:
        xbmc.log('[NuvioHub] elite badges: %d rule(s) salvaged from JS-only regex, '
                 '%d unusable' % (salvaged, dropped), xbmc.LOGINFO)
    return out


def _elite_rules_from_json_blob(blob):
    try:
        data = json.loads(blob or '{}')
    except Exception:
        return []
    out = []
    seen = set()
    try:
        for rule in _elite_iter_rule_entries(data):
            if rule in seen:
                continue
            seen.add(rule)
            out.append(rule)
    except Exception as exc:
        log.silent('ELITE_BADGES_PARSE', exc)
    return out


def _elite_badge_rules():
    """Rules for image badges.

    The bundled/default Elite rules stay instant and offline. If the user pastes
    a different badges.json URL in settings, fetch it once per Kodi process and
    fall back to the bundled rules if the URL is slow, invalid, or unavailable.
    """
    url = _elite_badge_setting_url()
    if not url:
        return _elite_builtin_badge_rules()
    # v4.7.4: the default URL used to short-circuit to the hardcoded builtin
    # rules and was never actually fetched — so switching AWAY from it and
    # hitting any snag landed on the same built-in art, which is what made
    # the first set look mandatory. Every configured URL is fetched now; the
    # builtin set is the offline safety net only.
    if _ELITE_BADGE_RULE_CACHE.get('url') and _ELITE_BADGE_RULE_CACHE['url'] != url:
        # a real change: let this URL report its own success/failure once
        for key in ('applied_url', 'warned_url', 'fail_url'):
            _ELITE_BADGE_RULE_CACHE.pop(key, None)

    now = time.monotonic()
    cached_url = _ELITE_BADGE_RULE_CACHE.get('url')
    cached_rules = _ELITE_BADGE_RULE_CACHE.get('rules')
    cached_ts = float(_ELITE_BADGE_RULE_CACHE.get('ts') or 0.0)
    if cached_url == url and cached_rules and (now - cached_ts) < 3600:
        return list(cached_rules)
    # v4.7.2: negative memo — after a failed fetch, do not stall EVERY list
    # rebuild retrying the URL for the memo window.
    if (_ELITE_BADGE_RULE_CACHE.get('fail_url') == url
            and (now - float(_ELITE_BADGE_RULE_CACHE.get('fail_ts') or 0.0)) < 180):
        disk = _elite_rules_from_disk(url)
        return disk if disk else _elite_builtin_badge_rules()

    rules = []
    try:
        if Request is None or urlopen is None:
            raise RuntimeError('urllib unavailable')
        req = Request(url, headers={'User-Agent': 'NuvioHub/%s Kodi' % (ADDON.getAddonInfo('version') or '3')})
        # v4.7.2: 3s + 512KB silently truncated/failed real-world files and
        # fell back to the BUILTIN rules — which read as "I changed the JSON
        # and nothing changed". 8s / 2MB, last-good disk copy, and a one-time
        # visible warning when the custom URL cannot be used.
        with urlopen(req, timeout=8.0) as resp:
            raw = resp.read(1024 * 1024 * 2)
        try:
            text = raw.decode('utf-8')
        except Exception:
            text = raw.decode('utf-8', 'ignore')
        rules = _elite_rules_from_json_blob(text)
        if rules:
            _elite_rules_to_disk(url, text)
    except Exception as exc:
        log.silent('ELITE_BADGES_JSON', exc)
        rules = []

    if rules:
        rules = _elite_compile_rules(rules)
        _ELITE_BADGE_RULE_CACHE.update({'url': url, 'ts': now, 'rules': list(rules)})
        _ELITE_BADGE_RULE_CACHE.pop('fail_url', None)
        xbmc.log('[NuvioHub] elite badges: source=custom via=%s rules=%d sample=%s url=%s'
                 % (_elite_url_provenance(), len(rules),
                    (rules[0][2] if rules else '-'), url), xbmc.LOGINFO)
        _elite_notify_custom_applied_once(url, len(rules))
        return rules
    _ELITE_BADGE_RULE_CACHE.update({'fail_url': url, 'fail_ts': now})
    disk = _elite_rules_from_disk(url)
    if disk:
        xbmc.log('[NuvioHub] elite badges: source=disk-lastgood rules=%d url=%s' % (len(disk), url), xbmc.LOGINFO)
        return disk
    xbmc.log('[NuvioHub] elite badges: source=builtin-after-fail url=%s' % url, xbmc.LOGWARNING)
    _elite_warn_custom_failed_once(url)
    return _elite_builtin_badge_rules()


_ELITE_BADGE_RULES_SYNC = _elite_badge_rules


def _elite_badge_rules_nonblocking():
    """Return cached/disk rules immediately and refresh a stale URL off-UI."""
    if _elite_badge_rules is not _ELITE_BADGE_RULES_SYNC:
        return _elite_badge_rules()
    url = _elite_badge_setting_url()
    if not url:
        return _elite_builtin_badge_rules()
    now = time.monotonic()
    if (_ELITE_BADGE_RULE_CACHE.get('url') == url
            and _ELITE_BADGE_RULE_CACHE.get('rules')
            and now - float(_ELITE_BADGE_RULE_CACHE.get('ts') or 0.0) < 3600):
        return list(_ELITE_BADGE_RULE_CACHE['rules'])
    if (_ELITE_BADGE_RULE_CACHE.get('fallback_url') == url
            and _ELITE_BADGE_RULE_CACHE.get('fallback_rules')):
        fallback = list(_ELITE_BADGE_RULE_CACHE['fallback_rules'])
    else:
        fallback = _elite_rules_from_disk(url) or _elite_builtin_badge_rules()
        _ELITE_BADGE_RULE_CACHE.update({
            'fallback_url': url, 'fallback_rules': list(fallback),
        })
    start = False
    with _ELITE_BADGE_REFRESH_LOCK:
        if _ELITE_BADGE_RULE_CACHE.get('refreshing_url') != url:
            _ELITE_BADGE_RULE_CACHE['refreshing_url'] = url
            start = True
    if start:
        def _refresh():
            try:
                _elite_badge_rules()
            finally:
                with _ELITE_BADGE_REFRESH_LOCK:
                    if _ELITE_BADGE_RULE_CACHE.get('refreshing_url') == url:
                        _ELITE_BADGE_RULE_CACHE.pop('refreshing_url', None)
        try:
            from .runtime_tasks import submit_optional
            accepted = submit_optional(
                _refresh, key='badge-rules:%s' % str(url))
        except Exception:
            accepted = False
        if not accepted:
            with _ELITE_BADGE_REFRESH_LOCK:
                _ELITE_BADGE_RULE_CACHE.pop('refreshing_url', None)
    return fallback


def _elite_notify_custom_applied_once(url, count):
    """v4.7.3: close the feedback loop — 'I changed the JSON and nothing
    changed' was undebuggable because success and silent-fallback looked
    identical on screen."""
    if _ELITE_BADGE_RULE_CACHE.get('applied_url') == url:
        return
    _ELITE_BADGE_RULE_CACHE['applied_url'] = url
    try:
        xbmcgui.Dialog().notification(
            'Nuvio Hub', tr('تم تطبيق %d قاعدة شارات من الرابط المخصص') % count,
            xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
    except Exception:
        pass


def _elite_rules_disk_path(url):
    import hashlib
    digest = hashlib.sha1(str(url or '').encode('utf-8', 'replace')).hexdigest()[:10]
    prof = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    return os.path.join(prof, 'elite_rules_%s.json' % digest)


def _elite_rules_to_disk(url, text):
    try:
        path = _elite_rules_disk_path(url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(text)
    except Exception as exc:
        log.silent('ELITE_BADGES_DISK', exc)


def _elite_rules_from_disk(url):
    """Last-good copy of the user's custom rules — survives restarts and
    network hiccups so a temporary fetch failure never flips badges back
    to the builtin set."""
    try:
        path = _elite_rules_disk_path(url)
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as handle:
                return _elite_compile_rules(_elite_rules_from_json_blob(handle.read()))
    except Exception as exc:
        log.silent('ELITE_BADGES_DISK', exc)
    return []


def _elite_warn_custom_failed_once(url):
    if _ELITE_BADGE_RULE_CACHE.get('warned_url') == url:
        return
    _ELITE_BADGE_RULE_CACHE['warned_url'] = url
    try:
        xbmcgui.Dialog().notification(
            'Nuvio Hub', tr('تعذر تحميل badges.json المخصص — سيتم استخدام الافتراضي'),
            xbmcgui.NOTIFICATION_WARNING, 4000, sound=False)
    except Exception:
        pass


def _elite_pattern_matches(pattern, text):
    try:
        if hasattr(pattern, 'search'):
            return pattern.search(text) is not None
        return re.search(pattern, text) is not None
    except Exception:
        try:
            cleaned = str(pattern or '').replace('(?i)', '')
            return re.search(cleaned, text, re.I) is not None
        except Exception:
            return False


_ELITE_RESULT_CACHE = {}
_ELITE_RESULT_CACHE_MAX = 512
# Noise that never decides a badge: sizes, seed/peer counts, durations,
# bare numbers and separators. Everything ELSE is kept, so a token this
# addon has never heard of still reaches the rules — the cache can only
# ever merge rows that differ by noise, never by a technical fact.
_ELITE_NOISE_RE = re.compile(
    # a number followed by a unit or a countable word — "24.5 GB",
    # "12 seeders", "1h 58min", "45 fps"
    r'(?i)\b\d+(?:[.,]\d+)?\s*'
    r'(?:[kmgt]i?b|bytes?|kbps|mbps|fps|hz|'
    r'min(?:ute)?s?|sec(?:ond)?s?|hrs?|hours?|h|m|s|'
    r'seed(?:er)?s?|peers?|leechers?|files?|parts?)\b'
    # or a labelled field: "size: 24.5GB", "seeders = 12"
    r'|\b(?:seed(?:er)?s?|peers?|leechers?|size|duration|age|files?|parts?)'
    r'\s*[:=]\s*\S+'
    # arrow/bolt counters and bare percentages
    r'|\d+\s*(?:\u2191|\u2193|\u26a1)\s*\d*'
    r'|\b\d{1,3}(?:[.,]\d{1,3})?\s*%')


def _elite_signature(text):
    """Collapse a stream blob to what can actually change its badges.

    v5.4.5: the previous per-row cache keyed on the FULL blob — which
    carries the file size, indexer and release group — so 300 rows of the
    same release produced 300 distinct keys and the cache never hit once.

    This strips only provable noise (sizes, seeds, durations, percentages)
    and lowercases the rest. Unknown tokens are PRESERVED: a set that keys
    on something this addon has never seen still gets its own cache entry,
    so the optimisation can never silently drop a badge.
    """
    cleaned = _ELITE_NOISE_RE.sub(' ', str(text or '').lower())
    return ' '.join(sorted(set(cleaned.split())))


# Fingerprint of the CONTENT of a rule set, cached inside the rules cache
# entry itself. An earlier version memoised on id(rules); CPython recycles
# id values once an object is freed, so a replaced set could inherit the
# previous set's fingerprint — and with it, its cached badge art. Content
# is the only safe key, and it is computed once per set, not once per row.
_ELITE_RULES_FP = {'id': None, 'fp': ''}


def _elite_rules_fingerprint(rules):
    # Memoised on a cheap CONTENT probe — length plus the first and last
    # rule — never on id(), which CPython recycles. Two different sets that
    # agree on all three are hashed in full anyway, because the probe is the
    # cache key, not the answer.
    rules = rules or ()
    probe = (len(rules),
             (rules[0][0], getattr(rules[0][1], 'pattern', ''), rules[0][2]) if rules else (),
             (rules[-1][0], getattr(rules[-1][1], 'pattern', ''), rules[-1][2]) if rules else ())
    if _ELITE_RULES_FP.get('id') == probe:
        return _ELITE_RULES_FP['fp']
    import hashlib
    digest = hashlib.sha1()
    for group, pattern, image in rules:
        digest.update(('%s\x00%s\x00%s\x1f' % (
            group, getattr(pattern, 'pattern', pattern), image)).encode('utf-8', 'replace'))
    fp = digest.hexdigest()[:12]
    _ELITE_RULES_FP.update({'id': probe, 'fp': fp})
    return fp


def _elite_badge_images(row, tags=None, max_items=10):
    if not _elite_badges_enabled():
        return []
    text = _elite_badge_blob(row or {}, tags=tags)
    if not text:
        return []
    # v5.4.5: the key identifies the RULE SET BY ITS CONTENT, not by the URL
    # it came from. Keying on url+timestamp looked equivalent but was not:
    # rules can be replaced without either changing (a repair, a disk
    # last-good copy, a set swapped in-process), and the shared cache would
    # then hand back art built from the previous set.
    rules = _elite_badge_rules_nonblocking()
    rules_id = _elite_rules_fingerprint(rules)
    cache_key = '%s|%s|%s' % (rules_id, int(max_items or 10), _elite_signature(text))
    cached = (row or {}).get('_elite_badge_cache')
    if isinstance(cached, tuple) and len(cached) == 2 and cached[0] == cache_key:
        return list(cached[1])
    shared = _ELITE_RESULT_CACHE.get(cache_key)
    if shared is not None:
        if isinstance(row, dict):
            row['_elite_badge_cache'] = (cache_key, shared)
        return list(shared)
    out = []
    used_images = set()
    group_counts = {}
    # v5.4.5: an early exit on "every group is full" was tried here and
    # REMOVED. It was worth ~11% while the signature cache below is worth
    # ~16x, and getting the saturation test exactly right across arbitrary
    # third-party sets proved fragile — one wrong reading silently drops a
    # badge. Speed that risks correctness is not worth 11%.
    for group, pattern, image_url in rules:
        if image_url in used_images:
            continue
        # v4.7.4: third-party sets use their own group ids ('gq', 'gr', …);
        # capping unknown groups at 1 truncated them to a few badges and made
        # different sets look interchangeable. Known groups keep their tuned
        # limits, unknown ones get 2.
        if group_counts.get(group, 0) >= _ELITE_GROUP_LIMITS.get(group, 2):
            continue
        if not _elite_pattern_matches(pattern, text):
            continue
        out.append(image_url)
        used_images.add(image_url)
        group_counts[group] = group_counts.get(group, 0) + 1
        if len(out) >= max_items:
            break
    result = tuple(out)
    if len(_ELITE_RESULT_CACHE) >= _ELITE_RESULT_CACHE_MAX:
        _ELITE_RESULT_CACHE.clear()          # cheap bound; sets are small
    _ELITE_RESULT_CACHE[cache_key] = result
    if isinstance(row, dict):
        row['_elite_badge_cache'] = (cache_key, result)
    return out


# --- dexhub-407-patch ---
# Sort modes for the results drawer. Kept separate from QUALITY_FILTERS so a
# filter and a sort can be active at the same time.
SORT_MODES = [
    ('S:DEFAULT',  'SORT \u2022 RECOMMENDED'),
    ('S:SIZE',     'SORT \u2022 SIZE'),
    ('S:QUALITY',  'SORT \u2022 QUALITY'),
    ('S:PROVIDER', 'SORT \u2022 SOURCE'),
    ('S:NAME',     'SORT \u2022 NAME'),
]

_SORT_QUALITY_RANK = (
    (('2160', '4K', 'UHD'), 5),
    (('1080', 'FHD'), 4),
    (('720', 'HD'), 3),
    (('480', 'SD'), 2),
)


def _sort_mode_label(value):
    for key, label in SORT_MODES:
        if key == value:
            return tr(label)
    return tr(SORT_MODES[0][1])


def _sort_size_bytes(row):
    """Parse the human size label ("12.4 GB") into bytes for ordering."""
    text = str((row or {}).get('size_label') or '').upper().replace(',', '')
    m = re.search(r'(\d+(?:\.\d+)?)\s*(TB|GB|MB|KB|B)\b', text)
    if not m:
        return -1.0
    try:
        value = float(m.group(1))
    except (TypeError, ValueError):
        return -1.0
    return value * {'TB': 1024.0 ** 4, 'GB': 1024.0 ** 3,
                    'MB': 1024.0 ** 2, 'KB': 1024.0, 'B': 1.0}[m.group(2)]


def _sort_quality_rank(row):
    blob = _row_quality_blob(row)
    for tokens, rank in _SORT_QUALITY_RANK:
        if any(t in blob for t in tokens):
            return rank
    return 0


def _sorted_rows(rows, mode):
    """Reorder rows for the chosen mode. S:DEFAULT keeps the ranked order."""
    rows = list(rows or [])
    mode = str(mode or 'S:DEFAULT')
    if mode == 'S:SIZE':
        # Rows with no size go last rather than sorting as zero.
        return sorted(rows, key=lambda r: (_sort_size_bytes(r) < 0, -_sort_size_bytes(r)))
    if mode == 'S:QUALITY':
        return sorted(rows, key=lambda r: (-_sort_quality_rank(r), -_sort_size_bytes(r)))
    if mode == 'S:PROVIDER':
        return sorted(rows, key=lambda r: (str(r.get('addon') or r.get('provider') or '').upper(),
                                           -_sort_size_bytes(r)))
    if mode == 'S:NAME':
        return sorted(rows, key=lambda r: str(r.get('name') or '').upper())
    return rows


def _quality_filter_label(value):
    for key, label, _tokens in QUALITY_FILTERS:
        if key == value:
            return tr(label)
    return tr(value or '')


def _filter_label(value):
    value = str(value or 'ALL')
    if value == 'ALL':
        return tr('ALL RESULTS')
    if value.startswith('Q:'):
        return _quality_filter_label(value)
    if value.startswith('P:'):
        return tr('PROVIDER • %s') % value[2:]
    if value.startswith('V:'):
        return tr('إضافة • %s') % value[2:]
    if value.startswith('T:'):
        return tr('TYPE • %s') % value[2:]
    return tr(value)


def _row_matches_quality(row, filter_value):
    blob = _row_quality_blob(row)
    for key, _label, tokens in QUALITY_FILTERS:
        if key != filter_value:
            continue
        if key == 'Q:720P':
            return any(t in blob for t in tokens) and '1080' not in blob and '2160' not in blob and '4K' not in blob
        if key == 'Q:480P':
            return any(t in blob for t in tokens) and '720' not in blob and '1080' not in blob and '2160' not in blob and '4K' not in blob
        return any(t in blob for t in tokens)
    return False


def _row_provider_filter(row):
    provider = str((row or {}).get('addon') or (row or {}).get('source_site') or (row or {}).get('provider') or '').strip().upper()
    return ('P:%s' % provider) if provider else ''


def _row_group_name(row):
    """v4.6.1: TOP-LEVEL provider (the addon the user installed — Dexstreams,
    Arabmedia, Plex…), as opposed to _row_provider_filter's inner scraper
    (EASYNEWS SEARCH 1080P, MEDIAFUSION…). The chips strip groups on this."""
    return str((row or {}).get('provider_name_raw')
               or (row or {}).get('provider') or '').strip()


def _row_group_filter(row):
    name = _row_group_name(row).upper()
    return ('V:%s' % name) if name else ''


def _group_cycle_values(rows):
    """Provider-chip order: All, then count descending and first-seen."""
    counts, order = {}, []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = _row_group_name(row)
        if not name:
            continue
        if name not in counts:
            counts[name] = 0
            order.append(name)
        counts[name] += 1
    ranked = sorted(order, key=lambda n: (-counts[n], order.index(n)))
    return ['ALL'] + ['V:%s' % n.upper() for n in ranked]


# v4.6.6: the regex-badge identity colours are BACK. The 4.6.0 rewrite
# flattened every format badge to one grey chip because the original
# per-tag fg/bg came through $INFO[ListItem…] colour attributes — the
# Kodi 22 no-per-item-resolution bug. The tag vocabulary is the closed
# _NATIVE_TAGS set, so each tag maps to one of nine colour CLASSES and the
# skin switches static-coloured label variants on the raw fmt{n}_cls key.
# Six visible slots keep the row light on ARM without changing parsed data.
_TAG_CLASS = {
    '2160P': 'res', '4K': 'res', '1080P': 'res', '720P': 'res',
    'HDR10+': 'hdr', 'HDR10': 'hdr', 'HDR': 'hdr',
    'DV': 'dv',
    'HEVC': 'codec', 'AV1': 'codec', 'H264': 'codec',
    'ATMOS': 'aud', 'TRUEHD': 'aud',
    'DTS-HD': 'aud', 'DTS-X': 'aud', 'DTS': 'aud',
    'DD+': 'aud', 'DD-EX': 'aud',
    '7.1': 'ch', '5.1': 'ch',
    'REMUX': 'remux',
    'BLURAY': 'src', 'WEB-DL': 'src', 'WEBDL': 'src', 'WEBRIP': 'src',
    'DUBBED': 'lang', 'MULTI': 'lang', 'SUBS': 'lang',
}


# The nine identity colours the skin used to hold as static variants.
# Keeping them here means one place to change a colour, and no per-frame
# condition in the row layout.
_TAG_CLASS_COLORS = {
    'res': 'FF8FBEDC',      # resolution — cool blue
    'hdr': 'FFD8B488',      # HDR10 / HDR10+ — muted amber
    'dv': 'FFBBA6D6',       # Dolby Vision — mauve
    'codec': 'FF9AC4A6',    # HEVC / AV1 / H264 — sage
    'aud': 'FFB4A8D8',      # Atmos / TrueHD / DTS / DD+ — lavender
    'ch': 'FFAEB2C6',       # 7.1 / 5.1 — steel
    'remux': 'FFD69C9C',    # REMUX — coral
    'src': 'FF9CB6CE',      # BluRay / WEB — soft blue
    'lang': 'FFC2C4A0',     # DUBBED / MULTI / SUBS — soft gold-green
    'oth': 'FFDDE3EC',      # fallback — light
}


def _tag_class(text):
    return _TAG_CLASS.get(str(text or '').strip().upper(), 'oth')


def _row_type_filter(row):
    # v4.1.0: the source-type chip doubles as a filter group so users can
    # narrow to just their USENET / DEBRID / TORRENT / DIRECT / server rows.
    stype = str((row or {}).get('source_type_label') or (row or {}).get('source_type') or '').strip().upper()
    return ('T:%s' % stype) if stype else ''


def _result_identity(row):
    """Stable UI identity without reparsing or mutating the playable URL."""
    row = row if isinstance(row, dict) else {}
    key = str(row.get('stream_key') or '').strip()
    if key:
        return key
    return '|'.join(str(row.get(name) or '') for name in (
        'provider_name_raw', 'provider', 'addon', 'name', 'size_label'))


def _looks_arabic_text(value):
    text = str(value or '').strip()
    if not text:
        return False
    for ch in text:
        o = ord(ch)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF:
            return True
    return False


def _source_art_identity_key(payload=None):
    data = payload or {}
    try:
        media_type = str(data.get('media_type') or data.get('type') or '').strip().lower()
        canonical = str(data.get('canonical_id') or data.get('id') or '').strip()
        video_id = str(data.get('video_id') or '').strip()
        tmdb_id = str(data.get('tmdb_id') or '').strip()
        imdb_id = str(data.get('imdb_id') or '').strip()
        tvdb_id = str(data.get('tvdb_id') or '').strip()
        season = str(data.get('season') or '').strip()
        episode = str(data.get('episode') or '').strip()
        title = str(data.get('show_title') or data.get('originaltitle') or data.get('title') or data.get('name') or '').strip().lower()
        return '|'.join([media_type, canonical, video_id, tmdb_id, imdb_id, tvdb_id, season, episode, title])
    except Exception:
        return ''


def _source_meta_backfill(meta):
    """Fast-path metadata enrichment for the source picker window.

    NEVER hits the network. It consults TMDb Helper's local SQLite database,
    which is already populated and cached by Kodi, and prefers that artwork to
    a provider's generic backdrop.
    """
    meta = dict(meta or {})
    tmdb_id = str(meta.get('tmdb_id') or '').strip()
    imdb_id = str(meta.get('imdb_id') or '').strip()
    media_type = str(meta.get('media_type') or meta.get('type') or 'movie').strip().lower()
    if media_type in ('show', 'tv', 'anime', 'series', 'tvshow'):
        media_type = 'series'
    title = str(meta.get('originaltitle') or meta.get('title') or meta.get('name') or '').strip()
    year = str(meta.get('year') or '').strip()
    if not (tmdb_id or imdb_id or title):
        return meta

    source_poster = meta.get('poster') or ''
    source_fanart = meta.get('fanart') or meta.get('background') or source_poster or ''
    source_clearlogo = meta.get('clearlogo') or meta.get('logo') or ''

    bundle = {}
    try:
        bundle = _tmdb_art_db.get_meta_bundle_from_db(
            tmdb_id=tmdb_id,
            media_type=media_type,
            imdb_id=imdb_id,
            title=title,
            year=year,
        ) or {}
    except Exception:
        bundle = {}

    tmdb_poster = bundle.get('poster') or ''
    tmdb_clearlogo = bundle.get('clearlogo') or ''
    tmdb_fanart = bundle.get('fanart') or bundle.get('landscape') or ''

    if tmdb_poster:
        meta['poster'] = tmdb_poster
    elif source_poster:
        meta['poster'] = source_poster

    # TMDb Helper is the canonical local artwork source. Its cached backdrop is
    # already richer and usually present in Kodi's texture cache, so it should
    # win over a provider's generic poster/background without any network call.
    if tmdb_fanart:
        meta['fanart'] = tmdb_fanart
        meta['background'] = tmdb_fanart
    elif source_fanart:
        meta['fanart'] = source_fanart
        meta['background'] = source_fanart

    if tmdb_clearlogo:
        meta['clearlogo'] = tmdb_clearlogo
        meta['logo'] = tmdb_clearlogo
    elif source_clearlogo:
        meta['clearlogo'] = source_clearlogo
        meta['logo'] = source_clearlogo

    db_title = bundle.get('title') or bundle.get('name') or ''
    current_title = str(meta.get('title') or '').strip()
    if db_title and (not current_title or _looks_arabic_text(current_title)):
        meta['title'] = db_title

    # Fill the hero text from the same local TMDb Helper row. Lists and tuples
    # are preserved here; onInit normalises them for Kodi labels below.
    for target, candidates in (
            ('plot', ('plot', 'overview', 'description')),
            ('year', ('year',)), ('rating', ('rating', 'imdbRating')),
            ('genre', ('genre', 'genres')), ('studio', ('studio', 'studios')),
            ('cast', ('cast',))):
        if meta.get(target) not in (None, '', [], {}):
            continue
        for source_key in candidates:
            value = bundle.get(source_key)
            if value not in (None, '', [], {}):
                meta[target] = value
                break

    if not meta.get('fanart') and meta.get('poster'):
        meta['fanart'] = meta.get('poster')
        meta['background'] = meta.get('poster')
    return meta


def _normalize_mode(value):
    raw = str(value or '').strip().lower()
    if raw in (MODE_PLAY_SUBS, 'play_with_subtitles', 'with_subtitles', 'with-subs', 'تشغيل مع ترجمة', 'play with subtitles'):
        return MODE_PLAY_SUBS
    # Legacy/empty/ask values all become normal playback. Playback mode is now
    # controlled from settings only; no per-click prompt.
    return MODE_PLAY


class SourcesWindow(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.results = kwargs.get('results') or []
        self.meta = kwargs.get('meta') or {}
        self.selected = None
        self.active_filter = 'ALL'
        # --- dexhub-407-patch ---
        try:
            self.active_sort = str(ADDON.getSetting('source_sort_mode') or 'S:DEFAULT') or 'S:DEFAULT'
        except Exception:
            self.active_sort = 'S:DEFAULT'
        if self.active_sort not in [k for k, _l in SORT_MODES]:
            self.active_sort = 'S:DEFAULT'
        self.filters = []
        self.play_mode = _normalize_mode(kwargs.get('play_mode') or MODE_ASK)
        self.play_with_subtitles = False
        self.session_key = kwargs.get('session_key') or ''
        self._session_version = 0
        self._poll_stop = threading.Event()
        self._poll_thread = None
        self._pending_lock = threading.Lock()
        self._pending_payload = None
        self._pending_art = None
        # v5.4.10: onInit re-entrancy flag — True after the first full build.
        self._inited = False
        # Double-dialog guard. Once a stream is chosen and the play-mode
        # picker has been shown, ALL further input is ignored. This kills the
        # symptom where a single OK press fired both onAction(SELECT) AND
        # onClick(2000) — the second event used to re-open the picker after
        # the first had already finalized the selection.
        self._closing = False
        self._mode_dialog_open = False
        self._action_guard = {}
        # v3.9.143: timestamp of the user's last input. The session poll
        # thread auto-applies queued live results only when the user has
        # been idle, so the list fills itself without keypresses while
        # still never mutating controls mid-navigation.
        self._last_input_ts = time.monotonic()
        self._last_focus_id = None
        self._last_busy_touch = 0.0
        # Build long AIOStreams/Plex result sets in TV-friendly chunks. Kodi's
        # Python bridge is far more expensive than normal Python: creating 300
        # ListItems with dozens of properties can freeze remote navigation for
        # seconds even though only ~12 rows are visible. The remaining rows are
        # appended as the cursor approaches the end, without resetting focus.
        self._visible_rows = []
        self._rendered_count = 0
        self._render_chunk = 30
        self._render_limit = self._render_chunk
        self._rendered_row_keys = []
        self._filter_signature = None
        self._chip_signature = None
        self._filters_dirty = False
        self._subtitle_status_checked_at = 0.0
        self._subtitle_status_signature = None

    def _touch_interactive(self):
        now = time.monotonic()
        if (now - self._last_busy_touch) < 2.0:
            return
        self._last_busy_touch = now
        try:
            xbmcgui.Window(10000).setProperty(
                'dexhub.interactive_busy', '%.3f' % time.time())
        except Exception:
            pass

    def onInit(self):
        self._touch_interactive()
        if getattr(self, '_inited', False):
            # v5.4.10: Kodi fires onInit on EVERY window activation —
            # including the return from fullscreen playback. The controls,
            # results, properties and poll thread from the first init are
            # all still alive on this same instance, so redoing the full
            # first-time build here pushes hundreds of ListItems through
            # Kodi's Python bridge ON THE GUI THREAD at the exact moment
            # AML resets the display after playback stops. On CoreELEC
            # that stall freezes the whole box (log: GLES re-init at
            # 15:25:11.9, silence at :13.9). It also spawned a duplicate
            # NuvioHubSourcePoll thread per round-trip. Re-activation only
            # needs the queued live updates drained on this (GUI) thread.
            self._drain_pending_updates()
            self._update_loading_state()
            return
        self._inited = True
        # v4.5.1: classic composition only — the search stopwatch stays for
        # the live summary strip.
        if not hasattr(self, '_search_t0'):
            self._search_t0 = time.time()
        try:
            from . import skin_theme
            skin_theme.publish_theme(self)
        except Exception:
            pass
        # XML chrome is translated through runtime properties because Kodi's
        # custom WindowXML files do not pass arbitrary labels through i18n.py.
        self.setProperty('results_label', tr('نتائج البحث'))
        self.setProperty('play_mode_prefix', tr('وضع التشغيل'))
        self.setProperty('filters_label', tr('الفلاتر'))
        self.setProperty('nav_hint_title', tr('اختصارات الريموت'))
        self.setProperty('nav_hint_updown', tr('أعلى / أسفل: اختيار النسخة'))
        self.setProperty('nav_hint_left', tr('يسار: الفلاتر والترتيب'))
        self.setProperty('nav_hint_right', tr('يمين: فلاتر المصادر'))
        self.setProperty('nav_hint_info', tr('معلومات: تفاصيل المصدر'))
        try:
            self.meta = _source_meta_backfill(self.meta)
        except Exception:
            self.meta = dict(self.meta or {})
        # Unify with TMDb Helper's live context: back-fill any missing art and
        # publish the aggregate ratings row (IMDb/TMDb/Trakt/RT) so NuvioHub shows
        # the same numbers the skin's info screen just showed.
        try:
            from . import tmdbh_context
            self.meta = tmdbh_context.enrich(self, self.meta)
        except Exception:
            pass
        # Push every visual property up-front so the XML can use $INFO
        # bindings (poster/fanart/clearlogo/title/plot). Imperative setImage
        # gets clobbered by static <texture> tags in the skin so we don't
        # rely on it as the primary path.
        _fanart = self.meta.get('fanart') or self.meta.get('background') or ''
        _clearlogo = self.meta.get('clearlogo') or ''
        # v3.9.89: route poster selection through art.clean_poster so the
        # results window uses the same TMDb-first policy as the player
        # overlay. Order: (1) MetaHub/TMDb URL when an IMDb id is known —
        # this is what TMDb Helper, the player overlay, and Cinemeta
        # all use; (2) the addon-provided URL when it's clearly not a
        # logo/icon; (3) the local portrait placeholder. The placeholder
        # is correctly proportioned 2:3 so it never renders as a banner
        # stuck at the top of an empty card.
        try:
            from .art import clean_poster
            _media_type = self.meta.get('media_type') or self.meta.get('type') or 'movie'
            _poster = clean_poster(self.meta, media_type=_media_type)
        except Exception:
            _poster = self.meta.get('poster') or ''
        _title_raw = self.meta.get('title') or self.meta.get('name') or ''
        _fallback_title = self.meta.get('originaltitle') or self.meta.get('english_title') or self.meta.get('name') or _title_raw or ''
        _title = _kodi_safe_meta_text(_title_raw, _fallback_title)
        plot_raw = self.meta.get('plot') or self.meta.get('description') or self.meta.get('overview') or ''
        _plot = _kodi_safe_meta_text(str(plot_raw)[:600], '') if plot_raw else ''
        _year = _kodi_safe_meta_text(self.meta.get('year') or '', '')
        _rating = _kodi_safe_meta_text(self.meta.get('rating') or '', '')
        _genre_raw = self.meta.get('genre') or ''
        _studio_raw = self.meta.get('studio') or ''
        if isinstance(_genre_raw, (list, tuple)):
            _genre_raw = ' / '.join(str(x) for x in _genre_raw[:3] if x)
        if isinstance(_studio_raw, (list, tuple)):
            _studio_raw = ' / '.join(str(x) for x in _studio_raw[:2] if x)
        _genre = _kodi_safe_meta_text(_genre_raw, '')
        _studio = _kodi_safe_meta_text(_studio_raw, '')
        # v3.9.55: namespaced art property names. Always set, even
        # to empty, so we explicitly clear any leftover from a previous
        # session of the results window — this is the fix for the
        # "previous item's poster appears briefly" issue.
        self.setProperty('dexhub.results.fanart', _fanart or '')
        self.setProperty('dexhub.results.clearlogo', _clearlogo or '')
        # v3.9.89: _poster is always either a TMDb URL, a vetted addon
        # URL, or the local portrait placeholder — never empty, never
        # landscape — so no extra fallback is needed here.
        self.setProperty('dexhub.results.poster', _poster or '')
        self.setProperty('title', _title)
        self.setProperty('plot', _clean_header_plot(_plot))
        self.setProperty('year', _year)
        self.setProperty('rating', _rating)
        self.setProperty('genre', _genre)
        self.setProperty('studio', _studio)
        try:
            home = xbmcgui.Window(10000)
            home.setProperty('dexhub.source.fanart', _fanart)
            home.setProperty('dexhub.source.clearlogo', _clearlogo)
            home.setProperty('dexhub.source.poster', _poster or _fanart or '')
            home.setProperty('dexhub.source.thumb', _poster or _fanart or '')
            home.setProperty('dexhub.source.title', _title)
            home.setProperty('dexhub.source.plot', _plot)
            home.setProperty('dexhub.source.year', _year)
            home.setProperty('dexhub.source.rating', _rating)
            home.setProperty('dexhub.source.genre', _genre)
            home.setProperty('dexhub.source.studio', _studio)
            home.setProperty('dexhub.source.key', _source_art_identity_key(self.meta))
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
        self.setProperty('filters_visible', 'false')
        # Belt-and-braces: also push the poster image directly. Harmless
        # if the XML uses $INFO; covers skins that only honor setImage.
        try:
            self.getControl(200).setImage(_poster or _fanart or 'special://home/addons/plugin.video.nuviohub/resources/media/default_video.png')
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
        self._build_filters()
        self._apply_filter('ALL')
        self._update_play_mode_label()
        self._update_subtitle_status(force=True)
        self._update_loading_state()
        self._start_session_poll()
        # Artwork and hero metadata are intentionally TMDb Helper local-only.
        # Do not start a second network lookup after AIOStreams has finished;
        # the picker should become idle as soon as the stream list is ready.
        try:
            self.setFocusId(2000)
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
    def _update_loading_state(self):
        label = tr('جار جلب نتائج إضافية...') if self.getProperty('loading_more') == 'true' else ''
        self.setProperty('loading_label', label)
        # v4.4.0: live search summary for the header strip.
        try:
            rows = self.results if isinstance(self.results, list) else []
            providers = len({str(r.get('provider_name') or r.get('provider') or '?')
                             for r in rows if isinstance(r, dict)})
            elapsed = time.time() - getattr(self, '_search_t0', time.time())
            done = not str(label or '').strip()
            parts = []
            if providers:
                parts.append('%d %s' % (providers, tr('مصادر')))
            total = len(rows)
            if total:
                parts.append('%d %s' % (total, tr('نتيجة')))
            parts.append('%.1f%s' % (elapsed, tr('ث')))
            summary = '  •  '.join(parts)
            # v4.6.1: no check-mark glyph (U+2713) prefix here — it renders
            # as a tofu box in the active skin font on CoreELEC.

            self.setProperty('dexhub.search.summary', summary)
            self.setProperty('dexhub.search.done', '1' if done else '')
        except Exception:
            pass

    def _update_subtitle_status(self, force=False):
        """Publish the shared source-scan subtitle job without blocking UI."""
        now = time.monotonic()
        # Kodi may call both onAction and onFocus for one Up/Down press.  The
        # old implementation crossed the Python/C++ boundary four times per
        # keypress just to rewrite an unchanged countdown.  A 500ms sample is
        # still visually live while keeping navigation free of that work.
        if (not force and
                now - float(self._subtitle_status_checked_at or 0.0) < 0.50):
            return
        self._subtitle_status_checked_at = now
        try:
            from .playback.subtitle_files import subtitle_prefetch_status
            status = subtitle_prefetch_status(
                self.meta.get('media_type') or 'movie',
                self.meta.get('canonical_id') or '',
                self.meta.get('season'), self.meta.get('episode'))
        except Exception:
            status = {'exists': False, 'budget': 15.0}
        budget = int(round(float(status.get('budget') or 15.0)))
        if status.get('running'):
            remaining = max(0, int(__import__('math').ceil(
                float(status.get('remaining') or 0.0))))
            label = tr('الترجمة: جار البحث — متبقٍ %s ث من %s') % (
                remaining, budget)
            ready = ''
        elif status.get('ready') and int(status.get('count') or 0) > 0:
            label = tr('الترجمة: %s جاهزة') % int(status.get('count') or 0)
            ready = '1'
        elif status.get('ready'):
            label = tr('الترجمة: اكتمل البحث دون نتيجة خلال %s ث') % budget
            ready = ''
        else:
            label = tr('الترجمة: عند الطلب')
            ready = ''
        signature = (label, ready)
        if signature == self._subtitle_status_signature:
            return
        self._subtitle_status_signature = signature
        self.setProperty('dexhub.subtitle.status', label)
        self.setProperty('dexhub.subtitle.ready', ready)

    def _apply_session_payload(self, payload):
        if not isinstance(payload, dict):
            return
        rows = payload.get('entries') or []
        if isinstance(rows, list):
            self.results = rows
        done = bool(payload.get('done'))
        self.setProperty('loading_more', 'false' if done else 'true')
        # v3.9.263: live provider tally (Fen Light-style) — "AIOStreams: 12 |
        # Torrentio: 8". Updates as each provider's results stream in, so a
        # silent provider is visible at a glance.
        try:
            from resources.lib.plugin import _provider_stats_line
            stats = _provider_stats_line(self.results)
            self.setProperty('dexhub.results.provider_stats', stats)
            self.setProperty('provider_stats', stats)
        except Exception:
            pass
        self._update_loading_state()
        old_active = self.active_filter or 'ALL'
        self._build_filters()
        active = old_active if old_active in set(self.filters or ['ALL']) else 'ALL'
        self._apply_filter(active)

    def _queue_session_payload(self, payload):
        if not isinstance(payload, dict):
            return
        try:
            with self._pending_lock:
                self._pending_payload = payload
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
    def _queue_art_update(self, art):
        if not isinstance(art, dict):
            return
        try:
            with self._pending_lock:
                self._pending_art = art
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
    def _drain_pending_updates(self):
        payload = None
        art = None
        try:
            with self._pending_lock:
                payload = self._pending_payload
                art = self._pending_art
                self._pending_payload = None
                self._pending_art = None
        except Exception:
            payload = None
            art = None
        if art:
            try:
                # Only overwrite when the async fetch actually produced art —
                # never clobber the carried-over backdrop/logo with empty.
                if art.get('poster'):
                    self.setProperty('dexhub.results.poster', art.get('poster'))
                if art.get('fanart'):
                    self.setProperty('dexhub.results.fanart', art.get('fanart'))
                if art.get('clearlogo'):
                    self.setProperty('dexhub.results.clearlogo', art.get('clearlogo'))
                # v3.9.144: hero TEXT filled from the same TMDb meta_for call.
                if art.get('plot'):
                    _cleaned_plot = _clean_header_plot(art.get('plot'))
                    if _cleaned_plot:
                        self.setProperty('plot', _cleaned_plot)
                if art.get('year'):
                    self.setProperty('year', art.get('year'))
                if art.get('genre'):
                    self.setProperty('genre', art.get('genre'))
                if art.get('rating'):
                    self.setProperty('rating', art.get('rating'))
                if art.get('studio'):
                    self.setProperty('studio', art.get('studio'))
            except Exception as _silent_exc:
                log.silent('RESULTS_WIN', _silent_exc)
        if payload:
            try:
                self._apply_session_payload(payload)
            except Exception as _silent_exc:
                log.silent('RESULTS_WIN', _silent_exc)
    def _has_pending_updates(self):
        try:
            with self._pending_lock:
                return bool(self._pending_payload or self._pending_art)
        except Exception:
            return False

    def _poll_session(self):
        while not self._poll_stop.is_set():
            try:
                # Condition-backed wait: wake on a real provider update rather
                # than opening/checking the session cache every 400ms.
                payload = source_session.wait_for_update(
                    self.session_key, self._session_version,
                    timeout=0.5, default=None) or {}
                version = int(payload.get('version') or 0)
                if payload and version != self._session_version:
                    self._session_version = version
                    # Do not mutate Kodi controls from this worker thread
                    # WHILE the user is navigating. Queue the payload; it is
                    # applied either by onAction/onClick on the dialog thread
                    # or by the idle auto-apply below.
                    self._queue_session_payload(payload)
            except Exception as _silent_exc:
                log.silent('RESULTS_WIN', _silent_exc)
            # Kodi controls are not thread-safe. The worker only queues data;
            # onFocus/onAction/onClick drain it on Kodi's dialog thread.

    def _start_session_poll(self):
        if not self.session_key:
            self.setProperty('loading_more', 'false')
            return
        if self._poll_thread is not None and self._poll_thread.is_alive():
            # v5.4.10: guard against duplicate pollers. Before the onInit
            # re-entry fix, every fullscreen round-trip leaked one thread.
            return
        try:
            payload = source_session.get(self.session_key) or {}
        except Exception:
            payload = {}
        if payload:
            self._session_version = int(payload.get('version') or 0)
            self._apply_session_payload(payload)
        else:
            self.setProperty('loading_more', 'true')
            self._update_loading_state()
        try:
            self._poll_thread = threading.Thread(target=self._poll_session, name='NuvioHubSourcePoll', daemon=True)
            self._poll_thread.start()
        except RuntimeError as exc:
            # Thread quota exhausted. Do not crash the picker; show the initial
            # results and mark the live background refresh as finished.
            self._poll_thread = None
            self.setProperty('loading_more', 'false')
            self._update_loading_state()
            try:
                xbmc.log('[NuvioHub] source picker live poll disabled: %s' % exc, xbmc.LOGWARNING)
            except Exception:
                pass

    def _build_filters(self):
        values = ['ALL']
        seen = {'ALL'}
        # Quality filters first so users can quickly narrow by 4K/1080P/HDR/DV.
        for filter_value, _label, _tokens in QUALITY_FILTERS:
            try:
                if any(_row_matches_quality(row, filter_value) for row in self.results if isinstance(row, dict)):
                    seen.add(filter_value)
                    values.append(filter_value)
            except Exception as _silent_exc:
                log.silent('RESULTS_WIN', _silent_exc)
        # v4.1.0: source-type group (USENET / DEBRID / TORRENT / DIRECT / …)
        for row in self.results:
            value = _row_type_filter(row)
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        # v4.6.1: top-level addon group (Dexstreams / Arabmedia / …). These
        # back the chips strip (list 2300); they must live in self.filters or
        # _apply_session_payload resets an active V: filter to ALL on every
        # live-session refresh.
        for row in self.results:
            value = _row_group_filter(row)
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        for row in self.results:
            value = _row_provider_filter(row)
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        self.filters = values
        try:
            control = self.getControl(2100)
        except Exception:
            control = None
        previous_value = ''
        previous_pos = 0
        if control is not None:
            try:
                previous_pos = int(control.getSelectedPosition())
                previous_item = control.getSelectedItem()
                previous_value = (previous_item.getProperty('filter_value')
                                  if previous_item else '')
            except Exception:
                pass
        items = []
        item_specs = []
        # --- dexhub-407-patch --- sort entries head the drawer
        for sort_key, _sort_label in SORT_MODES:
            marker = '> ' if sort_key == self.active_sort else '   '
            label = '%s%s' % (marker, _sort_mode_label(sort_key))
            item_specs.append((sort_key, label))
        for name in values:
            item_specs.append((name, _filter_label(name)))
        signature = tuple(item_specs)
        # Live providers frequently publish a new payload with the same filter
        # vocabulary. Do not reset the Kodi control (and its cursor) then.
        if signature == getattr(self, '_filter_signature', None):
            return
        self._filter_signature = signature
        restore_idx = -1
        for idx, (filter_value, label) in enumerate(item_specs):
            li = xbmcgui.ListItem(label=label)
            li.setProperty('label', label)
            li.setProperty('filter_value', filter_value)
            items.append(li)
            if previous_value and filter_value == previous_value:
                restore_idx = idx
        try:
            control = control or self.getControl(2100)
            control.reset()
            control.addItems(items)
            if items:
                if restore_idx < 0:
                    restore_idx = min(max(previous_pos, 0), len(items) - 1)
                control.selectItem(restore_idx)
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
    def _results_for_filter(self, filter_value):
        # --- dexhub-407-patch --- filter first, then apply the active sort
        return _sorted_rows(self._filtered_rows(filter_value), getattr(self, 'active_sort', 'S:DEFAULT'))

    def _filtered_rows(self, filter_value):
        if not filter_value or filter_value == 'ALL':
            return list(self.results)
        if str(filter_value).startswith('Q:'):
            return [row for row in self.results if _row_matches_quality(row, filter_value)]
        if str(filter_value).startswith('T:'):
            wanted = str(filter_value)
            return [row for row in self.results if _row_type_filter(row) == wanted]
        if str(filter_value).startswith('V:'):
            wanted = str(filter_value)
            return [row for row in self.results if _row_group_filter(row) == wanted]
        if str(filter_value).startswith('P:'):
            wanted = str(filter_value)[2:]
            return [row for row in self.results if _row_provider_filter(row) == ('P:%s' % wanted)]
        return [row for row in self.results if _row_provider_filter(row) == ('P:%s' % str(filter_value).strip().upper())]

    _CHIP_LIST_ID = 2300

    def _build_provider_chips(self):
        """v4.6.1: interactive provider chips (list 2300) above the results.

        One chip per TOP-LEVEL addon (Dexstreams, Arabmedia, …) — not the
        inner scrapers, which produced six near-identical "EASYNEWS SEARCH"
        chips — plus a leading "All". Selecting a chip applies/clears the V:
        filter (see onClick). Colours are the same stable identity slots as
        the loading dashboard and the row bars. Counts always come from the
        FULL result set so the strip stays a map of what the search found.
        """
        try:
            rows = self.results if isinstance(self.results, list) else []
            counts = {}
            order = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = _row_group_name(row)
                if not name:
                    continue
                if name not in counts:
                    counts[name] = 0
                    order.append(name)
                counts[name] += 1
            ranked = sorted(order, key=lambda n: (-counts[n], order.index(n)))
            active = str(self.active_filter or 'ALL')
            entries = [(tr('الكل'), len(rows), '', 0,
                        not active.startswith('V:'))]
            for name in ranked:
                entries.append((name, counts[name], name,
                                _provider_color_index(name),
                                active == ('V:%s' % name.upper())))
            try:
                control = self.getControl(self._CHIP_LIST_ID)
            except Exception:
                return
            previous_value = ''
            try:
                prev = int(control.getSelectedPosition())
                previous_item = control.getSelectedItem()
                previous_value = (previous_item.getProperty('vfilter')
                                  if previous_item else '')
            except Exception:
                prev = 0
            signature = tuple(
                (label, int(count), vfilter, int(coloridx), bool(is_active))
                for label, count, vfilter, coloridx, is_active in entries)
            if signature == getattr(self, '_chip_signature', None):
                return
            self._chip_signature = signature
            items = []
            restore_idx = -1
            for idx, (label, count, vfilter, coloridx, is_active) in enumerate(entries):
                li = xbmcgui.ListItem(label=label)
                li.setProperty('label', '%s  %d' % (_kodi_safe_text(label), count))
                li.setProperty('vfilter', vfilter)          # raw name; '' = All
                li.setProperty('coloridx', str(coloridx) if coloridx else '')
                li.setProperty('active', '1' if is_active else '')
                items.append(li)
                if vfilter == previous_value:
                    restore_idx = idx
            control.reset()
            control.addItems(items)
            if items:
                if restore_idx < 0:
                    restore_idx = min(max(prev, 0), len(items) - 1)
                control.selectItem(restore_idx)
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)

    def _apply_chip_filter(self):
        """OK on a chip: All clears the group filter, a provider applies it,
        and re-selecting the active provider toggles back to All."""
        try:
            item = self.getControl(self._CHIP_LIST_ID).getSelectedItem()
        except Exception:
            item = None
        if not item:
            return
        name = str(item.getProperty('vfilter') or '').strip()
        target = ('V:%s' % name.upper()) if name else 'ALL'
        if target != 'ALL' and target == str(self.active_filter or ''):
            target = 'ALL'
        self._apply_filter(target)
        try:
            self.setFocusId(self._CHIP_LIST_ID)
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)

    def _make_result_item(self, row):
        """Build one rich source ListItem for reset and append paths."""
        row = row if isinstance(row, dict) else {}
        li = xbmcgui.ListItem(
            label=_kodi_safe_text(row.get('name') or ''),
            label2=_kodi_safe_text(row.get('label2') or ''),
        )
        for key in (
                'highlight', 'quality', 'provider', 'provider_name_raw',
                'provider_icon', 'provider_domain', 'provider_url',
                'addon', 'addon_domain', 'addon_url', 'source_site', 'indexer',
                'service_name', 'origin_line', 'extraInfo', 'extraInfo2',
                'size_label', 'count', 'name', 'stream_key', 'badges',
                'formatter_summary', 'source_type', 'source_type_label', 'source_type_color'):
            value = str(row.get(key) or '')
            li.setProperty(
                key,
                value if key in (
                    'stream_key', 'provider_icon', 'provider_url', 'addon_url'
                ) else _bidi_anchor(_kodi_safe_text(value)),
            )
        li.setProperty('name_fit', _fit_label(
            _bidi_anchor(_kodi_safe_text(row.get('name') or ''))))
        li.setProperty('quality_key', str(row.get('quality') or '--'))
        li.setProperty('type_key', str(row.get('source_type') or ''))
        li.setProperty('result_identity', _result_identity(row))
        li.setProperty('pcolor', str(_provider_color_index(
            row.get('addon') or row.get('source_site') or
            row.get('provider_name_raw') or row.get('provider') or '')))
        li.setProperty('video_bits', ' | '.join(row.get('video_bits') or []))
        li.setProperty('audio_bits', ' | '.join(row.get('audio_bits') or []))

        tags = list(row.get('formatter_tags') or [])
        if len(tags) < 2:
            all_bits_up = [str(bit).upper() for bit in (
                list(row.get('video_bits') or []) +
                list(row.get('audio_bits') or []))]
            seen = {
                str(tag.get('text') or '').upper()
                for tag in tags if isinstance(tag, dict)
            }
            for key, bg, fg in _NATIVE_TAGS:
                if key in all_bits_up and key not in seen:
                    tags.append({'text': key, 'bg': bg, 'fg': fg})
                    seen.add(key)
                if len(tags) >= 6:
                    break
        for tag_idx in range(6):
            tag = (tags[tag_idx] if tag_idx < len(tags) and
                   isinstance(tags[tag_idx], dict) else {})
            n = tag_idx + 1
            li.setProperty('fmt%d_text' % n,
                           _kodi_safe_text(tag.get('text') or ''))
            li.setProperty('fmt%d_bg' % n,
                           str(tag.get('bg') or 'FF2B2F3E'))
            li.setProperty('fmt%d_fg' % n,
                           str(tag.get('fg') or 'FFF2F4FB'))
            _cls = _tag_class(tag.get('text')) if tag.get('text') else ''
            li.setProperty('fmt%d_cls' % n, _cls)
            # v5.4.6: the colour now travels INSIDE the label text.
            # The skin used to carry ten pre-coloured variants per slot,
            # switched by String.IsEqual on fmt{n}_cls — 60 conditions per
            # row that Kodi re-evaluates every frame, which is most of what
            # made a long result list feel heavy on ARM. One label now.
            _txt = _kodi_safe_text(tag.get('text') or '')
            li.setProperty('fmt%d_label' % n,
                           ('[B][COLOR %s]%s[/COLOR][/B]'
                            % (_TAG_CLASS_COLORS.get(_cls, 'FFDDE3EC'), _txt))
                           if _txt else '')
        # v5.4.2: back to ten slots. 5.4.0 cut the strip to six for ARM
        # render cost, but a single rich WEB-DL already matches resolution,
        # source, HDR, audio, channels, codec and the streaming service —
        # six meant everything after that was dropped silently.
        elite_images = _elite_badge_images(row, tags=tags, max_items=10)
        for badge_idx in range(10):
            li.setProperty(
                'elite_badge%d' % (badge_idx + 1),
                elite_images[badge_idx]
                if badge_idx < len(elite_images) else '',
            )
        li.setProperty('source_info',
                       _kodi_safe_text(row.get('source_info') or ''))
        return li

    def _apply_filter(self, filter_value):
        # --- dexhub-407-patch --- a sort pick changes the order, never the filter
        requested_filter = str(filter_value or 'ALL')
        filter_changed = (not requested_filter.startswith('S:') and
                          requested_filter != str(self.active_filter or 'ALL'))
        if filter_changed:
            self._render_limit = self._render_chunk
        if str(filter_value or '').startswith('S:'):
            self.active_sort = filter_value
            try:
                ADDON.setSetting('source_sort_mode', filter_value)
            except Exception as _silent_exc:
                log.silent('RESULTS_WIN', _silent_exc)
            try:
                self._build_filters()
            except Exception as _silent_exc:
                log.silent('RESULTS_WIN', _silent_exc)
            filter_value = self.active_filter or 'ALL'
        self.active_filter = filter_value or 'ALL'
        visible_all = self._results_for_filter(self.active_filter)
        self._visible_rows = visible_all
        loading = self.getProperty('loading_more') == 'true'
        total_label = str(len(visible_all))
        if loading:
            total_label = '%s +' % total_label
        self.setProperty('total_results', total_label)
        # --- dexhub-407-patch --- show filter and sort side by side
        _info_bits = []
        if self.active_filter != 'ALL':
            _info_bits.append(_filter_label(self.active_filter))
        if getattr(self, 'active_sort', 'S:DEFAULT') != 'S:DEFAULT':
            _info_bits.append(_sort_mode_label(self.active_sort))
        self.setProperty('filter_info', (u'| %s' % u'  \u00b7  '.join(_info_bits)) if _info_bits else '')
        self._build_provider_chips()
        previous_key = ''
        previous_pos = 0
        try:
            control = self.getControl(2000)
            previous_pos = int(control.getSelectedPosition())
            current_item = control.getSelectedItem()
            previous_key = (current_item.getProperty('result_identity')
                            if current_item else '')
        except Exception:
            control = None
        # Only materialize the first chunk through Kodi's Python/C++ bridge.
        # Preserve enough rows to keep the old cursor valid after a live
        # update, then append another chunk as the user nears the end.
        render_limit = min(
            len(visible_all),
            max(int(self._render_limit or self._render_chunk),
                int(previous_pos or 0) + 1),
        )
        visible = visible_all[:render_limit]
        visible_keys = [_result_identity(row) for row in visible]
        rendered_keys = list(getattr(self, '_rendered_row_keys', []) or [])
        # Default live scans append providers/results in a stable order. When
        # the already-rendered prefix is unchanged, cross the Python/C++ bridge
        # only for genuinely new rows instead of resetting the whole list.
        append_only = bool(
            control is not None and rendered_keys and
            len(visible_keys) >= len(rendered_keys) and
            visible_keys[:len(rendered_keys)] == rendered_keys)
        if append_only:
            try:
                start = len(rendered_keys)
                if start < len(visible):
                    control.addItems([
                        self._make_result_item(row)
                        for row in visible[start:]
                    ])
                self._rendered_count = len(visible)
                self._rendered_row_keys = visible_keys
                return
            except Exception as _silent_exc:
                log.silent('RESULTS_WIN', _silent_exc)
        items = []
        restore_idx = -1
        for idx, row in enumerate(visible):
            li = self._make_result_item(row)
            items.append(li)
            if previous_key and _result_identity(row) == previous_key:
                restore_idx = idx
        try:
            control = control or self.getControl(2000)
            control.reset()
            control.addItems(items)
            self._rendered_count = len(items)
            self._rendered_row_keys = visible_keys
            if items:
                if restore_idx < 0:
                    restore_idx = min(max(previous_pos, 0), len(items) - 1)
                control.selectItem(restore_idx)
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)

    def _maybe_extend_results(self):
        """Expose the next result chunk without ever losing the chosen row."""
        total = len(self._visible_rows or [])
        start = int(self._rendered_count or 0)
        if total <= start:
            return False
        try:
            control = self.getControl(2000)
            pos = int(control.getSelectedPosition())
        except Exception:
            return False
        if pos < max(0, start - 12):
            return False
        end = min(total, start + int(self._render_chunk))
        try:
            # Kodi's list control supports appending a batch.  v5.2 rebuilt
            # every already-visible rich row whenever the cursor approached
            # the bottom, creating a noticeable hitch and sometimes moving
            # focus on slower boxes.  Build only the new range and leave the
            # selected item untouched.
            control.addItems([
                self._make_result_item(row)
                for row in self._visible_rows[start:end]
            ])
            self._rendered_count = end
            self._render_limit = end
            row_keys = list(getattr(self, '_rendered_row_keys', []) or [])
            row_keys.extend(
                _result_identity(row)
                for row in self._visible_rows[start:end])
            self._rendered_row_keys = row_keys
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
            return False
        return True
    def _guard_action(self, name, interval=0.25):
        # A quarter second still suppresses Kodi's onAction/onClick duplicate
        # for one OK press, without making quick remote input feel ignored.
        now = time.monotonic()
        prev = float(self._action_guard.get(name) or 0.0)
        if (now - prev) < interval:
            return True
        self._action_guard[name] = now
        return False

    def _play_mode_label(self):
        if self.play_mode == MODE_PLAY_SUBS:
            return tr('تشغيل مع ترجمة')
        return tr('تشغيل')

    def _update_play_mode_label(self):
        self.setProperty('play_mode_label', self._play_mode_label())

    def _pick_play_mode(self):
        if self._closing or self._mode_dialog_open:
            return
        self._mode_dialog_open = True
        try:
            options = [
                (tr('تشغيل فقط'), MODE_PLAY),
                (tr('تشغيل مع ترجمة'), MODE_PLAY_SUBS),
            ]
            idx = xbmcgui.Dialog().select(tr('وضع التشغيل'), [label for label, _ in options])
            if idx >= 0:
                self.play_mode = options[idx][1]
                self._update_play_mode_label()
        finally:
            self._mode_dialog_open = False
            # v3.9.33: re-stamp the 'mode' action guard with NOW so any
            # pending Kodi event for the original OK press (which fired
            # both onAction AND onClick for the same physical button
            # press) is suppressed for the next 0.6s. Without this, if
            # the user spent >0.6s deciding inside the picker, the
            # tail-end onClick(2200) would slip past the guard and
            # reopen the picker immediately. Fixes the "Playmode opens
            # twice" report.
            self._action_guard['mode'] = time.monotonic()
        try:
            self.setFocusId(2000)
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
    def _resolve_choice_mode(self):
        return self.play_mode

    def _choose(self):
        # Hard guards against the OK-press double-event:
        #   1. window is already closing → drop
        #   2. play-mode dialog is currently up → drop (the in-flight call owns it)
        #   3. selection was already finalized → drop
        if self._closing or self._mode_dialog_open or self.selected:
            return
        try:
            item = self.getControl(2000).getSelectedItem()
        except Exception:
            item = None
        stream_key = item.getProperty('stream_key') if item else None
        if not stream_key:
            return
        chosen_mode = self._resolve_choice_mode()
        if not chosen_mode:
            return
        # Re-check after the modal returns — if something else finalized a
        # selection in the meantime, do not double-fire.
        if self._closing or self.selected:
            return
        self.selected = stream_key
        self.play_with_subtitles = (chosen_mode == MODE_PLAY_SUBS)
        self._closing = True
        self._shutdown()
        self.close()

    def _show_info(self):
        try:
            focus_id = self.getFocusId()
        except Exception:
            focus_id = 2000
        if focus_id == 2100:
            text = tr('Filter: %s') % _filter_label(self.active_filter)
            xbmcgui.Dialog().textviewer('Nuvio Hub', tr(text))
            return
        try:
            item = self.getControl(2000).getSelectedItem()
        except Exception:
            item = None
        if not item:
            return
        text = item.getProperty('source_info') or item.getProperty('name') or ''
        xbmcgui.Dialog().textviewer('Nuvio Hub', tr(text))

    def _selected_filter_value(self):
        try:
            item = self.getControl(2100).getSelectedItem()
        except Exception:
            item = None
        return item.getProperty('filter_value') if item else 'ALL'

    def _filters_open(self):
        try:
            return self.getProperty('filters_visible') == 'true'
        except Exception:
            return False

    def _open_filters(self):
        if len(self.filters or []) <= 1:
            return False
        self.setProperty('filters_visible', 'true')
        try:
            self.setFocusId(2100)
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
        return True

    def _close_filters(self):
        self.setProperty('filters_visible', 'false')
        try:
            self.setFocusId(2000)
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)

    def _apply_selected_filter(self, filter_value=None):
        # Capture before draining a live provider update. The old order reset
        # list 2100 to its first row, so OK visibly selected one filter but
        # silently applied another.
        filter_value = filter_value or self._selected_filter_value()
        self._apply_filter(filter_value)
        self._close_filters()
        self._drain_pending_updates()

    def onFocus(self, controlId):
        self._last_input_ts = time.monotonic()
        previous_focus = self._last_focus_id
        self._last_focus_id = controlId
        self._update_subtitle_status()
        # Some Kodi builds fire onFocus for every movement inside a list.
        # Rebuilding the source, filter or provider list there makes its
        # cursor hitch or jump. Apply queued rows only when focus actually
        # crosses between controls (or enters a non-list control).
        same_interactive_list = (
            controlId == previous_focus and controlId in (2000, 2100, 2300))
        if not same_interactive_list:
            self._drain_pending_updates()

    def onClick(self, controlId):
        self._last_input_ts = time.monotonic()
        self._touch_interactive()
        self._update_subtitle_status()
        if self._closing or self._mode_dialog_open:
            return
        if controlId == 2000:
            # Keep the row under the cursor stable. A queued live refresh is
            # intentionally not applied until after this selection.
            if not self._guard_action('choose'):
                self._choose()
        elif controlId == 2100:
            filter_value = self._selected_filter_value()
            if not self._guard_action('filter'):
                self._apply_selected_filter(filter_value)
        elif controlId == 2200:
            if not self._guard_action('mode'):
                self._pick_play_mode()
        elif controlId == 2300:
            # v4.6.1: provider chip — apply / toggle the top-level V: filter.
            if not self._guard_action('chip'):
                self._apply_chip_filter()
                self._drain_pending_updates()

    def onAction(self, action):
        self._last_input_ts = time.monotonic()
        self._touch_interactive()
        if self._closing or self._mode_dialog_open:
            # While the play-mode picker is up (or after a successful pick),
            # ignore every action to prevent stacked dialogs.
            return
        action_id = action.getId()
        self._update_subtitle_status()
        # Never rebuild the list on navigation/select/back. Kodi is in the
        # middle of changing focus during these callbacks; resetting control
        # 2000 here was the main cause of remote-control lag and cursor jumps.
        if action_id not in (ACTION_MOVE | ACTION_LEFT | ACTION_RIGHT |
                             ACTION_SELECT | ACTION_BACK):
            self._drain_pending_updates()
        try:
            focus_id = self.getFocusId()
        except Exception:
            focus_id = 2000
        drawer_open = self._filters_open()
        if focus_id == 2000 and action_id in (4, 6):
            self._maybe_extend_results()
        if action_id in ACTION_BACK:
            if drawer_open:
                self._close_filters()
                return
            self.selected = None
            self._closing = True
            self._shutdown()
            self.close()
            return
        if action_id in ACTION_INFO or action_id in ACTION_CONTEXT:
            self._show_info()
            return
        if drawer_open and action_id in ACTION_RIGHT:
            # RIGHT closes without changing the selected filter; OK applies.
            self._close_filters()
            return
        if drawer_open and focus_id == 2100 and action_id in ACTION_SELECT:
            filter_value = self._selected_filter_value()
            if not self._guard_action('filter'):
                self._apply_selected_filter(filter_value)
            return
        if focus_id == 2200 and action_id in ACTION_SELECT:
            if not self._guard_action('mode'):
                self._pick_play_mode()
            return
        if focus_id == 2000 and action_id in ACTION_SELECT:
            if not self._guard_action('choose'):
                self._choose()
            return
        if focus_id == 2300 and action_id in ACTION_SELECT:
            if not self._guard_action('chip'):
                self._apply_chip_filter()
                self._drain_pending_updates()
            return
        if focus_id == 2000 and action_id in ACTION_RIGHT:
            # RIGHT reaches the provider/addon strip; LEFT opens the full
            # quality/type/sort drawer. Play mode remains one UP from chips.
            try:
                self.setFocusId(2300)
            except Exception as _silent_exc:
                log.silent('RESULTS_WIN', _silent_exc)
            return
        if (not drawer_open and action_id in ACTION_LEFT and
                focus_id in (2000, 2100)):
            # Some Kodi 22 builds move focus to the XML onleft target before
            # Python receives the action; accepting both ids makes it robust.
            self._open_filters()
            return

    def _shutdown(self):
        try:
            self._poll_stop.set()
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
        try:
            if self._poll_thread and self._poll_thread.is_alive():
                self._poll_thread.join(0.2)
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
        # v3.9.34: clear stale art properties from the home window so the
        # next SourcesWindow opening for a DIFFERENT item doesn't briefly
        # show the previous item's poster/clearlogo/fanart before the
        # new onInit() can populate them. The bug: home window keeps
        # `dexhub.source.poster` etc set between window opens, and the
        # skin reads them as $INFO bindings; if the user picked item A,
        # closed the picker, then opened item B, the half-second between
        # the new picker's open and its onInit setting fresh values
        # showed A's art.
        try:
            home = xbmcgui.Window(10000)
            for key in (
                'dexhub.source.fanart', 'dexhub.source.clearlogo',
                'dexhub.source.poster', 'dexhub.source.thumb',
                'dexhub.source.title',  'dexhub.source.plot',
                'dexhub.source.year',   'dexhub.source.rating',
                'dexhub.source.genre',  'dexhub.source.studio',
            ):
                try:
                    home.clearProperty(key)
                except Exception as _silent_exc:
                    log.silent('RESULTS_WIN', _silent_exc)
        except Exception as _silent_exc:
            log.silent('RESULTS_WIN', _silent_exc)
    def run(self):
        self.doModal()
        self._shutdown()
        return {
            'stream_key': self.selected,
            'play_with_subtitles': self.play_with_subtitles,
            'play_mode': self.play_mode,
        }


def open_sources_window(results, meta, play_mode=MODE_ASK, session_key=''):
    skin_xml = 'sources_results.xml'
    win = SourcesWindow(skin_xml, ADDON_PATH, 'Default', '1080i', results=results, meta=meta, play_mode=play_mode, session_key=session_key)
    try:
        return win.run()
    finally:
        del win
