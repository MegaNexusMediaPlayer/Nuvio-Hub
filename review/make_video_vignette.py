#!/usr/bin/env python3
"""Generate script.nuvio/resources/media/nuvio_video_vignette.png (reproducible).

Black frame for small video windows: fully opaque at the very edge (so the
video's border never shows, even where a device ignores partial transparency
over the hardware video plane), fading to transparent towards the centre.
"""
from pathlib import Path
import struct
import zlib

W, H = 320, 180
BORDER_X, BORDER_Y = 0.14, 0.16  # fade width as a fraction of the size


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def alpha(x, y):
    dx = min(x + .5, W - x - .5) / (W * BORDER_X)
    dy = min(y + .5, H - y - .5) / (H * BORDER_Y)
    edge = min(dx, dy)
    return int(round(255 * (1 - smooth(edge))))


def png(width, height, pixel):
    rows = b''.join(b'\x00' + b''.join(bytes((0, 0, 0, pixel(x, y))) for x in range(width)) for y in range(height))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b''))


if __name__ == '__main__':
    out = Path(__file__).resolve().parents[1] / 'script.nuvio/resources/media/nuvio_video_vignette.png'
    out.write_bytes(png(W, H, alpha))
    print(out, out.stat().st_size)
