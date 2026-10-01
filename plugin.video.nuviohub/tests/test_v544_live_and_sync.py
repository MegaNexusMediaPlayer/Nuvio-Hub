# -*- coding: utf-8 -*-
"""v5.4.4 — shared live reads, and sync settings that explain themselves.

live_settings.py exists because the badge toggle failed in a way no single
fix would have prevented: three layers read the same key with three
different fallbacks, and the one that guessed wrong outranked the setting.
One reader, one default, used by all of them.

The sync screen is the other half. Two of its switches lived in the General
category with no label at all, and the section headers said only "Nuvio"
and "Stremio" — so nothing told the user what each account actually
carries, or that Stremio cannot store folder layouts.
"""
import io
import os
import re
import unittest
import xml.etree.ElementTree as ET

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
live = kodi_stub.import_lib_module('live_settings')
sb = kodi_stub.import_lib_module('source_browser')
import xbmcgui  # noqa: E402

SETTINGS = os.path.join(ROOT, 'resources', 'settings.xml')
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'),
             encoding='utf-8').read()


class TestSharedLiveReader(unittest.TestCase):
    def setUp(self):
        self.win = xbmcgui.Window(10000)
        self.win.clearProperty('nuviohub.test.prop')
        live._SETTINGS_FILE_MEMO.update({'sig': None, 'values': {}})

    tearDown = setUp

    def test_public_surface(self):
        for name in ('live_setting', 'live_bool', '_settings_file_value'):
            self.assertTrue(callable(getattr(live, name, None)), name)

    def test_published_value_is_used_when_no_file_value(self):
        self.win.setProperty('nuviohub.test.prop', 'from-service')
        self.assertEqual(live.live_setting('nope', 'nuviohub.test.prop', 'fb'),
                         'from-service')

    def test_dash_sentinel_means_empty(self):
        self.win.setProperty('nuviohub.test.prop', '-')
        self.assertEqual(live.live_setting('nope', 'nuviohub.test.prop', 'fb'), '')

    def test_default_is_shared_by_every_layer(self):
        """The badge bug in one line: one default, not three."""
        self.assertTrue(live.live_bool('never_written_key', default=True))
        self.assertFalse(live.live_bool('never_written_key', default=False))

    def test_source_browser_uses_the_shared_reader(self):
        self.assertIn("_live.live_bool('elite_badges_enabled'", SB)
        # the hand-rolled three-layer copy is gone
        self.assertNotIn("getProperty('nuviohub.badges.enabled')", SB)

    def test_badges_still_default_on_end_to_end(self):
        self.assertTrue(sb._elite_badges_enabled())


class TestSyncSettingsAreSelfExplanatory(unittest.TestCase):
    def setUp(self):
        self.root = ET.parse(SETTINGS).getroot()
        self.nodes = {s.get('id'): s for s in self.root.iter('setting') if s.get('id')}
        self.po = {}
        for lang in ('en_gb', 'ar_sa'):
            self.po[lang] = io.open(
                os.path.join(ROOT, 'resources', 'language',
                             'resource.language.%s' % lang, 'strings.po'),
                encoding='utf-8').read()

    def _text(self, lang, num):
        m = re.search(r'msgctxt "#%s"\nmsgid "[^"]*"\nmsgstr "([^"]*)"' % num,
                      self.po[lang])
        return m.group(1) if m else ''

    def test_every_sync_toggle_has_a_translated_label(self):
        for sid in ('nuvio_sync_enabled', 'nuvio_sync_addons', 'nuvio_sync_progress',
                    'nuvio_sync_collections', 'nuvio_sync_library',
                    'stremio_sync_enabled', 'stremio_sync_addons',
                    'stremio_sync_progress', 'cloud_sync_continuous',
                    'cloud_sync_interval_min'):
            self.assertIn(sid, self.nodes, sid)
            label = self.nodes[sid].get('label')
            self.assertTrue(label, '%s has no label at all' % sid)
            if str(label).isdigit():
                for lang in ('en_gb', 'ar_sa'):
                    self.assertTrue(self._text(lang, label),
                                    '%s has no %s translation' % (sid, lang))

    def test_labels_name_the_service_they_sync_with(self):
        """"Sync installed add-ons" alone does not say WHERE they go."""
        for sid, service in (('nuvio_sync_addons', 'Nuvio'),
                             ('nuvio_sync_progress', 'Nuvio'),
                             ('nuvio_sync_collections', 'Nuvio'),
                             ('stremio_sync_addons', 'Stremio'),
                             ('stremio_sync_progress', 'Stremio')):
            label = self.nodes[sid].get('label')
            self.assertIn(service, self._text('en_gb', label), sid)

    def test_section_headers_say_what_each_account_carries(self):
        raw = io.open(SETTINGS, encoding='utf-8').read()
        self.assertNotIn('<setting type="lsep" label="Nuvio"', raw)
        self.assertNotIn('<setting type="lsep" label="Stremio"', raw)
        heads = [self._text('en_gb', n) for n in
                 re.findall(r'<setting type="lsep" label="(\d+)"', raw)]
        nuvio = [h for h in heads if h.startswith('Nuvio account')]
        stremio = [h for h in heads if h.startswith('Stremio account')]
        self.assertTrue(nuvio, 'no descriptive Nuvio header')
        self.assertTrue(stremio, 'no descriptive Stremio header')
        # the Stremio limitation must be stated, not discovered
        self.assertIn('folder layout', stremio[0].lower())

    def test_sync_toggles_live_in_the_sync_category(self):
        """nuvio_sync_library and _collections sat in General, far from the
        account they belong to."""
        for cat in self.root.iter('category'):
            ids = [s.get('id') for s in cat.iter('setting') if s.get('id')]
            if 'nuvio_sync_enabled' in ids:
                for sid in ('nuvio_sync_library', 'nuvio_sync_collections',
                            'nuvio_sync_addons', 'nuvio_sync_progress'):
                    self.assertIn(sid, ids, '%s is in another category' % sid)
                return
        self.fail('no category contains nuvio_sync_enabled')


if __name__ == '__main__':
    unittest.main(verbosity=2)
