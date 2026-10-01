"""6.0.17: 'Remove Nuvio build' works as the standalone script Kodi really runs."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
SOURCE = ROOT / 'plugin.video.nuviohub/resources/lib/nuvio_uninstall.py'
BUNDLE_DEPS = {'plugin.video.nuviohub': [], 'script.nuvio': ['plugin.video.nuviohub'],
               'skin.nuvio': ['script.nuvio'], 'screensaver.nuvio': ['script.nuvio'], 'skin.estuary': []}


class FakeKodi:
    """Enforces Kodi's rules: no disabling an add-on that an enabled add-on
    needs, nor the active skin or screensaver."""

    def __init__(self, home):
        self.home = Path(home)
        self.enabled = {aid: True for aid in BUNDLE_DEPS}
        self.settings = {'screensaver.mode': 'screensaver.nuvio', 'lookandfeel.skin': 'skin.nuvio'}
        self.disabled_order, self.builtins, self.dialogs, self.props = [], [], [], {}
        for aid in BUNDLE_DEPS:
            (self.home / 'addons' / aid).mkdir(parents=True)
            (self.home / 'addons' / aid / 'addon.xml').write_text('<addon id="%s" version="1"/>' % aid)

    def rpc(self, raw):
        request = json.loads(raw)
        method, params = request['method'], request.get('params') or {}
        def ok(result):
            return json.dumps({'result': result})
        def error():
            return json.dumps({'error': {'message': 'refused'}})
        if method == 'Addons.GetAddons':
            rows = [{'addonid': aid, 'enabled': self.enabled[aid], 'path': '',
                     'dependencies': [{'addonid': d} for d in deps]}
                    for aid, deps in BUNDLE_DEPS.items() if (self.home / 'addons' / aid).exists()]
            return ok({'addons': rows})
        if method == 'Settings.GetSettingValue':
            return ok({'value': self.settings.get(params['setting'], '')})
        if method == 'Settings.SetSettingValue':
            self.settings[params['setting']] = params['value']
            return ok(True)
        if method == 'Addons.SetAddonEnabled':
            aid = params['addonid']
            if not params['enabled']:
                needed = any(aid in deps and self.enabled[other] for other, deps in BUNDLE_DEPS.items())
                if needed or self.settings['lookandfeel.skin'] == aid or self.settings['screensaver.mode'] == aid:
                    return error()
                self.disabled_order.append(aid)
            self.enabled[aid] = params['enabled']
            return ok('OK')
        if method == 'Addons.GetAddonDetails':
            return ok({'addon': {'enabled': self.enabled[params['addonid']]}})
        raise AssertionError(method)

    def modules(self):
        kodi = self
        xbmc = types.ModuleType('xbmc')
        xbmc.LOGWARNING = 2
        xbmc.executeJSONRPC = self.rpc
        xbmc.getSkinDir = lambda: kodi.settings['lookandfeel.skin']
        xbmc.getCondVisibility = lambda condition: False
        xbmc.executebuiltin = lambda command, *a: kodi.builtins.append(command)
        xbmc.log = lambda *a, **k: None
        xbmc.Monitor = lambda: types.SimpleNamespace(waitForAbort=lambda s: False, abortRequested=lambda: False)
        xbmc.Player = lambda: types.SimpleNamespace(isPlaying=lambda: False)
        gui = types.ModuleType('xbmcgui')

        class Dialog:
            def select(self, *a, **k):
                return 0

            def yesno(self, *a, **k):
                return True

            def ok(self, title, text):
                kodi.dialogs.append((title, text))
        gui.Dialog = Dialog
        gui.Window = lambda wid: types.SimpleNamespace(getProperty=lambda k: kodi.props.get(k, ''),
                                                       setProperty=lambda k, v: kodi.props.__setitem__(k, v),
                                                       clearProperty=lambda k: kodi.props.pop(k, None))
        vfs = types.ModuleType('xbmcvfs')
        paths = {'special://home/addons': self.home / 'addons', 'special://profile/addon_data': self.home / 'addon_data',
                 'special://temp': self.home / 'temp'}
        vfs.translatePath = lambda p: str(paths.get(p.rstrip('/'), self.home / 'other'))
        addon_mod = types.ModuleType('xbmcaddon')
        addon_mod.Addon = lambda aid=None: types.SimpleNamespace(getAddonInfo=lambda k: str(self.home / 'addon_data' / 'plugin.video.nuviohub'))
        return {'xbmc': xbmc, 'xbmcgui': gui, 'xbmcvfs': vfs, 'xbmcaddon': addon_mod}


class RemoveBuild(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.kodi = FakeKodi(self.home)
        # Kodi runs a COPY of the helper from special://temp, outside any package.
        copy = self.home / 'nuvio-uninstall-copy.py'
        shutil.copyfile(SOURCE, copy)
        spec = importlib.util.spec_from_file_location('nuvio_uninstall_copy', copy)
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.assertFalse(self.helper.__package__)

    def test_whole_build_is_removed_in_dependency_order(self):
        with mock.patch.dict(sys.modules, self.kodi.modules()):
            self.helper.run()
        self.assertEqual(self.kodi.settings['screensaver.mode'], 'screensaver.xbmc.builtin.dim')
        self.assertEqual(self.kodi.settings['lookandfeel.skin'], 'skin.estuary')
        order = self.kodi.disabled_order
        self.assertLess(order.index('screensaver.nuvio'), order.index('script.nuvio'))
        self.assertLess(order.index('skin.nuvio'), order.index('script.nuvio'))
        self.assertEqual(order[-1], 'plugin.video.nuviohub')
        for aid in ('plugin.video.nuviohub', 'script.nuvio', 'skin.nuvio', 'screensaver.nuvio'):
            self.assertFalse((self.home / 'addons' / aid).exists(), aid)
        self.assertTrue((self.home / 'addons' / 'skin.estuary').exists())
        self.assertIn('UpdateLocalAddons', self.kodi.builtins)
        self.assertEqual(self.kodi.dialogs[-1][0], 'Nuvio removed')

    def test_seek_restore_needs_no_package(self):
        with mock.patch.dict(sys.modules, self.kodi.modules()):
            self.assertTrue(callable(self.helper.seek_restore(ROOT)))

    def test_kodi_settings_offer_removal(self):
        text = (ROOT / 'plugin.video.nuviohub/resources/settings.xml').read_text(encoding='utf-8')
        self.assertIn('action=nuvio_uninstall', text)


if __name__ == '__main__':
    unittest.main()
