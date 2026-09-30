# -*- coding: utf-8 -*-
"""v4.1.0 wiring tests — guard the silent-failure bug classes on file text:

  * every new action is registered in the dispatcher (past bug: menu rows
    whose actions were never dispatched did nothing),
  * every settings label id exists in BOTH language PO files,
  * the skin exposes the new listitem properties in both layouts,
  * source_browser copies the new properties onto listitems,
  * the Simkl reporter is actually registered in companion.get_reporter.
"""
import io
import os
import re
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
BROWSER = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()
COMPANION = io.open(os.path.join(ROOT, 'resources', 'lib', 'companion.py'), encoding='utf-8').read()
SETTINGS = io.open(os.path.join(ROOT, 'resources', 'settings.xml'), encoding='utf-8').read()
SKIN = io.open(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'sources_results.xml'), encoding='utf-8').read()
PO_EN = io.open(os.path.join(ROOT, 'resources', 'language', 'resource.language.en_gb', 'strings.po'), encoding='utf-8').read()
PO_AR = io.open(os.path.join(ROOT, 'resources', 'language', 'resource.language.ar_sa', 'strings.po'), encoding='utf-8').read()

NEW_ACTIONS = (
    'simkl_menu', 'simkl_auth', 'simkl_logout', 'simkl_import',
    'simkl_lists_menu', 'simkl_list_browse',
    'mdblist_menu', 'mdblist_set_key', 'mdblist_my_lists',
    'mdblist_watchlist_browse', 'mdblist_list_browse_id',
)


class TestDispatcherRegistration(unittest.TestCase):
    def test_every_new_action_dispatched(self):
        for action in NEW_ACTIONS:
            pattern = "if action == '%s':" % action
            self.assertIn(pattern, PLUGIN, 'action %r built in a menu but never dispatched' % action)

    def test_every_new_action_has_a_handler_def(self):
        for action in NEW_ACTIONS:
            self.assertRegex(PLUGIN, r'\ndef %s\(' % re.escape(action),
                             'no handler function for %r' % action)

    def test_menus_reference_only_registered_actions(self):
        built = set(re.findall(r"build_url\(action='([a-z0-9_]+)'", PLUGIN))
        dispatched = set(re.findall(r"if action == '([a-z0-9_]+)'", PLUGIN))
        missing = sorted(a for a in built if a.startswith(('simkl_', 'mdblist_')) and a not in dispatched)
        self.assertEqual(missing, [], 'menu rows point at undispatched actions: %s' % missing)


class TestSettingsAndTranslations(unittest.TestCase):
    def test_simkl_settings_declared(self):
        for sid in ('simkl_client_id', 'enable_simkl', 'simkl_mark_watched', 'simkl_watched_threshold'):
            self.assertIn('id="%s"' % sid, SETTINGS)

    def test_settings_labels_exist_in_both_po_files(self):
        labels = re.findall(r'label="(308[0-9]{2})"', SETTINGS)
        new_labels = sorted({l for l in labels if 30840 <= int(l) <= 30859})
        self.assertTrue(new_labels, 'expected v4.1.0 settings labels in the 3084x range')
        for label in new_labels:
            self.assertIn('msgctxt "#%s"' % label, PO_EN, '#%s missing from en_gb' % label)
            self.assertIn('msgctxt "#%s"' % label, PO_AR, '#%s missing from ar_sa' % label)

    def test_settings_actions_point_at_real_dispatch(self):
        for action in re.findall(r'action=simkl_([a-z_]+)\)', SETTINGS):
            self.assertIn("if action == 'simkl_%s':" % action, PLUGIN)
        self.assertIn('action=mdblist_menu', SETTINGS)


class TestSkinAndBrowserProps(unittest.TestCase):
    def test_type_chip_in_both_layouts(self):
        self.assertEqual(SKIN.count('ListItem.Property(source_type_label)'), 4,
                         'label must appear in itemlayout+focusedlayout (visible + label each)')
        # v4.6.0: the $INFO[ListItem.Property(source_type_color)] colordiffuse
        # binding was the white-chip bug (Kodi 22 resolves it without a
        # listitem context → raw white texture). The chip colour is now six
        # static variants per layout switched on the RAW type_key.
        self.assertNotIn('ListItem.Property(source_type_color)', SKIN)
        self.assertEqual(SKIN.count('String.IsEqual(ListItem.Property(type_key)'), 12)

    def test_browser_copies_new_props(self):
        self.assertIn("'source_type', 'source_type_label', 'source_type_color'", BROWSER)

    def test_type_filter_group_wired(self):
        self.assertIn('_row_type_filter', BROWSER)
        self.assertIn("startswith('T:')", BROWSER)
        self.assertIn("tr('TYPE • %s')", BROWSER)

    def test_row_builder_attaches_fields(self):
        self.assertIn("'source_type': _stype,", PLUGIN)
        self.assertIn("'source_type_label': _stype_label,", PLUGIN)
        self.assertIn("'source_type_color': _stype_color,", PLUGIN)


class TestCompanionReporter(unittest.TestCase):
    def test_simkl_reporter_defined_and_registered(self):
        self.assertIn('class SimklReporter', COMPANION)
        self.assertIn('reporters.append(SimklReporter())', COMPANION)
        self.assertIn('simkl.mark_watched_from_ctx', COMPANION)

    def test_reporter_import_present(self):
        self.assertIn('from . import trakt, simkl, playback_store', COMPANION)


class TestIdlistRendererSeam(unittest.TestCase):
    def test_single_renderer_four_entry_points(self):
        self.assertIn('def _render_idlist_rows(', PLUGIN)
        for fn in ('def mdblist_list_browse(', 'def mdblist_list_browse_id(',
                   'def mdblist_watchlist_browse(', 'def simkl_list_browse('):
            self.assertIn(fn, PLUGIN)
        # each wrapper must delegate to the shared renderer
        self.assertGreaterEqual(PLUGIN.count('_render_idlist_rows(rows'), 3)
        self.assertIn('_render_idlist_rows(visible_rows', PLUGIN)


if __name__ == '__main__':
    unittest.main(verbosity=2)
