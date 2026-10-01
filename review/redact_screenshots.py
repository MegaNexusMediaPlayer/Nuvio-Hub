#!/usr/bin/env python3
"""Redact public screenshots: personal data and third-party artwork (6.0.24 docs).

Personal data and trademarked service/studio logos are pixelated and blurred
until unreadable; posters and stills are shown as captured. Usage:
redact_screenshots.py <source folder> <output folder>.
"""
import subprocess
import sys
from pathlib import Path

# output name: (source file, [(x, y, w, h, kind), ...])  coordinates in source pixels
# kind 'private': personal data; 'logo': trademarked service/studio logos.
# Posters, stills and collection artwork are shown as captured.
JOBS = {
    'hub.png': ('clipboard_2026-10-01_13-41.png', []),
    'hub-settings.png': ('clipboard_2026-10-01_13-42 (2).png', []),
    'phone-setup-qr.png': ('clipboard_2026-10-01_13-42.png', [
        (296, 239, 480, 480, 'private'),   # QR code (LAN address + one-time key)
        (870, 680, 780, 40, 'private')]),  # URL with IP and key
    'poster-preload.png': ('clipboard_2026-10-01_13-43.png', []),
    'home-collections.png': ('clipboard_2026-10-01_13-44 (2).png', [
        (30, 755, 1808, 180, 'logo')]),    # streaming service logos
    'home-continue-watching.png': ('clipboard_2026-10-01_13-44.png', []),
    'home-studios-decades.png': ('clipboard_2026-10-01_13-45.png', [
        (54, 490, 1809, 182, 'logo')]),    # studio logos
    'phone-addons.png': ('IMG_8729.PNG', [
        (90, 1596, 330, 70, 'private'),    # private add-on name
        (440, 2576, 400, 76, 'private')]), # IP in the address bar
    'phone-account.png': ('IMG_8730.PNG', [
        (86, 768, 720, 72, 'private'),     # account email
        (86, 836, 500, 54, 'private'),     # profile name
        (440, 2576, 400, 76, 'private')]),
    'phone-collections.png': ('IMG_8731.PNG', [(440, 2576, 400, 76, 'private')]),
    'phone-display.png': ('IMG_8732.PNG', [(440, 2576, 400, 76, 'private')]),
}

STRENGTH = {'private': ('3%', '0x12'), 'logo': ('4%', '0x8')}


def redact(src, dst, regions):
    args = ['magick', str(src)]
    for x, y, w, h, kind in regions:
        scale, blur = STRENGTH[kind]
        args += ['(', '-clone', '0', '-crop', '%dx%d+%d+%d' % (w, h, x, y), '+repage',
                 '-scale', scale, '-scale', '%dx%d!' % (w, h), '-blur', blur, ')',
                 '-geometry', '+%d+%d' % (x, y), '-composite']
    # Phone captures are downscaled for the README; TV captures stay 1080p-ish.
    args += ['-resize', '1920x1400>', '-depth', '8', '-strip', '-define', 'png:compression-level=9', str(dst)]
    subprocess.run(args, check=True)


def main():
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for name, (file, regions) in JOBS.items():
        redact(source / file, out / name, regions)
        print(name)


if __name__ == '__main__':
    main()
