# -*- coding: utf-8 -*-
"""v5.4.12 — a Home you choose, and an English UI that is actually English.

Three things this release owes the user:

  * Home was a fixed list. Every row now has a switch, defaulting ON, so a
    fresh install looks exactly as before and a crowded Home becomes the
    user's choice rather than something to scroll past. The pattern is
    borrowed from Rivulet, which drives its Home sections from a small
    table of (row, setting) pairs instead of hardcoding them.
  * 21 strings reached the screen in Arabic even with the interface set to
    English, because they were passed to tr() without ever being added to
    the translation table. tr() falls back to its input, so the failure was
    silent - the UI simply looked half-translated.
  * "Source" was doing two jobs in English: an installed Stremio add-on,
    and one playable link for a title. The first sense is now "add-on";
    the second stays "source", because that is what the source picker,
    the switch-source shortcut and the quality filters are about.
"""
import io
import os
import re
import unittest
import xml.etree.ElementTree as ET

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
pl = kodi_stub.import_lib_module('plugin')
live = kodi_stub.import_lib_module('live_settings')
i18n = kodi_stub.import_lib_module('i18n')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SETTINGS = os.path.join(ROOT, 'resources', 'settings.xml')
ARABIC = re.compile(r'[\u0600-\u06FF]')


class TestHomeRowVisibility(unittest.TestCase):
    def _with(self, off):
        """Run a callable with the given settings switched off."""
        orig = live.live_bool
        live.live_bool = lambda key, prop='', default=True: (
            False if key in off else default)
        return orig

    def test_everything_shows_by_default(self):
        for key, _sid in pl._HOME_ROW_SETTINGS:
            self.assertTrue(pl._home_row_visible(key), key)

    def test_an_unknown_row_is_never_hidden(self):
        """A row without a switch must not vanish because of one."""
        self.assertTrue(pl._home_row_visible('something_new'))
        self.assertTrue(pl._home_row_visible(''))
        self.assertTrue(pl._home_row_visible(None))

    def test_switching_a_row_off_hides_only_that_row(self):
        orig = self._with({'home_show_plex'})
        try:
            self.assertFalse(pl._home_row_visible('plex'))
            self.assertTrue(pl._home_row_visible('emby'))
            self.assertTrue(pl._home_row_visible('continue'))
        finally:
            live.live_bool = orig

    def test_buckets_follow_the_same_switches(self):
        orig = self._with({'home_show_movies'})
        try:
            self.assertFalse(pl._home_bucket_visible('movies'))
            self.assertTrue(pl._home_bucket_visible('series'))
        finally:
            live.live_bool = orig

    def test_custom_folders_are_never_hidden_by_a_builtin_toggle(self):
        orig = self._with({'home_show_movies', 'home_show_series'})
        try:
            self.assertTrue(pl._home_bucket_visible('custom:my folder'))
        finally:
            live.live_bool = orig

    def test_a_broken_settings_read_shows_the_row(self):
        """Fail open: a Home row must never disappear because a read threw."""
        orig = live.live_bool
        def boom(*_a, **_k):
            raise RuntimeError('settings unavailable')
        live.live_bool = boom
        try:
            self.assertTrue(pl._home_row_visible('plex'))
        finally:
            live.live_bool = orig

    def test_every_row_is_gated_in_the_renderer(self):
        for key, _sid in pl._HOME_ROW_SETTINGS:
            if key in ('movies', 'series', 'anime', 'live', 'tmdbh'):
                continue          # rendered through the bucket loop
            self.assertIn("_home_row_visible('%s')" % key, PLUGIN, key)
        self.assertIn('_home_bucket_visible(bucket)', PLUGIN)

    def test_no_gate_is_applied_twice(self):
        self.assertEqual(
            re.findall(r"if (_home_row_visible\('\w+'\)):\n\s+if \1:", PLUGIN), [])

    def test_every_switch_is_declared_and_translated(self):
        nodes = {s.get('id'): s for s in ET.parse(SETTINGS).getroot().iter('setting')
                 if s.get('id')}
        pos = {}
        for lang in ('en_gb', 'ar_sa'):
            pos[lang] = io.open(os.path.join(ROOT, 'resources', 'language',
                                             'resource.language.%s' % lang, 'strings.po'),
                                encoding='utf-8').read()
        for _key, sid in pl._HOME_ROW_SETTINGS:
            self.assertIn(sid, nodes, sid)
            self.assertEqual(nodes[sid].get('default'), 'true', sid)
            self.assertNotEqual(nodes[sid].get('visible'), 'false', sid)
            label = nodes[sid].get('label')
            for lang in ('en_gb', 'ar_sa'):
                self.assertIn('msgctxt "#%s"' % label, pos[lang],
                              '%s missing %s translation' % (sid, lang))


class TestEnglishUiIsComplete(unittest.TestCase):
    def test_every_arabic_string_passed_to_tr_has_a_translation(self):
        """tr() returns its input when a key is missing, so an untranslated
        string reaches the screen in Arabic with no error anywhere."""
        missing = set()
        files = [os.path.join(dp, f)
                 for dp, _dn, fn in os.walk(os.path.join(ROOT, 'resources', 'lib'))
                 for f in fn if f.endswith('.py')]
        files.append(os.path.join(ROOT, 'service.py'))
        for path in files:
            src = io.open(path, encoding='utf-8').read()
            for m in re.finditer(r"tr\('((?:[^'\\]|\\.)*)'\)", src):
                text = m.group(1).replace('\\n', '\n')
                if ARABIC.search(text) and text not in i18n.STRINGS:
                    missing.add(text[:60])
        self.assertEqual(sorted(missing), [],
                         'untranslated strings reach the UI: %s' % sorted(missing)[:6])

    def test_translations_are_not_themselves_arabic(self):
        bad = [k for k, v in i18n.STRINGS.items()
               if isinstance(v, str) and ARABIC.search(v)]
        self.assertEqual(bad, [], 'English values still contain Arabic: %s' % bad[:5])


class TestAddonWording(unittest.TestCase):
    """"Source" meant two things; only the add-on sense was renamed."""

    def test_installed_addons_are_called_add_ons(self):
        for key, expected in (('المصادر', 'Add-ons'),
                              ('تعديل المصدر', 'Edit add-on'),
                              ('إضافة مصدر Stremio', 'Add a Stremio add-on')):
            self.assertEqual(i18n.STRINGS.get(key), expected, key)

    def test_the_stream_sense_still_says_source(self):
        """The picker, the switch shortcut and quality filters are about a
        playable link, not an installed add-on."""
        keep = [v for v in i18n.STRINGS.values()
                if isinstance(v, str) and re.search(r'(?i)\bsource', v)]
        self.assertTrue(keep, 'the stream sense of "source" was renamed away')
        joined = ' | '.join(keep).lower()
        self.assertIn('switch source', joined)

    def test_no_english_string_mixes_both_senses(self):
        for value in i18n.STRINGS.values():
            if not isinstance(value, str):
                continue
            if re.search(r'(?i)\badd-on', value) and re.search(r'(?i)\bsources?\b', value):
                self.assertNotRegex(value, r'(?i)add-on sources')


if __name__ == '__main__':
    unittest.main(verbosity=2)
