#!/usr/bin/env python3
"""Generate the Dark and Semi-dark interface themes from the Light one (6.0.28).

Source: script.nuvio/resources/skins/Default/1080i (Light, MegaNexus blue).
Output: .../skins/Dark/1080i and .../skins/Dim/1080i, plus skin.nuvio/colors
dark.xml and dim.xml from defaults.xml. Run after any change to the Light XML;
test_nuvio_628 fails when the variants are out of date.

* Dark (OLED): the blue background becomes pure black, dark-blue panels and
  pills become neutral dark grey; text, blue accents/focus and the original
  catalog card boxes stay.
* Dim: the background becomes black (the top around the small video) and a
  dark-blue gradient rises from the bottom of the main screens; panels stay blue.
Both use the theme's banner and screensaver background images.
"""
import colorsys
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKINS = ROOT / 'script.nuvio/resources/skins'
COLORS = ROOT / 'skin.nuvio/colors'
BACKGROUND = '040F22'          # Light background (logo "space" navy)
BOTTOM_BLUE = 'FF0A2350'       # Dim: dark blue at the bottom
MEDIA = 'special://home/addons/script.nuvio/resources/media/'
DIM_GRADIENT_WINDOWS = {'nuvio_home.xml', 'nuvio_home_compact.xml', 'nuvio_details.xml', 'nuvio_details_landscape.xml',
                        'nuvio_catalog.xml', 'nuvio_catalog_landscape.xml', 'nuvio_person.xml', 'nuvio_info.xml'}
KEEP_ORIGINAL = re.compile(r'nuvio_(?:tile|poster)_mask')
HEX = re.compile(r'\b([0-9A-Fa-f]{2})([0-9A-Fa-f]{6})\b')
FILES = {'dark': {'nuvio_banner.png': 'nuvio_banner_dark.png', 'meganexus_saver_bg.png': 'meganexus_saver_bg_dark.png'},
         'dim': {'nuvio_banner.png': 'nuvio_banner_dim.png', 'meganexus_saver_bg.png': 'meganexus_saver_bg_dim.png'}}
FOLDERS = {'dark': 'Dark', 'dim': 'Dim'}


def dark_color(rgb):
    if rgb.upper() == BACKGROUND:
        return '000000'
    r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if 200 <= h * 360 <= 235 and s >= 0.45 and l <= 0.30:   # dark-blue panels/pills -> neutral grey
        v = round(l * 0.8 * 255)
        return '%02X%02X%02X' % (v, v, v)
    return None


def dim_color(rgb):
    return '000000' if rgb.upper() == BACKGROUND else None


def recolor(text, mapping):
    def sub(m):
        new = mapping(m.group(2))
        return m.group(1).upper() + new if new else m.group(0)
    return ''.join(line if KEEP_ORIGINAL.search(line) else HEX.sub(sub, line)
                   for line in text.splitlines(keepends=True))


def add_bottom_gradient(text):
    """After the first full-screen background image, a dark-blue gradient from the middle down."""
    for m in re.finditer(r'<control type="image">(?:(?!</control>).)*?</control>', text, re.S):
        block = m.group(0)
        if ('FF000000' in block and '<width>1920</width>' in block and '<height>1080</height>' in block
                and ('black.png' in block or 'white.png' in block)):
            indent = re.search(r'\n([ \t]*)$', text[:m.start()])
            pad = indent.group(1) if indent else '    '
            gradient = ('\n%s<control type="image">\n%s  <left>0</left>\n%s  <top>560</top>\n%s  <width>1920</width>\n'
                        '%s  <height>520</height>\n%s  <aspectratio>stretch</aspectratio>\n'
                        '%s  <texture colordiffuse="%s">%snuvio_bottom_fade.png</texture>\n%s</control>'
                        % ((pad,) * 7 + (BOTTOM_BLUE, MEDIA, pad)))
            return text[:m.end()] + gradient + text[m.end():]
    return text


def variant(name, text, theme):
    text = recolor(text, dark_color if theme == 'dark' else dim_color)
    for old, new in FILES[theme].items():
        text = text.replace(MEDIA + old, MEDIA + new)
    if theme == 'dim' and name in DIM_GRADIENT_WINDOWS:
        text = add_bottom_gradient(text)
    return text


def build(out_root=SKINS, colors_out=COLORS):
    source = SKINS / 'Default/1080i'
    for theme, folder in FOLDERS.items():
        target = Path(out_root) / folder / '1080i'
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for path in sorted(source.glob('*.xml')):
            (target / path.name).write_text(variant(path.name, path.read_text(encoding='utf-8'), theme), encoding='utf-8')
        # Kodi colour theme for the MegaNexus skin (dialogs, pills).
        defaults = (COLORS / 'defaults.xml').read_text(encoding='utf-8')
        (Path(colors_out) / (theme + '.xml')).write_text(recolor(defaults, dark_color if theme == 'dark' else dim_color),
                                                         encoding='utf-8')


if __name__ == '__main__':
    build()
    print('Dark and Dim themes generated.')
    sys.exit(0)
