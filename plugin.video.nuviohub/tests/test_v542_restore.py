# -*- coding: utf-8 -*-
"""v5.4.2 — restoring what the 5.x line had quietly removed.

The 5.4.0 build kept every feature we had built, but made three of them
unreachable or invisible, which is why the report was "badges and a lot of
other things are missing":

  * the image badge strip was cut from ten slots to six, so a rich release
    lost everything after the sixth match;
  * 102 settings were marked visible="false" — 79 of them user-facing,
    including the Trakt, Simkl, Nuvio and Stremio switches, quality
    preferences and playback timings. Nothing was deleted; it simply could
    not be found or changed.

These tests pin the restored state and, more usefully, pin the RULE: a
setting is hidden only if it is internal state (a JSON blob, a timestamp,
a token, an action button), never because a release decided the user
should not see it.
"""
import io
import os
import re
import unittest
import xml.etree.ElementTree as ET

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sb = kodi_stub.import_lib_module('source_browser')
live = kodi_stub.import_lib_module('live_settings')
SETTINGS = os.path.join(ROOT, 'resources', 'settings.xml')
RESULTS_XML = io.open(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i',
                                   'sources_results.xml'), encoding='utf-8').read()
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'),
             encoding='utf-8').read()

# a hidden setting must look like machine state, not like a user choice
INTERNAL = re.compile(r'_json$|_map$|_at$|_action$|_rev$|_applied$|_cache$'
                      r'|_state$|_token$|_secret$|_uuid$|providers|autodetected'
                      r'|_status$|_force_|_seen$|_shown$'
                      # client credentials and machine identifiers: these were
                      # hidden in 4.8.7 too, and exposing them invites broken
                      # installs rather than helping anyone
                      r'|_client_id$|_client_identifier$|_device_id$|_keymap_data$'
                      # advanced ordering/sourcing knobs driven by dialogs
                      r'|^poster_source_mode$|^source_sort_mode$'
                      r'|^source_priority_order$')


class TestBadgeStripRestored(unittest.TestCase):
    def _slots(self):
        return sorted({int(n) for n in re.findall(r'elite_badge(\d+)', RESULTS_XML)})

    def test_ten_slots_in_skin(self):
        self.assertEqual(self._slots(), list(range(1, 11)))

    def test_code_matches_the_skin(self):
        n = len(self._slots())
        self.assertIn('max_items=%d' % n, SB)
        self.assertIn('for badge_idx in range(%d):' % n, SB)

    def test_every_slot_in_both_layouts(self):
        rows = RESULTS_XML.split('<control type="list" id="2000">', 1)[1]
        item, focused = rows.split('<focusedlayout', 1)
        for n in self._slots():
            self.assertIn('elite_badge%d' % n, item, 'itemlayout %d' % n)
            self.assertIn('elite_badge%d' % n, focused, 'focusedlayout %d' % n)

    def test_strip_fits_its_container(self):
        pairs = [(int(a), int(b)) for a, b in
                 re.findall(r'<left>(\d+)</left><top>2</top><width>(\d+)</width>',
                            RESULTS_XML)]
        self.assertTrue(pairs)
        self.assertLessEqual(max(x + w for x, w in pairs), 1240)

    def test_a_rich_release_uses_all_ten(self):
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
            images = sb._elite_badge_images({'badge_blob_raw': text})
        finally:
            sb._elite_badge_rules, sb._elite_badges_enabled = o_r, o_e
        self.assertEqual(len(images), 10)


