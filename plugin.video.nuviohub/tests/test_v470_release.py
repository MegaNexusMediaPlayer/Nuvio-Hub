# -*- coding: utf-8 -*-
"""v4.7.0 release-defaults audit.

The flagship features must work out of the box, and two PERMANENT
constraints are pinned as guards:

  * clean_catalog_view MUST default to 'false' everywhere — 'true' broke
    the "+ Add to home" workflow (the v3.9.82 regression). The audit found
    it had regressed to 'true' in settings.xml AND in two code fallbacks
    AND was force-WRITTEN into existing installs by the one-time
    '139-clean-defaults' migration; a corrective one-time migration now
    resets poisoned installs.

  * NuvioHub must NEVER bind itself as TMDb Helper's default player (the
    v3.9.63 incident that broke Arctic Fuse 3 search). The NuvioHub-side
    click-mode redirect is fine; writing into TMDb Helper's players
    machinery is not.
"""
import io
import os
import re
import unittest
import xml.etree.ElementTree as ET

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
SETTINGS = ET.parse(os.path.join(ROOT, 'resources', 'settings.xml'))
DEFAULTS = {s.get('id'): s.get('default')
            for s in SETTINGS.getroot().iter('setting') if s.get('id')}
PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
CTX = io.open(os.path.join(ROOT, 'resources', 'lib', 'context.py'), encoding='utf-8').read()
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()
ADDON_XML = io.open(os.path.join(ROOT, 'addon.xml'), encoding='utf-8').read()


class TestReleaseDefaults(unittest.TestCase):
    def test_badges_on_by_default_both_sides(self):
        self.assertEqual(DEFAULTS.get('elite_badges_enabled'), 'true')
        body = SB.split('def _elite_badges_enabled():', 1)[1].split('\ndef ', 1)[0]
        # v5.4.4: one shared reader with one default, instead of three copies
        self.assertIn('live_bool(', body)
        self.assertIn('default=True', body)

    def test_cinematic_search_is_default(self):
        # lvalues order: 30877 = NuvioHub cinematic, 30878 = Classic
        self.assertEqual(DEFAULTS.get('search_style'), '0')

    def test_deliberate_defaults_unchanged(self):
        self.assertEqual(DEFAULTS.get('theme_preset'), '1')       # Dex Crimson (4.7.1)
        self.assertEqual(DEFAULTS.get('home_style'), '1')         # fork: rounded-poster home
        self.assertEqual(DEFAULTS.get('simkl_mark_watched'), 'true')


class TestPermanentCleanCatalogGuard(unittest.TestCase):
    """clean_catalog_view = 'false' is a PERMANENT constraint."""

    def test_settings_xml_default_false(self):
        self.assertEqual(DEFAULTS.get('clean_catalog_view'), 'false')

    def test_every_code_fallback_is_false(self):
        for blob, name in ((PLUGIN, 'plugin'), (CTX, 'context'), (SB, 'source_browser')):
            for m in re.finditer(
                    r"getSetting\('clean_catalog_view'\)\s*or\s*'(\w+)'", blob):
                self.assertEqual(m.group(1), 'false', name)
        self.assertIn("'clean_catalog_view': 'false',", CTX)
        self.assertNotIn("'clean_catalog_view': 'true'", CTX)

    def test_corrective_migration_resets_poisoned_installs(self):
        # the 139 migration WROTE 'true' into existing installs — a one-time
        # corrective revision must reset them and re-stamp
        self.assertIn("if rev == '470-release-defaults':", CTX)
        seg = CTX.split("if rev == '139-clean-defaults':", 1)[1][:900]
        self.assertIn("ADDON.setSetting('clean_catalog_view', 'false')", seg)
        self.assertIn("'470-release-defaults'", seg)


class TestNoDefaultPlayerBinding(unittest.TestCase):
    """NuvioHub must never write itself into TMDb Helper's players system."""

    def test_no_players_dir_writes_or_make_default(self):
        blob = PLUGIN + CTX
        for pattern in (
                r'themoviedb\.helper[^\n]*players',   # writing into TMDbH players dir
                r'players\.select',
                r'make_?default_?player',
                r'set_?default_?player'):
            self.assertIsNone(re.search(pattern, blob, re.I), pattern)


class TestSingleVersionNews(unittest.TestCase):
    def test_news_contains_only_the_latest_release(self):
        news = ADDON_XML.split('<news>', 1)[1].split('</news>', 1)[0]
        markers = re.findall(r'^v\d+\.\d+\.\d+', news, re.M)
        self.assertEqual(markers, ['v5.4.12'])
        self.assertLess(len(news), 2600)          # a summary, not an archive


if __name__ == '__main__':
    unittest.main(verbosity=2)
