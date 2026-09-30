# -*- coding: utf-8 -*-
"""v4.6.4 regression tests.

1. WARM-VM INVOCATION STATE — reuselanguageinvoker keeps module globals
   alive between invocations. context.py froze HANDLE/BASE_URL from
   sys.argv at import time, and plugin.py's `from .context import *`
   copied them; a RunPlugin invocation (handle -1) spawning a fresh VM
   poisoned every later folder render that reused it — the empty ".."
   directory + "GetDirectory(plugin://) failed" when entering the Stremio
   sync section. BASE_URL is now a constant derived from the addon id and
   HANDLE is refreshed at the start of every dispatch.

2. THEME REACH — dexhub_home.xml and search_results.xml hardcoded the old
   amber FFFFA500, so switching the theme preset never touched Home or
   Search; both now consume the published accent token. theme_select also
   invalidates the settings cache before republishing (the per-invocation
   snapshot otherwise served the OLD preset to publish_theme).

3. ASSETS — poster corners come from a fixed-size 340x510 alpha mask
   (circle.png's radius stretches with the target and drew ovals), the
   mark-only icon replaces the wordmark icon, and the progress-fill width
   is pushed only after show() (Kodi logged "Non-Existent Control 5110").
"""
import io
import os
import struct
import sys
import unittest
import zlib

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
context = kodi_stub.import_lib_module('context')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
CTX_SRC = io.open(os.path.join(ROOT, 'resources', 'lib', 'context.py'), encoding='utf-8').read()
LOADING_PY = io.open(os.path.join(ROOT, 'resources', 'lib', 'sources_loading.py'), encoding='utf-8').read()
_home_path = os.path.join(ROOT, 'resources', 'skins', 'Default',
                          '1080i', 'dexhub_home.xml')
# v5.4.1: Home renders through Kodi's own skin in the 5.x line;
# the custom window is gone, so this file is optional now.
HOME_XML = (io.open(_home_path, encoding='utf-8').read()
            if os.path.isfile(_home_path) else '')
SEARCH_XML = io.open(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'search_results.xml'), encoding='utf-8').read()
RESULTS_XML = io.open(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'sources_results.xml'), encoding='utf-8').read()


def _png_size(path):
    """stdlib-only IHDR reader (the suite must stay PIL-free)."""
    with open(path, 'rb') as fh:
        head = fh.read(33)
    assert head[:8] == b'\x89PNG\r\n\x1a\n', 'not a PNG'
    return struct.unpack('>II', head[16:24])


def _png_pixels(path):
    """Decode a small RGBA8 PNG with zlib + manual un-filtering."""
    with open(path, 'rb') as fh:
        data = fh.read()
    w, h = _png_size(path)
    idat = b''
    pos = 8
    while pos < len(data):
        length, ctype = struct.unpack('>I4s', data[pos:pos + 8])
        if ctype == b'IDAT':
            idat += data[pos + 8:pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = w * 4
    out = bytearray()
    prev = bytearray(stride)
    p = 0
    for _y in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        for i in range(stride):
            a = line[i - 4] if i >= 4 else 0
            b = prev[i]
            c = prev[i - 4] if i >= 4 else 0
            if f == 1:
                line[i] = (line[i] + a) & 0xFF
            elif f == 2:
                line[i] = (line[i] + b) & 0xFF
            elif f == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        out += line
        prev = line
    return w, h, bytes(out)


class TestWarmVmInvocationState(unittest.TestCase):
    def test_base_url_is_argv_independent_constant(self):
        self.assertNotIn('BASE_URL = sys.argv[0]', CTX_SRC)
        self.assertIn("BASE_URL = 'plugin://%s/'", CTX_SRC)
        self.assertEqual(context.BASE_URL, 'plugin://plugin.video.nuviohub/')
        self.assertTrue(context.build_url(action='x').startswith(
            'plugin://plugin.video.nuviohub/?'))

    def test_refresh_invocation_rereads_argv_handle(self):
        old_argv = list(sys.argv)
        try:
            sys.argv = ['plugin://plugin.video.nuviohub/', '-1', '?action=stremio_login']
            self.assertEqual(context.refresh_invocation(), -1)
            sys.argv = ['plugin://plugin.video.nuviohub/', '27', '']
            self.assertEqual(context.refresh_invocation(), 27)
            self.assertEqual(context.HANDLE, 27)
            sys.argv = ['x']
            self.assertEqual(context.refresh_invocation(), -1)
        finally:
            sys.argv = old_argv
            context.refresh_invocation()

    def test_dispatch_rebinds_plugins_copied_handle(self):
        body = PLUGIN.split('def _reset_invocation_state():', 1)[1]
        body = body.split('\ndef ', 1)[0]
        self.assertIn('global HANDLE', body)
        self.assertIn('refresh_invocation()', body)


class TestThemeReach(unittest.TestCase):
    def test_shipped_skins_consume_the_accent_token(self):
        # v5.4.1: only the two result browsers keep custom XML; whichever
        # of them ships must use the theme token, never a hardcoded amber.
        checked = 0
        for blob, name in ((HOME_XML, 'home'), (SEARCH_XML, 'search')):
            if not blob:
                continue
            checked += 1
            self.assertNotIn('FFFFA500', blob, name)
            self.assertIn('dexhub.theme.accent', blob, name)
        self.assertGreater(checked, 0, 'no themed skin file found')

    def test_theme_select_invalidates_settings_cache_before_publish(self):
        body = PLUGIN.split('def theme_select_action():', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('_sc.invalidate()', body)
        # order: the docstring also mentions publish_theme — anchor on the call
        self.assertLess(body.index('_sc.invalidate()'),
                        body.index('skin_theme.publish_theme('))


class TestAssets(unittest.TestCase):
    def test_poster_mask_shape_and_wiring(self):
        path = os.path.join(ROOT, 'resources', 'media', 'poster_mask.png')
        w, h, px = _png_pixels(path)
        self.assertEqual((w, h), (340, 510))
        self.assertEqual(px[3], 0)                          # corner transparent
        center = ((255 * 340) + 170) * 4
        self.assertEqual(px[center + 3], 255)               # centre opaque
        self.assertIn('poster_mask.png', RESULTS_XML)
        self.assertIn('poster_mask_bottom.png', RESULTS_XML)
        bw, bh = _png_size(os.path.join(ROOT, 'resources', 'media',
                                        'poster_mask_bottom.png'))
        self.assertEqual((bw, bh), (340, 126))

    def test_icon_is_original_nuvio_mark(self):
        self.assertEqual(_png_size(os.path.join(ROOT, 'resources', 'media',
                                                'icon.png')), (1080, 1080))

    def test_progress_width_pushed_only_after_show(self):
        enter = LOADING_PY.split('def __enter__', 1)[1].split('\n    def ', 1)[0]
        self.assertIn('self._win.show()', enter)
        self.assertIn('self._set_progress_width(0)', enter)
        self.assertLess(enter.index('self._win.show()'),
                        enter.index('self._set_progress_width(0)'))
        initial = LOADING_PY.split('def _apply_initial_props', 1)[1].split('\n    def ', 1)[0]
        self.assertNotIn('_set_progress_width', initial)


if __name__ == '__main__':
    unittest.main(verbosity=2)
