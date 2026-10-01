"""6.0.25: removal works step by step; removed components are not reinstalled."""
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import zipfile
import frontend_test_support
frontend_test_support.install()
import kodi_stub
from test_nuvio_617 import FakeKodi, SOURCE

installer = importlib.import_module('resources.lib.bundle_installer')


class StepByStepRemoval(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.kodi = FakeKodi(self.home)
        copy = self.home / 'nuvio-uninstall-copy.py'
        shutil.copyfile(SOURCE, copy)
        spec = importlib.util.spec_from_file_location('nuvio_uninstall_copy625', copy)
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)

    def test_order_is_skin_screensaver_program_video(self):
        with mock.patch.dict(sys.modules, self.kodi.modules()):
            self.helper.run()
        self.assertEqual(self.kodi.disabled_order,
                         ['skin.nuvio', 'screensaver.nuvio', 'script.nuvio', 'plugin.video.nuviohub'])
        self.assertEqual(self.kodi.dialogs[-1][0], 'MegaNexus removed')

    def test_kept_settings_do_not_skip_the_next_first_start(self):
        with mock.patch.dict(sys.modules, self.kodi.modules()):
            self.helper.run()
        self.assertEqual(self.kodi.addon_settings, {'nuvio_skin_applied': '', 'nuvio_screensaver_applied': '', 'nuvio_components_for': ''})

    def test_a_locked_folder_is_retried(self):
        real = self.helper.stage_removal
        calls = []
        def flaky(root, ids, stage):
            calls.append(ids[0])
            if ids == ['script.nuvio'] and calls.count('script.nuvio') < 3:
                raise PermissionError('in use')
            return real(root, ids, stage)
        with mock.patch.dict(sys.modules, self.kodi.modules()), mock.patch.object(self.helper, 'stage_removal', flaky):
            self.helper.run()
        self.assertEqual(calls.count('script.nuvio'), 3)
        self.assertFalse((self.home / 'addons/script.nuvio').exists())
        self.assertEqual(self.kodi.dialogs[-1][0], 'MegaNexus removed')

    def test_a_failure_keeps_what_is_still_needed_and_says_what_is_left(self):
        real = self.helper.stage_removal
        def locked(root, ids, stage):
            if ids == ['script.nuvio']:
                raise PermissionError('in use')
            return real(root, ids, stage)
        with mock.patch.dict(sys.modules, self.kodi.modules()), mock.patch.object(self.helper, 'stage_removal', locked):
            self.helper.run()
        self.assertFalse((self.home / 'addons/skin.nuvio').exists())
        self.assertFalse((self.home / 'addons/screensaver.nuvio').exists())
        self.assertTrue((self.home / 'addons/script.nuvio').exists())
        self.assertTrue((self.home / 'addons/plugin.video.nuviohub').exists())
        self.assertTrue(self.kodi.enabled['script.nuvio'], 'the component that could not be removed is enabled again')
        title, text = self.kodi.dialogs[-1]
        self.assertEqual(title, 'MegaNexus removal')
        self.assertIn('Not removed: script.nuvio, plugin.video.nuviohub', text)
        self.assertEqual(self.kodi.props.get('nuvio.uninstalling'), None)


