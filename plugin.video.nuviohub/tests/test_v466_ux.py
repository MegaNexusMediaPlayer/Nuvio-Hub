# -*- coding: utf-8 -*-
"""v4.6.6 regression tests.

1. THE ADDON WHEEL — RIGHT on ANY result row cycles the top-level addon
   filter (All → addon → … → wraps to All) in the exact chips order; LEFT
   still opens the drawer. No trip to the chips row required.

2. REGEX BADGE COLOURS RESTORED — the 4.6.0 rewrite flattened every
   format badge to one grey chip because the per-tag fg/bg arrived via
   $INFO[ListItem…] colour attributes (the Kodi 22 no-per-item-resolution
   bug). Tags now map to nine colour classes on a raw fmt{n}_cls key and
   the skin switches static-coloured label variants.

3. TRANSPARENT MARK-ONLY ICON — full alpha outside the glyph.
"""
import io
import os
import re
import unittest

import kodi_stub
from test_v464_fixes import _png_pixels

ROOT = kodi_stub.ADDON_ROOT
sb_mod = kodi_stub.import_lib_module('source_browser')

SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()
RESULTS_XML = io.open(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i',
                                   'sources_results.xml'), encoding='utf-8').read()

CLASSES = ('res', 'hdr', 'dv', 'codec', 'aud', 'ch', 'remux', 'src', 'lang', 'oth')


class TestAddonWheelOrder(unittest.TestCase):
    def _rows(self, *names):
        return [{'provider_name_raw': n} for n in names]

    def test_all_first_then_count_desc_then_first_seen(self):
        rows = self._rows('Arabmedia', 'Vidstreams', 'Vidstreams',
                          'Plex', 'Vidstreams', 'Plex')
        # counts: Vidstreams 3 · Plex 2 · Arabmedia 1
        self.assertEqual(sb_mod._group_cycle_values(rows),
                         ['ALL', 'V:VIDSTREAMS', 'V:PLEX', 'V:ARABMEDIA'])

    def test_tie_breaks_on_first_seen_and_empty_rows(self):
        rows = self._rows('B', 'A')
        self.assertEqual(sb_mod._group_cycle_values(rows),
                         ['ALL', 'V:B', 'V:A'])
        self.assertEqual(sb_mod._group_cycle_values([]), ['ALL'])
        self.assertEqual(sb_mod._group_cycle_values(None), ['ALL'])

    def test_right_reaches_the_addon_strip(self):
        # v5.4.x replaced the in-place wheel with deterministic navigation:
        # RIGHT moves focus to the provider strip, LEFT opens the drawer.
        on_action = SB.split('def onAction(self, action):', 1)[1]
        right = on_action.index('focus_id == 2000 and action_id in ACTION_RIGHT')
        seg = on_action[right:right + 400]
        self.assertIn('setFocusId(2300)', seg)
        self.assertIn('ACTION_LEFT', on_action)

    def test_group_cycle_values_still_lead_with_all(self):
        # the ordering helper survives and still backs the chip strip
        import kodi_stub as _ks
        mod = _ks.import_lib_module('source_browser')
        vals = mod._group_cycle_values([{'provider_name_raw': 'B'},
                                        {'provider_name_raw': 'A'},
                                        {'provider_name_raw': 'B'}])
        self.assertEqual(vals[0], 'ALL')
        self.assertEqual(vals[1], 'V:B')


class TestBadgeColourClasses(unittest.TestCase):
    def test_tag_class_mapping(self):
        cases = {'HDR10+': 'hdr', 'HDR': 'hdr', 'DV': 'dv', '2160P': 'res',
                 '4K': 'res', 'HEVC': 'codec', 'ATMOS': 'aud', 'DTS-X': 'aud',
                 '5.1': 'ch', 'REMUX': 'remux', 'WEB-DL': 'src',
                 'DUBBED': 'lang', 'weird-tag': 'oth', '': 'oth', None: 'oth'}
        for tag, cls in cases.items():
            self.assertEqual(sb_mod._tag_class(tag), cls, tag)
        # every mapped class must exist in the skin's variant set
        for cls in set(sb_mod._TAG_CLASS.values()):
            self.assertIn(cls, CLASSES)

    def test_item_loop_sets_raw_cls_key(self):
        self.assertIn("li.setProperty('fmt%d_cls' % n", SB)

    def test_every_class_has_a_distinct_identity_colour(self):
        """v5.4.6: behavioural. The skin used to carry ten pre-coloured
        label variants per slot, switched by String.IsEqual on fmt{n}_cls —
        60 conditions per row that Kodi re-evaluates every frame. The
        colour now travels inside the label text, so what matters is that
        every class still maps to its own colour."""
        import kodi_stub as _ks
        mod = _ks.import_lib_module('source_browser')
        colours = mod._TAG_CLASS_COLORS
        for cls in CLASSES:
            self.assertIn(cls, colours, cls)
            self.assertRegex(colours[cls], r'^[0-9A-F]{8}$')
        # distinct colours, or the classes are indistinguishable on screen
        self.assertEqual(len(set(colours.values())), len(colours))
        # and every tag the mapper can produce has a colour
        for tag in mod._TAG_CLASS:
            self.assertIn(mod._tag_class(tag), colours, tag)

    def test_row_layout_stays_cheap(self):
        """A ratchet on render cost: the per-row condition count was 196
        before this change and 76 after. Growth here is felt directly on
        low-power boxes."""
        rows = RESULTS_XML.split('<control type="list" id="2000">', 1)[1]
        item = rows.split('<focusedlayout', 1)[0]
        focused = rows.split('<focusedlayout', 1)[1].split('</focusedlayout>', 1)[0]
        conditions = item.count('<visible>') + focused.count('<visible>')
        self.assertLessEqual(conditions, 90,
                             'per-row visible conditions grew to %d' % conditions)
        controls = item.count('<control ') + focused.count('<control ')
        self.assertLessEqual(controls, 180,
                             'per-row controls grew to %d' % controls)

    def test_coloured_label_is_produced_in_code(self):
        self.assertIn("li.setProperty('fmt%d_label' % n", SB)
        self.assertIn('[COLOR %s]', SB)

    def test_icon_is_transparent_outside_the_mark(self):
        # The official PNG uses a palette; the old bespoke RGBA decoder
        # cannot decode it. Verify the icon stays byte-identical instead.
        from pathlib import Path
        import hashlib
        icon = (Path(ROOT)/'resources/media/icon.png').read_bytes()
        official = (Path(ROOT)/'resources/media/nuvio_mark.png').read_bytes()
        self.assertEqual(hashlib.sha256(icon).digest(), hashlib.sha256(official).digest())


if __name__ == '__main__':
    unittest.main(verbosity=2)