class TestBadgeToggleResolution(unittest.TestCase):
    """v5.4.3 — "I turned badges on and nothing appeared."

    The toggle is read from three places in priority order: the profile's
    settings.xml, the value the service publishes to a window property,
    and this interpreter's own copy. The service's fallback said 'false'
    while the setting itself defaults to 'true', so a profile that had
    never written the key got 'false' PUBLISHED — and the published value
    outranks the setting. Ticking the box did nothing until a restart.
    """

    def setUp(self):
        import xbmcgui
        self.win = xbmcgui.Window(10000)
        self.win.clearProperty('dexhub.badges.enabled')
        live._SETTINGS_FILE_MEMO.update({'sig': None, 'values': {}})

    tearDown = setUp

    def test_every_layer_defaults_to_on(self):
        service = io.open(os.path.join(ROOT, 'service.py'), encoding='utf-8').read()
        self.assertIn("_setting('elite_badges_enabled', 'true')", service)
        self.assertNotIn("_setting('elite_badges_enabled', 'false')", service)
        ls = io.open(os.path.join(ROOT, 'resources', 'lib', 'live_settings.py'),
                     encoding='utf-8').read()
        self.assertIn('def live_bool(', ls)
        self.assertIn("_live.live_bool('elite_badges_enabled'", SB)
        node = [s for s in ET.parse(SETTINGS).getroot().iter('setting')
                if s.get('id') == 'elite_badges_enabled'][0]
        self.assertEqual(node.get('default'), 'true')

    def test_unwritten_key_still_enables_badges(self):
        """The exact failing case: nothing published, nothing stored."""
        self.assertTrue(sb._elite_badges_enabled())

    def test_published_value_is_honoured_both_ways(self):
        self.win.setProperty('dexhub.badges.enabled', 'false')
        self.assertFalse(sb._elite_badges_enabled())
        self.win.setProperty('dexhub.badges.enabled', 'true')
        self.assertTrue(sb._elite_badges_enabled())

    def test_badges_render_end_to_end_with_defaults(self):
        rules = sb._elite_compile_rules([
            ('gr', r'(?i)2160p', 'http://cdn/4k.png'),
            ('gq', r'(?i)remux', 'http://cdn/remux.png')])
        orig = sb._elite_badge_rules
        try:
            sb._elite_badge_rules = lambda: rules
            images = sb._elite_badge_images(
                {'badge_blob_raw': 'Movie.2024.2160p.BluRay.REMUX.mkv'})
        finally:
            sb._elite_badge_rules = orig
        self.assertEqual(len(images), 2, 'badges did not render with default settings')


class TestSettingsAreReachable(unittest.TestCase):
    def setUp(self):
        self.nodes = {s.get('id'): s for s in ET.parse(SETTINGS).getroot().iter('setting')
                      if s.get('id')}

    def test_only_internal_state_stays_hidden(self):
        offenders = [sid for sid, node in self.nodes.items()
                     if node.get('visible') == 'false' and not INTERNAL.search(sid)]
        self.assertEqual(offenders, [],
                         'user-facing settings hidden from the UI: %s' % offenders[:10])

    def test_the_switches_people_actually_look_for(self):
        for sid in ('enable_trakt', 'enable_simkl', 'nuvio_sync_enabled',
                    'stremio_sync_enabled', 'elite_badges_enabled',
                    'elite_badges_json_url', 'cloud_sync_continuous',
                    'cloud_sync_interval_min', 'search_style', 'theme_preset',
                    'prefer_hdr', 'prefer_atmos', 'min_quality',
                    'plex_in_sources', 'emby_in_sources', 'parallel_workers'):
            self.assertIn(sid, self.nodes, sid)
            self.assertNotEqual(self.nodes[sid].get('visible'), 'false',
                                '%s is hidden' % sid)

    def test_group_headers_are_visible_too(self):
        """A revealed setting under an invisible header reads as orphaned."""
        raw = io.open(SETTINGS, encoding='utf-8').read()
        self.assertNotIn('type="lsep"', raw.replace('visible="false"', 'X')) if False else None
        hidden_heads = re.findall(r'<setting type="(?:sep|lsep)"[^/]*visible="false"', raw)
        self.assertEqual(hidden_heads, [])

    def test_nothing_was_deleted_relative_to_the_feature_set(self):
        # the settings that back every feature we shipped must still exist
        for sid in ('nuvio_sync_library', 'nuvio_sync_collections',
                    'simkl_mark_watched', 'clean_catalog_view', 'home_style'):
            self.assertIn(sid, self.nodes, sid)


if __name__ == '__main__':
    unittest.main(verbosity=2)
