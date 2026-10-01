# -*- coding: utf-8 -*-
"""v4.7.8 — two findings straight out of the user's kodi.log.

1. PLAYBACK FAILURE was self-inflicted. The log pairs

       Error resolving item ... cw_resume
       Playlist Player: skipping unplayable item: 0, path [plugin://...]

   The second line is the damage, and it came from the resolve-abort added
   in 4.7.2 and extended in 4.7.5: calling setResolvedUrl(False) to silence
   a cosmetic log line tells Kodi the item is UNPLAYABLE, so the Playlist
   Player skips it. Both aborts are reverted — the handoff owns playback.

2. THE BADGES URL never reached the addon on this device even after 4.7.7
   read the profile settings.xml directly (the log still shows the default
   preset URL). Instead of guessing at yet another Kodi settings layer,
   NuvioHub now owns the value: an addon-written file that the loader reads
   first, set from a menu entry that reports the result immediately. The
   log line also names which layer answered.
"""
import io
import os
import shutil
import tempfile
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sb = kodi_stub.import_lib_module('source_browser')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()
I18N = io.open(os.path.join(ROOT, 'resources', 'lib', 'i18n.py'), encoding='utf-8').read()


class _Profile(object):
    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix='nuviohub_ov_')
        self._orig = sb.ADDON.getAddonInfo
        sb.ADDON.getAddonInfo = lambda key: (self.dir if key == 'profile'
                                             else self._orig(key))
        sb._SETTINGS_FILE_MEMO.update({'sig': None, 'values': {}})
        return self.dir

    def __exit__(self, *exc):
        sb.ADDON.getAddonInfo = self._orig
        sb._SETTINGS_FILE_MEMO.update({'sig': None, 'values': {}})
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


class TestAddonOwnedUrl(unittest.TestCase):
    URL = ('https://raw.githubusercontent.com/djgenesis/badges/'
           'refs/heads/main/gold_badges_complete.json')

    def test_written_url_wins_and_survives_a_reread(self):
        with _Profile():
            self.assertIsNone(sb._elite_url_override_read())
            self.assertTrue(sb._elite_url_override_write(self.URL))
            self.assertEqual(sb._elite_badge_setting_url(), self.URL)
            self.assertEqual(sb._elite_url_override_read(), self.URL)

    def test_empty_file_means_builtin_not_unset(self):
        with _Profile():
            sb._elite_url_override_write('')
            self.assertEqual(sb._elite_badge_setting_url(), '')
            self.assertIsNotNone(sb._elite_url_override_read())

    def test_none_clears_back_to_the_kodi_setting(self):
        with _Profile():
            sb._elite_url_override_write(self.URL)
            sb._elite_url_override_write(None)
            self.assertIsNone(sb._elite_url_override_read())

    def test_write_drops_cached_rules_and_settings_memo(self):
        with _Profile():
            sb._ELITE_BADGE_RULE_CACHE.update({'url': 'x', 'rules': [('a', 'b', 'c')]})
            sb._SETTINGS_FILE_MEMO.update({'sig': 'stale', 'values': {'k': 'v'}})
            sb._elite_url_override_write(self.URL)
            self.assertEqual(sb._ELITE_BADGE_RULE_CACHE, {})
            self.assertIsNone(sb._SETTINGS_FILE_MEMO['sig'])

    def test_provenance_names_the_answering_layer(self):
        with _Profile():
            self.assertEqual(sb._elite_url_provenance(), 'getSetting')
            sb._elite_url_override_write(self.URL)
            self.assertEqual(sb._elite_url_provenance(), 'nuviohub-file')
        self.assertIn('via=%s', SB)

    def test_override_is_checked_before_every_other_layer(self):
        body = SB.split('def _elite_badge_setting_url():', 1)[1].split('\ndef ', 1)[0]
        self.assertLess(body.index('_elite_url_override_read()'),
                        body.index('_settings_file_value('))


class TestBadgesFrontDoor(unittest.TestCase):
    def test_action_router_and_menu_entry(self):
        self.assertIn('def badges_url_action():', PLUGIN)
        self.assertIn("if action == 'badges_url':", PLUGIN)
        self.assertIn("build_url(action='badges_url')", PLUGIN)

    def test_action_offers_set_builtin_and_status(self):
        body = PLUGIN.split('def badges_url_action():', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("tr('تعيين رابط JSON للشارات')", body)
        self.assertIn("tr('استخدام المجموعة المدمجة')", body)
        self.assertIn("tr('عرض الحالة الحالية')", body)
        self.assertIn('_elite_url_override_write(', body)
        self.assertIn('_elite_badge_rules()', body)          # reports the outcome
        self.assertIn('_elite_url_provenance()', body)

    def test_new_strings_translated_once(self):
        for key in ("'شارات الجودة'", "'رابط JSON للشارات'",
                    "'تم التبديل إلى المجموعة المدمجة'", "'تعذر حفظ الرابط'"):
            self.assertEqual(I18N.count(key), 1, key)


class TestResolveAbortsReverted(unittest.TestCase):
    """The playlist-skip regression must not come back."""

    def test_no_abort_at_either_handoff(self):
        for marker in ('v4.7.8: do NOT report a failed resolve here',
                       'v4.7.8: reverted the 4.7.5 resolve-abort here'):
            self.assertIn(marker, PLUGIN)
            seg = PLUGIN.split(marker, 1)[1][:600]
            self.assertNotIn('setResolvedUrl(HANDLE, False', seg)

    def test_reason_documented_for_the_next_reader(self):
        self.assertIn('skipping unplayable item', PLUGIN)


if __name__ == '__main__':
    unittest.main(verbosity=2)
