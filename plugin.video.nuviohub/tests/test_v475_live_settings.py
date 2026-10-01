# -*- coding: utf-8 -*-
"""v4.7.5 — "I change the URL and it reverts to the saved link and images."

The user's kodi.log settles it: after the URL was changed, three separate
picker opens all logged

    elite badges: source=custom rules=29 url=<the OLD default preset>

so the fetch and the parser were fine — the addon was still READING the
old value. Cause: reuselanguageinvoker=true keeps the plugin in a
long-lived Python process whose addon-settings copy is loaded once, while
the settings dialog saves in Kodi's MAIN process. The reused interpreter
therefore keeps returning the value it started with, and pasting a new
badges URL changes nothing until Kodi is restarted.

Fix: the service (a process Kodi notifies via onSettingsChanged)
republishes the live URL and toggle to window properties — global to Kodi
and never stale — and the badge code reads those first, with getSetting as
the fallback. '-' is the empty sentinel (window properties cannot hold a
distinct empty state).

Also pinned here, both found in the same log:
  * "Error resolving item ... cw_resume" on every Continue Watching play
    (40x): a resume position forces the picker path onto Player.play,
    abandoning the resolve context. 4.7.2 closed it at the play-dispatch
    handoff; this is the picker-side site it missed.
  * 486 identical "row dropped (no playable url)" INFO lines and 27
    repeats of the same Simkl network error in one session.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sb = kodi_stub.import_lib_module('source_browser')
import xbmcgui  # noqa: E402  (populated by kodi_stub)

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SERVICE = io.open(os.path.join(ROOT, 'service.py'), encoding='utf-8').read()
SIMKL = io.open(os.path.join(ROOT, 'resources', 'lib', 'simkl.py'), encoding='utf-8').read()


class TestLiveValueBridge(unittest.TestCase):
    def setUp(self):
        self.win = xbmcgui.Window(10000)
        self.win.clearProperty('nuviohub.badges.url')
        self.win.clearProperty('nuviohub.badges.enabled')

    tearDown = setUp

    def test_published_url_wins_over_the_stale_setting(self):
        self.win.setProperty('nuviohub.badges.url', 'https://new/set.json')
        self.assertEqual(sb._elite_badge_setting_url(), 'https://new/set.json')

    def test_empty_sentinel_means_unset(self):
        self.win.setProperty('nuviohub.badges.url', '-')
        self.assertEqual(sb._elite_badge_setting_url(), '')

    def test_falls_back_to_getsetting_when_unpublished(self):
        # no property (service not up yet) → the old path still answers
        self.assertIsInstance(sb._elite_badge_setting_url(), str)

    def test_toggle_uses_the_live_value_too(self):
        self.win.setProperty('nuviohub.badges.enabled', 'false')
        self.assertFalse(sb._elite_badges_enabled())
        self.win.setProperty('nuviohub.badges.enabled', 'true')
        self.assertTrue(sb._elite_badges_enabled())

    def test_service_publishes_on_startup_and_on_change(self):
        self.assertIn('def _publish_badge_props():', SERVICE)
        body = SERVICE.split('def _publish_badge_props():', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("setProperty('nuviohub.badges.url', url or '-')", body)
        self.assertIn("setProperty('nuviohub.badges.enabled'", body)
        changed = SERVICE.split('def onSettingsChanged(self):', 1)[1][:600]
        self.assertIn('_publish_badge_props()', changed)
        self.assertEqual(SERVICE.count('_publish_badge_props()'), 3)  # def + change + boot


class TestCwResumeResolveReverted(unittest.TestCase):
    """The 4.7.5 picker-side abort is reverted in 4.7.8 — see
    test_v478_badges_front_door for the full reasoning."""

    def test_picker_handoff_does_not_abort_the_resolve(self):
        marker = 'v4.7.8: reverted the 4.7.5 resolve-abort here'
        self.assertIn(marker, PLUGIN)
        seg = PLUGIN.split(marker, 1)[1][:600]
        self.assertNotIn('setResolvedUrl(HANDLE, False', seg)


class TestLogVolume(unittest.TestCase):
    def test_dropped_row_detail_is_capped_and_debug(self):
        seg = PLUGIN.split('_dropped_no_url += 1', 1)[1][:800]
        self.assertIn('if _dropped_no_url <= 3:', seg)
        self.assertIn('xbmc.LOGDEBUG', seg)
        self.assertNotIn("keys=%s' % (\n", seg.split('LOGDEBUG')[1][:200])

    def test_simkl_repeats_suppressed_for_an_hour(self):
        self.assertIn('_FAIL_LOG_MEMO = {}', SIMKL)
        seg = SIMKL.split('_sig = ', 1)[1][:600]
        self.assertIn('> 3600', seg)
        self.assertIn('LOGWARNING', seg)
        self.assertIn('(repeat)', seg)


if __name__ == '__main__':
    unittest.main(verbosity=2)
