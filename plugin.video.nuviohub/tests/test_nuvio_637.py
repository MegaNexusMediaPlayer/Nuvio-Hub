"""6.0.37: Kodi 22 RC1 windows (read-only SWIG classes) and touch row dragging."""
import importlib
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()
import kodi_stub

dialog = importlib.import_module('nuvio_ui.dialog')
page = importlib.import_module('nuvio_ui.settings_page')
home = importlib.import_module('nuvio_ui.home_window')


class ReadOnlyClasses(unittest.TestCase):
    def test_window_classes_are_never_modified_after_creation(self):
        # Kodi 22 RC1: "cannot modify read-only attribute ...onInit".
        text = open(kodi_stub.ADDON_ROOT + '/../script.nuvio/nuvio_ui/dialog.py', encoding='utf-8').read()
        self.assertNotIn('def __init_subclass__', text)
        self.assertNotIn('setattr(cls', text)
        self.assertIs(page.SettingsPage.__dict__['onClick'].__name__, 'onClick')   # the class keeps its own method

    def test_callbacks_are_wrapped_per_window(self):
        class Probe(dialog.Dialog):
            def onInit(self):
                self.inited = True
            def onClick(self, cid):
                self.clicked = cid
        win = Probe()
        self.assertIn('onClick', win.__dict__)
        win.onInit()
        self.assertTrue(win.inited and win._xml_ready.is_set())
        win.onClick(7)
        self.assertFalse(hasattr(win, 'clicked'), 'deferred to the window loop, as before')
        win.drain_events()
        self.assertEqual(win.clicked, 7)


def action(aid, x=0.0, y=0.0):
    return SimpleNamespace(getId=lambda: aid, getAmount1=lambda: x, getAmount2=lambda: y)


class TouchRows(unittest.TestCase):
    def drag(self, rows, points, height=1080):
        class Rows(dialog.Dialog):
            TOUCH_ROWS = rows
            def onAction(self, a):
                self.handled = a.getId()
        win = Rows()
        sent = []
        with mock.patch.object(dialog.xbmc, 'executebuiltin', side_effect=sent.append), \
                mock.patch.object(dialog.xbmcgui, 'getScreenHeight', return_value=height, create=True):
            win.onAction(action(dialog.GESTURE_BEGIN, *points[0]))
            for point in points[1:]:
                win.onAction(action(dialog.GESTURE_PAN, *point))
                self.assertTrue(win.touching())
            win.onAction(action(dialog.GESTURE_END, *points[-1]))
        return win, sent

    def test_vertical_drag_over_posters_steps_rows(self):
        step = 1080 * dialog.TOUCH_STEP
        win, sent = self.drag(True, [(500, 900), (505, 870), (510, 900 - step * 2 - 40)])
        self.assertEqual(sent, ['Action(Down)', 'Action(Down)'])
        win, sent = self.drag(True, [(500, 200), (500, 240), (500, 200 + step + 50)])
        self.assertEqual(sent, ['Action(Up)'])

    def test_horizontal_drag_is_left_to_kodi(self):
        win, sent = self.drag(True, [(900, 500), (700, 510), (300, 520)])
        self.assertEqual(sent, [])

    def test_windows_without_rows_and_remote_keys_are_unchanged(self):
        win, sent = self.drag(False, [(500, 900), (500, 870), (500, 300)])
        self.assertEqual(sent, [])
        self.assertFalse(hasattr(win, 'handled'), 'gestures never reach the window handler')
        win.onAction(action(92))
        self.assertEqual(win.handled, 92)   # Back still at once

    def test_rows_screens_opt_in(self):
        sports = importlib.import_module('nuvio_ui.sports')
        library = importlib.import_module('nuvio_ui.library')
        self.assertTrue(home.HomeWindow.TOUCH_ROWS and sports.SportsWindow.TOUCH_ROWS and library.LibraryWindow.TOUCH_ROWS)
        self.assertFalse(dialog.Dialog.TOUCH_ROWS)


