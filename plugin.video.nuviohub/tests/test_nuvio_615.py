"""6.0.15: Nuvio never blocks on setup; Cinemeta defaults; Home rows on/off."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import frontend_test_support
frontend_test_support.install()
from resources.lib import collection_profile as profiles
from resources.lib.nuviohub import store, client
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
setup = importlib.import_module('resources.lib.default_setup')
collections_home = importlib.import_module('resources.lib.collections_home')
GENRES = ['Action', 'Adventure', 'Animation', 'Biography', 'Comedy', 'Crime', 'Documentary', 'Drama', 'Family',
          'Fantasy', 'History', 'Horror', 'Mystery', 'Romance', 'Sci-Fi', 'Sport', 'Thriller', 'War', 'Western']


def cinemeta_manifest():
    """Shape of https://v3-cinemeta.strem.io/manifest.json (checked 30 Sep 2026)."""
    catalogs = []
    for kind in ('movie', 'series'):
        catalogs += [{'type': kind, 'id': 'top', 'name': 'Popular',
                      'extra': [{'name': 'genre', 'options': GENRES}, {'name': 'search'}, {'name': 'skip'}]},
                     {'type': kind, 'id': 'year', 'name': 'New',
                      'extra': [{'name': 'genre', 'isRequired': True, 'options': [str(y) for y in range(2026, 1990, -1)]},
                                {'name': 'skip'}]},
                     {'type': kind, 'id': 'imdbRating', 'name': 'Featured',
                      'extra': [{'name': 'genre', 'options': GENRES}, {'name': 'skip'}]}]
    return {'id': setup.CINEMETA_ID, 'name': 'Cinemeta', 'version': '3.0.14', 'types': ['movie', 'series'],
            'resources': ['catalog', 'meta', 'addon_catalog'], 'idPrefixes': ['tt'], 'catalogs': catalogs}


def cinemeta_provider():
    return {'id': 'cinemeta', 'name': 'Cinemeta', 'manifest_url': setup.CINEMETA_URL,
            'base_url': setup.CINEMETA_URL.rsplit('/', 1)[0], 'manifest': cinemeta_manifest()}


