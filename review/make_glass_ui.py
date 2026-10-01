#!/usr/bin/env python3
"""Glass look (6.0.29): card boxes, focus rings, pills, clock capsule.

6.0.30: no drop shadows and no rim lines (they showed an odd edge around
pills and frames) - plain translucent glass only; transparency up to 50 %.

Renders the PNG assets (ImageMagick 7) and patches the Light windows in
script.nuvio/resources/skins/Default plus the HUB skin buttons. Idempotent:
already patched files are left alone. Afterwards run make_theme_variants.py.

Kodi cannot blur what is behind a control, so "frosted glass" is a translucent
white layer with a top highlight and a light rim; it reads as glass on any
background (Light, Dark and Semi-dark themes).
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / 'script.nuvio/resources/media'
SKIN_MEDIA = ROOT / 'skin.nuvio/media/nuvio'
DEFAULT = ROOT / 'script.nuvio/resources/skins/Default/1080i'
URL = 'special://home/addons/script.nuvio/resources/media/'
OPACITY = (('10', 90), ('20', 80), ('30', 70), ('40', 60), ('50', 50))  # Settings: card transparency
OPACITY_PROPERTY = 'Window(Home).Property(nuvio.card_opacity)'


def magick(*args):
    subprocess.run(['magick', *map(str, args)], check=True)


def glass_from_mask(mask, out, top=0.10, bottom=0.03, rim=0.0, rim_px=4):
    """Translucent white fill (brighter at the top) inside the mask, light rim."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        w, h = (int(v) for v in subprocess.run(['magick', 'identify', '-format', '%w %h', str(mask)],
                                               capture_output=True, text=True, check=True).stdout.split())
        magick(mask, '-alpha', 'extract', t / 'a.png')
        magick('-size', '%dx%d' % (w, h), 'gradient:gray(%d%%)-gray(%d%%)' % (top * 100, bottom * 100), t / 'fill.png')
        magick(t / 'a.png', '-morphology', 'Erode', 'Disk:%d' % rim_px, t / 'inner.png')
        magick(t / 'a.png', t / 'inner.png', '-compose', 'minus_src', '-composite', '-evaluate', 'multiply', str(rim), t / 'rim.png')
        magick(t / 'fill.png', t / 'inner.png', '-compose', 'multiply', '-composite', t / 'rim.png', '-compose', 'lighten',
               '-composite', t / 'alpha.png')
        magick('-size', '%dx%d' % (w, h), 'xc:white', t / 'alpha.png', '-alpha', 'off', '-compose', 'copyopacity',
               '-composite', '-depth', '8', '-strip', 'PNG32:%s' % out)


def focus_glass(ring, out, pad=12, glow=9):
    """The focus ring with a soft outer glow; ``pad`` px of room for the glow."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        magick(ring, '-alpha', 'extract', '-bordercolor', 'black', '-border', pad, t / 'a.png')
        magick(t / 'a.png', '-blur', '0x%d' % glow, '-evaluate', 'multiply', '0.55', t / 'glow.png')
        magick(t / 'a.png', '-evaluate', 'multiply', '0.92', t / 'glow.png', '-compose', 'lighten', '-composite', t / 'alpha.png')
        magick(t / 'alpha.png', '(', '+clone', '-fill', 'white', '-colorize', '100', ')', '+swap', '-alpha', 'off',
               '-compose', 'copyopacity', '-composite', '-depth', '8', '-strip', 'PNG32:%s' % out)


def pills():
    """64x64 9-slice pills (border 22): glass at rest, bright glass when focused."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        base = MEDIA / 'nuvio_pill.png'
        rest, focus = t / 'rest.png', t / 'focus.png'
        glass_from_mask(base, rest, top=0.20, bottom=0.10)
        glass_from_mask(base, focus, top=0.97, bottom=0.82)
        for folder in (MEDIA, SKIN_MEDIA):
            magick(rest, folder / 'nuvio_pill_glass.png')
            magick(focus, folder / 'nuvio_pill_glass_focus.png')


def assets():
    glass_from_mask(MEDIA / 'nuvio_tile_mask_v2.png', MEDIA / 'nuvio_tile_glass.png')
    glass_from_mask(MEDIA / 'nuvio_poster_mask_v2.png', MEDIA / 'nuvio_poster_glass.png')
    focus_glass(MEDIA / 'nuvio_tile_focus_v2.png', MEDIA / 'nuvio_tile_focus_glass.png')
    focus_glass(MEDIA / 'nuvio_poster_focus_v2.png', MEDIA / 'nuvio_poster_focus_glass.png')
    pills()


BOX = re.compile(r'(?P<indent>[ \t]*)<control type="image">\s*<left>(?P<l>-?\d+)</left>\s*<top>(?P<t>-?\d+)</top>\s*'
                 r'<width>(?P<w>\d+)</width>\s*<height>(?P<h>\d+)</height>\s*<aspectratio>stretch</aspectratio>\s*'
                 r'<texture colordiffuse="FF202532">' + re.escape(URL) + r'nuvio_(?P<kind>tile|poster)_mask_v2\.png</texture>\s*</control>')
FOCUS = re.compile(r'<control type="image">(?P<pre>\s*)<left>(?P<l>-?\d+)</left>\s*<top>(?P<t>-?\d+)</top>\s*'
                   r'<width>(?P<w>\d+)</width>\s*<height>(?P<h>\d+)</height>(?P<mid>\s*<aspectratio>stretch</aspectratio>\s*'
                   r'<texture colordiffuse="FFDBECFF">)' + re.escape(URL) + r'nuvio_(?P<kind>tile|poster)_focus_v2\.png')
