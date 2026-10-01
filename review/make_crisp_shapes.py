#!/usr/bin/env python3
"""Crisp rounded corners (6.0.31).

Card masks and focus rings were drawn at 3x and Kodi shrinks GUI textures
without mipmaps, so their corners came out jagged; 9-slice pills (64 px,
border 22) are drawn 1:1 per Kodi's GUITexture and turn soft when the GUI is
scaled up on 4K. Here:

* card masks / focus rings are redrawn at 2x with supersampled edges;
* every pill and button of a fixed size gets its own 2x texture (no 9-slice),
  white, tinted by the existing ``colordiffuse``; glass pills use a 20 % white
  diffuse at rest and near-white when focused;
* the glass capsule behind clock/weather is removed;
* 6.0.32: the header buttons Home / Search / Settings / HUB are plain text at
  rest (no pill); the pill shows only on the focused one;
* every MegaNexus logo gets its own 2x wordmark (Lanczos from the 1600 px
  master) instead of the master shrunk 5-10x by Kodi.
Large panels keep their 9-slice texture (a full-size 2x texture would waste
GPU memory). Idempotent. Afterwards run make_theme_variants.py.
"""
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / 'script.nuvio/resources/media'
SKIN_MEDIA = ROOT / 'skin.nuvio/media/nuvio'
DEFAULT = ROOT / 'script.nuvio/resources/skins/Default/1080i'
SKIN_XML = (ROOT / 'skin.nuvio/xml/Home.xml', ROOT / 'skin.nuvio/xml/SkinSettings.xml')
URL = 'special://home/addons/script.nuvio/resources/media/'
SCALE = 2           # texture pixels per skin pixel
SUPER = 4           # supersampling factor for drawing
MAX_AREA = 150000   # skin px^2: larger panels keep 9-slice
GLASS_REST = '33FFFFFF'   # 20 % white
GLASS_FOCUS = 'F2FFFFFF'


def magick(*args):
    subprocess.run(['magick', *map(str, args)], check=True)


def rounded(out, w, h, r, inset=0.0):
    """White rounded rectangle w x h (skin px) at SCALE, radius r, smooth edge."""
    s = SCALE * SUPER
    W, H = round(w * s), round(h * s)
    i = inset * s
    magick('-size', '%dx%d' % (W, H), 'xc:none', '-fill', 'white',
           '-draw', 'roundrectangle %f,%f %f,%f %f,%f' % (i, i, W - 1 - i, H - 1 - i, r * s, r * s),
           '-filter', 'Lanczos', '-resize', '%dx%d!' % (round(w * SCALE), round(h * SCALE)),
           '-depth', '8', '-strip', 'PNG32:%s' % out)


def ring(out, w, h, r, thickness):
    """White rounded ring (outer radius r, given thickness) at SCALE."""
    s = SCALE * SUPER
    W, H, t = round(w * s), round(h * s), thickness * s
    magick('-size', '%dx%d' % (W, H), 'xc:none', '-fill', 'white',
           '-draw', 'roundrectangle 0,0 %f,%f %f,%f' % (W - 1, H - 1, r * s, r * s),
           '-fill', 'black', '-draw', 'roundrectangle %f,%f %f,%f %f,%f' % (t, t, W - 1 - t, H - 1 - t, (r - thickness) * s, (r - thickness) * s),
           '-alpha', 'off', '(', '+clone', '-fill', 'white', '-colorize', '100', ')', '+swap', '-compose', 'copyopacity', '-composite',
           '-filter', 'Lanczos', '-resize', '%dx%d!' % (round(w * SCALE), round(h * SCALE)),
           '-depth', '8', '-strip', 'PNG32:%s' % out)


def cards():
    """Masks (card shape, radius 19), focus rings (radius 25, 4.3 px) and their glass versions."""
    import make_glass_ui as glass
    rounded(MEDIA / 'nuvio_tile_mask_v2.png', 304, 171, 19)
    rounded(MEDIA / 'nuvio_poster_mask_v2.png', 192, 288, 19)
    ring(MEDIA / 'nuvio_tile_focus_v2.png', 312, 179, 25, 4.3)
    ring(MEDIA / 'nuvio_poster_focus_v2.png', 200, 296, 25, 4.3)
    glass.glass_from_mask(MEDIA / 'nuvio_tile_mask_v2.png', MEDIA / 'nuvio_tile_glass.png')
    glass.glass_from_mask(MEDIA / 'nuvio_poster_mask_v2.png', MEDIA / 'nuvio_poster_glass.png')
    glass.focus_glass(MEDIA / 'nuvio_tile_focus_v2.png', MEDIA / 'nuvio_tile_focus_glass.png', pad=4 * SCALE, glow=3 * SCALE)
    glass.focus_glass(MEDIA / 'nuvio_poster_focus_v2.png', MEDIA / 'nuvio_poster_focus_glass.png', pad=4 * SCALE, glow=3 * SCALE)


BLOCK = re.compile(r'<control type="(?:button|image|radiobutton)"[^>]*>(?:(?!<control ).)*?</control>', re.S)
PILL = re.compile(r'<(?P<tag>texture(?:focus|nofocus)?)(?P<attrs>[^>]*)>(?P<base>' + re.escape(URL) +
                  r'|nuvio/)nuvio_pill(?P<kind>_glass_focus|_glass)?\.png</(?P=tag)>')
