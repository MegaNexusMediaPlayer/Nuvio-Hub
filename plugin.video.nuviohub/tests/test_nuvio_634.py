"""6.0.34: after an update, reboot on CoreELEC/LibreELEC, close Kodi on Android
and Apple, restart on Windows/Linux."""
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()
import kodi_stub

restart = importlib.import_module('resources.lib.kodi_restart')
updater = importlib.import_module('resources.lib.updater')


def kind(true=(), os_release=''):
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'os-release'
        path.write_text(os_release, encoding='utf-8')
        with mock.patch.object(restart.xbmc, 'getCondVisibility', side_effect=lambda c: c in true):
            return restart.platform_kind(str(path))


class Platforms(unittest.TestCase):
    def test_coreelec_and_libreelec_reboot(self):
        self.assertEqual(kind({'System.Platform.Linux'}, 'NAME="CoreELEC"\nID=coreelec\n'), 'elec')
        self.assertEqual(kind({'System.Platform.Linux'}, 'ID=libreelec\n'), 'elec')
        self.assertEqual(kind({'System.Platform.Linux', 'System.HasAddon(service.coreelec.settings)'}), 'elec')
        self.assertEqual(restart.plan('elec')[0], 'Reboot')

    def test_android_is_not_mistaken_for_linux(self):
        self.assertEqual(kind({'System.Platform.Android', 'System.Platform.Linux'}, 'ID=coreelec\n'), 'android')
        self.assertEqual(restart.plan('android')[:2], ('Quit', 'Close Kodi'))

    def test_apple_closes_and_pc_restarts(self):
        self.assertEqual(kind({'System.Platform.Darwin', 'System.Platform.OSX'}), 'apple')
        self.assertEqual(restart.plan('apple')[0], 'Quit')
        self.assertEqual(kind({'System.Platform.Windows'}), 'windows')
        self.assertEqual(kind({'System.Platform.Linux'}, 'ID=ubuntu\nID_LIKE=debian\n'), 'linux')
        for k in ('windows', 'linux', 'other'):
            self.assertEqual(restart.plan(k)[0], 'RestartApp')


class Prompt(unittest.TestCase):
    def ask(self, kind_name, answer=True):
        builtins, questions, settings = [], [], {}
        addon = SimpleNamespace(setSetting=settings.__setitem__)
        dialog = SimpleNamespace(yesno=lambda title, text, nolabel='', yeslabel='': questions.append((text, yeslabel)) or answer)
        with mock.patch.object(restart, 'platform_kind', return_value=kind_name), \
                mock.patch('xbmcgui.Dialog', return_value=dialog), \
                mock.patch('xbmcgui.Window', return_value=SimpleNamespace(setProperty=lambda k, v: None)), \
                mock.patch('xbmc.executebuiltin', side_effect=builtins.append):
            result = updater.prompt_restart(addon, '6.0.34')
        return result, builtins, questions

    def test_coreelec_reboots_instead_of_restarting_kodi(self):
        result, builtins, questions = self.ask('elec')
        self.assertTrue(result)
        self.assertEqual(builtins, ['Reboot'])
        self.assertEqual(questions[0][1], 'Reboot')
        self.assertIn('Reboot the box', questions[0][0])

    def test_android_closes_kodi_and_says_to_open_it_again(self):
        _, builtins, questions = self.ask('android')
        self.assertEqual(builtins, ['Quit'])
        self.assertIn('open Kodi again', questions[0][0])

    def test_later_does_nothing(self):
        result, builtins, _ = self.ask('elec', answer=False)
        self.assertFalse(result)
        self.assertEqual(builtins, [])


if __name__ == '__main__':
    unittest.main()
