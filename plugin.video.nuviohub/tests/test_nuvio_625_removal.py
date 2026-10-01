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
        for patch in (mock.patch.object(installer, 'paths', return_value=(self.packages, self.addons)),
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

    def test_nothing_happens_during_a_removal(self):
        self.props['nuvio.uninstalling'] = '1'
        self.assertEqual(installer.auto_install(self.monitor, attempts=2), [])
        self.assertFalse((self.addons / 'script.nuvio').exists())


if __name__ == '__main__':
    unittest.main()
