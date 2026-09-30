# -*- coding: utf-8 -*-
"""
NuvioHub skin-aware theming engine.

Reads the *active* Kodi skin's accent colour and derives a full, mathematically
consistent palette from it, then publishes the palette as Home-window
properties that NuvioHub's WindowXML dialogs bind to. The result: NuvioHub adopts
the host skin's identity instead of looking like a foreign add-on.

Supported skins get their real accent read directly; any unknown skin falls
back to the DexWorld brand palette so nothing ever looks broken.

Published properties (Window 10000):
    dexhub.theme.accent        AARRGGBB  primary accent
    dexhub.theme.accent_soft   AARRGGBB  ~70% accent (sub-accents, icons)
    dexhub.theme.accent_dim    AARRGGBB  ~28% accent (fills, hovers)
    dexhub.theme.accent_glow   AARRGGBB  lightened accent (highlights/sheen)
    dexhub.theme.secondary     AARRGGBB  complementary/secondary accent
    dexhub.theme.surface       AARRGGBB  deep surface background
    dexhub.theme.surface_card  AARRGGBB  raised card surface
    dexhub.theme.text          AARRGGBB  primary text
    dexhub.theme.muted         AARRGGBB  muted/secondary text
    dexhub.theme.ok            AARRGGBB  success/cached green (kept stable)
    dexhub.theme.skin          string    active skin id
    dexhub.theme.ready         '1' once published
"""

import xbmc
import xbmcgui


HOME = xbmcgui.Window(10000)

# DexWorld brand palette — the fallback identity when the skin is unknown
# or exposes no usable accent.
BRAND_ACCENT = 'FF8B5CF6'     # refined violet
BRAND_SECONDARY = 'FF22D3EE'  # crisp cyan
BRAND_SURFACE = 'FF080D18'
BRAND_SURFACE_CARD = 'FF111827'
BRAND_TEXT = 'FFF8FAFC'
BRAND_MUTED = 'FF94A3B8'
BRAND_OK = 'FF34D399'


# --------------------------------------------------------------------------- #
#  Colour maths (pure stdlib — operates on AARRGGBB / RRGGBB hex strings)      #
# --------------------------------------------------------------------------- #

def _parse_hex(value):
    """Return (a, r, g, b) ints from an AARRGGBB or RRGGBB hex string, or None."""
    if not value:
        return None
    v = value.strip().lstrip('#')
    # Kodi colours are AARRGGBB; some skins store RRGGBB.
    if len(v) == 6:
        v = 'FF' + v
    if len(v) != 8:
        return None
    try:
        a = int(v[0:2], 16)
        r = int(v[2:4], 16)
        g = int(v[4:6], 16)
        b = int(v[6:8], 16)
        return (a, r, g, b)
    except ValueError:
        return None


def _to_hex(a, r, g, b):
    clamp = lambda x: max(0, min(255, int(round(x))))
    return '%02X%02X%02X%02X' % (clamp(a), clamp(r), clamp(g), clamp(b))


def _with_alpha(argb, alpha):
    a, r, g, b = argb
    return _to_hex(alpha, r, g, b)


def _scale(argb, factor):
    """Lighten (factor>1) or darken (factor<1) the RGB channels."""
    a, r, g, b = argb
    return _to_hex(a, r * factor, g * factor, b * factor)


def _mix(argb, tint, ratio):
    """Mix argb toward a tint (r,g,b) by ratio 0..1, keeping argb's alpha."""
    a, r, g, b = argb
    tr, tg, tb = tint
    nr = r + (tr - r) * ratio
    ng = g + (tg - g) * ratio
    nb = b + (tb - b) * ratio
    return _to_hex(a, nr, ng, nb)


def _luminance(argb):
    _, r, g, b = argb
    # Rec. 601 luma
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def _complement(argb):
    """A pleasing secondary: rotate toward a cooler/warmer partner.

    We don't do full HSL rotation (overkill); instead we swap emphasis between
    channels to get a harmonious, distinct secondary that still feels related.
    """
    a, r, g, b = argb
    # Emphasise the two lower channels, damp the dominant one a touch.
    mx = max(r, g, b)
    nr = b if r == mx else r
    ng = r if g == mx else g
    nb = g if b == mx else b
    return _to_hex(a, (nr + b) / 2, (ng + r) / 2, (nb + g) / 2)


# --------------------------------------------------------------------------- #
#  Skin accent detection                                                      #
# --------------------------------------------------------------------------- #

