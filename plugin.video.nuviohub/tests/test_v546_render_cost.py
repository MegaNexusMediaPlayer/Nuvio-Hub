# -*- coding: utf-8 -*-
"""v5.4.6 — the heaviness on opening a title, on playback and on badges.

All three complaints shared one cause, and it was not Python. Measured on
the shipped skins:

    per result row : 277 controls, 196 <visible> conditions
    search screen  : 198 controls, 108 conditions

Kodi re-evaluates every one of those conditions per frame, for every
visible row. Sixty of the row's conditions existed only to pick a colour:
each format badge carried TEN pre-coloured label variants switched by
String.IsEqual on fmt{n}_cls, because Kodi 22 cannot resolve
$INFO[ListItem.Property(...)] inside a colour attribute.

The colour now travels inside the label text as a [COLOR] tag, which the
row renders with one label instead of ten. The search dashboard drops from
eight provider cards to six — a real setup runs four to six, and the last
two slots were paying render cost to stay empty.

    per result row : 163 controls, 76 conditions   (-41% / -61%)
    search screen  : 154 controls, 82 conditions   (-22% / -24%)
"""
import io
import os
import re
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sb = kodi_stub.import_lib_module('source_browser')
sl = kodi_stub.import_lib_module('sources_loading')

SKINS = os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i')
RESULTS = io.open(os.path.join(SKINS, 'sources_results.xml'), encoding='utf-8').read()
LOADING = io.open(os.path.join(SKINS, 'sources_loading.xml'), encoding='utf-8').read()
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'),
             encoding='utf-8').read()


def _row_layouts():
    rows = RESULTS.split('<control type="list" id="2000">', 1)[1]
    item = rows.split('<focusedlayout', 1)[0]
    focused = rows.split('<focusedlayout', 1)[1].split('</focusedlayout>', 1)[0]
    return item, focused


class TestRowRenderCost(unittest.TestCase):
    """Ratchets. These numbers are felt directly on a low-power box."""

    def test_conditions_per_row(self):
        item, focused = _row_layouts()
        n = item.count('<visible>') + focused.count('<visible>')
        self.assertLessEqual(n, 90, 'per-row conditions grew to %d (was 76)' % n)

    def test_controls_per_row(self):
        item, focused = _row_layouts()
        n = item.count('<control ') + focused.count('<control ')
        self.assertLessEqual(n, 180, 'per-row controls grew to %d (was 163)' % n)

    def test_no_colour_variant_stacks_remain(self):
        """The pattern that caused it: N pre-coloured copies of one label."""
        variants = re.findall(r'String\.IsEqual\(ListItem\.Property\(fmt\d_cls\)', RESULTS)
        self.assertEqual(variants, [],
                         'format badges are back to switched colour variants')

    def test_search_screen_cost(self):
        self.assertLessEqual(len(re.findall(r'<visible>', LOADING)), 95)
        self.assertLessEqual(LOADING.count('<control '), 170)


class TestColoursSurvivedTheChange(unittest.TestCase):
    """Cheaper must not mean plainer — the identity palette is intact."""

    def test_every_class_keeps_a_distinct_colour(self):
        colours = sb._TAG_CLASS_COLORS
        self.assertGreaterEqual(len(colours), 10)
        self.assertEqual(len(set(colours.values())), len(colours))
        for value in colours.values():
            self.assertRegex(value, r'^[0-9A-F]{8}$')

    def test_every_known_tag_maps_to_a_colour(self):
        for tag in sb._TAG_CLASS:
            self.assertIn(sb._tag_class(tag), colours_of(sb), tag)

    def test_unknown_tags_fall_back_visibly(self):
        self.assertIn(sb._tag_class('some-new-tag'), sb._TAG_CLASS_COLORS)

    def test_label_carries_the_colour(self):
        self.assertIn("li.setProperty('fmt%d_label' % n", SB)
        self.assertIn('[COLOR %s]', SB)
        self.assertIn('_TAG_CLASS_COLORS.get(_cls', SB)

    def test_skin_reads_the_prepared_label(self):
        item, focused = _row_layouts()
        for layout in (item, focused):
            self.assertIn('ListItem.Property(fmt1_label)', layout)


def colours_of(mod):
    return mod._TAG_CLASS_COLORS


class TestProviderCards(unittest.TestCase):
    def test_skin_and_code_agree_on_the_slot_count(self):
        slots = sorted({int(n) for n in re.findall(r'pv(\d)_name', LOADING)})
        self.assertEqual(slots,
                         list(range(1, sl.SourcesLoadingDialog._CARD_SLOTS + 1)))

    def test_overflow_is_still_reported(self):
        self.assertIn('pv_more', LOADING)
        body = SB if False else io.open(
            os.path.join(ROOT, 'resources', 'lib', 'sources_loading.py'),
            encoding='utf-8').read()
        self.assertIn('pv_more', body)

    def test_each_visible_card_binds_its_full_property_set(self):
        for slot in range(1, sl.SourcesLoadingDialog._CARD_SLOTS + 1):
            for suffix in ('_name', '_count', '_state', '_coloridx'):
                self.assertIn('pv%d%s' % (slot, suffix), LOADING,
                              'slot %d missing %s' % (slot, suffix))


if __name__ == '__main__':
    unittest.main(verbosity=2)
