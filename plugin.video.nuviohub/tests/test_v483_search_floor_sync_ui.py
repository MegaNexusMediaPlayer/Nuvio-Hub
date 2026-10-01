# -*- coding: utf-8 -*-
"""v4.8.3 — the two things still wrong after 4.8.2.

1. "I can't find the sync option or the timing." Both settings existed but
   sat mid-way through the long Accounts category — unreachable in
   practice, the same problem the theme preset had before it got a picker.
   A dialog now shows the live mode and interval and writes them, and it is
   linked from all three sync menus.

2. "Search still returns unrelated titles in alphabetical order." Ranking
   alone was never enough: an addon that ignores the search extra answers
   with its plain catalogue, and those rows were still RENDERED, just below
   the real hits. The Pro IPTV server drops them outright
   (`.filter(x => x.score > 0)`) and falls back to the unfiltered set only
   when nothing scores at all. Both search paths now do the same.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
pl = kodi_stub.import_lib_module('plugin')
sm = kodi_stub.import_lib_module('search_match')
PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
I18N = io.open(os.path.join(ROOT, 'resources', 'lib', 'i18n.py'), encoding='utf-8').read()


class TestRelevanceFloor(unittest.TestCase):
    """v4.8.4: these exercise the real filter instead of grepping for it.

    The behaviour under test is the reported symptom: an addon that
    ignores the search extra answers with its plain A-Z catalogue, and
    those rows used to render below the genuine hits.
    """

    ARABIC_JUNK = ['A Different Show', 'Abandoned', 'Aftermath',
                   'The Big Bang Theory', 'Avatar']

    def test_alphabetical_catalogue_is_dropped_entirely(self):
        rows = self.ARABIC_JUNK + ['العاصوف']
        kept, dropped = sm.filter_relevant(rows, 'العاصوف')
        self.assertEqual([item for item, _s in kept], ['العاصوف'])
        self.assertEqual(dropped, len(self.ARABIC_JUNK))

    def test_nothing_matches_falls_back_to_the_full_set(self):
        """The safety valve: an empty page would be worse than noise."""
        kept, dropped = sm.filter_relevant(self.ARABIC_JUNK, 'العاصوف')
        self.assertEqual(len(kept), len(self.ARABIC_JUNK))
        self.assertEqual(dropped, 0)

    def test_ordering_is_by_score_then_arrival(self):
        rows = ['The Debt Collector 2', 'Debt Collector', 'A Debt Collector Story']
        kept, _ = sm.filter_relevant(rows, 'Debt Collector')
        ranked = [item for item, _score in
                  sorted(kept, key=lambda pair: -pair[1])]
        self.assertEqual(ranked[0], 'Debt Collector')        # exact wins
        self.assertEqual(len(ranked), 3)                     # all are relevant

    def test_empty_input_is_safe(self):
        self.assertEqual(sm.filter_relevant([], 'x'), ([], 0))
        self.assertEqual(sm.filter_relevant(None, 'x'), ([], 0))

    def test_title_extractor_supports_dict_rows(self):
        rows = [{'title': 'العاصوف'}, {'title': 'Avatar'}]
        kept, dropped = sm.filter_relevant(rows, 'العاصوف',
                                           lambda r: r.get('title') or '')
        self.assertEqual(kept[0][0]['title'], 'العاصوف')
        self.assertEqual(dropped, 1)

    def test_both_search_paths_use_the_shared_filter(self):
        # one implementation, so a fix can no longer miss a site
        self.assertEqual(PLUGIN.count('_search_match.filter_relevant('), 2)
        self.assertNotIn('_matched = [r for r in _flat if r[4] > 0]', PLUGIN)

    def test_dropped_rows_are_logged(self):
        self.assertIn('dropped %d irrelevant row(s) of %d', PLUGIN)

    def test_an_alphabetical_catalogue_scores_zero(self):
        for junk in self.ARABIC_JUNK:
            self.assertEqual(sm.match_score('العاصوف', junk), 0, junk)
        self.assertGreater(sm.match_score('العاصوف', 'العاصوف'), 0)

    def test_relevant_rows_survive_the_floor(self):
        for q, t in (('الطيار', 'الطيار'), ('العاصوف', 'العاصوف الجزء الثاني'),
                     ('debt collector', 'The Debt Collector')):
            kept, _ = sm.filter_relevant([t], q)
            self.assertGreater(kept[0][1], 0, '%s/%s' % (q, t))


class TestSyncOptionsFrontDoor(unittest.TestCase):
    def test_action_defined_and_routed(self):
        self.assertIn('def sync_options_action():', PLUGIN)
        self.assertIn("if action == 'sync_options':", PLUGIN)
        # v5.4.x moved the dialog body into routes/accounts.sync_options
        self.assertIn('_accounts_route_mod.sync_options(ADDON, tr, _setting)', PLUGIN)

    def test_linked_from_every_sync_menu(self):
        self.assertEqual(PLUGIN.count("build_url(action='sync_options')"), 3)

    def test_dialog_writes_both_settings(self):
        # v5.4.1: the dialog body moved to routes/accounts.sync_options
        body = io.open(os.path.join(ROOT, 'resources', 'lib', 'routes',
                                    'accounts.py'), encoding='utf-8').read()
        body = body.split('def sync_options(addon, tr, setting):', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("addon.setSetting('cloud_sync_continuous'", body)
        self.assertIn("addon.setSetting('cloud_sync_interval_min'", body)
        self.assertIn('settings_cache.invalidate()', body)
        # it must be able to turn continuous ON, not only off
        self.assertIn("'true' if pick == 0 else 'false'", body)

    def test_dialog_offers_every_mode_and_sync_now(self):
        body = io.open(os.path.join(ROOT, 'resources', 'lib', 'routes',
                                    'accounts.py'), encoding='utf-8').read()
        body = body.split('def sync_options(addon, tr, setting):', 1)[1].split('\ndef ', 1)[0]
        for key in ("tr('مستمرة (فورية)')", "tr('ذكية وخفيفة')", "tr('موقوفة')",
                    "tr('مزامنة الآن')"):
            self.assertIn(key, body, key)
        self.assertIn('sync_now(addon, tr', body)

    def test_new_strings_translated_once(self):
        for key in ("'وضع المزامنة والتوقيت'", "'وضع المزامنة'",
                    "'فترة السحب'", "'مستمرة (فورية)'", "'%d دقيقة'"):
            self.assertEqual(I18N.count(key), 1, key)


if __name__ == '__main__':
    unittest.main(verbosity=2)