CAPSULE = re.compile(r'[ \t]*<control type="image">\s*<!-- Glass capsule behind weather and clock\. -->(?:(?!</control>).)*?</control>\n', re.S)


def pill_name(w, h, r):
    return 'nuvio_pill_%dx%d_r%d.png' % (w, h, r)


def convert(text, made):
    def block(m):
        b = m.group(0)
        w = re.search(r'<width>(\d+)</width>', b)
        h = re.search(r'<height>(\d+)</height>', b)
        if not (w and h):
            return b
        w, h = int(w.group(1)), int(h.group(1))
        if w * h > MAX_AREA:
            return b
        def tex(t):
            attrs = t['attrs']
            border = re.search(r'border="(\d+)"', attrs)
            if border and border.group(1) == '0':
                return t.group(0)  # stretched dots keep their texture
            r = min(int(border.group(1)) if border else 22, h // 2, w // 2)
            attrs = re.sub(r'\s*border="\d+"', '', attrs)
            if t['kind'] and 'colordiffuse' not in attrs:
                attrs += ' colordiffuse="%s"' % (GLASS_FOCUS if t['kind'] == '_glass_focus' else GLASS_REST)
            name = pill_name(w, h, r)
            made.add((w, h, r))
            return '<%s%s>%s%s</%s>' % (t['tag'], attrs, t['base'], name, t['tag'])
        return PILL.sub(tex, b)
    return BLOCK.sub(block, text)


WORDMARK = 'nuvio_wordmark.png'   # master, 1600x507; phone page /logo.png
LOGO = re.compile(r'<control type="image">(?:(?!</control>).)*?nuvio_wordmark(?:_\d+x\d+)?\.png</texture>(?:(?!</control>).)*?</control>', re.S)


HEADER_IDS = ('101', '105', '107', '108')   # Home, Search, Settings, HUB
HEADER = re.compile(r'(<control type="button" id="(?:%s)">(?:(?!</control>).)*?)\n[ \t]*<texturenofocus[^>]*>[^<]*</texturenofocus>'
                    % '|'.join(HEADER_IDS), re.S)


def plain_header(text):
    return HEADER.sub(r'\1', text)


def wordmark_name(w, h):
    return 'nuvio_wordmark_%dx%d.png' % (w, h)


def logo_size(block, ratio):
    """Texture size (2x of what Kodi draws) for one logo control."""
    w = int(re.search(r'<width>(\d+)</width>', block).group(1))
    h = int(re.search(r'<height>(\d+)</height>', block).group(1))
    mode = re.search(r'<aspectratio[^>]*>(\w+)</aspectratio>', block)
    mode = mode.group(1) if mode else 'stretch'
    if mode == 'keep':
        fit_h = w / h > ratio
    elif mode == 'scale':
        fit_h = w / h <= ratio
    else:
        return w * SCALE, h * SCALE
    dw, dh = (h * ratio, h) if fit_h else (w, w / ratio)
    return round(dw * SCALE), round(dh * SCALE)


def logos(text, made, ratio):
    def block(m):
        w, h = logo_size(m.group(0), ratio)
        made.add((w, h))
        return re.sub(r'nuvio_wordmark(?:_\d+x\d+)?\.png', wordmark_name(w, h), m.group(0))
    return LOGO.sub(block, text)


def wordmark(out, w, h):
    magick(MEDIA / WORDMARK, '-filter', 'Lanczos', '-resize', '%dx%d!' % (w, h), '-depth', '8', '-strip', 'PNG32:%s' % out)


def patch():
    made, changed, marks = set(), [], set()
    w, h = (int(v) for v in subprocess.run(['magick', 'identify', '-format', '%w %h', str(MEDIA / WORDMARK)],
                                           capture_output=True, text=True, check=True).stdout.split())
    for path in sorted(DEFAULT.glob('*.xml')) + list(SKIN_XML):
        text = path.read_text(encoding='utf-8')
        new = CAPSULE.sub('', text)
        new = convert(new, made)
        new = logos(new, marks, w / h)
        if path.name.startswith('nuvio_home'):
            new = plain_header(new)
        if new != text:
            path.write_text(new, encoding='utf-8')
            changed.append(path.name)
    # Textures for every size still referenced (also when already converted).
    sizes = set()
    for path in sorted(DEFAULT.glob('*.xml')) + list(SKIN_XML):
        sizes.update((int(a), int(b), int(c)) for a, b, c in re.findall(r'nuvio_pill_(\d+)x(\d+)_r(\d+)\.png', path.read_text(encoding='utf-8')))
    for w, h, r in sorted(sizes):
        for folder in (MEDIA, SKIN_MEDIA):
            target = folder / pill_name(w, h, r)
            if not target.exists():
                rounded(target, w, h, r)
    for w, h in sorted(marks):
        wordmark(MEDIA / wordmark_name(w, h), w, h)
    return changed, sorted(sizes), sorted(marks)


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    cards()
    changed, sizes, marks = patch()
    print('patched:', ', '.join(changed) or 'nothing')
    print('pill sizes:', len(sizes))
    print('logos:', ', '.join('%dx%d' % m for m in marks))
