# -*- coding: utf-8 -*-
"""v4.7.2 regression tests.

1. MERGED RELEVANCE SEARCH — Stremio + Plex + Emby results interleave in
   one relevance-ranked stream per section (exact > prefix > all-tokens >
   substring > partial), Arabic-aware, stable on ties — instead of
   provider-arrival blocks.

2. CUSTOM badges.json — "I change the JSON and nothing changes": the 3s
   timeout / 512KB cap silently failed real files and fell back to the
   BUILTIN rules. Now 8s / 2MB, a last-good disk copy that survives
   restarts and hiccups, a 180s negative memo so lists don't stall
   retrying, and a one-time visible warning when the custom URL is
   unusable.

3. RESOLVE ABORT — the playlist/direct handoffs abandoned the IsPlayable
   resolve context, logging "Error resolving ... is not playable" on
   every play (proven in the user's kodi.log). The context is now closed
   cleanly before the handoff.
"""
import io
import os
import tempfile
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
plugin_mod = kodi_stub.import_lib_module('plugin')
sb_mod = kodi_stub.import_lib_module('source_browser')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()


class TestRelevanceScorer(unittest.TestCase):
    score = staticmethod(lambda q, t: plugin_mod._search_match_score(q, t))

    def test_tier_ordering(self):
        # v4.8.2 rebalanced the tiers when the Arabic-first scorer landed:
        # full token coverage is 80, a single-word query must hit a WHOLE
        # word (so 'topia' no longer scores against 'Zootopia'), and the
        # ordering exact > prefix > coverage > partial still holds.
        self.assertEqual(self.score('Zootopia', 'zootopia'), 100)
        self.assertEqual(self.score('zootopia', 'Zootopia 2'), 88)
        self.assertEqual(self.score('debt collector', 'The Debt Collector'), 80)
        self.assertEqual(self.score('topia', 'Zootopia'), 0)
        partial = self.score('matrix reloaded xyzzy', 'The Matrix')
        self.assertTrue(0 < partial < 80, partial)
        self.assertEqual(self.score('x', 'totally different'), 0)
        self.assertEqual(self.score('', 'anything'), 0)
        self.assertGreater(self.score('Zootopia', 'zootopia'),
                           self.score('zootopia', 'Zootopia 2'))

    def test_arabic_normalization(self):
        # alef-lam prefix, hamza forms and ta-marbuta must not break a match
        self.assertGreaterEqual(self.score('الطيار', 'طيار'), 74)
        self.assertGreaterEqual(self.score('أحمد', 'احمد'), 100)
        self.assertGreaterEqual(self.score('مدرسة', 'مدرسه'), 100)

    def test_merged_ordering_interleaves_providers_by_score(self):
        """v4.8.4: behavioural — build the same (provider, meta, batch,
        index, score) tuples the renderer builds and check the ordering
        rather than grepping for the sort call."""
        import kodi_stub as _ks
        sm = _ks.import_lib_module('search_match')
        batches = [
            ({'name': 'Plex'}, [{'name': 'Zootopia 2'}, {'name': 'Unrelated'}]),
            ({'name': 'Stremio'}, [{'name': 'Zootopia'}]),
        ]
        rows = [(prov, meta, b, m)
                for b, (prov, metas) in enumerate(batches)
                for m, meta in enumerate(metas)]
        kept, dropped = sm.filter_relevant(rows, 'Zootopia',
                                           lambda r: r[1].get('name') or '')
        flat = sorted([row + (score,) for row, score in kept],
                      key=lambda r: (-r[4], r[2], r[3]))
        # the exact hit from the SECOND provider must lead
        self.assertEqual(flat[0][1]['name'], 'Zootopia')
        self.assertEqual(flat[0][0]['name'], 'Stremio')
        self.assertEqual(dropped, 1)                 # 'Unrelated' is gone
        self.assertNotIn('Unrelated', [r[1]['name'] for r in flat])


class TestEliteJsonHardening(unittest.TestCase):
    def test_fetch_limits_raised(self):
        body = SB.split('def _elite_badge_rules():', 1)[1].split('\ndef _elite_pattern', 1)[0]
        self.assertIn('timeout=8.0', body)
        self.assertIn('1024 * 1024 * 2', body)
        self.assertNotIn('timeout=3.0', body)

    def test_last_good_disk_copy_roundtrip(self):
        tmp = tempfile.mkdtemp(prefix='dexhub_elite_')
        orig = sb_mod._elite_rules_disk_path
        try:
            sb_mod._elite_rules_disk_path = lambda url: os.path.join(tmp, 'rules.json')
            blob = ('{"filters":[{"groupId":"video","pattern":"(?i)HDR",'
                    '"imageURL":"https://cdn/x.png"}]}')
            sb_mod._elite_rules_to_disk('https://u/custom.json', blob)
            rules = sb_mod._elite_rules_from_disk('https://u/custom.json')
        finally:
            sb_mod._elite_rules_disk_path = orig
        # v4.7.7: the disk path returns rules with their pattern already
        # compiled (matching happens per row, compiling must not).
        self.assertEqual(len(rules), 1)
        group, pattern, image = rules[0]
        self.assertEqual((group, image), ('video', 'https://cdn/x.png'))
        self.assertTrue(hasattr(pattern, 'search'))
        self.assertTrue(pattern.search('this is HDR here'))

    def test_disk_path_deterministic_per_url(self):
        p1 = sb_mod._elite_rules_disk_path('https://a/rules.json')
        p2 = sb_mod._elite_rules_disk_path('https://a/rules.json')
        p3 = sb_mod._elite_rules_disk_path('https://b/rules.json')
        self.assertEqual(p1, p2)
        self.assertNotEqual(p1, p3)

    def test_negative_memo_and_one_time_warning(self):
        body = SB.split('def _elite_badge_rules():', 1)[1].split('\ndef _elite_pattern', 1)[0]
        self.assertIn("'fail_url'", body)
        self.assertIn('< 180', body)
        self.assertIn('_elite_warn_custom_failed_once(url)', body)
        warn = SB.split('def _elite_warn_custom_failed_once(url):', 1)[1]
        warn = warn.split('\ndef ', 1)[0] if '\ndef ' in warn else warn
        self.assertIn("'warned_url'", warn)
        self.assertIn('NOTIFICATION_WARNING', warn)

    def test_fetch_failure_prefers_disk_over_builtin(self):
        body = SB.split('def _elite_badge_rules():', 1)[1].split('\ndef _elite_rules_disk_path', 1)[0]
        idx_disk = body.rindex('_elite_rules_from_disk(url)')
        idx_builtin = body.rindex('_elite_builtin_badge_rules()')
        self.assertLess(idx_disk, idx_builtin)


class TestResolveAbortReverted(unittest.TestCase):
    """v4.7.8 reverted the 4.7.2 abort.

    Closing the abandoned resolve context with setResolvedUrl(False) did
    silence Kodi's "Error resolving item" line, but it also declared the
    item UNPLAYABLE — the user's log then showed "Playlist Player:
    skipping unplayable item" on the very click that should play. A
    cosmetic log line is not worth poisoning the playlist.
    """

    def test_play_dispatch_does_not_declare_the_item_unplayable(self):
        marker = 'v4.7.8: do NOT report a failed resolve here'
        self.assertIn(marker, PLUGIN)
        seg = PLUGIN.split(marker, 1)[1][:600]
        self.assertNotIn('setResolvedUrl(HANDLE, False', seg)

    def test_reason_documented(self):
        self.assertIn('skipping unplayable item', PLUGIN)


if __name__ == '__main__':
    unittest.main(verbosity=2)
