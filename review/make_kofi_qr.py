#!/usr/bin/env python3
"""Generate script.nuvio/resources/media/kofi_qr.png (needs: pip install qrcode pypng)."""
from pathlib import Path
import qrcode
from qrcode.image.pure import PyPNGImage

URL = 'https://ko-fi.com/master100janovic'

if __name__ == '__main__':
    out = Path(__file__).resolve().parents[1] / 'script.nuvio/resources/media/kofi_qr.png'
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=16, border=2)
    qr.add_data(URL)
    qr.make(fit=True)
    qr.make_image(image_factory=PyPNGImage).save(str(out))
    print(out, out.stat().st_size)
