# -*- coding: utf-8 -*-
"""Plex QR sign-in for Nuvio Hub (ported from DPlex's plexsignin approach).

Renders the plex.tv/link URL as a QR code the user can scan with a phone,
so no code has to be typed on a TV remote.  The PNG is written locally with
a tiny raw encoder — no Pillow, no network service, no skin dependency.
"""
from __future__ import absolute_import

import os
import struct
import sys
import zlib

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
# --- nuviohub-403-patch ---
try:
    from .i18n import tr as tr
except Exception:
    from resources.lib.i18n import tr as tr


_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)


def _profile_dir():
    try:
        return xbmcvfs.translatePath(xbmcaddon.Addon('plugin.video.nuviohub').getAddonInfo('profile'))
    except Exception:
        return xbmc.translatePath('special://profile/addon_data/plugin.video.nuviohub')


def qr_png(data, box_size=8, border=4):
    """Write a QR PNG for `data` and return its path ('' on failure)."""
    try:
        import qrcode  # bundled pure-Python encoder
        qr = qrcode.QRCode(version=None,
                           error_correction=qrcode.constants.ERROR_CORRECT_M,
                           box_size=1, border=border)
        qr.add_data(data)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        width = len(matrix) * box_size
        white, black = b'\xff\xff\xff', b'\x00\x00\x00'
        rows = []
        for row in matrix:
            expanded = b''.join((black if cell else white) * box_size for cell in row)
            for _ in range(box_size):
                rows.append(b'\x00' + expanded)
        raw = b''.join(rows)

        def chunk(kind, payload):
            crc = zlib.crc32(kind + payload) & 0xffffffff
            return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', crc)

        png = (b'\x89PNG\r\n\x1a\n' +
               chunk(b'IHDR', struct.pack('>IIBBBBB', width, width, 8, 2, 0, 0, 0)) +
               chunk(b'IDAT', zlib.compress(raw, 9)) +
               chunk(b'IEND', b''))
        # v4.6.7: filename derived from the ENCODED DATA. Kodi's texture
        # cache is keyed by path — the old fixed single-name QR file meant
        # the FIRST QR ever rendered on the box was shown forever (a stale,
        # expired PIN), for the Plex link AND the pairing QR which shared
        # the same file. Every payload now gets its own path and older
        # QR files (including the legacy fixed name) are purged.
        import glob as _glob
        import hashlib as _hashlib
        digest = _hashlib.sha1(
            data.encode('utf-8', 'replace') if isinstance(data, str) else bytes(data)
        ).hexdigest()[:10]
        prof = _profile_dir()
        os.makedirs(prof, exist_ok=True)
        path = os.path.join(prof, 'plex_link_qr_%s.png' % digest)
        for stale in _glob.glob(os.path.join(prof, 'plex_link_qr*.png')):
            if os.path.abspath(stale) != os.path.abspath(path):
                try:
                    os.remove(stale)
                except Exception:
                    pass
        tmp = path + '.tmp'
        with open(tmp, 'wb') as handle:
            handle.write(png)
        os.replace(tmp, path)
        return path
    except Exception as exc:
        try:
            xbmc.log('[NuvioHub] QR generation failed: %s' % exc, xbmc.LOGWARNING)
        except Exception:
            pass
        return ''


class QRLinkWindow(xbmcgui.WindowDialog):
    """Borderless dialog: QR on the left, code + instructions on the right.

    Uses plain xbmcgui controls so it renders on every skin (no pyxbmct, no
    custom XML).  show() is non-blocking: the caller polls the PIN and calls
    close() when linking completes; BACK/ESC sets `cancelled`.
    """

    def __init__(self, *args, **kwargs):
        self.cancelled = False
        try:
            qr_path = kwargs.get('qr_path') or ''
            code = kwargs.get('code') or ''
        except Exception:
            qr_path, code = '', ''
        w, h = 900, 460
        x = (1280 - w) // 2
        y = (720 - h) // 2
        self.addControl(xbmcgui.ControlImage(x, y, w, h, '', colorDiffuse='DD000000'))
        if qr_path:
            self.addControl(xbmcgui.ControlImage(x + 40, y + 60, 340, 340, qr_path))
        head = xbmcgui.ControlLabel(x + 410, y + 60, w - 450, 40, 'Link Plex',
                                    textColor='FFFFFFFF')
        self.addControl(head)
        body = xbmcgui.ControlTextBox(x + 410, y + 120, w - 450, 280)
        self.addControl(body)
        body.setText(
            tr('Scan the QR code with your phone camera to open the Plex link page.\n\n'
            'Or open: plex.tv/link\n'
            'and enter the code:\n\n'
            '[B]%s[/B]\n\n'
            'Waiting for confirmation… (Back to cancel)') % code)
        self._body = body

    def set_status(self, text):
        try:
            self._body.setText(text)
        except Exception:
            pass

    def onAction(self, action):  # noqa: N802 (Kodi API)
        try:
            if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61467, 61448):
                self.cancelled = True
                self.close()
        except Exception:
            self.cancelled = True
            self.close()