class ExternalCollectionSources(unittest.TestCase):
    def setUp(self):
        self.profile = importlib.import_module('resources.lib.collection_profile')
        self.sources = importlib.import_module('resources.lib.collection_sources')
        self.tmdb = importlib.import_module('resources.lib.tmdb_lists')
        self.trakt = importlib.import_module('resources.lib.trakt_lists')
        self.ch = importlib.import_module('resources.lib.collections_home')

    def export(self):
        return [{'id': 'streaming', 'title': 'Streaming', 'folders': [{'id': 'netflix', 'title': 'Netflix', 'catalogSources': [
            {'provider': 'tmdb', 'tmdbSourceType': 'NETWORK', 'tmdbId': 213, 'mediaType': 'TV', 'sortBy': 'popularity.desc',
             'filters': {'withOriginalLanguage': 'en', 'releaseDateGte': '2020-01-01'}},
            {'provider': 'trakt', 'traktListId': 1248149, 'mediaType': 'MOVIE', 'sortBy': 'released', 'sortHow': 'desc', 'title': 'MCU'},
            {'provider': 'tmdb', 'tmdbSourceType': 'BOGUS', 'tmdbId': 1}]}]}]

    def test_nuvio_tmdb_and_trakt_sources_are_imported(self):
        groups = self.profile.normalize(self.export())
        sources = groups[0]['folders'][0]['sources']
        self.assertEqual([s['provider'] for s in sources], ['tmdb', 'trakt'])
        self.assertEqual((sources[0]['sourceType'], sources[0]['type']), ('NETWORK', 'series'))
        self.assertEqual((sources[1]['listId'], sources[1]['sortBy'], sources[1]['sortHow']), (1248149, 'released', 'desc'))
        self.assertEqual(self.profile.normalize(groups), groups, 'stored form re-normalizes to itself')

    def key(self, value):
        """has_key on every loaded copy of tmdb_lists (the suite loads the
        library under two package names)."""
        import sys
        from contextlib import ExitStack
        stack = ExitStack()
        for name, mod in list(sys.modules.items()):
            if name.endswith('.tmdb_lists') and hasattr(mod, 'has_key'):
                stack.enter_context(mock.patch.object(mod, 'has_key', return_value=value))
        return stack

    def test_shelf_loads_them_like_catalogs_and_asks_for_a_tmdb_key(self):
        folder = self.profile.normalize(self.export())[0]['folders'][0]
        with self.key(True):
            shelf = self.ch.folder_shelf(folder, [])
        kinds = [p['kind'] for p, _, _ in shelf['collection_job']]
        self.assertEqual(kinds, ['tmdb', 'trakt'])
        only_tmdb = dict(folder, sources=[folder['sources'][0]])
        with self.key(False):
            shelf = self.ch.folder_shelf(only_tmdb, [])
        self.assertEqual(shelf['rows'][0]['title'], 'Add your TMDb API key')

    def test_tmdb_network_uses_discover_with_nuvio_filters(self):
        source = self.profile.normalize(self.export())[0]['folders'][0]['sources'][0]
        _, catalog, _ = self.tmdb.job(source)
        calls = []
        def request(path, params=None, timeout=None):
            calls.append((path, params))
            return {'results': [{'id': 1399, 'name': 'Show', 'poster_path': '/p.jpg', 'first_air_date': '2021-04-01', 'vote_average': 8.12}]}
        with mock.patch.object(self.tmdb, 'has_key', return_value=True), \
                mock.patch('resources.lib.tmdb_direct._request', side_effect=request):
            data = self.tmdb.fetch(catalog, {'skip': 20})
        path, params = calls[0]
        self.assertEqual(path, '/discover/tv')
        self.assertEqual((params['with_networks'], params['with_original_language'], params['first_air_date.gte'], params['page']),
                         (213, 'en', '2020-01-01', 2))
        self.assertEqual(data['metas'][0], {'id': 'tmdb:1399', 'type': 'series', 'name': 'Show', 'poster': 'https://image.tmdb.org/t/p/w500/p.jpg',
                                            'background': '', 'description': '', 'releaseInfo': '2021', 'imdbRating': '8.1'})

    def test_tmdb_needs_the_users_key(self):
        _, catalog, _ = self.tmdb.job(self.tmdb.normalize({'tmdbSourceType': 'LIST', 'tmdbId': 5, 'mediaType': 'MOVIE'}))
        with mock.patch.object(self.tmdb, 'has_key', return_value=False):
            with self.assertRaises(ValueError):
                self.tmdb.fetch(catalog)

    def test_trakt_list_is_read_like_nuvio_tv(self):
        source = self.profile.normalize(self.export())[0]['folders'][0]['sources'][1]
        _, catalog, _ = self.trakt.job(source)
        trakt = importlib.import_module('resources.lib.trakt')
        row = {'movie': {'title': 'Iron Man', 'year': 2008, 'rating': 7.91, 'ids': {'imdb': 'tt0371746'},
                         'images': {'poster': ['media.trakt.tv/images/p.jpg']}}}
        with mock.patch.object(trakt, '_request', return_value=[row]) as request, \
                mock.patch.object(trakt, 'authorized', return_value=False):
            data = self.trakt.fetch(catalog, {'skip': 50})
        path = request.call_args.args[0]
        self.assertTrue(path.startswith('/lists/1248149/items/movies?'))
        for part in ('extended=full%2Cimages', 'page=2', 'limit=50', 'sort_by=released', 'sort_how=desc'):
            self.assertIn(part, path)
        self.assertEqual(data['metas'][0]['poster'], 'https://media.trakt.tv/images/p.jpg')
        self.assertEqual(data['metas'][0]['imdbRating'], '7.9')

    def test_cache_and_grid_use_the_same_path(self):
        browse = open(kodi_stub.ADDON_ROOT + '/resources/lib/browse_cache.py', encoding='utf-8').read()
        self.assertIn("provider.get('kind') in ('trakt', 'tmdb')", browse)
        pages = open(kodi_stub.ADDON_ROOT + '/resources/lib/catalog_pages.py', encoding='utf-8').read()
        self.assertIn('collection_sources.is_virtual(spec)', pages)
        page = open(kodi_stub.ADDON_ROOT + '/resources/phone_setup/index.html', encoding='utf-8').read()
        self.assertIn("api('/api/tmdb/key'", page)


if __name__ == '__main__':
    unittest.main()
