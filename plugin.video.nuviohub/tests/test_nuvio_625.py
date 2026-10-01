"""6.0.25: no "Welcome to Nuvio"; blue settings focus; connecting Nuvio imports everything."""
import colorsys
import importlib
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()
import kodi_stub

importer = importlib.import_module('resources.lib.nuvio_import')
profiles = importlib.import_module('resources.lib.collection_profile')
phone = importlib.import_module('resources.lib.phone_setup')

ROOT = Path(kodi_stub.ADDON_ROOT).parent
SHIPPED = ('plugin.video.nuviohub', 'script.nuvio', 'skin.nuvio', 'screensaver.nuvio')


class Wording(unittest.TestCase):
    def test_no_nuvio_welcome_or_setup_titles(self):
        found = []
        for component in SHIPPED:
            for path in (ROOT / component).rglob('*'):
                if path.suffix not in ('.py', '.xml', '.po', '.html') or 'tests' in path.parts:
                    continue
                text = path.read_text(encoding='utf-8', errors='ignore')
                for phrase in ('Welcome to Nuvio', "'Nuvio setup'"):
                    if phrase in text:
                        found.append((str(path.relative_to(ROOT)), phrase))
        self.assertEqual(found, [])

    def test_welcome_texts_say_meganexus(self):
        self.assertIn("'Welcome to MegaNexus'", (ROOT / 'script.nuvio/nuvio_ui/home_window.py').read_text(encoding='utf-8'))
        self.assertIn('Welcome to MegaNexus — start setup', (ROOT / 'plugin.video.nuviohub/resources/lib/plugin.py').read_text(encoding='utf-8'))


class SettingsFocus(unittest.TestCase):
    def test_settings_focus_bar_is_blue(self):
        xml = (ROOT / 'script.nuvio/resources/skins/Default/1080i/nuvio_settings.xml').read_text(encoding='utf-8')
        for alpha, rgb in re.findall(r'colordiffuse="([0-9A-Fa-f]{2})([0-9A-Fa-f]{6})"', xml):
            r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
            h, l, s = colorsys.rgb_to_hls(r, g, b)
            self.assertFalse(235 <= h * 360 <= 300 and s > 0.12, rgb)


class AddonIcons(unittest.TestCase):
    def test_new_icon_paths_so_kodi_has_no_cached_nuvio_logo(self):
        import xml.etree.ElementTree as ET
        icon = (ROOT / 'script.nuvio/resources/media/nuvio_mark.png').read_bytes()
        banner = (ROOT / 'script.nuvio/resources/media/nuvio_banner.png').read_bytes()
        for component in SHIPPED:
            assets = ET.parse(ROOT / component / 'addon.xml').getroot().find(".//assets")
            for tag, expected in (('icon', icon), ('fanart', banner)):
                rel = assets.findtext(tag)
                self.assertTrue(Path(rel).name.startswith('meganexus_'), (component, rel))
                self.assertEqual((ROOT / component / rel).read_bytes(), expected, (component, rel))


class AddonNames(unittest.TestCase):
    def test_skin_program_and_screensaver_are_named_meganexus(self):
        import xml.etree.ElementTree as ET
        for component in ('script.nuvio', 'skin.nuvio', 'screensaver.nuvio'):
            root = ET.parse(ROOT / component / 'addon.xml').getroot()
            self.assertEqual(root.get('name'), 'MegaNexus', component)
            self.assertNotIn('Nuvio community build', root.get('provider-name'), component)
        settings = (ROOT / 'script.nuvio/nuvio_ui/settings.py').read_text(encoding='utf-8')
        self.assertIn("'Use MegaNexus skin'", settings)
        self.assertIn("'MegaNexus screensaver'", settings)


REMOTE = [{'id': 'g', 'title': 'Streaming', 'folders': [
    {'id': 'f', 'title': 'Netflix', 'catalogSources': [{'addonId': 'aio.meta', 'catalogId': 'netflix', 'type': 'movie'}]}]}]
AIO = {'id': 'p-aio', 'name': 'AIOMetadata', 'manifest': {'id': 'aio.meta', 'resources': ['catalog', 'meta'], 'types': ['movie'],
       'catalogs': [{'id': 'netflix', 'type': 'movie', 'name': 'Netflix'}]}}


