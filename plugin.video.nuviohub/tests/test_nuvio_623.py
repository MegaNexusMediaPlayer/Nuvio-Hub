"""6.0.23: Ko-fi on the phone page, Cinemeta always installed, automatic component install."""
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import zipfile
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
setup = importlib.import_module('resources.lib.default_setup')
installer = importlib.import_module('resources.lib.bundle_installer')
phone = importlib.import_module('resources.lib.phone_setup')


class KoFiButton(unittest.TestCase):
    def test_phone_header_links_to_kofi_safely(self):
        page = (ROOT / 'plugin.video.nuviohub/resources/phone_setup/index.html').read_text(encoding='utf-8')
        header = page[page.index('<header>'):page.index('</header>')]
        self.assertIn('href="https://ko-fi.com/master100janovic"', header)
        self.assertIn('rel="noopener noreferrer"', header)
        self.assertIn('target="_blank"', header)
        self.assertIn('<svg', header)


class CinemetaAlwaysInstalled(unittest.TestCase):
    def test_added_off_when_new_and_untouched_when_present(self):
        store = importlib.import_module('resources.lib.nuviohub.store')
        client = importlib.import_module('resources.lib.nuviohub.client')
        meta = importlib.import_module('resources.lib.metadata_providers')
        added = {'id': 'cm', 'manifest': {'id': setup.CINEMETA_ID}}
        with mock.patch.object(store, 'list_providers', return_value=[]), \
                mock.patch.object(client, 'get_json', side_effect=OSError('offline')), \
                mock.patch.object(store, 'add_provider', return_value=added) as add, \
                mock.patch.object(meta, 'set_enabled') as switch, \
                mock.patch.object(meta, 'enabled', return_value=[]):
            self.assertIs(setup.add_cinemeta_off(), added)
        add.assert_called_once()  # offline: bundled manifest
        switch.assert_called_once_with('cm', False)
        with mock.patch.object(store, 'list_providers', return_value=[added]), \
                mock.patch.object(meta, 'set_enabled') as switch, \
                mock.patch.object(meta, 'enabled', return_value=[]):
            setup.add_cinemeta_off()
        switch.assert_not_called()  # an existing Cinemeta keeps the user's switch

    def test_phone_switch_of_cinemeta_is_a_manual_choice(self):
        values = {}
        addon = SimpleNamespace(getSetting=lambda k: values.get(k, ''), setSetting=lambda k, v: values.__setitem__(k, v))
        module = mock.Mock()
        cinemeta = {'id': 'cm', 'manifest': {'id': setup.CINEMETA_ID}}
        module.entries.return_value = [(cinemeta, True), ({'id': 'aio', 'manifest': {'id': 'aio'}}, True)]
        with mock.patch.object(phone, '_addon', return_value=addon):
            phone._apply_switches(module, [{'id': 'cm', 'enabled': False}, {'id': 'aio', 'enabled': False}], phone._manual_cinemeta)
            self.assertEqual(values[setup.CINEMETA_AUTO], 'off')
            module.entries.return_value = [(cinemeta, False)]
            phone._apply_switches(module, [{'id': 'cm', 'enabled': True}], phone._manual_cinemeta)
            self.assertEqual(values[setup.CINEMETA_AUTO], '')


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


class AutomaticInstall(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.packages, self.addons = base / 'packages', base / 'addons'
        make_packages(self.packages, 'first')
        patch = mock.patch.object(installer, 'paths', return_value=(self.packages, self.addons));patch.start();self.addCleanup(patch.stop)
        self.playing = False;self.front = ''
        self.monitor = mock.Mock(waitForAbort=mock.Mock(return_value=False))
        stack = [mock.patch('xbmc.Player', return_value=SimpleNamespace(isPlayingVideo=lambda: self.playing)),
                 mock.patch('xbmcgui.Window', return_value=SimpleNamespace(getProperty=lambda k: self.front)),
                 mock.patch('xbmcgui.Dialog')]
        for p in stack:
            p.start();self.addCleanup(p.stop)
        self.ensure = mock.patch.object(installer, 'ensure_components',
                                        side_effect=lambda force=False: installer.install_components(self.packages, self.addons, base / 'backups'))
        self.ensure.start();self.addCleanup(self.ensure.stop)

    def test_outdated_lists_components_that_differ(self):
        self.assertEqual(sorted(installer.outdated(self.packages, self.addons)), ['screensaver.nuvio', 'script.nuvio', 'skin.nuvio'])
        installer.install_components(self.packages, self.addons, self.addons.parent / 'b')
        self.assertEqual(installer.outdated(self.packages, self.addons), [])

    def test_update_installs_without_install_or_repair(self):
        self.assertEqual(len(installer.auto_install(self.monitor, attempts=3)), 3)
        self.assertEqual((self.addons / 'skin.nuvio/revision.txt').read_text(), 'first')
        make_packages(self.packages, 'second')  # the backend was updated
        self.assertEqual(len(installer.auto_install(self.monitor, attempts=3)), 3)
        self.assertEqual((self.addons / 'script.nuvio/revision.txt').read_text(), 'second')
        self.assertEqual(installer.auto_install(self.monitor, attempts=3), [])  # up to date: nothing

    def test_waits_while_video_plays_or_the_interface_is_open(self):
        self.playing = True
        self.assertEqual(installer.auto_install(self.monitor, attempts=2), [])
        self.playing, self.front = False, 'token'
        self.assertEqual(installer.auto_install(self.monitor, attempts=2), [])
        self.assertFalse((self.addons / 'script.nuvio').exists())
        self.front = ''
        self.assertEqual(len(installer.auto_install(self.monitor, attempts=2, busy=lambda: False)), 3)

    def test_abort_stops_waiting(self):
        self.monitor.waitForAbort.return_value = True
        self.assertEqual(installer.auto_install(self.monitor), [])
        self.assertFalse((self.addons / 'script.nuvio').exists())

    def test_service_starts_the_component_thread(self):
        service = (ROOT / 'plugin.video.nuviohub/service.py').read_text(encoding='utf-8')
        self.assertIn("target=_component_sync", service)
        self.assertIn('auto_install(mon, busy=_interactive_busy)', service)


if __name__ == '__main__':
    unittest.main()
