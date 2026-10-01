#!/usr/bin/env python3
"""Render the MegaNexus logo, banner and icons used by the bundle (6.0.21).

Input: the transparent MegaNexus mark (MegaNexus-App assets/brand/app_logo_mark.png).
Text is drawn from a vector font at the final size, so it stays sharp and the
blue "Nexus" is a clean gradient. Needs ImageMagick 7 (`magick`). Fonts are
used only for rendering; no font file is bundled.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

BOLD = '/usr/share/fonts/noto/NotoSans-Bold.ttf'
REGULAR = '/usr/share/fonts/noto/NotoSans-Regular.ttf'
WHITE = '#F4F7FC'
BLUE_TOP, BLUE_BOTTOM = '#4FB3FF', '#1468F0'
BG_CENTER, BG_EDGE = '#123a7a', '#050a18'


def magick(*args):
    subprocess.run(['magick', *map(str, args)], check=True)


def size(path):
    out = subprocess.run(['magick', 'identify', '-format', '%w %h', str(path)], check=True,
                         capture_output=True, text=True).stdout.split()
    return int(out[0]), int(out[1])


def word(tmp, text, font, pointsize, fill, name):
    """Tightly trimmed transparent text; fill is a colour or a vertical gradient pair."""
    mask = tmp / (name + '_mask.png')
    magick('-background', 'none', '-fill', 'white', '-font', font, '-pointsize', pointsize,
           'label:' + text, '-trim', '+repage', mask)
    w, h = size(mask)
    out = tmp / (name + '.png')
    if isinstance(fill, tuple):
        magick('-size', '%dx%d' % (w, h), 'gradient:%s-%s' % fill, mask, '-compose', 'copyopacity', '-composite', out)
    else:
        magick('-size', '%dx%d' % (w, h), 'xc:' + fill, mask, '-compose', 'copyopacity', '-composite', out)
    return out


def text_block(tmp, cap, tagline):
    """'Mega' + 'Nexus' on a shared baseline (both words start with a capital)."""
    point = int(cap / 0.714 * 1.0)   # Noto Sans cap height is ~0.714 em
    mega = word(tmp, 'Mega', BOLD, point, WHITE, 'mega')
    nexus = word(tmp, 'Nexus', BOLD, point, (BLUE_TOP, BLUE_BOTTOM), 'nexus')
    # 'Mega' has a descender (g); align both on the cap/x top instead.
    mw, mh = size(mega);nw, nh = size(nexus)
    gap = int(point * 0.05)
    height = max(mh, nh)
    out = tmp / 'text.png'
    magick('-size', '%dx%d' % (mw + gap + nw, height), 'xc:none', mega, '-geometry', '+0+0', '-composite',
           nexus, '-geometry', '+%d+0' % (mw + gap), '-composite', out)
    if not tagline:
        return out
    tag = word(tmp, 'Your media universe. connected.', REGULAR, int(point * 0.30), '#C9D6EA', 'tag')
    tw, th = size(tag);w, h = size(out)
    full = tmp / 'text_tag.png'
    top = int(cap * 1.02) + int(point * 0.30)
    magick('-size', '%dx%d' % (max(w, tw), top + th), 'xc:none', out, '-geometry', '+0+0', '-composite',
           tag, '-geometry', '+%d+%d' % ((w - tw) // 2 if w > tw else 0, top), '-composite', full)
    return full


def lockup(tmp, mark, height, tagline, name, text_ratio=0.30):
    """Mark + text, mark height = `height`, transparent, trimmed."""
    m = tmp / (name + '_mark.png')
    magick(mark, '-trim', '+repage', '-filter', 'Lanczos', '-resize', 'x%d' % height, m)
    mw, mh = size(m)
    text = text_block(tmp, int(height * text_ratio), tagline)
    tw, th = size(text)
    gap = int(height * 0.12)
    out = tmp / (name + '.png')
    magick('-size', '%dx%d' % (mw + gap + tw, max(mh, th)), 'xc:none',
           m, '-geometry', '+0+%d' % ((max(mh, th) - mh) // 2), '-composite',
           text, '-geometry', '+%d+%d' % (mw + gap, (max(mh, th) - th) // 2), '-composite', out)
    return out


def background(out, w=1920, h=1080, theme='light'):
    """light: MegaNexus blue; dark: black for OLED; dim: black top, dark blue bottom."""
    if theme == 'dark':
        magick('-size', '%dx%d' % (w, h), 'radial-gradient:#0b1220-#000000', '-depth', '8', out)
    elif theme == 'dim':
        magick('-size', '%dx%d' % (w, h), 'gradient:#000000-#0a2350', '(', '-size', '%dx%d' % (w, h),
               'radial-gradient:#123a7a-#000000', '-evaluate', 'multiply', '0.35', ')',
               '-compose', 'screen', '-composite', '-depth', '8', out)
    else:
        magick('-size', '%dx%d' % (w, h), 'radial-gradient:%s-%s' % (BG_CENTER, BG_EDGE), '-depth', '8', out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mark');parser.add_argument('out')
    args = parser.parse_args()
    out = Path(args.out);out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        # Header wordmark: 1600x507 (same 3.15:1 ratio as the layouts expect), no
        # tagline, larger letters relative to the mark so it reads at 90 px high.
        head = lockup(tmp, args.mark, 470, False, 'head', text_ratio=0.46)
        magick('-size', '1600x507', 'xc:none', '(', head, '-filter', 'Lanczos', '-resize', '1570x490', ')',
               '-gravity', 'center', '-composite',
               '-depth', '8', '-strip', 'PNG32:%s' % (out / 'wordmark.png'))
        # Banner / fanart: 1920x1080 with tagline.
        background(tmp / 'bg.png')
        big = lockup(tmp, args.mark, 330, True, 'big')
        magick(tmp / 'bg.png', big, '-gravity', 'center', '-geometry', '+0-70', '-composite',
               '-depth', '8', '-strip', out / 'banner.png')
        # Dark (OLED) and semi-dark themes: banner and screensaver background.
        for theme in ('dark', 'dim'):
            background(tmp / ('bg_%s.png' % theme), theme=theme)
            magick(tmp / ('bg_%s.png' % theme), big, '-gravity', 'center', '-geometry', '+0-70', '-composite',
                   '-depth', '8', '-strip', out / ('banner_%s.png' % theme))
            magick(tmp / ('bg_%s.png' % theme), '-depth', '8', '-strip', out / ('saver_bg_%s.png' % theme))
        # Screensaver layers (skin-animated): background, logo, glow, spark.
        magick('-size', '1920x1080', 'radial-gradient:%s-%s' % ('#0f3170', BG_EDGE), '-depth', '8', '-strip', out / 'saver_bg.png')
        magick('-size', '1920x1080', 'xc:none', big, '-gravity', 'center', '-geometry', '+0-70', '-composite',
               '-depth', '8', '-strip', 'PNG32:%s' % (out / 'saver_logo.png'))
        magick('-size', '1000x1000', 'radial-gradient:rgba(80,170,255,0.60)-rgba(20,70,170,0)', '-depth', '8', '-strip', out / 'saver_glow.png')
        magick('-size', '160x160', 'radial-gradient:white-black', '-evaluate', 'pow', '2.2', tmp / 'spark_mask.png')
        magick('-size', '160x160', 'xc:#DDF2FF', tmp / 'spark_mask.png', '-alpha', 'off', '-compose', 'copyopacity',
               '-composite', '-depth', '8', '-strip', out / 'saver_spark.png')
        # Icon: mark centred on the dark background, 1024x1024.
        background(tmp / 'ibg.png', 1024, 1024)
        magick(tmp / 'ibg.png', '(', args.mark, '-trim', '+repage', '-filter', 'Lanczos', '-resize', '820x', ')',
               '-gravity', 'center', '-composite', '-depth', '8', '-strip', out / 'icon.png')


if __name__ == '__main__':
    main()