def make_packages(path, revision):
    path.mkdir(exist_ok=True)
    rows = []
    for aid in ('script.nuvio', 'skin.nuvio', 'screensaver.nuvio'):
        target = path / (aid + '.zip')
        with zipfile.ZipFile(target, 'w') as z:
            z.writestr(aid + '/addon.xml', '<addon id="%s" version="1.0.0"/>' % aid)
            z.writestr(aid + '/revision.txt', revision)
        rows.append({'id': aid, 'file': target.name, 'version': '1.0.0', 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    (path / 'bundle.json').write_text(json.dumps(rows), encoding='utf-8')


class NoReinstallAfterManualUninstall(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.packages, self.addons = base / 'packages', base / 'addons'
        make_packages(self.packages, 'first')
        self.version = '6.0.25'
        self.values, self.props = {}, {}
        addon = SimpleNamespace(getSetting=lambda k: self.values.get(k, ''), setSetting=lambda k, v: self.values.__setitem__(k, v))
        monitor = mock.Mock(waitForAbort=mock.Mock(return_value=False))
        self.monitor = monitor
        updater = importlib.import_module(installer.__package__ + '.updater')
        self.restart = mock.Mock()
        for patch in (mock.patch.object(updater, 'mark_pending'),
                      mock.patch.object(updater, 'prompt_when_safe', self.restart),
                      mock.patch.object(installer, 'paths', return_value=(self.packages, self.addons)),
                      mock.patch.object(installer, 'backend_version', side_effect=lambda p: self.version),
                      mock.patch('xbmcaddon.Addon', return_value=addon),
                      mock.patch('xbmc.Player', return_value=SimpleNamespace(isPlayingVideo=lambda: False)),
                      mock.patch('xbmcgui.Window', return_value=SimpleNamespace(getProperty=lambda k: self.props.get(k, ''))),
                      mock.patch('xbmcgui.Dialog'),
                      mock.patch.object(installer, 'ensure_components', side_effect=lambda force=False:
                                        installer.install_components(self.packages, self.addons, base / 'backups'))):
            patch.start();self.addCleanup(patch.stop)

    def test_first_install_then_user_uninstall_is_respected(self):
        self.assertEqual(len(installer.auto_install(self.monitor, attempts=2)), 3)
        self.assertEqual(self.values[installer.VERSION_SETTING], '6.0.25')
        shutil.rmtree(self.addons / 'skin.nuvio')  # uninstalled in Kodi by the user
        self.assertEqual(installer.auto_install(self.monitor, attempts=2), [])
        self.assertFalse((self.addons / 'skin.nuvio').exists())

    def test_an_update_installs_again(self):
        installer.auto_install(self.monitor, attempts=2)
        shutil.rmtree(self.addons / 'skin.nuvio')
        self.version = '6.0.26'
        make_packages(self.packages, 'second')
        self.assertEqual(len(installer.auto_install(self.monitor, attempts=2)), 3)
        self.assertEqual((self.addons / 'skin.nuvio/revision.txt').read_text(), 'second')
        self.restart.assert_called_once()  # 6.0.27: an update asks to restart Kodi

    def test_nothing_happens_during_a_removal(self):
        self.props['nuvio.uninstalling'] = '1'
        self.assertEqual(installer.auto_install(self.monitor, attempts=2), [])
        self.assertFalse((self.addons / 'script.nuvio').exists())


class FirstOpen(unittest.TestCase):
    """Opening the video add-on before installing: install, skin, then MegaNexus."""
    def setUp(self):
        self.bridge = importlib.import_module('resources.lib.frontend_bridge')
        # The harness can load backend modules under two names; patch the copies
        # the bridge itself imports.
        installer = importlib.import_module(self.bridge.__package__ + '.bundle_installer')
        self.installer = installer
        self.values, self.builtins, self.calls = {}, [], []
        addon = SimpleNamespace(getSetting=lambda k: self.values.get(k, ''), setSetting=lambda k, v: self.values.__setitem__(k, v))
        self.busy = mock.Mock()
        for patch in (mock.patch('xbmcaddon.Addon', return_value=addon),
                      mock.patch.object(installer, 'paths', return_value=('p', 'a')),
                      mock.patch.object(installer, 'outdated', return_value=['skin.nuvio']),
                      mock.patch.object(installer, 'ensure_components', side_effect=lambda force=False: self.calls.append('install')),
                      mock.patch.object(self.bridge.xbmcgui, 'DialogProgressBG', return_value=self.busy, create=True),
                      mock.patch.object(self.bridge.xbmc, 'executebuiltin', side_effect=self.builtins.append),
                      mock.patch.object(self.bridge.xbmc, 'getCondVisibility', return_value=False)):
            patch.start();self.addCleanup(patch.stop)
        self.activation = importlib.import_module(self.bridge.__package__ + '.skin_activation')

    def test_installs_then_skin_then_opens(self):
        def switch(addon):
            self.calls.append('skin');addon.setSetting('nuvio_skin_applied', 'true');return 'ok'
        with mock.patch.object(self.activation, 'wanted', return_value=True), \
                mock.patch.object(self.activation, 'switch', side_effect=switch):
            self.bridge.open_home()
        self.assertEqual(self.calls, ['install', 'skin'])
        self.busy.create.assert_called_once()
        self.busy.close.assert_called_once()
        self.assertEqual(self.values['nuvio_skin_applied'], 'true')
        self.assertEqual(self.builtins, ['RunScript(script.nuvio)'])

    def test_declined_skin_still_opens_and_is_not_marked(self):
        with mock.patch.object(self.activation, 'wanted', return_value=True), \
                mock.patch.object(self.activation, 'switch', return_value='declined'):
            self.bridge.open_home(settings=True)
        self.assertNotEqual(self.values.get('nuvio_skin_applied'), 'true')
        self.assertEqual(self.builtins, ['RunScript(script.nuvio,settings)'])

    def test_skin_is_checked_at_every_entry_not_only_the_first(self):
        # 6.0.33: Kodi lost the skin after an update/restart; the flag alone hid it.
        self.values['nuvio_skin_applied'] = 'true'
        with mock.patch.object(self.activation, 'wanted', return_value=True), \
                mock.patch.object(self.activation, 'switch', return_value='ok') as switch:
            self.bridge.open_home()
        switch.assert_called_once()

    def test_failed_switch_explains_why(self):
        with mock.patch.object(self.activation, 'wanted', return_value=True), \
                mock.patch.object(self.activation, 'switch', return_value='failed'), \
                mock.patch.object(self.activation, 'report_failure') as report:
            self.bridge.open_home()
        report.assert_called_once()
        self.assertEqual(self.builtins, ['RunScript(script.nuvio)'])

    def test_install_error_is_shown_and_nothing_opens(self):
        with mock.patch.object(self.installer, 'ensure_components', side_effect=RuntimeError('Kodi has not discovered skin.nuvio')), \
                mock.patch.object(self.bridge.xbmcgui, 'Dialog') as dialog:
            self.bridge.open_home()
        dialog.return_value.ok.assert_called_once()
        self.busy.close.assert_called_once()
        self.assertEqual(self.builtins, [])


if __name__ == '__main__':
    unittest.main()
