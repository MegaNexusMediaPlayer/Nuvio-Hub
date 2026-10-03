"""6.0.37: Kodi 22 RC1 windows (read-only SWIG classes), touch row dragging,
Trakt/TMDB collection sources, security notice, Local storage."""
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


class TouchIsKodis(unittest.TestCase):
    """6.0.40: the 6.0.37/6.0.39 drag-to-row stepping was removed; touch
    gestures are Kodi's own again (remote, mouse and keyboard never changed)."""
    def test_gestures_reach_neither_the_window_nor_builtins(self):
        class Rows(dialog.Dialog):
            def onAction(self, a):
                self.handled = a.getId()
        win = Rows()
        sent = []
        with mock.patch.object(dialog.xbmc, 'executebuiltin', side_effect=sent.append):
            for aid in (501, 504, 504, 599, 511, 531):
                win.onAction(action(aid, 500, 500))
        self.assertEqual(sent, [])
        self.assertFalse(hasattr(win, 'handled'))
        win.onAction(action(92))
        self.assertEqual(win.handled, 92)   # Back still at once
        self.assertFalse(hasattr(dialog.Dialog, 'TOUCH_ROWS'))


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


class SecurityNotice(unittest.TestCase):
    def setUp(self):
        self.check = importlib.import_module('nuvio_ui.system_check')

    def found(self, enabled, trakt_connected=False):
        trakt = importlib.import_module('resources.lib.trakt')
        with mock.patch.object(self.check.xbmc, 'getCondVisibility', side_effect=lambda c: any(a in c for a in enabled)), \
                mock.patch.object(self.check, '_name', side_effect=lambda aid, name: name), \
                mock.patch.object(trakt, 'authorized', return_value=trakt_connected):
            return self.check.found()

    def test_known_addons_are_found(self):
        names = [n for _, n in self.found({'plugin.video.umbrella', 'plugin.video.fenlight', 'plugin.video.redlight', 'plugin.program.openwizard'})]
        self.assertEqual(names, ['Umbrella', 'Fen Light', 'Red Light', 'Open Wizard'])

    def test_trakt_addon_only_when_meganexus_uses_trakt(self):
        self.assertEqual(self.found({'script.trakt'}), [])
        self.assertEqual(self.found({'script.trakt'}, trakt_connected=True), [('script.trakt', 'Trakt')])

    def test_text_recommends_clean_install_first(self):
        text = self.check.text([('script.trakt', 'Trakt')])
        self.assertLess(text.index('clean Kodi install'), text.index('turn them off'))
        self.assertIn('logged twice', text)
        self.assertIn('Nothing is deleted', text)

    def run_check(self, choice, skipped=''):
        values = {self.check.SKIPPED_SETTING: skipped}
        addon = SimpleNamespace(getSetting=lambda k: values.get(k, ''), setSetting=values.__setitem__)
        win = mock.Mock(choice=choice)
        rpc = []
        with mock.patch.object(self.check, 'found', return_value=[('plugin.video.fen', 'Fen')]), \
                mock.patch.object(self.check.xbmcaddon, 'Addon', return_value=SimpleNamespace(getAddonInfo=lambda k: '/x', getSetting=addon.getSetting, setSetting=addon.setSetting)), \
                mock.patch.object(self.check, 'Notice', return_value=win) as notice, \
                mock.patch.object(self.check.xbmc, 'executeJSONRPC', side_effect=lambda r: rpc.append(r) or '{"result":"OK"}', create=True), \
                mock.patch.object(self.check.xbmcgui, 'Dialog'):
            result = self.check.run()
        return result, values, rpc, notice

    def test_turn_off_disables_them(self):
        result, values, rpc, _ = self.run_check('off')
        self.assertEqual(result, 'off')
        self.assertIn('"enabled": false', rpc[0])
        self.assertIn('plugin.video.fen', rpc[0])

    def test_skip_is_remembered_until_another_addon_appears(self):
        result, values, rpc, _ = self.run_check('skip')
        self.assertEqual((result, values[self.check.SKIPPED_SETTING], rpc), ('skip', 'plugin.video.fen', []))
        result, _, _, notice = self.run_check('off', skipped='plugin.video.fen')
        self.assertEqual(result, 'skip')
        notice.assert_not_called()

    def test_window_and_wiring(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(kodi_stub.ADDON_ROOT + '/../script.nuvio/resources/skins/Default/1080i/nuvio_notice.xml').getroot()
        labels = {c.get('id'): c.findtext('label') for c in root.iter('control') if c.get('type') == 'button'}
        self.assertEqual(labels, {'300': 'Turn them off', '301': 'Skip'})
        self.assertTrue(any('nuvio_shield.png' in (c.findtext('texture') or '') for c in root.iter('control')))
        default = open(kodi_stub.ADDON_ROOT + '/../script.nuvio/default.py', encoding='utf-8').read()
        self.assertIn('system_check()', default)


class LocalStorage(unittest.TestCase):
    MOVIES = {'limits': {'total': 2}, 'movies': [
        {'movieid': 7, 'label': 'Heat', 'year': 1995, 'art': {'poster': 'image://p/', 'fanart': 'image://f/'},
         'resume': {'position': 600, 'total': 6000}, 'playcount': 0, 'rating': 8.3},
        {'movieid': 8, 'label': 'Ronin', 'year': 1998, 'art': {}, 'resume': {}, 'playcount': 1}]}
    SHOWS = {'limits': {'total': 1}, 'tvshows': [
        {'tvshowid': 3, 'label': 'Dark', 'year': 2017, 'art': {'poster': 'image://d/'}, 'episode': 26, 'watchedepisodes': 10}]}

    def setUp(self):
        self.media = importlib.import_module('resources.lib.local_media')
        self.media.forget_counts()
        self.calls = []

    def fake_rpc(self, replies):
        import json
        def answer(raw):
            request = json.loads(raw)
            self.calls.append(request)
            return json.dumps({'result': replies.get(request['method'], {})})
        return mock.patch.object(self.media.xbmc, 'executeJSONRPC', side_effect=answer, create=True)

    def test_home_shows_local_rows_only_when_turned_on_and_not_empty(self):
        addon = mock.Mock(getSetting=lambda key: 'true')
        with self.fake_rpc({'VideoLibrary.GetMovies': self.MOVIES, 'VideoLibrary.GetTVShows': {'limits': {'total': 0}}}):
            shelves = self.media.shelves(addon)
        self.assertEqual([(s['title'], s['local_job']) for s in shelves], [('Local Movies', 'movie')])
        self.assertEqual(self.media.shelves(mock.Mock(getSetting=lambda key: 'false')), [])

    def test_movie_and_series_cards(self):
        with self.fake_rpc({'VideoLibrary.GetMovies': self.MOVIES, 'VideoLibrary.GetTVShows': self.SHOWS}):
            movies = self.media.rows('movie')
            shows = self.media.rows('series')
        self.assertEqual(self.calls[0]['params']['sort'], {'method': 'dateadded', 'order': 'descending'})
        heat, ronin = movies
        self.assertEqual((heat['title'], heat['percent_value'], heat['local'], heat['poster']),
                         ('Heat', 10, {'type': 'movie', 'id': 7, 'title': 'Heat'}, 'image://p/'))
        self.assertNotIn('target', heat)   # never sent to stream add-ons
        self.assertEqual(ronin['watched'], '1')
        self.assertEqual((shows[0]['subtitle'], shows[0]['local']['id']), ('2017  ·  16 new episodes', 3))

    def test_empty_library_points_to_settings(self):
        with self.fake_rpc({}):
            row, = self.media.rows('movie')
        self.assertIn('Local storage', row['plot'])
        self.assertIn('action=setup_center', row['path'])

    def test_play_opens_the_library_item_with_resume(self):
        with self.fake_rpc({'Player.Open': 'OK'}):
            self.assertTrue(self.media.play('episode', 41, resume=True))
        self.assertEqual(self.calls[0]['params'], {'item': {'episodeid': 41}, 'options': {'resume': True}})

    def test_next_episode_prefers_in_progress_then_unwatched(self):
        items = [{'playcount': 1}, {'playcount': 0}, {'playcount': 0, 'resume': {'position': 5, 'total': 50}}]
        self.assertEqual(self.media.next_episode(items), 2)
        self.assertEqual(self.media.next_episode(items[:2]), 1)

    def test_home_data_and_window_wiring(self):
        home_data = importlib.import_module('resources.lib.home_data')
        media = importlib.import_module(home_data.__package__ + '.local_media')   # the copy home_data imports
        with mock.patch.object(media, 'rows', return_value=['x']) as rows:
            self.assertEqual(home_data.load_catalog({'local_job': 'series'}), ['x'])
            self.assertIsNone(home_data.load_catalog({'local_job': 'series'}, cached_only=True))
        rows.assert_called_once_with('series')
        root = kodi_stub.ADDON_ROOT + '/../script.nuvio/nuvio_ui/'
        window = open(root + 'home_window.py', encoding='utf-8').read()
        self.assertIn("shelf.get('local_job')", window)
        self.assertIn('open_item', window)
        settings_text = open(root + 'settings.py', encoding='utf-8').read()
        self.assertIn("'Local storage", settings_text)
        editor = open(root + 'collection_editor.py', encoding='utf-8').read()
        self.assertIn('local_media.HOME_SETTING', editor)

    def test_open_item(self):
        storage = importlib.import_module('nuvio_ui.local_storage')
        self.assertIn('videodb://movies/titles/', storage.open_item({'type': 'all', 'kind': 'movie'}))
        with mock.patch.object(storage.local_media, 'resume_seconds', return_value=0), \
                mock.patch.object(storage.local_media, 'play', return_value=True) as play:
            self.assertEqual(storage.open_item({'type': 'movie', 'id': 7}), 'playing')
        play.assert_called_once_with('movie', 7, False)
        with mock.patch.object(storage.local_media, 'resume_seconds', return_value=754), \
                mock.patch.object(storage.local_media, 'play', return_value=True) as play, \
                mock.patch.object(storage.xbmcgui, 'Dialog') as dialog:
            dialog.return_value.contextmenu.return_value = 0
            self.assertEqual(storage.open_item({'type': 'movie', 'id': 7}), 'playing')
        self.assertEqual(dialog.return_value.contextmenu.call_args[0][0][0], 'Resume from 12:34')
        play.assert_called_once_with('movie', 7, True)


class PhoneSetupPort(unittest.TestCase):
    def test_fixed_port_with_fallback(self):
        # ufw default-deny dropped the phone on a random port; one fixed port can be allowed.
        phone = importlib.import_module('resources.lib.phone_setup')
        with mock.patch.object(phone, 'PORT', 0):
            first = phone.SetupService(host='127.0.0.1')
        try:
            with mock.patch.object(phone, 'PORT', first.port):
                second = phone.SetupService(host='127.0.0.1')   # busy -> any free port
            try:
                self.assertNotEqual(second.port, first.port)
            finally:
                second.server.server_close()
        finally:
            first.server.server_close()
        self.assertEqual(phone.PORT, 8765)
        tv = open(kodi_stub.ADDON_ROOT + '/../script.nuvio/nuvio_ui/phone_setup.py', encoding='utf-8').read()
        self.assertIn('allow TCP port', tv)


if __name__ == '__main__':
    unittest.main()
