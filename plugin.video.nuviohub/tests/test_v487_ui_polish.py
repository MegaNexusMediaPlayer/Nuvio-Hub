# -*- coding: utf-8 -*-
"""v4.8.7 — settings layout, badge capacity, and a picker you can read.

SETTINGS: "Accounts and API keys" had grown to 56 settings in one scroll —
cloud sync, Trakt, Simkl, Plex, Emby, TMDb Helper and five API keys stacked
together. That is where the sync mode and the badges URL were effectively
unreachable. It is now four focused categories.

BADGES: eight slots, and a single rich WEB-DL already matches resolution,
source, HDR, audio, channels, codec and streaming service — so extra
matches were silently cut. Ten slots now, at a slightly tighter pill so
the strip still fits the row.

PICKER: the set list showed bare names. It now shows each set's name with
a sample badge and its state underneath (Kodi's useDetails mode).
"""
import io
import os
import re
import unittest
import xml.etree.ElementTree as ET

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sb = kodi_stub.import_lib_module('source_browser')
i18n = kodi_stub.import_lib_module('i18n')

SETTINGS_XML = os.path.join(ROOT, 'resources', 'settings.xml')
RESULTS_XML = io.open(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i',
                                   'sources_results.xml'), encoding='utf-8').read()
PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()


class TestSettingsLayout(unittest.TestCase):
    def setUp(self):
        self.root = ET.parse(SETTINGS_XML).getroot()
        self.cats = list(self.root.iter('category'))

    def test_no_category_is_a_wall_of_settings(self):
        for cat in self.cats:
            n = len([s for s in cat.iter('setting') if s.get('id')])
            self.assertLessEqual(n, 30,
                                 'category %s has %d settings' % (cat.get('label'), n))

    def test_accounts_split_into_focused_categories(self):
        labels = [c.get('label') for c in self.cats]
        for expected in ('30290', '30884', '30885', '30886'):
            self.assertIn(expected, labels, expected)

    def test_no_setting_was_lost_or_duplicated(self):
        ids = [s.get('id') for s in self.root.iter('setting') if s.get('id')]
        self.assertEqual(len(ids), len(set(ids)), 'duplicate setting id')
        # every service still has its home
        for sid in ('nuvio_sync_enabled', 'stremio_sync_enabled', 'enable_trakt',
                    'enable_simkl', 'plex_login_action', 'emby_login_action',
                    'tmdb_api_key', 'mdblist_api_key', 'elite_badges_json_url',
                    'cloud_sync_continuous', 'cloud_sync_interval_min'):
            self.assertIn(sid, ids, sid)

    def test_every_category_label_is_translated(self):
        for lang in ('en_gb', 'ar_sa'):
            po = io.open(os.path.join(ROOT, 'resources', 'language',
                                      'resource.language.%s' % lang, 'strings.po'),
                         encoding='utf-8').read()
            for cat in self.cats:
                label = cat.get('label')
                if label and label.isdigit():
                    self.assertIn('msgctxt "#%s"' % label, po,
                                  '%s missing in %s' % (label, lang))


class TestBadgeCapacity(unittest.TestCase):
    """v5.4.1: the 5.x line trimmed the image strip to six badges for ARM
    render cost. The contract under test is no longer a fixed number — it
    is that the skin and the code agree, every slot exists in BOTH layouts,
    and the strip fits the row."""

    def _slots(self):
        return sorted({int(n) for n in re.findall(r'elite_badge(\d+)', RESULTS_XML)})

    def test_skin_and_code_agree_on_the_slot_count(self):
        slots = self._slots()
        self.assertTrue(slots, 'no badge slots in the skin')
        self.assertEqual(slots, list(range(1, len(slots) + 1)), 'gap in slot numbering')
        self.assertIn('max_items=%d' % len(slots), SB)
        self.assertIn('for badge_idx in range(%d):' % len(slots), SB)

    def test_every_slot_exists_in_both_layouts(self):
        rows = RESULTS_XML.split('<control type="list" id="2000">', 1)[1]
        item = rows.split('<focusedlayout', 1)[0]
        focused = rows.split('<focusedlayout', 1)[1]
        for n in self._slots():
            self.assertIn('elite_badge%d' % n, item, 'itemlayout slot %d' % n)
            self.assertIn('elite_badge%d' % n, focused, 'focusedlayout slot %d' % n)

    def test_strip_fits_the_row(self):
        pairs = [(int(a), int(b)) for a, b in
                 re.findall(r'<left>(\d+)</left><top>2</top><width>(\d+)</width>', RESULTS_XML)]
        if pairs:
            self.assertLessEqual(max(x + w for x, w in pairs), 1440,
                                 'badge strip overflows the row')

    def test_a_rich_release_fills_every_slot(self):
        n = len(self._slots())
        rules = [('g%d' % i, r'(?i)%s' % tok, 'http://cdn/%s.png' % tok)
                 for i, tok in enumerate(
                     ['2160p', 'web-dl', 'dv', 'hdr10', 'atmos', 'truehd',
                      '5\\.1', 'x265', 'remux', 'imax'])]
        compiled = sb._elite_compile_rules(rules)
        text = ('Movie.2024.2160p.WEB-DL.DV.HDR10.DDP5.1.Atmos.TrueHD.'
                'x265.REMUX.IMAX.mkv')
        o_r, o_e = sb._elite_badge_rules, sb._elite_badges_enabled
        try:
            sb._elite_badge_rules = lambda: compiled
            sb._elite_badges_enabled = lambda: True
            images = sb._elite_badge_images({'badge_blob_raw': text}, max_items=n)
        finally:
            sb._elite_badge_rules, sb._elite_badges_enabled = o_r, o_e
        self.assertEqual(len(images), n)
        self.assertEqual(len(images), len(set(images)))


class TestPresetPicker(unittest.TestCase):
    def test_presets_carry_a_preview_slot(self):
        for entry in sb.ELITE_BADGE_PRESETS:
            self.assertGreaterEqual(len(entry), 3, entry[0])

    def test_preview_helper_prefers_the_real_set(self):
        self.assertEqual(sb.elite_preset_preview('http://none', 'http://fallback.png'),
                         'http://fallback.png')
        orig = sb._elite_rules_from_disk
        try:
            sb._elite_rules_from_disk = lambda _u: [('g', 'p', 'http://live/badge.png')]
            self.assertEqual(sb.elite_preset_preview('http://x', 'http://fallback.png'),
                             'http://live/badge.png')
        finally:
            sb._elite_rules_from_disk = orig

    def test_picker_uses_details_with_a_graceful_fallback(self):
        body = PLUGIN.split('def badges_url_action():', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('useDetails=True', body)
        self.assertIn('setLabel2(', body)
        self.assertIn("setArt({'icon': preview", body)
        self.assertIn('except Exception:', body)      # older Kodi builds

    def test_new_strings_present(self):
        self.assertEqual(i18n.STRINGS.get('اضغط للتطبيق'), 'Select to apply')

    def test_i18n_table_has_one_entry_per_line(self):
        """A packed line hid entries from review; keep the table readable."""
        path = os.path.join(ROOT, 'resources', 'lib', 'i18n.py')
        packed = [n for n, line in enumerate(io.open(path, encoding='utf-8'), 1)
                  if line.count("': '") > 1]
        self.assertEqual(packed, [], 'run-together i18n entries on line(s) %s' % packed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
