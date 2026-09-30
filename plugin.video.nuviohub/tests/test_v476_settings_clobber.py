# -*- coding: utf-8 -*-
"""v4.7.6 — "I paste a new badges URL and it goes back to the previous one."

Ruled out first, with evidence: the user's set
(djgenesis/badges/gold_badges_complete.json) parses to 63 rules and renders
8 badges through the live code, so neither the fetch nor the parser was at
fault. Nothing in the addon writes elite_badges_json_url either.

The value was collateral damage. Kodi persists an addon's settings by
writing the WHOLE tree from whichever instance the write is made on. The
shared settings proxy is created once per process and, under
reuselanguageinvoker, lives for hours — so writing ONE unrelated key
through it re-saves a snapshot from before the user's edit and reverts it.

The write that did it arrived in 4.7.0: the corrective
'470-release-defaults' migration runs at plugin module load, i.e. the very
next time the user opens NuvioHub after changing a setting. Before 4.7.0
existing installs were already stamped and the function returned without
writing — which is exactly why older versions applied a new URL
immediately.

Fixes pinned here:
  1. every write goes through a FRESH xbmcaddon.Addon();
  2. the migration reads its revision from a fresh instance, writes
     clean_catalog_view only when it is actually wrong, and never writes
     while the addon settings dialog is on screen.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sc = kodi_stub.import_lib_module('settings_cache')
sb = kodi_stub.import_lib_module('source_browser')
import xbmcaddon  # noqa: E402  (populated by kodi_stub)

CTX = io.open(os.path.join(ROOT, 'resources', 'lib', 'context.py'), encoding='utf-8').read()
SC_SRC = io.open(os.path.join(ROOT, 'resources', 'lib', 'settings_cache.py'), encoding='utf-8').read()

GOLD = ('{"groups": [{"id": "g-res", "name": "Resolution"}],'
        ' "filters": [{"id": "uhd", "groupId": "g-res", "name": "4K",'
        ' "isEnabled": true,'
        ' "imageURL": "https://raw.githubusercontent.com/djgenesis/stream/refs/heads/main/badges/uhd.png",'
        ' "pattern": "(?i)\\\\b(?:4k|2160[pi]?|uhd)\\\\b", "type": "filter"},'
        ' {"id": "remux", "groupId": "g-src", "name": "Remux", "isEnabled": true,'
        ' "imageURL": "https://raw.githubusercontent.com/djgenesis/stream/refs/heads/main/badges/remux.png",'
        ' "pattern": "(?i)\\\\bremux\\\\b", "type": "filter"}]}')


class TestWritesUseAFreshInstance(unittest.TestCase):
    """The revert mechanism itself."""

    def test_set_setting_creates_a_new_addon_object(self):
        made = []

        class FakeAddon(object):
            store = {}

            def __init__(self, addon_id='plugin.video.nuviohub'):
                made.append(self)

            def getSetting(self, sid):
                return FakeAddon.store.get(sid, '')

            def setSetting(self, sid, value):
                FakeAddon.store[sid] = value

            def setSettingBool(self, sid, value):
                FakeAddon.store[sid] = bool(value)

        original = xbmcaddon.Addon
        xbmcaddon.Addon = FakeAddon
        try:
            stale = FakeAddon()
            proxy = sc.CachedAddon(stale)
            proxy._cache['x'] = 'cached'
            count_before = len(made)
            proxy.setSetting('badges_url', 'https://new/set.json')
            self.assertGreater(len(made), count_before)      # fresh instance
            self.assertEqual(FakeAddon.store['badges_url'], 'https://new/set.json')
            self.assertEqual(proxy._cache, {})               # reads re-fetched
            count_before = len(made)
            proxy.setSettingBool('flag', True)
            self.assertGreater(len(made), count_before)
        finally:
            xbmcaddon.Addon = original

    def test_source_documents_the_whole_tree_rewrite(self):
        self.assertIn('def _write_addon(self):', SC_SRC)
        self.assertIn('WHOLE tree', SC_SRC)


class TestMigrationCannotClobber(unittest.TestCase):
    def test_revision_read_from_a_fresh_instance(self):
        body = CTX.split('def apply_clean_defaults_once():', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("_fresh = xbmcaddon.Addon('plugin.video.nuviohub')", body)
        self.assertIn("_fresh.getSetting('dexhub_defaults_rev')", body)

    def test_never_writes_while_the_settings_dialog_is_open(self):
        body = CTX.split('def apply_clean_defaults_once():', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("Window.IsVisible(addonsettings)", body)
        # the guard must sit BEFORE any write
        self.assertLess(body.index('Window.IsVisible(addonsettings)'),
                        body.index('setSetting'))

    def test_corrective_branch_writes_only_when_actually_wrong(self):
        body = CTX.split("if rev == '139-clean-defaults':", 1)[1][:900]
        self.assertIn("_fresh.getSetting('clean_catalog_view')", body)
        self.assertIn("!= 'false'", body)

    def test_permanent_constraint_still_holds(self):
        self.assertIn("'clean_catalog_view': 'false',", CTX)


class TestUsersGoldSetWorks(unittest.TestCase):
    """Regression proof that the reported set is not the problem."""

    def test_parses_and_renders(self):
        rules = sb._elite_rules_from_json_blob(GOLD)
        self.assertEqual(len(rules), 2)
        orig_rules, orig_on = sb._elite_badge_rules, sb._elite_badges_enabled
        try:
            sb._elite_badge_rules = lambda: rules
            sb._elite_badges_enabled = lambda: True
            images = sb._elite_badge_images(
                {'badge_blob_raw': 'MOVIE 2026 2160p WEB-DL REMUX', 'name': 'x'})
        finally:
            sb._elite_badge_rules, sb._elite_badges_enabled = orig_rules, orig_on
        self.assertEqual(len(images), 2)
        self.assertTrue(all('djgenesis' in u for u in images))


if __name__ == '__main__':
    unittest.main(verbosity=2)