class ConnectImportsEverything(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'nuvio_collections.json'
        import sys
        # The harness loads this module under several names; patch every copy.
        copies = {profiles, importlib.import_module('nuviolib.collection_profile')}
        copies.update(m for n, m in list(sys.modules.items()) if m and n.endswith('.collection_profile'))
        for module in copies:
            module._LOADED.clear()
            patch = mock.patch.object(module, 'profile_file', return_value=path);patch.start()
            self.addCleanup(patch.stop);self.addCleanup(module._LOADED.clear)
        self.values = {}
        addon = SimpleNamespace(getSetting=lambda k: self.values.get(k, ''), setSetting=lambda k, v: self.values.__setitem__(k, v))
        patch = mock.patch('xbmcaddon.Addon', return_value=addon);patch.start();self.addCleanup(patch.stop)
        self.switched = {}

    def test_fetch_pulls_collections_only_when_asked(self):
        sync = importer.sync
        with mock.patch.object(sync.Nuvio, 'sync_addons', return_value=[]), \
                mock.patch.object(sync.Nuvio, 'sync_progress', return_value=[]), \
                mock.patch.object(sync.Nuvio, 'sync_collections', return_value=REMOTE) as pull:
            self.assertIsNone(importer.fetch()['collections'])
            pull.assert_not_called()
            self.assertEqual(importer.fetch(collections=True)['collections'], REMOTE)

    def test_collections_switch_their_metadata_add_on_on(self):
        meta = importlib.import_module('resources.lib.metadata_providers')
        with mock.patch.object(importer.store, 'list_providers', return_value=[AIO]), \
                mock.patch.object(meta, 'entries', return_value=[(AIO, False)]), \
                mock.patch.object(meta, 'set_enabled', side_effect=self.switched.__setitem__):
            self.assertEqual(importer.enable_collection_metadata(profiles.normalize(REMOTE)), ['AIOMetadata'])
        self.assertEqual(self.switched, {'p-aio': True})

    def test_apply_saves_layout_and_reports_metadata(self):
        with mock.patch.object(importer, 'enable_collection_metadata', return_value=['AIOMetadata']), \
                mock.patch.object(importer, 'enable_imported'), \
                mock.patch.object(importer.store, 'list_providers', return_value=[]), \
                mock.patch.object(importer.backend_api, 'provider', return_value=None):
            report = importer.apply({'providers': [], 'collections': REMOTE, 'progress': None, 'errors': []})
        self.assertEqual(report['collections'], 1)
        self.assertEqual(report['metadata_on'], ['AIOMetadata'])
        self.assertEqual(profiles.load()[0]['title'], 'Streaming')

    def test_own_layout_is_detected_and_automatic_layout_is_not(self):
        self.assertFalse(importer.layout_is_users_own())  # nothing yet
        setup = importlib.import_module('resources.lib.default_setup')
        profiles.save(setup.cinemeta_collections(), auto=True)
        self.values[setup.AUTO_LAYOUT] = 'cinemeta'
        self.assertFalse(importer.layout_is_users_own())
        profiles.save(REMOTE)  # a user save clears the automatic mode
        self.assertTrue(importer.layout_is_users_own())

    def test_phone_sign_in_with_one_profile_imports_with_collections(self):
        sync = importer.sync
        with mock.patch.object(sync.Nuvio, 'authenticate', return_value={'access_token': 't'}), \
                mock.patch.object(sync.Nuvio, 'save_token'), \
                mock.patch.object(sync.Nuvio, 'profiles', return_value=[{'profile_index': 1, 'profile_name': 'Me'}]), \
                mock.patch.object(sync.Nuvio, 'select_profile'), \
                mock.patch.object(phone, '_addon', return_value=SimpleNamespace(setSetting=lambda *a: None)), \
                mock.patch.object(importer, 'layout_is_users_own', return_value=False), \
                mock.patch.object(phone, 'nuvio_import', return_value={'providers': 3}) as imp:
            result = phone.nuvio_sign_in('a@b.c', 'pw')
        imp.assert_called_once_with(collections=True)
        self.assertEqual(result['imported'], {'providers': 3})

    def test_phone_keeps_a_users_own_layout(self):
        with mock.patch.object(importer, 'layout_is_users_own', return_value=True), \
                mock.patch.object(phone, 'nuvio_import', return_value={}) as imp:
            phone.first_import()
        imp.assert_called_once_with(collections=False)

    def test_tv_sign_in_runs_the_full_import(self):
        settings = importlib.import_module('nuvio_ui.settings')
        source = (ROOT / 'script.nuvio/nuvio_ui/settings.py').read_text(encoding='utf-8')
        self.assertIn('import_from_nuvio()  # 6.0.25', source)
        self.assertIn("nuvio_import.fetch(collections=collections)", source)
        self.assertTrue(callable(settings.import_from_nuvio))


if __name__ == '__main__':
    unittest.main()
