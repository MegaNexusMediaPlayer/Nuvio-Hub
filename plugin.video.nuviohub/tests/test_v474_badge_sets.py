# -*- coding: utf-8 -*-
"""v4.7.4 — "I switch to a different badges source and nothing changes;
the first set acts mandatory."

Root cause (reproduced against the parser directly): the JSON reader
accepted exactly ONE shape — a {'filters': [...]} object whose entries
carry the literal keys 'pattern' and 'imageURL'. Every other convention
in the wild — a top-level array, those collections keyed by rule id,
rules nested under their group, or the same data under regex/match/
icon/url names — parsed to an empty rule list, and an empty list falls
back to the BUILT-IN rules. That fallback is why the first set looked
forced: the screen kept rendering built-in art no matter what URL was
pasted, with nothing to distinguish it from success.

Two amplifiers fixed with it:
  * the DEFAULT url short-circuited straight to the builtin rules and was
    never fetched, so "default" and "failed custom" were the same picture;
  * unknown group ids were capped at ONE badge each, truncating any
    third-party set to a handful of images.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sb = kodi_stub.import_lib_module('source_browser')
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()

RULE = ('gq', '(?i)remux', 'http://x/a.png')


class TestSchemaTolerance(unittest.TestCase):
    """Every one of these returned EMPTY before 4.7.4."""

    def test_betterformatter_object(self):
        self.assertEqual(sb._elite_rules_from_json_blob(
            '{"filters":[{"groupId":"gq","pattern":"(?i)remux",'
            '"imageURL":"http://x/a.png","isEnabled":true}]}'), [RULE])

    def test_top_level_array(self):
        self.assertEqual(sb._elite_rules_from_json_blob(
            '[{"groupId":"gq","pattern":"(?i)remux","imageURL":"http://x/a.png"}]'),
            [RULE])

    def test_collection_keyed_by_rule_id(self):
        self.assertEqual(sb._elite_rules_from_json_blob(
            '{"filters":{"r1":{"groupId":"gq","pattern":"(?i)remux",'
            '"imageURL":"http://x/a.png"}}}'), [RULE])

    def test_rules_nested_under_their_group(self):
        self.assertEqual(sb._elite_rules_from_json_blob(
            '{"groups":[{"id":"gq","filters":[{"pattern":"(?i)remux",'
            '"imageURL":"http://x/a.png"}]}]}'), [RULE])

    def test_key_aliases(self):
        for blob in ('{"filters":[{"group":"gq","regex":"(?i)remux","icon":"http://x/a.png"}]}',
                     '{"badges":[{"category":"gq","match":"(?i)remux","url":"http://x/a.png"}]}',
                     '{"rules":[{"groupId":"gq","expr":"(?i)remux","image":"http://x/a.png"}]}'):
            self.assertEqual(sb._elite_rules_from_json_blob(blob), [RULE], blob[:40])

    def test_disabled_and_incomplete_entries_skipped(self):
        self.assertEqual(sb._elite_rules_from_json_blob(
            '{"filters":[{"groupId":"gq","pattern":"(?i)x","imageURL":"http://x/a.png",'
            '"isEnabled":false}]}'), [])
        self.assertEqual(sb._elite_rules_from_json_blob(
            '{"filters":[{"groupId":"gq","pattern":"(?i)x"}]}'), [])   # no image
        self.assertEqual(sb._elite_rules_from_json_blob(
            '{"filters":[{"groupId":"gq","imageURL":"http://x/a.png"}]}'), [])  # no pattern

    def test_malformed_input_never_raises(self):
        for blob in ('not json', '', None, '[]', '{}', '{"filters":null}', '3'):
            self.assertEqual(sb._elite_rules_from_json_blob(blob), [])

    def test_duplicates_collapsed(self):
        blob = ('[{"groupId":"gq","pattern":"(?i)remux","imageURL":"http://x/a.png"},'
                '{"groupId":"gq","pattern":"(?i)remux","imageURL":"http://x/a.png"}]')
        self.assertEqual(sb._elite_rules_from_json_blob(blob), [RULE])


class TestSwitchingSetsActuallyChangesArt(unittest.TestCase):
    """The end-to-end property the report was about."""

    ROW = {'badge_blob_raw': '\u265b GRP | 2160p REMUX ATMOS', 'name': 'x'}

    def _images(self, blob):
        orig_rules, orig_on = sb._elite_badge_rules, sb._elite_badges_enabled
        try:
            sb._elite_badge_rules = lambda: sb._elite_rules_from_json_blob(blob)
            sb._elite_badges_enabled = lambda: True
            return sb._elite_badge_images(dict(self.ROW))
        finally:
            sb._elite_badge_rules, sb._elite_badges_enabled = orig_rules, orig_on

    def test_two_sets_render_their_own_art(self):
        set_a = ('{"filters":[{"groupId":"gq","pattern":"(?i)remux","imageURL":"http://A/remux.png"},'
                 '{"groupId":"gr","pattern":"(?i)2160p","imageURL":"http://A/4k.png"}]}')
        set_b = ('[{"group":"gq","regex":"(?i)remux","icon":"http://B/remux.png"},'
                 '{"group":"gr","regex":"(?i)2160p","icon":"http://B/4k.png"},'
                 '{"group":"ga","regex":"(?i)atmos","icon":"http://B/atmos.png"}]')
        images_a = self._images(set_a)
        images_b = self._images(set_b)
        self.assertEqual(images_a, ['http://A/remux.png', 'http://A/4k.png'])
        self.assertEqual(len(images_b), 3)
        self.assertTrue(all(u.startswith('http://B/') for u in images_b))
        self.assertFalse(set(images_a) & set(images_b))

    def test_unknown_groups_allow_more_than_one_badge(self):
        blob = ('[{"group":"gq","regex":"(?i)remux","icon":"http://B/1.png"},'
                '{"group":"gq","regex":"(?i)2160p","icon":"http://B/2.png"}]')
        self.assertEqual(len(self._images(blob)), 2)
        self.assertEqual(sb._ELITE_GROUP_LIMITS.get('source'), 1)   # tuned ones kept


class TestDefaultUrlIsFetchedLikeAnyOther(unittest.TestCase):
    def test_no_short_circuit_on_the_default_url(self):
        body = SB.split('def _elite_badge_rules():', 1)[1].split('def _elite_rules_disk_path', 1)[0]
        self.assertNotIn('url == _ELITE_BADGE_DEFAULT_JSON_URL', body)
        self.assertIn('if not url:', body)          # builtin only when unset

    def test_url_change_resets_the_once_guards(self):
        body = SB.split('def _elite_badge_rules():', 1)[1].split('def _elite_rules_disk_path', 1)[0]
        self.assertIn("for key in ('applied_url', 'warned_url', 'fail_url'):", body)

    def test_log_states_which_set_is_live(self):
        self.assertIn('source=custom via=%s rules=%d sample=%s', SB)


if __name__ == '__main__':
    unittest.main(verbosity=2)