ART = re.compile(r'(?P<indent>[ \t]*)(?P<tex><texture background="true" diffuse="' + re.escape(URL) +
                 r'nuvio_(?:tile|poster)_mask_v2\.png">[^<]*</texture>)(?P<rest>(?:(?!</control>).)*?)(?P<end>\n[ \t]*</control>)', re.S)


def box(m):
    i, l, t, w, h, kind = m['indent'], int(m['l']), int(m['t']), int(m['w']), int(m['h']), m['kind']
    inner = i + '  '
    return ('%s<control type="image">\n%s<left>%d</left>\n%s<top>%d</top>\n%s<width>%d</width>\n%s<height>%d</height>\n'
            '%s<aspectratio>stretch</aspectratio>\n%s<texture>%snuvio_%s_glass.png</texture>\n%s</control>'
            % (i, inner, l, inner, t, inner, w, inner, h, inner, inner, URL, kind, i))


SHADOW = re.compile(r'[ \t]*<control type="image">(?:(?!</control>).)*?nuvio_(?:tile|poster)_shadow\.png</texture>\s*</control>\n', re.S)
FADE = re.compile(r'\n[ \t]*<animation effect="fade" start="\d+" end="\d+" time="0" condition="String\.IsEqual\(Window\(Home\)\.Property\(nuvio\.card_opacity\),\d+\)">Conditional</animation>')


def focus(m):
    l, t, w, h = int(m['l']), int(m['t']), int(m['w']), int(m['h'])
    pre = m['pre']  # newline + indentation of the original block
    return ('<control type="image">%s<left>%d</left>%s<top>%d</top>%s<width>%d</width>%s<height>%d</height>%s%snuvio_%s_focus_glass.png'
            % (pre, l - 4, pre, t - 4, pre, w + 8, pre, h + 8, m['mid'], URL, m['kind']))


def art(m):
    pad = m['indent']
    fades = ''.join('\n%s<animation effect="fade" start="%d" end="%d" time="0" condition="String.IsEqual(%s,%s)">Conditional</animation>'
                    % (pad, alpha, alpha, OPACITY_PROPERTY, key) for key, alpha in OPACITY)
    return pad + m['tex'] + FADE.sub('', m['rest']) + fades + m['end']


PILL_REST = re.compile(r'<texturenofocus border="22" colordiffuse="[0-9A-F]{8}">' + re.escape(URL) + r'nuvio_pill\.png</texturenofocus>')
PILL_FOCUS = re.compile(r'<texturefocus border="22">' + re.escape(URL) + r'nuvio_pill\.png</texturefocus>')
CLOCK = re.compile(r'(?P<indent>[ \t]*)<control type="label">\s*<left>1750</left>\s*<top>39</top>(?:(?!</control>).)*?System\.Time\(hh:mm\)(?:(?!</control>).)*?</control>', re.S)


def clock(m):
    i = m['indent'];inner = i + '  '
    capsule = ('%s<control type="image">\n%s<!-- Glass capsule behind weather and clock. -->\n%s<left>1596</left>\n%s<top>30</top>\n'
               '%s<width>276</width>\n%s<height>58</height>\n%s<texture border="22">%snuvio_pill_glass.png</texture>\n'
               '%s<visible>!Skin.HasSetting(nuvio.hideweather) + !String.IsEqual(Window(10000).Property(nuvio.hide_weather_clock),1)</visible>\n%s</control>\n'
               % (i, inner, inner, inner, inner, inner, inner, URL, inner, i))
    return capsule + m.group(0)


def patch_windows():
    changed = []
    for path in sorted(DEFAULT.glob('*.xml')):
        text = path.read_text(encoding='utf-8')
        new = SHADOW.sub('', text)  # 6.0.30: shadows removed
        new = BOX.sub(box, new)
        new = FOCUS.sub(focus, new)
        new = ART.sub(art, new)
        new = PILL_REST.sub('<texturenofocus border="22">%snuvio_pill_glass.png</texturenofocus>' % URL, new)
        new = PILL_FOCUS.sub('<texturefocus border="22">%snuvio_pill_glass_focus.png</texturefocus>' % URL, new)
        if 'Glass capsule behind weather and clock' not in new:
            new = CLOCK.sub(clock, new, count=1)
        if new != text:
            path.write_text(new, encoding='utf-8')
            changed.append(path.name)
    for name in ('Home.xml', 'SkinSettings.xml'):
        path = ROOT / 'skin.nuvio/xml' / name
        text = path.read_text(encoding='utf-8')
        new = text.replace('<texturenofocus border="22" colordiffuse="nuvio_pill">nuvio/nuvio_pill.png</texturenofocus>',
                           '<texturenofocus border="22">nuvio/nuvio_pill_glass.png</texturenofocus>')
        new = new.replace('<texturefocus border="22">nuvio/nuvio_pill.png</texturefocus>',
                          '<texturefocus border="22">nuvio/nuvio_pill_glass_focus.png</texturefocus>')
        if new != text:
            path.write_text(new, encoding='utf-8')
            changed.append(name)
    return changed


if __name__ == '__main__':
    if '--assets' in sys.argv or len(sys.argv) == 1:
        assets()
    print('patched:', ', '.join(patch_windows()) or 'nothing (already glass)')