# Per-skin recipe: which Skin.String / Skin.Color holds the accent, and an
# optional explicit fallback accent for that skin family.
_SKIN_ACCENT_SOURCES = {
    'skin.arctic.fuse.3': ['Skin.String(focuscolor.name)'],
    'skin.arctic.fuse.2': ['Skin.String(focuscolor.name)'],
    'skin.arctic.horizon.2': ['Skin.String(focuscolor.name)'],
    'skin.arctic.zephyr.2.resurrection.mod': ['Skin.String(focuscolor.name)'],
    'skin.arctic.zephyr.reloaded': ['Skin.String(focuscolor.name)'],
    'skin.estuary': ['Skin.String(focuscolor.name)'],
}

# Generic skin-string names worth probing on any unknown skin.
_GENERIC_ACCENT_PROBES = [
    'Skin.String(focuscolor.name)',
    'Skin.String(highlightcolor)',
    'Skin.String(accentcolor)',
    'Skin.String(AccentColor)',
    'Skin.String(focuscolor)',
]


def _looks_like_hex(value):
    return _parse_hex(value) is not None


def _read_active_accent(skin_id):
    """Try the skin-specific source first, then generic probes."""
    probes = list(_SKIN_ACCENT_SOURCES.get(skin_id, []))
    for p in _GENERIC_ACCENT_PROBES:
        if p not in probes:
            probes.append(p)

    for probe in probes:
        try:
            val = xbmc.getInfoLabel(probe) or ''
        except Exception:  # pylint: disable=broad-except
            val = ''
        if _looks_like_hex(val):
            argb = _parse_hex(val)
            # Reject near-black / near-white "accents" (skins sometimes store
            # text colours here) — they make a terrible accent.
            lum = _luminance(argb)
            if 0.06 < lum < 0.95:
                return val
    return None


# --------------------------------------------------------------------------- #
#  Palette construction                                                        #
# --------------------------------------------------------------------------- #

def build_palette(accent_hex):
    """Derive a full palette from a single accent hex (AARRGGBB or RRGGBB)."""
    argb = _parse_hex(accent_hex) or _parse_hex(BRAND_ACCENT)
    # Force full opacity on the accent itself.
    a, r, g, b = argb
    accent = _to_hex(255, r, g, b)
    accent_argb = (255, r, g, b)

    lum = _luminance(accent_argb)
    # If the accent is quite dark, lighten the glow more aggressively so the
    # "lit from above" sheen still reads.
    glow_factor = 1.55 if lum < 0.35 else 1.28

    palette = {
        'accent': accent,
        'accent_soft': _with_alpha(accent_argb, 0xB3),   # 70%
        'accent_dim':  _with_alpha(accent_argb, 0x47),   # 28%
        'accent_glow': _scale(accent_argb, glow_factor),
        'secondary':   _complement(accent_argb),
        # Neutral surfaces: very dark, faintly tinted by the accent so the UI
        # feels cohesive rather than a pure-grey slab.
        'surface':      _mix(_parse_hex(BRAND_SURFACE), (r, g, b), 0.06),
        'surface_card': _mix(_parse_hex(BRAND_SURFACE_CARD), (r, g, b), 0.10),
        'text':  BRAND_TEXT,
        'muted': BRAND_MUTED,
        'ok':    BRAND_OK,  # cached/success stays a stable green for meaning
    }
    return palette


# --------------------------------------------------------------------------- #
#  Public API                                                                  #
# --------------------------------------------------------------------------- #

def current_skin():
    try:
        return xbmc.getSkinDir() or ''
    except Exception:  # pylint: disable=broad-except
        return ''


# --------------------------------------------------------------------------- #
#  v4.4.0: fixed theme presets (the six approved design mockups)              #
# --------------------------------------------------------------------------- #

THEME_PRESETS = {
    '1': dict(name='Nuvio Crimson',    accent='FFE0314A', secondary='FF9BE29B',
              surface='FF0D0D12', surface_card='FF1B1B24', text='FFF2F2F7', muted='FF8E94A6'),
    '2': dict(name='Midnight Ocean', accent='FF22D3EE', secondary='FF7DD3FC',
              surface='FF070B14', surface_card='FF121B2E', text='FFEAF4FF', muted='FF7C8AA6'),
    '3': dict(name='Royal Violet',   accent='FF8B5CF6', secondary='FFC4B5FD',
              surface='FF0E0A16', surface_card='FF1D1430', text='FFF1EDFB', muted='FF8B84A6'),
    '4': dict(name='Emerald Noir',   accent='FF10B981', secondary='FF6EE7B7',
              surface='FF08110D', surface_card='FF12211A', text='FFECFDF5', muted='FF7FA695'),
    '5': dict(name='Amber Cinema',   accent='FFF59E0B', secondary='FFFCD34D',
              surface='FF120F0A', surface_card='FF241C12', text='FFFDF6EC', muted='FFA6987C'),
    '6': dict(name='Slate Mono',     accent='FFE5E7EB', secondary='FFA1A1AA',
              surface='FF0C0D0F', surface_card='FF1A1C21', text='FFF5F5F6', muted='FF71717A'),
}


