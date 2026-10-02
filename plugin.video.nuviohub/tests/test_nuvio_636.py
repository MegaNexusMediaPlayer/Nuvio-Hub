"""6.0.36: the update check looks at every component, not only the backend."""
import importlib
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()
import kodi_stub

settings = importlib.import_module('nuvio_ui.settings')
installer = importlib.import_module('resources.lib.bundle_installer')
restart = importlib.import_module('resources.lib.kodi_restart')


def row(aid, files, kodi=None, current=None, wanted='6.0.36'):
    return {'id': aid, 'wanted': wanted, 'files': files, 'kodi': kodi or files,
            'current': (files == wanted) if current is None else current}


class UpdateCheck(unittest.TestCase):
    def run_check(self, report, answer=False):
        dialog = mock.Mock()
        dialog.yesno.return_value = answer
        values = {}
        # Resolve the modules now: other suites may have replaced resources.lib.*
        live_installer = importlib.import_module('resources.lib.bundle_installer')
        live_restart = importlib.import_module('resources.lib.kodi_restart')
        with mock.patch.object(live_installer, 'component_report', return_value=report), \
                mock.patch.object(settings, 'ADDON', SimpleNamespace(setSetting=values.__setitem__)), \
                mock.patch.object(live_restart, 'plan', return_value=('Reboot', 'Reboot', '%s')), \
                mock.patch.object(settings.xbmc, 'executebuiltin') as builtin:
            settings.components_up_to_date('6.0.36', dialog, '6.0.36')
        return dialog, values, builtin

    def test_old_interface_is_not_called_up_to_date(self):
        report = [row('script.nuvio', '6.0.27'), row('skin.nuvio', '6.0.36'), row('screensaver.nuvio', '6.0.36')]
        dialog, values, builtin = self.run_check(report, answer=True)
        dialog.ok.assert_not_called()
        text = dialog.yesno.call_args.args[1]
        self.assertIn('interface 6.0.27', text)
        self.assertEqual(values[installer.VERSION_SETTING], '')   # the service installs it again
        builtin.assert_called_once_with('Reboot')                # platform restart (6.0.34)

    def test_kodi_still_running_the_old_version_needs_a_restart(self):
        report = [row('script.nuvio', '6.0.36', kodi='6.0.27'), row('skin.nuvio', '6.0.36')]
        dialog, values, builtin = self.run_check(report)
        self.assertIn('Kodi still uses interface 6.0.27', dialog.yesno.call_args.args[1])
        builtin.assert_not_called()

    def test_everything_current(self):
        dialog, _, _ = self.run_check([row('script.nuvio', '6.0.36'), row('skin.nuvio', '6.0.36')])
        dialog.ok.assert_called_once()
        self.assertIn('up to date', dialog.ok.call_args.args[1])
        dialog.yesno.assert_not_called()

    def test_maintenance_row_shows_an_older_interface(self):
        versions = {'plugin.video.nuviohub': '6.0.36', 'script.nuvio': '6.0.27'}
        with mock.patch.object(settings.xbmcaddon, 'Addon', side_effect=lambda aid: SimpleNamespace(getAddonInfo=lambda k: versions[aid])):
            self.assertEqual(settings.version_label(), '6.0.36 · interface 6.0.27')


class AutoInstall(unittest.TestCase):
    def test_a_failed_install_is_retried(self):
        addon = SimpleNamespace(getSetting=lambda k: '', setSetting=lambda k, v: None)
        monitor = SimpleNamespace(waitForAbort=lambda s: False)
        with mock.patch('xbmcaddon.Addon', return_value=addon), \
                mock.patch.object(installer, 'paths', return_value=('p', 'a')), \
                mock.patch.object(installer, 'backend_version', return_value='6.0.36'), \
                mock.patch.object(installer, 'outdated', return_value=['script.nuvio']), \
                mock.patch.object(installer, 'ensure_components', side_effect=[RuntimeError('Kodi has not discovered script.nuvio'), ['script.nuvio']]) as ensure, \
                mock.patch('xbmc.Player', return_value=SimpleNamespace(isPlayingVideo=lambda: False)), \
                mock.patch('xbmcgui.Window', return_value=SimpleNamespace(getProperty=lambda k: '')), \
                mock.patch('xbmcgui.Dialog'):
            self.assertEqual(installer.auto_install(monitor, wait=0, retry=0), ['script.nuvio'])
        self.assertEqual(ensure.call_count, 2)

    def test_waits_much_longer_than_an_hour_while_the_interface_is_open(self):
        import inspect
        defaults = inspect.signature(installer.auto_install).parameters
        self.assertGreaterEqual(defaults['attempts'].default * defaults['retry'].default, 24 * 3600)


if __name__ == '__main__':
    unittest.main()
