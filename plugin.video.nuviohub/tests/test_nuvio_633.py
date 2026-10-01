"""6.0.33: the MegaNexus skin survives updates and Android restarts."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
activation = importlib.import_module('resources.lib.skin_activation')
installer = importlib.import_module('resources.lib.bundle_installer')


class Settings:
    def __init__(self, **values):
        self.values = dict(values)

    def getSetting(self, key):
        return self.values.get(key, '')

    def setSetting(self, key, value):
        self.values[key] = value


class Kodi:
    """Addons.GetAddonDetails / SetAddonEnabled answers from a dict."""
    def __init__(self, addons):
        self.addons = addons
        self.enabled = []

    def rpc(self, request):
        request = json.loads(request)
        params = request['params']
        if request['method'] == 'Addons.GetAddonDetails':
            addon = self.addons.get(params['addonid'])
            return json.dumps({'result': {'addon': dict(addon, addonid=params['addonid'])}} if addon else {'error': {'message': 'not found'}})
        if request['method'] == 'Addons.SetAddonEnabled':
            self.enabled.append(params['addonid'])
            self.addons[params['addonid']]['enabled'] = True
            return json.dumps({'result': 'OK'})
        return json.dumps({'result': 'OK'})


def skin(version='6.0.33', script='6.0.33', script_enabled=True):
    return {'skin.nuvio': {'enabled': True, 'version': version,
                           'dependencies': [{'addonid': 'xbmc.gui', 'version': '5.17.0', 'optional': False},
                                            {'addonid': 'script.nuvio', 'version': version, 'optional': False}]},
            'script.nuvio': {'enabled': script_enabled, 'version': script, 'dependencies': []}}


class Checks(unittest.TestCase):
    def test_ready_skin_has_no_problem_and_disabled_parts_are_enabled(self):
        kodi = Kodi(skin(script_enabled=False))
        with mock.patch.object(activation.xbmc, 'executeJSONRPC', side_effect=kodi.rpc, create=True):
            self.assertEqual(activation._problem(), '')
        self.assertEqual(kodi.enabled, ['script.nuvio'])

    def test_old_interface_still_loaded_is_reported_not_hidden(self):
        kodi = Kodi(skin(script='6.0.32'))
        with mock.patch.object(activation.xbmc, 'executeJSONRPC', side_effect=kodi.rpc, create=True):
            problem = activation._problem()
        self.assertIn('script.nuvio 6.0.32', problem)
        self.assertIn('Restart Kodi', problem)

    def test_check_rescans_and_waits_for_the_new_version(self):
        kodi = Kodi(skin(script='6.0.32'))
        builtins = []
        def wait(seconds):
            kodi.addons['script.nuvio']['version'] = '6.0.33'
            return False
        with mock.patch.object(activation.xbmc, 'executeJSONRPC', side_effect=kodi.rpc, create=True), \
                mock.patch.object(activation.xbmc, 'executebuiltin', side_effect=builtins.append):
            self.assertEqual(activation.check(SimpleNamespace(waitForAbort=wait)), '')
        self.assertEqual(builtins, ['UpdateLocalAddons'])

    def test_missing_skin(self):
        with mock.patch.object(activation.xbmc, 'executeJSONRPC', side_effect=Kodi({}).rpc, create=True):
            self.assertIn('Install or repair', activation._problem())


class Persist(unittest.TestCase):
    def write(self, text):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'guisettings.xml'
        path.write_text(text, encoding='utf-8')
        return path

    def test_skin_is_written_at_once(self):
        path = self.write('<settings version="2">\n    <setting id="lookandfeel.skin" default="true">skin.estuary</setting>\n'
                          '    <setting id="audiooutput.volumesteps">90</setting>\n</settings>\n')
        with mock.patch('xbmcvfs.translatePath', return_value=str(path), create=True):
            self.assertTrue(activation.persist())
        root = ET.parse(path).getroot()
        node = next(n for n in root.iter('setting') if n.get('id') == 'lookandfeel.skin')
        self.assertEqual((node.text, node.get('default')), ('skin.nuvio', None))
        self.assertEqual(next(n for n in root.iter('setting') if n.get('id') == 'audiooutput.volumesteps').text, '90')
        self.assertFalse(Path(str(path) + '.meganexus-tmp').exists())

    def test_missing_setting_is_added_and_unknown_formats_are_left_alone(self):
        path = self.write('<settings version="2"></settings>')
        with mock.patch('xbmcvfs.translatePath', return_value=str(path), create=True):
            self.assertTrue(activation.persist())
        self.assertIn('skin.nuvio', path.read_text(encoding='utf-8'))
        old = self.write('<settings><lookandfeel><skin>skin.estuary</skin></lookandfeel></settings>')
        with mock.patch('xbmcvfs.translatePath', return_value=str(old), create=True):
            self.assertFalse(activation.persist())
        self.assertIn('skin.estuary', old.read_text(encoding='utf-8'))


class Restore(unittest.TestCase):
    def run_restore(self, applied='true', declined='', skin_dir='skin.estuary'):
        home = {}
        if declined:
            home[activation.DECLINED] = declined
        window = SimpleNamespace(getProperty=lambda k: home.get(k, ''), setProperty=home.__setitem__,
                                 clearProperty=lambda k: home.pop(k, None))
        monitor = SimpleNamespace(waitForAbort=lambda s: False)
        conditions = {'Window.IsActive(home)': True, 'System.HasModalDialog': False}
        with mock.patch.object(activation, '_home', return_value=window), \
                mock.patch.object(activation.xbmc, 'getSkinDir', return_value=skin_dir, create=True), \
                mock.patch.object(activation.xbmc, 'getCondVisibility', side_effect=lambda c: conditions.get(c, False)), \
                mock.patch.object(activation.xbmc, 'Player', return_value=SimpleNamespace(isPlayingVideo=lambda: False)), \
                mock.patch.object(activation, 'switch', return_value='ok') as switch:
            activation.restore_on_start(monitor, Settings(nuvio_skin_applied=applied), wait=0)
        return switch

    def test_lost_skin_is_restored_at_kodi_start(self):
        self.run_restore().assert_called_once()

    def test_not_chosen_declined_or_active_skin_is_left_alone(self):
        self.run_restore(applied='').assert_not_called()
        self.run_restore(declined='1').assert_not_called()
        self.run_restore(skin_dir='skin.nuvio').assert_not_called()

    def test_service_runs_the_check_after_component_sync(self):
        source = (ROOT / 'plugin.video.nuviohub/service.py').read_text(encoding='utf-8')
        self.assertLess(source.index('auto_install(mon, busy=_interactive_busy)'),
                        source.index('restore_on_start(mon, busy=_interactive_busy)'))


class SwitchOutcome(unittest.TestCase):
    def test_failed_switch_keeps_the_reason(self):
        with mock.patch.object(activation.xbmc, 'getSkinDir', return_value='skin.estuary', create=True), \
                mock.patch.object(activation, 'check', return_value='Kodi still uses script.nuvio 6.0.32'), \
                mock.patch.object(activation.xbmc, 'Monitor'):
            self.assertEqual(activation.switch(Settings()), 'failed')
        self.assertIn('6.0.32', activation.LAST_REASON[0])

    def test_hub_settings_switch_reports_failures(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/system_setup.py').read_text(encoding='utf-8')
        self.assertIn("if skin_activation.switch()=='failed':skin_activation.report_failure()", source)


class InstallerWaitsForTheNewVersion(unittest.TestCase):
    def test_old_version_still_loaded_requests_a_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            packages = Path(temp) / 'packages';packages.mkdir()
            (packages / 'bundle.json').write_text(json.dumps([{'id': a, 'version': '6.0.33'} for a in
                                                              ('script.nuvio', 'skin.nuvio', 'screensaver.nuvio')]))
            kodi = Kodi({'script.nuvio': {'enabled': True, 'version': '6.0.32'},
                         'skin.nuvio': {'enabled': True, 'version': '6.0.33'},
                         'screensaver.nuvio': {'enabled': True, 'version': '6.0.33'},
                         'plugin.video.nuvio': None})
            addon = SimpleNamespace(getAddonInfo=lambda k: str(Path(temp)) if k == 'path' else str(Path(temp) / 'profile'),
                                    getSetting=lambda k: 'true', setSetting=lambda k, v: None)
            (Path(temp) / 'resources').mkdir()
            (Path(temp) / 'resources/packages').symlink_to(packages)
            with mock.patch('xbmcaddon.Addon', return_value=addon), \
                    mock.patch('xbmcvfs.translatePath', side_effect=lambda p: temp, create=True), \
                    mock.patch.object(installer, 'install_components', return_value=[]), \
                    mock.patch('xbmc.executeJSONRPC', side_effect=kodi.rpc, create=True), \
                    mock.patch('xbmc.executebuiltin'), mock.patch('xbmc.getSkinDir', return_value='skin.nuvio', create=True), \
                    mock.patch('xbmc.Monitor', return_value=SimpleNamespace(waitForAbort=lambda s: False)), \
                    mock.patch('xbmc.Player', return_value=SimpleNamespace(isPlayingVideo=lambda: False)), \
                    mock.patch('xbmcgui.Window', return_value=SimpleNamespace(getProperty=lambda k: '')):
                changed = installer.ensure_components()
        self.assertEqual(changed, ['script.nuvio'])


if __name__ == '__main__':
    unittest.main()
