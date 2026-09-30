# -*- coding: utf-8 -*-
"""v4.8.0 — the five community badge sets, and the sync sections that never ran.

BADGES: the sets the user asked for are authored against JavaScript regex,
which allows VARIABLE-LENGTH lookbehind. Python's `re` rejects it, so those
rules raised at compile time and were dropped — on the Sterzeck set that
silently cost the DD/AC3, AAC and Opus audio badges. The compiler now
retries without the offending lookbehind (slightly more permissive, never
missing) and logs how many rules were salvaged. All six sets are also
offered as one-tap presets, because typing a gist URL on a TV remote is
its own kind of bug.

SYNC: _sections_for hard-coded 'collections': False for both services, so
the nuvio_sync_collections setting was dead — switching it on changed
nothing. It reads its setting now, and Nuvio defaults to on.
"""
import io
import os
import re
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sb = kodi_stub.import_lib_module('source_browser')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()
SYNC = io.open(os.path.join(ROOT, 'resources', 'lib', 'dexhub', 'nuvio_stremio_sync.py'), encoding='utf-8').read()

# Verbatim shapes from the real sets (Sterzeck rules 'DV.HDR10+' and
# 'ATMOS TRUEHD' both gate on a media file extension, which is why the raw
# blob must carry the filename).
JS_ONLY = (r'(?is)^(?=.*?(?:(?:(?<![a-z0-9])(?:dd(?!p|\+)|(?<!e[-_. ]?)ac[-_. ]?3)'
           r'(?![a-z0-9]))))')
FIXED_OK = r'(?i)(?<![a-z0-9])remux(?![a-z0-9])'


class TestJsRegexSalvage(unittest.TestCase):
    def test_variable_lookbehind_is_salvaged_not_dropped(self):
        rules = [('ga', JS_ONLY, 'http://x/ac3.png')]
        compiled = sb._elite_compile_rules(rules)
        self.assertEqual(len(compiled), 1)
        self.assertTrue(compiled[0][1].search('Movie.2024.AC3.mkv'))

    def test_fixed_width_lookbehind_kept_untouched(self):
        compiled = sb._elite_compile_rules([('gq', FIXED_OK, 'http://x/r.png')])
        self.assertEqual(len(compiled), 1)
        self.assertTrue(compiled[0][1].search('a REMUX b'))
        self.assertFalse(compiled[0][1].search('xremuxy'))

    def test_stripper_removes_only_lookbehind_groups(self):
        out = sb._strip_variable_lookbehind(r'(?<!e[-_. ]?)ac3(?![a-z])')
        self.assertNotIn('(?<!', out)
        self.assertIn('ac3', out)
        self.assertIn('(?![a-z])', out)          # lookahead survives
        # character classes containing parens must not confuse the scanner
        self.assertEqual(sb._strip_variable_lookbehind(r'[(]x[)]'), r'[(]x[)]')

    def test_unusable_pattern_still_dropped_without_raising(self):
        compiled = sb._elite_compile_rules([('g', '((((', 'http://x/a.png'),
                                            ('g2', FIXED_OK, 'http://x/b.png')])
        self.assertEqual(len(compiled), 1)


class TestCommunityPresets(unittest.TestCase):
    def test_all_requested_sets_are_offered(self):
        urls = [e[1] for e in sb.ELITE_BADGE_PRESETS]
        self.assertGreaterEqual(len(urls), 6)
        for needle in ('Sterzeck_badge.json',
                       'transparent-nosvasedis-badges-nuvio',
                       'mono-nosvasedis-badges-nuvio',
                       'solid-nosvasedis-badges-nuvio',
                       '76c519d05f6518f0ed186ba802847c625ba730fa/nosvasedis-badges-nuvio',
                       'mono-bgb-sep-nodv.json'):
            self.assertTrue(any(needle in u for u in urls), needle)

    def test_presets_are_absolute_urls_and_unique(self):
        urls = [e[1] for e in sb.ELITE_BADGE_PRESETS]
        self.assertEqual(len(urls), len(set(urls)))
        for u in urls:
            self.assertTrue(u.startswith('https://'), u)
        names = [e[0] for e in sb.ELITE_BADGE_PRESETS]
        self.assertEqual(len(names), len(set(names)))

    def test_extensionless_urls_supported(self):
        # four of the gist sets have no .json suffix; nothing may require one
        body = SB.split('def _elite_badge_rules():', 1)[1].split('def _elite_rules_disk_path', 1)[0]
        self.assertNotIn(".endswith('.json')", body)

    def test_picker_wired_into_the_badges_action(self):
        body = PLUGIN.split('def badges_url_action():', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('ELITE_BADGE_PRESETS', body)
        self.assertIn("tr('اختيار مجموعة جاهزة')", body)
        self.assertIn('_elite_url_override_write(url)', body)
        # the later branches must still line up after the inserted option
        self.assertIn('choice -= 1', body)


class TestSyncSectionsHonourSettings(unittest.TestCase):
    """v4.8.4: behavioural — 'collections' was hard-coded False, so the
    setting was dead and switching it on changed nothing."""

    def _sections(self, svc, store):
        sync = kodi_stub.import_lib_module('dexhub.nuvio_stremio_sync')
        orig = sync._setting
        try:
            sync._setting = lambda key, default='': store.get(key, default)
            return sync._sections_for(svc)
        finally:
            sync._setting = orig

    def test_collections_toggle_is_live(self):
        on = self._sections('nuvio', {'nuvio_sync_collections': 'true'})
        off = self._sections('nuvio', {'nuvio_sync_collections': 'false'})
        self.assertTrue(on['collections'])
        self.assertFalse(off['collections'])

    def test_nuvio_defaults_on_stremio_off(self):
        self.assertTrue(self._sections('nuvio', {})['collections'])
        self.assertFalse(self._sections('stremio', {})['collections'])

    def test_every_section_is_reported(self):
        sections = self._sections('nuvio', {})
        self.assertEqual(set(sections), {'addons', 'collections', 'progress', 'library'})
        self.assertTrue(all(sections[k] for k in ('addons', 'progress', 'library')))

    def test_settings_default_matches(self):
        import xml.etree.ElementTree as ET
        d = {s.get('id'): s.get('default')
             for s in ET.parse(os.path.join(ROOT, 'resources', 'settings.xml')
                               ).getroot().iter('setting')}
        self.assertEqual(d['nuvio_sync_collections'], 'true')
        self.assertEqual(d['nuvio_sync_addons'], 'true')
        self.assertEqual(d['nuvio_sync_progress'], 'true')


if __name__ == '__main__':
    unittest.main(verbosity=2)
