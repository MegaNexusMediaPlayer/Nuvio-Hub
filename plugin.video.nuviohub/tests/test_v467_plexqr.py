# -*- coding: utf-8 -*-
"""v4.6.7 — the "static Plex QR" report, root-caused and pinned.

Two independent defects made the barcode effectively frozen:

1. STALE TEXTURE — qr_png() wrote every QR to ONE fixed path
   (plex_link_qr.png), shared by the Plex link AND the pairing QR. Kodi's
   texture cache is keyed by path, so the FIRST QR ever rendered on the
   box kept displaying forever — an expired PIN from some earlier attempt.
   The filename is now derived from the encoded payload and older QR
   files (including the legacy fixed name) are purged.

2. DEAD-END TARGET — the QR encoded plex.tv/link/?pin=…, and that page
   ignores the query string entirely, so scanning only ever opened the
   generic type-a-code page. The QR now encodes the DIRECT auth deep link
   whose contract is verified against python-plexapi
   (pkkid/python-plexapi → MyPlexPinLogin.oauthUrl): app.plex.tv/auth/#!?
   with clientID + code + the full context[device][*] set, built from the
   SAME headers used to create the PIN so the token lands on our pin.
"""
import io
import os
import shutil
import struct
import tempfile
import unittest
from urllib.parse import parse_qsl

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
plex_qr = kodi_stub.import_lib_module('plex_qr')
plex_client = kodi_stub.import_lib_module('plex_client')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
QR_SRC = io.open(os.path.join(ROOT, 'resources', 'lib', 'plex_qr.py'), encoding='utf-8').read()


class _TempProfile:
    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix='nuviohub_qr_')
        self._orig = plex_qr._profile_dir
        plex_qr._profile_dir = lambda: self.dir
        return self.dir

    def __exit__(self, *exc):
        plex_qr._profile_dir = self._orig
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


def _png_dims(path):
    with open(path, 'rb') as fh:
        head = fh.read(33)
    assert head[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', head[16:24])


class TestQrStaleness(unittest.TestCase):
    def test_unique_path_per_payload_and_deterministic(self):
        with _TempProfile():
            p1 = plex_qr.qr_png('https://app.plex.tv/auth/#!?code=AAAA')
            self.assertTrue(p1 and os.path.isfile(p1))
            p2 = plex_qr.qr_png('https://app.plex.tv/auth/#!?code=BBBB')
            self.assertNotEqual(p1, p2)                 # new code → new path
            p3 = plex_qr.qr_png('https://app.plex.tv/auth/#!?code=BBBB')
            self.assertEqual(p2, p3)                    # same payload → same path
            w, h = _png_dims(p3)
            self.assertEqual(w, h)
            self.assertGreater(w, 100)

    def test_stale_files_purged_including_legacy_fixed_name(self):
        with _TempProfile() as prof:
            legacy = os.path.join(prof, 'plex_link_qr.png')
            with open(legacy, 'wb') as fh:
                fh.write(b'\x89PNG\r\n\x1a\nstale')
            p1 = plex_qr.qr_png('payload-one')
            self.assertFalse(os.path.exists(legacy))    # legacy purged
            p2 = plex_qr.qr_png('payload-two')
            self.assertFalse(os.path.exists(p1))        # older code purged
            leftovers = [f for f in os.listdir(prof) if f.startswith('plex_link_qr')]
            self.assertEqual(leftovers, [os.path.basename(p2)])  # exactly one

    def test_no_fixed_single_filename_remains(self):
        self.assertNotIn("'plex_link_qr.png'", QR_SRC)
        self.assertIn('plex_link_qr_%s.png', QR_SRC)


class TestAuthDeepLink(unittest.TestCase):
    def test_url_shape_matches_plexapi_contract(self):
        url = plex_client.auth_link_url('ABCD')
        self.assertTrue(url.startswith('https://app.plex.tv/auth/#!?'))
        params = dict(parse_qsl(url.split('#!?', 1)[1]))
        self.assertEqual(params.get('code'), 'ABCD')
        self.assertEqual(params.get('clientID'), plex_client.client_identifier())
        for key in ('context[device][product]', 'context[device][version]',
                    'context[device][platform]', 'context[device][platformVersion]',
                    'context[device][device]', 'context[device][deviceName]'):
            self.assertIn(key, params, key)
        self.assertEqual(params['context[device][product]'], 'Nuvio Hub')

    def test_client_id_matches_pin_creation_headers(self):
        # the SAME identifier must sign the pin request and the auth URL,
        # or the authorised token never lands on our pin
        self.assertEqual(plex_client.auth_link_url('X'),
                         plex_client.auth_link_url('X'))
        self.assertEqual(plex_client._headers()['X-Plex-Client-Identifier'],
                         plex_client.client_identifier())

    def test_login_uses_dual_pins_weak_typed_strong_qr(self):
        """v4.6.8: the 4.6.7 deep link was fed the weak 4-char pin —
        app.plex.tv only accepts STRONG pins (plexapi gates oauthUrl behind
        them), so linking broke. The weak pin is back to the early-versions
        typed flow verbatim; a separate strong pin drives the QR."""
        body = PLUGIN.split("Plex PIN created id=", 1)[1][:3000]
        self.assertIn('request_pin(strong=True)', body)
        self.assertIn("auth_link_url(pin_qr.get('code')", body)
        # strong-pin failure must degrade to the early plex.tv/link QR
        self.assertIn('scan_url = link_url', body)
        # never feed the deep link the weak code again
        self.assertNotIn('auth_link_url(code)', body)

    def test_login_polls_both_pins_alternately(self):
        body = PLUGIN.split("Plex PIN created id=", 1)[1][:6000]
        self.assertIn('pin_targets = [pin] + ([pin_qr] if pin_qr else [])', body)
        self.assertIn('pin_targets[tick % len(pin_targets)]', body)
        self.assertIn("poll_pin(target.get('id')", body)

    def test_request_pin_sends_the_strong_flag(self):
        captured = []
        orig_request, orig_json = plex_client._request, plex_client._json
        try:
            plex_client._request = lambda *a, **k: captured.append(k) or b'{}'
            plex_client._json = lambda _v: {'id': '77', 'code': 'LONGSTRONGCODE'}
            strong = plex_client.request_pin(strong=True)
            weak_kwargs_idx = len(captured)
            plex_client._json = lambda _v: {'id': '78', 'code': 'abcd'}
            weak = plex_client.request_pin()
        finally:
            plex_client._request, plex_client._json = orig_request, orig_json
        self.assertIn('strong=true', captured[0].get('data', ''))
        self.assertIn('strong=false', captured[weak_kwargs_idx].get('data', ''))
        self.assertTrue(strong.get('strong'))
        self.assertEqual(strong.get('code'), 'LONGSTRONGCODE')   # case preserved
        self.assertFalse(weak.get('strong'))
        self.assertEqual(weak.get('code'), 'ABCD')               # typed = upper

    def test_verification_provenance_documented(self):
        src = io.open(os.path.join(ROOT, 'resources', 'lib', 'plex_client.py'),
                      encoding='utf-8').read()
        self.assertIn('python-plexapi', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
