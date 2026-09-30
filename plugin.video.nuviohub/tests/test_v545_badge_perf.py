# -*- coding: utf-8 -*-
"""v5.4.5 — badge matching on long result lists.

Measured before touching anything, with the user's real 83-rule set:

    _elite_badge_images   0.53 ms/row   (0.44 ms of it raw regex)
    _stream_facts         0.57 ms/row

On a 300-row list that is ~160 ms spent re-deciding badges for rows that
mostly describe the SAME release. There was already a per-row cache, but
it keyed on the full blob — which carries the file size, seeder count and
indexer — so 300 rows produced 300 distinct keys and it never hit once.

The fix keys the cache on the blob with provable NOISE stripped (sizes,
seeds, durations, percentages) and everything else preserved. That last
part is the safety property under test here: an unknown token still
reaches the rules, so the cache can only merge rows that differ by noise,
never by a technical fact.

    300 rows: 158 ms -> 9.4 ms   (16.8x), identical badges
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sb = kodi_stub.import_lib_module('source_browser')

RULES_JSON = ('{"filters":['
              '{"groupId":"gr","pattern":"(?i)2160p|4k","imageURL":"http://c/4k.png"},'
              '{"groupId":"gs","pattern":"(?i)web-?dl","imageURL":"http://c/web.png"},'
              # NOTE: \\b needs FOUR backslashes here — two are eaten by the
              # Python literal and JSON decodes \\b as a backspace, not a
              # word boundary. The same trap cost a fixture in v4.8.4.
              '{"groupId":"gv","pattern":"(?i)\\\\bdv\\\\b","imageURL":"http://c/dv.png"},'
              '{"groupId":"ga","pattern":"(?i)atmos","imageURL":"http://c/atmos.png"},'
              '{"groupId":"ge","pattern":"(?i)x265|hevc","imageURL":"http://c/hevc.png"},'
              '{"groupId":"gx","pattern":"(?i)quokka","imageURL":"http://c/quokka.png"}]}')


class _Rules(object):
    """Install a known rule set and an empty cache."""

    def __enter__(self):
        self.rules = sb._elite_compile_rules(sb._elite_rules_from_json_blob(RULES_JSON))
        self._r, self._e = sb._elite_badge_rules, sb._elite_badges_enabled
        sb._elite_badge_rules = lambda: self.rules
        sb._elite_badges_enabled = lambda: True
        sb._ELITE_RESULT_CACHE.clear()
        # the fingerprint is memoised on the rules list's identity, so a
        # previous test's list can otherwise still be considered current
        sb._ELITE_RULES_FP.update({'id': None, 'fp': ''})
        return self

    def __exit__(self, *exc):
        sb._elite_badge_rules, sb._elite_badges_enabled = self._r, self._e
        sb._ELITE_RESULT_CACHE.clear()
        sb._ELITE_RULES_FP.update({'id': None, 'fp': ''})
        return False


class TestSignatureCollapsesNoiseOnly(unittest.TestCase):
    def test_size_seed_and_duration_are_noise(self):
        a = sb._elite_signature('X.2160p.mkv | 24.5 GB | 12 seeders | 1h 58min')
        b = sb._elite_signature('X.2160p.mkv | 31.7 GB | 44 seeders | 2h 05min')
        self.assertEqual(a, b)

    def test_labelled_fields_are_noise(self):
        a = sb._elite_signature('X.1080p | size: 3.4GB | seeders=12')
        b = sb._elite_signature('X.1080p | size: 9.9GB | seeders=99')
        self.assertEqual(a, b)

    def test_technical_facts_are_never_collapsed(self):
        pairs = [('X.2160p.mkv', 'X.1080p.mkv'),
                 ('X.WEB-DL.mkv', 'X.BluRay.mkv'),
                 ('X.Atmos.mkv', 'X.DTS.mkv'),
                 ('X.DV.HDR10.mkv', 'X.HDR10.mkv'),
                 ('X.mkv PEACOCK', 'X.mkv NETFLIX')]
        for a, b in pairs:
            self.assertNotEqual(sb._elite_signature(a), sb._elite_signature(b),
                                '%s vs %s collapsed' % (a, b))

    def test_unknown_tokens_are_preserved(self):
        """The safety property: a set may key on anything, including words
        this addon has never seen."""
        self.assertIn('quokka', sb._elite_signature('X.2160p.QUOKKA.mkv'))
        self.assertNotEqual(sb._elite_signature('X.2160p.QUOKKA.mkv'),
                            sb._elite_signature('X.2160p.mkv'))

    def test_short_duration_units_do_not_eat_audio_tags(self):
        """'1h 58min' must collapse, but '7.1', '5.1', '10bit' and 'AAC2.0'
        are technical facts that must survive."""
        self.assertEqual(sb._elite_signature('X.2160p.mkv | 1h 58min'),
                         sb._elite_signature('X.2160p.mkv | 2h 05min'))
        for tag, token in (('M.TrueHD.7.1.mkv', '7.1'),
                           ('M.DTS-HD.MA.5.1.mkv', '5.1'),
                           ('M.2160p.10bit.mkv', '10bit'),
                           ('M.AAC2.0.mkv', 'aac2.0')):
            self.assertIn(token, sb._elite_signature(tag), tag)

    def test_empty_input_is_safe(self):
        for value in ('', None, '   '):
            self.assertEqual(sb._elite_signature(value), '')


class TestCacheIsCorrectAndShared(unittest.TestCase):
    BASE = 'The.Movie.2024.2160p.WEB-DL.DV.Atmos.x265-GRP.mkv'

    def test_rows_differing_only_by_noise_share_one_entry(self):
        with _Rules():
            rows = [{'badge_blob_raw': '%s | %.1f GB | %d seeders'
                     % (self.BASE, 10 + i * 0.3, i)} for i in range(50)]
            results = [tuple(sb._elite_badge_images(r)) for r in rows]
            self.assertEqual(len(set(results)), 1, 'same release gave different badges')
            self.assertEqual(len(sb._ELITE_RESULT_CACHE), 1)

    def test_a_different_release_is_not_reused(self):
        with _Rules():
            first = tuple(sb._elite_badge_images({'badge_blob_raw': self.BASE}))
            second = tuple(sb._elite_badge_images(
                {'badge_blob_raw': 'Show.S01E01.1080p.BluRay.DTS.mkv'}))
            self.assertNotEqual(first, second)
            self.assertEqual(len(sb._ELITE_RESULT_CACHE), 2)

    def test_unknown_token_gets_its_own_entry(self):
        with _Rules():
            plain = tuple(sb._elite_badge_images({'badge_blob_raw': self.BASE}))
            quokka = tuple(sb._elite_badge_images(
                {'badge_blob_raw': self.BASE.replace('.mkv', '.QUOKKA.mkv')}))
            self.assertIn('http://c/quokka.png', quokka)
            self.assertNotIn('http://c/quokka.png', plain)

    def test_cache_is_bounded(self):
        with _Rules():
            for i in range(sb._ELITE_RESULT_CACHE_MAX + 40):
                sb._elite_badge_images({'badge_blob_raw': 'Rel.%d.2160p.mkv' % i})
            self.assertLessEqual(len(sb._ELITE_RESULT_CACHE),
                                 sb._ELITE_RESULT_CACHE_MAX)

    def test_changing_the_badge_set_invalidates_results(self):
        """The key carries the set URL and load stamp, so switching sets
        cannot serve art from the previous one."""
        with _Rules():
            sb._elite_badge_images({'badge_blob_raw': self.BASE})
            keys = list(sb._ELITE_RESULT_CACHE)
            self.assertTrue(keys)
            stamp = str(int(sb._ELITE_BADGE_RULE_CACHE.get('ts') or 0))
            self.assertIn(stamp, keys[0])


class TestEarlyExitWasRejected(unittest.TestCase):
    """An early exit on "every group is full" was measured at ~11% and
    removed: the signature cache is worth ~16x, and a saturation test that
    is subtly wrong for one third-party set silently drops a badge. This
    pins the decision so it is not re-added without the same scrutiny."""

    def test_matching_does_not_short_circuit(self):
        src = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'),
                      encoding='utf-8').read()
        body = src.split('def _elite_badge_images(', 1)[1].split('\ndef ', 1)[0]
        self.assertNotIn('remaining_groups', body)
        self.assertIn('REMOVED', body)

    def test_all_matching_rules_are_honoured(self):
        with _Rules():
            images = sb._elite_badge_images(
                {'badge_blob_raw': 'M 2024 2160p WEB-DL DV Atmos x265 | GRP'})
            self.assertEqual(len(images), 5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
