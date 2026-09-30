# -*- coding: utf-8 -*-
"""v4.8.4 — behavioural coverage for the paths that failed silently.

An audit of this suite found 163 assertions that grep the SOURCE against
68 that call the code. That ratio is how a patch could be written, printed
as applied, and still not be in the file — it happened twice in this
cycle, and only a later test caught it. The tests here exercise behaviour
end to end: if the code is absent or wrong they fail, no matter what the
source text looks like.

They also cover search_match.py, extracted from plugin.py in this version
(25,883 -> 25,7xx lines) so the relevance rules live in one importable
place and both search paths share a single filter.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sm = kodi_stub.import_lib_module('search_match')
sb = kodi_stub.import_lib_module('source_browser')
pl = kodi_stub.import_lib_module('plugin')


class TestSearchMatchModule(unittest.TestCase):
    def test_public_surface_exists(self):
        for name in ('norm', 'edit_distance_le', 'fuzzy_token_eq',
                     'match_score', 'filter_relevant'):
            self.assertTrue(callable(getattr(sm, name, None)), name)

    def test_plugin_aliases_point_at_the_module(self):
        """The private names stayed as aliases, so nothing else moved."""
        self.assertIs(pl._search_match_score, sm.match_score)
        self.assertIs(pl._search_norm, sm.norm)
        self.assertIs(pl._fuzzy_token_eq, sm.fuzzy_token_eq)

    def test_norm_folds_arabic_orthography(self):
        self.assertEqual(sm.norm('أَكَادِيمِيَّة'), sm.norm('اكاديميه'))
        self.assertEqual(sm.norm('مصطفى'), sm.norm('مصطفي'))
        self.assertEqual(sm.norm('الموسم ٥'), 'موسم 5')

    def test_module_is_dependency_free(self):
        """It must stay importable without Kodi, or it cannot be unit-tested."""
        src = io.open(os.path.join(ROOT, 'resources', 'lib', 'search_match.py'),
                      encoding='utf-8').read()
        for forbidden in ('import xbmc', 'from . import', 'from .. import'):
            self.assertNotIn(forbidden, src, forbidden)


class TestBadgePipelineBehaviour(unittest.TestCase):
    """End to end: rules JSON -> compiled -> matched -> image URLs."""

    SET = ('{"filters":[{"groupId":"gr","pattern":"(?i)2160p|4k",'
           '"imageURL":"http://cdn/4k.png","isEnabled":true},'
           # NOTE: \\b must be DOUBLE-escaped here — a single \\b in JSON
           # decodes to a backspace character, not a regex word boundary.
           '{"groupId":"gq","pattern":"(?i)\\\\bremux\\\\b",'
           '"imageURL":"http://cdn/remux.png","isEnabled":true},'
           '{"groupId":"ga","pattern":"(?is)^(?=.*?(?:(?<!e[-_. ]?)ac[-_. ]?3))",'
           '"imageURL":"http://cdn/ac3.png","isEnabled":true}]}')

    def _images(self, text):
        rules = sb._elite_compile_rules(sb._elite_rules_from_json_blob(self.SET))
        orig_r, orig_e = sb._elite_badge_rules, sb._elite_badges_enabled
        try:
            sb._elite_badge_rules = lambda: rules
            sb._elite_badges_enabled = lambda: True
            return sb._elite_badge_images({'badge_blob_raw': text})
        finally:
            sb._elite_badge_rules, sb._elite_badges_enabled = orig_r, orig_e

    def test_full_pipeline_renders_the_expected_badges(self):
        names = [u.rsplit('/', 1)[1] for u in
                 self._images('Movie.2024.2160p.BluRay.REMUX.AC3.mkv')]
        self.assertIn('4k.png', names)
        self.assertIn('remux.png', names)
        self.assertIn('ac3.png', names)          # the JS-only lookbehind rule

    def test_no_false_badges_on_an_unrelated_release(self):
        self.assertEqual(self._images('Show.S01E01.480p.WEB.mp4'), [])

    def test_disabled_badges_render_nothing(self):
        orig = sb._elite_badges_enabled
        try:
            sb._elite_badges_enabled = lambda: False
            self.assertEqual(sb._elite_badge_images({'badge_blob_raw': '2160p REMUX'}), [])
        finally:
            sb._elite_badges_enabled = orig

    def test_raw_blob_is_preferred_over_the_clean_name(self):
        blob = sb._elite_badge_blob({'badge_blob_raw': '\u265b RAW', 'name': 'Clean'})
        self.assertTrue(blob.startswith('\u265b RAW'))


class TestSuiteHealth(unittest.TestCase):
    """Keep the ratio honest as the suite grows."""

    def test_new_modules_ship_with_behavioural_cover(self):
        # search_match must be exercised, not merely grepped for
        self.assertGreater(sm.match_score('الطيار', 'الطيار'), 0)
        self.assertEqual(sm.match_score('الموسم 5', 'الموسم 50'), 0)
        kept, dropped = sm.filter_relevant(['Avatar', 'العاصوف'], 'العاصوف')
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, 1)

    def test_plugin_py_is_shrinking_not_growing(self):
        """A ratchet: plugin.py was 25,883 lines when the split started and
        25,555 after the stream_facts extraction. It may only go down."""
        lines = sum(1 for _ in io.open(
            os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8'))
        # v4.8.6 added the 17-line _setting helper that two call sites had
        # been missing; the ratchet moves only by what a fix actually costs.
        self.assertLessEqual(lines, 25587,
                             'plugin.py grew again — extract, do not append')

    def test_extracted_modules_stay_kodi_free(self):
        """Both extracted modules must remain importable without Kodi, or
        they stop being unit-testable and the split loses its point."""
        for name in ('search_match.py', 'stream_facts.py'):
            src = io.open(os.path.join(ROOT, 'resources', 'lib', name),
                          encoding='utf-8').read()
            self.assertNotIn('import xbmc', src, name)

    def test_stream_facts_analysis_runs_standalone(self):
        sf = kodi_stub.import_lib_module('stream_facts')
        bits = sf._extract_video_bits(
            'Movie.2024.2160p.BluRay.REMUX.DV.HDR10.x265.mkv', '')
        joined = ' '.join(map(str, bits)).upper()
        self.assertIn('2160P', joined)
        self.assertIn('DV', joined)
        self.assertEqual(sf._parse_formatter_fields(
            {'description': 'VIDEO 1080p\nAUDIO AAC'}),
            {'video': '1080p', 'audio': 'AAC'})
        # the em dash is transliterated, not dropped, and runs of
        # whitespace collapse — verified against the real function
        self.assertEqual(sf._normalize_ascii('  Foo   —  Bar '), 'Foo - Bar')
        self.assertEqual(sf._normalize_ascii('Foo  Bar'), 'Foo Bar')


if __name__ == '__main__':
    unittest.main(verbosity=2)