def _preset_setting():
    """Read the theme_preset enum ('0' auto / '1'..'6' fixed presets)."""
    try:
        import xbmcaddon
        return (xbmcaddon.Addon('plugin.video.nuviohub').getSetting('theme_preset') or '0').strip()
    except Exception:  # pylint: disable=broad-except
        return '0'


def _preset_palette(key):
    preset = THEME_PRESETS.get(key)
    if not preset:
        return None
    palette = build_palette(preset['accent'])
    for token in ('secondary', 'surface', 'surface_card', 'text', 'muted'):
        palette[token] = preset[token]
    return palette


def resolve_palette():
    """Return (palette_dict, skin_id, accent_source_str)."""
    preset_key = _preset_setting()
    if preset_key and preset_key != '0':
        palette = _preset_palette(preset_key)
        if palette:
            return palette, current_skin(), 'preset:%s' % preset_key
    skin_id = current_skin()
    accent = _read_active_accent(skin_id)
    source = accent if accent else 'brand-fallback'
    if not accent:
        accent = BRAND_ACCENT
    return build_palette(accent), skin_id, source


def publish_theme(window=None, log=None):
    """Compute and publish the theme to the Home window (and optionally a
    specific window). Safe to call repeatedly (e.g. on every dialog onInit).
    """
    palette, skin_id, source = resolve_palette()

    targets = [HOME]
    if window is not None and window is not HOME:
        targets.append(window)

    for win in targets:
        try:
            for key, val in palette.items():
                win.setProperty('dexhub.theme.%s' % key, val)
            # v4.4.0: glass-card token — surface_card with translucent alpha
            # so result rows let the fanart backdrop breathe through.
            try:
                win.setProperty('dexhub.theme.card_glass', 'B8' + palette['surface_card'][2:])
            except Exception:
                pass
            win.setProperty('dexhub.theme.skin', skin_id)
            win.setProperty('dexhub.theme.ready', '1')
        except Exception:  # pylint: disable=broad-except
            pass

    if log:
        try:
            log('skin_theme: skin=%s accent=%s source=%s'
                % (skin_id, palette['accent'], source))
        except Exception:  # pylint: disable=broad-except
            pass

    return palette


def clear_theme():
    try:
        for key in ('accent', 'accent_soft', 'accent_dim', 'accent_glow',
                    'secondary', 'surface', 'surface_card', 'text', 'muted',
                    'ok', 'skin', 'ready'):
            HOME.clearProperty('dexhub.theme.%s' % key)
    except Exception:  # pylint: disable=broad-except
        pass


# --------------------------------------------------------------------------- #
#  v4.6.0: stable per-provider identity colours                               #
#                                                                             #
#  Every provider (Dexstreams, Arabmedia, Plex, ...) gets ONE colour that is  #
#  identical on the loading dashboard, the results rows, and the filter       #
#  chips — session after session — because it is derived from the provider    #
#  NAME (crc32), not from arrival order. Eight hues, tuned to stay readable   #
#  as 3-6px bars and small dots on the dark surfaces of every theme preset.   #
# --------------------------------------------------------------------------- #

PROVIDER_PALETTE = (
    'FF22D3EE',  # 1 cyan
    'FFF59E0B',  # 2 amber
    'FFA78BFA',  # 3 violet
    'FF34D399',  # 4 emerald
    'FFF472B6',  # 5 pink
    'FF60A5FA',  # 6 blue
    'FFFB923C',  # 7 orange
    'FFA3E635',  # 8 lime
)


def provider_color_index(name):
    """1-based palette index for a provider name. Deterministic across
    sessions and windows. Empty names collapse to slot 1."""
    try:
        import zlib
        text = str(name or '').strip().lower()
        if not text:
            return 1
        return (zlib.crc32(text.encode('utf-8', 'replace')) % len(PROVIDER_PALETTE)) + 1
    except Exception:  # pylint: disable=broad-except
        return 1


def provider_color(name):
    """AARRGGBB colour string for a provider name."""
    return PROVIDER_PALETTE[provider_color_index(name) - 1]