class TempProfile(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'nuvio_collections.json'
        # Backend and frontend load this module under two names in the test harness.
        for module in {profiles, importlib.import_module('resources.lib.collection_profile')}:
            module._LOADED.clear()
            patch = mock.patch.object(module, 'profile_file', return_value=self.path)
            patch.start()
            self.addCleanup(patch.stop)
            self.addCleanup(module._LOADED.clear)


class CinemetaDefaults(TempProfile):
    def test_every_default_source_resolves_to_a_cinemeta_catalog_and_filter(self):
        validation = importlib.import_module('resources.lib.collection_validation')
        groups = profiles.normalize(setup.cinemeta_collections(year=2026))
        provider = cinemeta_provider()
        for folder, source in validation.sources(groups):
            match = collections_home.matching_catalog(source, [provider])
            self.assertIsNotNone(match, (folder['title'], source))
            self.assertEqual(validation.filter_error(match[1], validation.extra_for(source)), '', folder['title'])

    def test_default_art_ships_in_the_bundle(self):
        build = (ROOT / 'review/build_bundle.py').read_text(encoding='utf-8')
        self.assertIn('COLLECTION_MEDIA', build)
        shipped = {value for group in json.loads((ROOT / 'plugin.video.nuviohub/resources/collections.json').read_text())
                   for folder in group['folders'] for key, value in folder.items() if key in ('cover', 'backdrop')}
        for group in setup.cinemeta_collections():
            for folder in group['folders']:
                self.assertIn(folder['cover'], shipped, folder['title'])
                self.assertTrue((ROOT / 'script.nuvio' / folder['cover']).is_file(), folder['cover'])

    def test_install_adds_and_enables_cinemeta_once(self):
        providers = []
        metadata = importlib.import_module('resources.lib.metadata_providers')

        def add(name, url, manifest):
            row = {'id': 'cm', 'name': name, 'manifest_url': url, 'manifest': manifest}
            providers.append(row)
            return row
        with mock.patch.object(store, 'list_providers', side_effect=lambda: list(providers)), \
                mock.patch.object(store, 'add_provider', side_effect=add) as added, \
                mock.patch.object(client, 'get_json', return_value=cinemeta_manifest()) as fetched, \
                mock.patch.object(metadata, 'enabled', return_value=[]), \
                mock.patch.object(metadata, 'set_enabled') as switch:
            self.assertEqual(setup.install_cinemeta()['id'], 'cm')
            setup.install_cinemeta()
        added.assert_called_once()
        fetched.assert_called_once()
        switch.assert_called_with('cm', True)

    def test_wrong_manifest_is_rejected(self):
        with mock.patch.object(store, 'list_providers', return_value=[]), \
                mock.patch.object(client, 'get_json', return_value={'id': 'other'}):
            with self.assertRaises(ValueError):
                setup.install_cinemeta()

    def test_numb3rs_help_links_the_setup_page(self):
        self.assertIn('https://numb3rs.stream', setup.NUMB3RS_HELP)
        self.assertTrue(setup.numb3rs_ready([{'manifest': {'id': 'aio-metadata'}}]))
        self.assertFalse(setup.numb3rs_ready([cinemeta_provider()]))


class NeverBlocked(TempProfile):
    def setUp(self):
        super().setUp()
        from nuvio_ui import setup_gate
        self.gate = setup_gate

    def test_nothing_configured_gets_cinemeta_and_collections(self):
        with mock.patch.object(self.gate.metadata_providers, 'candidates', return_value=[]), \
                mock.patch.object(self.gate.default_setup, 'install_cinemeta') as install:
            self.gate.ensure_defaults()
        install.assert_called_once()
        self.assertEqual([g['id'] for g in profiles.load()], ['cinemeta.discover', 'collections.genres'])
        self.assertTrue(self.gate.ready())

    def test_offline_first_start_still_enters(self):
        with mock.patch.object(self.gate.metadata_providers, 'candidates', return_value=[]), \
                mock.patch.object(self.gate.default_setup, 'install_cinemeta', side_effect=OSError('offline')):
            self.gate.ensure_defaults()
        self.assertTrue(self.gate.ready())

    def test_existing_setup_is_left_alone(self):
        mine = [{'id': 'g', 'title': 'Mine', 'folders': [{'id': 'f', 'title': 'F',
                 'sources': [{'addonId': 'x', 'catalogId': 'c', 'type': 'movie'}]}]}]
        profiles.save(mine)
        with mock.patch.object(self.gate.metadata_providers, 'candidates', return_value=[{'id': 'aio'}]), \
                mock.patch.object(self.gate.default_setup, 'install_cinemeta') as install:
            self.gate.ensure_defaults()
        # 6.0.23: Cinemeta is always installed, but never switched ON here.
        install.assert_called_once_with(enable=False)
        self.assertEqual(profiles.load()[0]['title'], 'Mine')

    def test_ensure_ready_always_enters(self):
        with mock.patch.object(self.gate, 'ensure_defaults'), \
                mock.patch.object(self.gate, 'offer_switch_on', return_value=False):
            self.assertTrue(self.gate.ensure_ready())

    def test_saving_collections_needs_no_network(self):
        settings = importlib.import_module('nuvio_ui.settings')
        validation = importlib.import_module('resources.lib.collection_validation')
        with mock.patch.object(validation, 'validate', side_effect=AssertionError('network check')), \
                mock.patch.object(settings, '_switch_on_collection_addons', return_value=False):
            self.assertTrue(settings.commit_collections(setup.cinemeta_collections()))
        self.assertEqual(len(profiles.load()), 2)


class HomeRows(TempProfile):
    def test_hidden_group_is_saved_and_left_out_of_home(self):
        groups = setup.cinemeta_collections()
        groups[1]['hidden'] = True
        profiles.save(groups)
        self.assertTrue(profiles.load()[1]['hidden'])
        home_mod = importlib.import_module('resources.lib.collections_home')
        with mock.patch.object(home_mod, 'tile_settings', return_value={'animated': False, 'built_in': {}, 'overrides': {}}):
            titles = [row['title'] for row in home_mod.home_rows()]
        self.assertEqual(titles, ['Discover'])
        self.assertIsNotNone(home_mod.find_collection('cinemeta.genre.action'), 'a hidden row can still be edited')

    def test_continue_watching_row_can_be_hidden(self):
        home_data = importlib.import_module('resources.lib.home_data')
        profiles.save(setup.cinemeta_collections())
        home_mod = importlib.import_module('resources.lib.collections_home')
        with mock.patch('resources.lib.settings_cache.cached_addon', return_value=mock.Mock(getSetting=lambda k: 'false')), \
                mock.patch.object(home_data, 'continue_shelf', side_effect=AssertionError('built')), \
                mock.patch.object(home_mod, 'tile_settings', return_value={'animated': False, 'built_in': {}, 'overrides': {}}):
            shelves = home_data.initial_shelves()
        self.assertFalse(any(s.get('continue_job') for s in shelves))

    def test_settings_declare_continue_switch(self):
        text = (ROOT / 'plugin.video.nuviohub/resources/settings.xml').read_text(encoding='utf-8')
        self.assertIn('id="nuvio_home_continue" type="bool" default="true"', text)


if __name__ == '__main__':
    unittest.main()
