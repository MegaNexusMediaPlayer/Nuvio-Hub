"""6.0.19: restart question after an automatic update, never over video or Nuvio."""
import importlib
from pathlib import Path
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
updater = importlib.import_module('resources.lib.updater')


class Kodi:
    def __init__(self):
        self.props, self.settings, self.builtins = {}, {}, []
        self.playing = False
        self.answer = False
        self.questions = []

    def patches(self):
        window = SimpleNamespace(getProperty=lambda k: self.props.get(k, ''),
                                 setProperty=lambda k, v: self.props.__setitem__(k, v))
        dialog = mock.Mock()
        dialog.yesno.side_effect = lambda *a, **k: (self.questions.append(a[1]), self.answer)[1]
        return [mock.patch('xbmcgui.Window', return_value=window),
                mock.patch('xbmcgui.Dialog', return_value=dialog),
                mock.patch('xbmc.Player', return_value=SimpleNamespace(isPlayingVideo=lambda: self.playing)),
                mock.patch('xbmc.executebuiltin', side_effect=self.builtins.append)]

    def addon(self):
        return SimpleNamespace(getSetting=lambda k: self.settings.get(k, ''),
                               setSetting=lambda k, v: self.settings.__setitem__(k, v))


class RestartPrompt(unittest.TestCase):
    def setUp(self):
        self.kodi = Kodi()
        for patch in self.kodi.patches():
            patch.start()
            self.addCleanup(patch.stop)
        self.addon = self.kodi.addon()

    def test_yes_restarts_kodi_and_clears_the_reminder(self):
        updater.mark_pending(self.addon, '6.0.20')
        self.kodi.answer = True
        self.assertTrue(updater.prompt_at_entry(self.addon))
        self.assertEqual(self.kodi.builtins, ['RestartApp'])
        self.assertEqual(self.kodi.questions, ['Nuvio Hub 6.0.20 is installed. Restart Kodi now?'])
        self.assertEqual(updater.pending_version(self.addon), '')

    def test_later_keeps_the_reminder_for_the_next_entry(self):
        updater.mark_pending(self.addon, '6.0.20')
        self.assertFalse(updater.prompt_at_entry(self.addon))
        self.assertFalse(updater.prompt_at_entry(self.addon))
        self.assertEqual(len(self.kodi.questions), 2, 'asked again at every Nuvio entry')
        self.assertEqual(self.kodi.builtins, [])

    def test_not_over_a_video(self):
        updater.mark_pending(self.addon, '6.0.20')
        self.kodi.playing = True
        self.assertFalse(updater.prompt_at_entry(self.addon))
        self.assertEqual(self.kodi.questions, [])

    def test_service_waits_for_no_video_and_nuvio_closed_then_asks_once(self):
        updater.mark_pending(self.addon, '6.0.20')
        self.kodi.playing = True
        self.kodi.props['nuvio.frontend.running'] = 'x'
        waits = []

        def wait(seconds):
            waits.append(seconds)
            if len(waits) == 2:
                self.kodi.playing = False
            if len(waits) == 3:
                self.kodi.props.pop('nuvio.frontend.running')
            return False
        monitor = SimpleNamespace(abortRequested=lambda: False, waitForAbort=wait)
        self.assertFalse(updater.prompt_when_safe(self.addon, monitor, poll=0))
        self.assertEqual(len(waits), 3)
        self.assertEqual(len(self.kodi.questions), 1)
        self.assertFalse(updater.prompt_when_safe(self.addon, monitor, poll=0))
        self.assertEqual(len(self.kodi.questions), 1, 'the service asks once per Kodi session')

    def test_a_kodi_restart_clears_the_reminder(self):
        updater.mark_pending(self.addon, '6.0.20')
        self.kodi.props[updater.BOOT_PROPERTY] = 'new-session'
        self.assertEqual(updater.pending_version(self.addon), '')
        self.assertFalse(updater.prompt_at_entry(self.addon))
        self.assertEqual(self.kodi.questions, [])

    def test_automatic_install_marks_the_restart_instead_of_notifying(self):
        self.addon.getAddonInfo = lambda k: '6.0.19'
        with mock.patch.object(updater, 'latest', return_value={'version': '6.0.20', 'url': 'u', 'sha256_url': ''}), \
                mock.patch.object(updater, 'install'), \
                mock.patch('xbmcvfs.translatePath', side_effect=lambda p: p):
            self.assertEqual(updater.check_and_update(self.addon)[0], 'installed')
        self.assertEqual(updater.pending_version(self.addon), '6.0.20')
        self.assertEqual(self.kodi.questions, [], 'the service asks later, when it is safe')


class Wiring(unittest.TestCase):
    def test_service_uses_the_prompt_not_a_notification(self):
        source = (ROOT / 'plugin.video.nuviohub/service.py').read_text(encoding='utf-8')
        self.assertIn('updater.prompt_when_safe(_addon, mon)', source)
        self.assertNotIn('Restart Kodi to finish', source)

    def test_entry_asks_before_the_interface_opens(self):
        source = (ROOT / 'script.nuvio/default.py').read_text(encoding='utf-8')
        self.assertLess(source.index('updater.prompt_at_entry()'), source.index('    if not restarting:\n        launch()'))

    def test_pending_setting_is_declared(self):
        text = (ROOT / 'plugin.video.nuviohub/resources/settings.xml').read_text(encoding='utf-8')
        self.assertIn('id="nuvio_restart_pending"', text)


if __name__ == '__main__':
    unittest.main()
