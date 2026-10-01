#!/usr/bin/env python3
"""6.0.21: move the interface theme from violet to the MegaNexus logo blues.

* Violet accents (hue 235-300°) become logo blue (hue 212°), same lightness,
  mid tones at least 70 % saturated so focus stays vivid.
* Neutral slate backgrounds (dark, hue 200-245°, low saturation) become the
  deep "space" navy of the logo (#001E56 family), same lightness.
* Violet pixels in bundled UI PNGs (skin weather icons; script media from the
  builder's UI_MEDIA list) are hue-rotated the same way. Brand marks stay.
Idempotent: blue values are outside both source ranges.
"""
import colorsys
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLUE_HUE = 212 / 360
NAVY_HUE = 218 / 360
XML = [*sorted((ROOT / 'script.nuvio/resources/skins').rglob('*.xml')),
       *sorted((ROOT / 'skin.nuvio/xml').glob('*.xml')), ROOT / 'skin.nuvio/colors/defaults.xml']
PNG_SKIP = {'mdblist.png', 'stremio.png'}
HEX = re.compile(r'\b([0-9A-Fa-f]{2})([0-9A-Fa-f]{6})\b')


def recolor(rgb):
    r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    deg = h * 360
    if 235 <= deg <= 300 and s > 0.12 and l > 0.12:  # 6.0.25: also greyish violet (settings focus)
        if l < 0.7:
            s = max(s, 0.7)
        h = BLUE_HUE
    elif 200 <= deg <= 245 and s < 0.4 and 0.02 < l < 0.26:
        h, s, l = NAVY_HUE, 0.8, max(l, 0.075)  # never pure black: deep space navy
    else:
        return None
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return '%02X%02X%02X' % (round(r * 255), round(g * 255), round(b * 255))


KEEP_ORIGINAL = re.compile(r'nuvio_(?:tile|poster)_mask')  # catalog card boxes keep their original colour (6.0.28)


def fix_text(path):
    text = path.read_text(encoding='utf-8')
    changed = 0
    def sub(m):
        nonlocal changed
        new = recolor(m.group(2))
        if not new:
            return m.group(0)
        changed += 1
        return m.group(1).upper() + new
    out = ''.join(line if KEEP_ORIGINAL.search(line) else HEX.sub(sub, line)
                  for line in text.splitlines(keepends=True))
    if out != text:
        path.write_text(out, encoding='utf-8')
    return changed


def violet_share(path):
    data = subprocess.run(['magick', str(path), '-resize', '48x48', 'txt:-'], capture_output=True, text=True).stdout
    total = violet = 0
    for m in re.finditer(r'srgba?\((\d+),(\d+),(\d+)(?:,([\d.]+))?\)', data):
        if float(m.group(4) or 1) < 0.2:
            continue
        total += 1
        h, l, s = colorsys.rgb_to_hls(*(int(x) / 255 for x in m.groups()[:3]))
        violet += s > 0.2 and 0.66 < h < 0.88 and 0.1 < l < 0.97
    return violet / total if total else 0


def fix_png(path):
    # HSL hue is 0..1 in ImageMagick; rotate only violet pixels.
    shift = (258 - 212) / 360
    subprocess.run(['magick', str(path), '-colorspace', 'HSL', '-channel', 'R',
                    '-fx', 'u>0.64 && u<0.86 ? u-%.4f : u' % shift, '+channel',
                    '-colorspace', 'sRGB', '-depth', '8', '-strip', str(path)], check=True)


def main():
    total = 0
    for path in XML:
        n = fix_text(path)
        total += n
        if n:
            print('%4d  %s' % (n, path.relative_to(ROOT)))
    sys.path.insert(0, str(ROOT / 'review'))
    from build_bundle import UI_MEDIA
    pngs = [ROOT / 'script.nuvio/resources/media' / name for name in sorted(UI_MEDIA) if name.endswith('.png')]
    pngs += sorted((ROOT / 'skin.nuvio/media/nuvio').rglob('*.png'))
    pngs = [p for p in pngs if p.name not in PNG_SKIP]
    for path in pngs:
        if violet_share(path) >= 0.1:
            fix_png(path)
            print('png   %s' % path.relative_to(ROOT))
    print('colour values changed:', total)
    return 0


if __name__ == '__main__':
    sys.exit(main())
