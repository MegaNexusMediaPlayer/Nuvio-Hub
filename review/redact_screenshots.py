#!/usr/bin/env python3
"""Redact public screenshots: personal data and third-party artwork (6.0.24 docs).

Each region is pixelated, then blurred, so text, faces and logos cannot be
recovered. Usage: redact_screenshots.py <source folder> <output folder>.
"""
import subprocess
import sys
from pathlib import Path

# output name: (source file, [(x, y, w, h), ...])  coordinates in source pixels
JOBS = {
    'hub.png': ('clipboard_2026-10-01_13-41.png', []),
    'hub-settings.png': ('clipboard_2026-10-01_13-42 (2).png', []),
    'phone-setup-qr.png': ('clipboard_2026-10-01_13-42.png', [
        (296, 239, 480, 480),          # QR code (LAN address + one-time key)
        (870, 680, 780, 40)]),         # URL with IP and key
    'poster-preload.png': ('clipboard_2026-10-01_13-43.png', []),
    'home-collections.png': ('clipboard_2026-10-01_13-44 (2).png', [
        (850, 0, 988, 612),            # hero backdrop (posters), right of the description
        (585, 0, 265, 258), (585, 312, 265, 300),  # hero above/below the description text
        (30, 486, 1306, 178),          # Discover card artwork
        (30, 755, 1808, 180)]),        # streaming service logos
    'home-continue-watching.png': ('clipboard_2026-10-01_13-44.png', [
        (600, 0, 1252, 612),           # hero still
        (46, 486, 1806, 300),          # Continue Watching posters
        (46, 874, 1310, 152)]),        # Discover card artwork
    'home-studios-decades.png': ('clipboard_2026-10-01_13-45.png', [
        (790, 0, 1073, 622),           # hero artwork, right of the description
        (605, 0, 185, 265), (605, 318, 185, 304),  # hero above/below the description text
        (54, 490, 1809, 182),          # studio logos
        (54, 760, 1809, 182)]),        # decade artwork
    'phone-addons.png': ('IMG_8729.PNG', [
        (90, 1596, 330, 70),           # private add-on name
        (440, 2576, 400, 76)]),        # IP in the address bar
    'phone-account.png': ('IMG_8730.PNG', [
        (86, 768, 720, 72),            # account email
        (86, 836, 500, 54),            # profile name
        (440, 2576, 400, 76)]),
    'phone-collections.png': ('IMG_8731.PNG', [(440, 2576, 400, 76)]),
    'phone-display.png': ('IMG_8732.PNG', [(440, 2576, 400, 76)]),
}


def redact(src, dst, regions):
    args = ['magick', str(src)]
    for x, y, w, h in regions:
        args += ['(', '-clone', '0', '-crop', '%dx%d+%d+%d' % (w, h, x, y), '+repage',
                 '-scale', '3%', '-scale', '%dx%d!' % (w, h), '-blur', '0x12', ')',
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
