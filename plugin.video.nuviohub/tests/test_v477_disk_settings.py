# -*- coding: utf-8 -*-
"""v4.7.7 — read the badges settings from the file Kodi actually wrote.

4.0.2 (which the user confirms applied a new URL immediately) turned out
to read the setting exactly the way current code does, with the same
reuselanguageinvoker=true and the same settings definition — so the read
API was never the difference. Rather than keep chasing which in-memory
copy went stale (the reused interpreter's, our own read proxy's, or the
service's published one), the URL is now taken from the profile's
settings.xml: the file Kodi rewrites the instant the dialog is confirmed,
and the one source that cannot lag. The previous routes remain as
fallbacks for the case where the file cannot be read.

Also here: badge patterns are compiled once per rules load instead of on
every row (63 rules x hundreds of rows per screen).
"""
import io
import os
import shutil
import tempfile
import time
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sb = kodi_stub.import_lib_module('source_browser')
# v5.4.4: the settings-file reader moved to live_settings.py; the
# profile it consults is that module's ADDON, not source_browser's.
live = kodi_stub.import_lib_module('live_settings')
import xbmcgui  # noqa: E402

SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()

KODI19_FILE = ('<settings version="2">'
               '<setting id="elite_badges_json_url">https://disk/gold.json</setting>'
               '<setting id="elite_badges_enabled">false</setting>'
               '</settings>')
LEGACY_FILE = ('<settings>'
               '<setting id="elite_badges_json_url" value="https://legacy/set.json" />'
               '</settings>')


class _Profile(object):
    """Point the addon profile at a temp dir holding a real settings.xml."""

    def __init__(self, content):
        self.content = content

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix='nuviohub_prof_')
        with io.open(os.path.join(self.dir, 'settings.xml'), 'w', encoding='utf-8') as fh:
            fh.write(self.content)
        self._orig = live.ADDON.getAddonInfo
        live.ADDON.getAddonInfo = lambda key: (self.dir if key == 'profile'
                                               else self._orig(key))
        live._SETTINGS_FILE_MEMO.update({'sig': None, 'values': {}})
        return self.dir

    def __exit__(self, *exc):
        live.ADDON.getAddonInfo = self._orig
        live._SETTINGS_FILE_MEMO.update({'sig': None, 'values': {}})
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


class TestDiskTruthRead(unittest.TestCase):
    def setUp(self):
        xbmcgui.Window(10000).clearProperty('nuviohub.badges.url')
        xbmcgui.Window(10000).clearProperty('nuviohub.badges.enabled')

    tearDown = setUp

    def test_url_comes_from_the_settings_file(self):
        with _Profile(KODI19_FILE):
            self.assertEqual(sb._elite_badge_setting_url(), 'https://disk/gold.json')

    def test_file_beats_a_stale_published_property(self):
        xbmcgui.Window(10000).setProperty('nuviohub.badges.url', 'https://STALE/old.json')
        with _Profile(KODI19_FILE):
            self.assertEqual(sb._elite_badge_setting_url(), 'https://disk/gold.json')

    def test_legacy_value_attribute_supported(self):
        with _Profile(LEGACY_FILE):
            self.assertEqual(sb._elite_badge_setting_url(), 'https://legacy/set.json')

    def test_toggle_read_from_the_file_too(self):
        with _Profile(KODI19_FILE):
            self.assertFalse(sb._elite_badges_enabled())

    def test_edit_is_picked_up_without_restart(self):
        with _Profile(KODI19_FILE) as prof:
            self.assertEqual(sb._elite_badge_setting_url(), 'https://disk/gold.json')
            time.sleep(0.01)
            with io.open(os.path.join(prof, 'settings.xml'), 'w', encoding='utf-8') as fh:
                fh.write(KODI19_FILE.replace('https://disk/gold.json',
                                             'https://disk/second.json'))
            self.assertEqual(sb._elite_badge_setting_url(), 'https://disk/second.json')

    def test_missing_file_falls_back_not_raises(self):
        orig = live.ADDON.getAddonInfo
        live.ADDON.getAddonInfo = lambda key: ('/nonexistent-nuviohub-profile'
                                               if key == 'profile' else orig(key))
        live._SETTINGS_FILE_MEMO.update({'sig': None, 'values': {}})
        try:
            self.assertIsNone(live._settings_file_value('elite_badges_json_url'))
            self.assertIsInstance(sb._elite_badge_setting_url(), str)
        finally:
            live.ADDON.getAddonInfo = orig
            live._SETTINGS_FILE_MEMO.update({'sig': None, 'values': {}})

    def test_memoized_on_file_signature(self):
        with _Profile(KODI19_FILE):
            sb._elite_badge_setting_url()
            first = dict(live._SETTINGS_FILE_MEMO['values'])
            sb._elite_badge_setting_url()
            self.assertEqual(live._SETTINGS_FILE_MEMO['values'], first)
            self.assertIsNotNone(live._SETTINGS_FILE_MEMO['sig'])


class TestPatternPrecompile(unittest.TestCase):
    RULES = [('g', r'(?i)\bremux\b', 'http://x/r.png'),
             ('g2', r'(?i)\b2160p\b', 'http://x/4k.png')]

    def test_rules_are_compiled_once(self):
        compiled = sb._elite_compile_rules(self.RULES)
        self.assertEqual(len(compiled), 2)
        for _group, pattern, _image in compiled:
            self.assertTrue(hasattr(pattern, 'search'))

    def test_uncompilable_pattern_dropped_not_raised(self):
        compiled = sb._elite_compile_rules([('g', '((((', 'http://x/a.png')] + self.RULES)
        self.assertEqual(len(compiled), 2)

    def test_compiled_rules_still_match(self):
        orig_r, orig_e = sb._elite_badge_rules, sb._elite_badges_enabled
        try:
            sb._elite_badge_rules = lambda: sb._elite_compile_rules(self.RULES)
            sb._elite_badges_enabled = lambda: True
            images = sb._elite_badge_images({'badge_blob_raw': 'X 2160p REMUX'})
        finally:
            sb._elite_badge_rules, sb._elite_badges_enabled = orig_r, orig_e
        self.assertEqual(len(images), 2)

    def test_every_load_path_compiles(self):
        body = SB.split('def _elite_badge_rules():', 1)[1].split('def _elite_rules_disk_path', 1)[0]
        self.assertIn('_elite_compile_rules(rules)', body)
        disk = SB.split('def _elite_rules_from_disk(url):', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('_elite_compile_rules(', disk)
        # the builtin table ships pre-compiled already
        self.assertIn('_ELITE_COMPILED_BADGE_RULES = tuple(', SB)


if __name__ == '__main__':
    unittest.main(verbosity=2)
