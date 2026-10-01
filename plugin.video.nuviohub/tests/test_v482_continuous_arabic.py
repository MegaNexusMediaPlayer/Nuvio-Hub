# -*- coding: utf-8 -*-
"""v4.8.2 — continuous Nuvio sync, and Arabic-first search matching.

SYNC: the loop woke at most every 5 minutes (30 by default), so a title
saved on the phone took that long to appear. Continuous mode wakes every
20s and syncs when either a local change is pending or the pull cadence is
due. Every NuvioHub write (favourite, watch progress) raises a dirty flag, so
outbound changes travel in seconds. Idle ticks cost nothing: run_sync
already pushes deltas and skips sections whose fingerprint is unchanged.

SEARCH: the scorer is ported from the DexWorld Pro server's own
titleMatchScore/arabicNorm — already tuned against this catalogue. Beyond
folding hamza/ta-marbuta/alef-maqsura and stripping tashkeel, two rules
carry over verbatim: a query digit must appear EXACTLY (so "الموسم 5" never
scores against "الموسم 50"), and a single-word query must match a whole
word rather than a fragment. A Damerau/OSA distance forgives typos.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
pl = kodi_stub.import_lib_module('plugin')

SERVICE = io.open(os.path.join(ROOT, 'service.py'), encoding='utf-8').read()
FAV = io.open(os.path.join(ROOT, 'resources', 'lib', 'favorites_store.py'), encoding='utf-8').read()
PB = io.open(os.path.join(ROOT, 'resources', 'lib', 'nuviohub', 'playback_store.py'), encoding='utf-8').read()

score = staticmethod(pl._search_match_score)


class TestArabicMatching(unittest.TestCase):
    def s(self, q, t):
        return pl._search_match_score(q, t)

    def test_orthographic_folding_is_an_exact_match(self):
        for q, t in (('احمد', 'أحمد'), ('اكاديميه', 'أكاديمية'),
                     ('مدرسه المشاغبين', 'مدرسة المشاغبين'),
                     ('مصطفي', 'مصطفى'), ('مسلسل', 'مُسَلْسَل')):
            self.assertEqual(self.s(q, t), 100, '%s / %s' % (q, t))

    def test_definite_article_is_noise(self):
        self.assertGreaterEqual(self.s('الطيار', 'طيار'), 74)
        self.assertGreaterEqual(self.s('طيار', 'الطيار'), 74)

    def test_prefix_and_partial_titles(self):
        self.assertGreaterEqual(self.s('العاصوف', 'العاصوف الجزء الثاني'), 74)
        self.assertGreater(self.s('الحشاشين', 'الحشاشون'), 0)   # typo tolerance

    def test_numeric_strictness(self):
        """The server's rule: a digit in the query must match exactly."""
        self.assertEqual(self.s('الموسم 5', 'الموسم 50'), 0)
        self.assertEqual(self.s('bein 5', 'bein 1'), 0)
        self.assertEqual(self.s('الموسم 5', 'الموسم 5'), 100)

    def test_arabic_indic_digits_fold_to_latin(self):
        self.assertEqual(self.s('الموسم ٥', 'الموسم 5'), 100)

    def test_single_short_word_never_matches_a_fragment(self):
        self.assertEqual(self.s('ابن', 'ابناء الشوارع'), 0)
        self.assertGreater(self.s('ابن', 'ابن حلال'), 0)

    def test_latin_titles_still_rank(self):
        self.assertEqual(self.s('Zootopia', 'zootopia'), 100)
        self.assertGreaterEqual(self.s('debt collector', 'The Debt Collector'), 74)
        self.assertEqual(self.s('x', 'totally different'), 0)

    def test_empty_input_is_zero_not_a_crash(self):
        for q, t in (('', 'x'), ('x', ''), ('', ''), (None, None)):
            self.assertEqual(self.s(q, t), 0)

    def test_edit_distance_helper(self):
        self.assertTrue(pl._edit_distance_le('nine', 'ninie', 1))
        self.assertTrue(pl._edit_distance_le('form', 'from', 1))     # transposition
        self.assertFalse(pl._edit_distance_le('cat', 'dog', 1))

    def test_digits_never_fuzzy_match(self):
        self.assertFalse(pl._fuzzy_token_eq('bein5', 'bein1'))
        self.assertFalse(pl._fuzzy_token_eq('2024', '2025'))


class TestContinuousSync(unittest.TestCase):
    def test_loop_honours_the_continuous_setting(self):
        # v5.4.1: 5.4.0 kept a sturdier loop (cycle lock, retry backoff) but
        # hardcoded its timings, so the setting did nothing.
        body = SERVICE.split('def _cloud_sync_loop(mon):', 1)[1]
        self.assertIn("_setting('cloud_sync_continuous', 'true')", body)
        self.assertIn('debounce = 8.0 if continuous else 45.0', body)
        self.assertIn('mon.waitForAbort(5 if continuous else 30)', body)

    def test_dirty_flag_triggers_a_sync(self):
        body = SERVICE.split('def _cloud_sync_loop(mon):', 1)[1]
        self.assertIn('SYNC_DIRTY_PROP', body)
        self.assertIn('dirty_due or pull_due', body)
        self.assertIn('clearProperty(SYNC_DIRTY_PROP)', body)

    def test_sync_off_is_still_honoured(self):
        body = SERVICE.split('def _cloud_sync_loop(mon):', 1)[1].split('\n    try:', 1)[0]
        self.assertIn('if interval <= 0:', body)

    def test_local_writes_raise_the_flag(self):
        self.assertIn('def _mark_sync_dirty():', FAV)
        self.assertEqual(FAV.count('_mark_sync_dirty()'), 3)       # def + add + remove
        # a row pulled FROM nuvio must not bounce straight back
        self.assertIn("if (source or 'local') != 'nuvio':", FAV)
        self.assertIn("setProperty('nuviohub.sync_dirty', '1')", PB)

    def test_setting_declared_and_translated(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(ROOT, 'resources', 'settings.xml')).getroot()
        node = [s for s in root.iter('setting') if s.get('id') == 'cloud_sync_continuous']
        self.assertEqual(len(node), 1)
        self.assertEqual(node[0].get('default'), 'true')
        for lang in ('en_gb', 'ar_sa'):
            po = io.open(os.path.join(ROOT, 'resources', 'language',
                                      'resource.language.%s' % lang, 'strings.po'),
                         encoding='utf-8').read()
            self.assertIn('msgctxt "#%s"' % node[0].get('label'), po, lang)


if __name__ == '__main__':
    unittest.main(verbosity=2)
