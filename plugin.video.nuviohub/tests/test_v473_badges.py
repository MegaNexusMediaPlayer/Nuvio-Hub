# -*- coding: utf-8 -*-
"""v4.7.3 — custom badges.json: match the text the presets were WRITTEN for.

The user's report "I paste a new set URL and nothing changes" survived the
4.7.2 fetch hardening because the remaining failure was silent at the
MATCHING layer: BetterFormatter presets (the settings default is one)
gate their quality rules on the ♛ crown marker of AIOStreams' FORMATTED
output — e.g. pattern (?i)^(?=.*♛)(?=.*remux) — but the badge blob was
built from the CLEANED display name with the markers stripped, so those
rules could never match and the screen kept looking like the old set.

Fixes pinned here:
  1. every finalized row carries badge_blob_raw (the raw stream texts via
     _collect_stream_texts) and the blob consumes it FIRST;
  2. rule loading logs its resolution (custom / disk-lastgood /
     builtin-after-fail) so kodi.log answers "which rules am I on?";
  3. a one-time success toast when a custom URL applies (failure already
     warns), and the service reloads + toasts IMMEDIATELY on URL change
     via onSettingsChanged — success and silent-fallback are no longer
     indistinguishable.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sb_mod = kodi_stub.import_lib_module('source_browser')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()
SERVICE = io.open(os.path.join(ROOT, 'service.py'), encoding='utf-8').read()

# Two REAL entries from the settings-default preset
# (9mousaa/BetterFormatter/presets/mono-bgb-sep-nodv.json @ HEAD).
REAL_PRESET = ('{"filters": ['
               '{"borderColor": "#FF858283", "groupId": "gq", "id": "q-br",'
               ' "imageURL": "https://raw.githubusercontent.com/9mousaa/BetterFormatter/main/images/mono-best-remux.png",'
               ' "isEnabled": true, "name": "Best Remux",'
               ' "pattern": "(?i)^(?=.*\\u265b)(?=.*remux)",'
               ' "tagColor": "#33FFFFFF", "type": "filter"},'
               '{"borderColor": "#FF858283", "groupId": "gr", "id": "r-4k",'
               ' "imageURL": "https://raw.githubusercontent.com/9mousaa/BetterFormatter/main/images/mono-2160p.png",'
               ' "isEnabled": true, "name": "2160p",'
               ' "pattern": "(?i)2160p|4k", "type": "filter"}],'
               ' "groups": [{"id": "gq", "name": "Quality"}]}')


class TestRealPresetParsesAndMatches(unittest.TestCase):
    def test_real_schema_parses(self):
        rules = sb_mod._elite_rules_from_json_blob(REAL_PRESET)
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0][0], 'gq')
        self.assertIn('\u265b', rules[0][1])

    def test_crown_rule_needs_the_raw_text(self):
        rules = sb_mod._elite_rules_from_json_blob(REAL_PRESET)
        crown = rules[0][1]
        raw = '\u265b PRE | 4K REMUX HDR | seeders 120'
        cleaned = 'PRE 4K REMUX HDR'
        self.assertTrue(sb_mod._elite_pattern_matches(crown, raw))
        self.assertFalse(sb_mod._elite_pattern_matches(crown, cleaned))

    def test_blob_consumes_raw_first_and_row_carries_it(self):
        row = {'badge_blob_raw': '\u265b X | REMUX', 'name': 'Clean Name'}
        blob = sb_mod._elite_badge_blob(row)
        self.assertTrue(blob.startswith('\u265b X | REMUX'))
        # finalize attaches it from the raw stream texts
        self.assertIn("'badge_blob_raw': ' | '.join(_collect_stream_texts(row))[:4096]",
                      PLUGIN)

    def test_end_to_end_images_for_a_crown_row(self):
        orig = sb_mod._elite_badge_rules
        orig_enabled = sb_mod._elite_badges_enabled
        try:
            sb_mod._elite_badge_rules = lambda: sb_mod._elite_rules_from_json_blob(REAL_PRESET)
            sb_mod._elite_badges_enabled = lambda: True
            row = {'badge_blob_raw': '\u265b GROUP | 2160p REMUX', 'name': 'x'}
            images = sb_mod._elite_badge_images(row)
        finally:
            sb_mod._elite_badge_rules = orig
            sb_mod._elite_badges_enabled = orig_enabled
        self.assertEqual(len(images), 2)          # crown-remux + 2160p
        self.assertTrue(all(u.startswith('https://') for u in images))


class TestDiagnosticsAndFeedback(unittest.TestCase):
    def test_rule_load_logs_every_resolution(self):
        body = SB.split('def _elite_badge_rules():', 1)[1].split('def _elite_notify', 1)[0]
        self.assertIn('source=custom via=%s rules=%d', body)
        self.assertIn('source=disk-lastgood rules=%d', body)
        self.assertIn('source=builtin-after-fail', body)

    def test_success_toast_once_per_url(self):
        self.assertIn('def _elite_notify_custom_applied_once(url, count):', SB)
        body = SB.split('def _elite_notify_custom_applied_once(url, count):', 1)[1]
        body = body.split('\ndef ', 1)[0]
        self.assertIn("'applied_url'", body)
        self.assertIn('NOTIFICATION_INFO', body)
        rules_body = SB.split('def _elite_badge_rules():', 1)[1].split('def _elite_rules_disk_path', 1)[0]
        self.assertIn('_elite_notify_custom_applied_once(url, len(rules))', rules_body)

    def test_service_reloads_instantly_on_url_change(self):
        self.assertIn('def onSettingsChanged(self):', SERVICE)
        seg = SERVICE.split('def onSettingsChanged(self):', 1)[1][:1400]
        self.assertIn("elite_badges_json_url", seg)
        self.assertIn('_ELITE_BADGE_RULE_CACHE.clear()', seg)
        self.assertIn('_elite_badge_rules()', seg)
        # the plain Monitor must have been replaced, not duplicated
        self.assertIn('monitor = _NuvioHubMonitor()', SERVICE)
        self.assertNotIn('monitor = xbmc.Monitor()', SERVICE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
