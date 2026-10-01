"""6.0.12 regression contracts: playback start, trailers, ratings, details.

HTTP and Kodi are fakes; timings are asserted with generous bounds only.
"""
import importlib
import json
from pathlib import Path
import threading
import time
import unittest
from unittest import mock
import frontend_test_support
frontend_test_support.install()
from resources.lib import backend_api as api, home_data, browse_cache
from resources.lib.nuviohub import store, client
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
streams_mod = importlib.import_module('resources.lib.stream_providers')


def provider(pid, name=None, resources=('stream',)):
    return {'id': pid, 'name': name or pid, 'base_url': 'https://example.invalid/' + pid,
            'manifest_url': 'https://example.invalid/%s/manifest.json' % pid,
            'manifest': {'id': 'm.' + pid, 'name': name or pid, 'resources': list(resources), 'types': ['movie']}}


class Settings(dict):
    def addon_class(self):
        values = self

        class Addon(kodi_stub._Addon):
            def getSetting(self, key):
                return values.get(key, '')

            def setSetting(self, key, value):
                values[key] = value
        return Addon


class FastSourceLoading(unittest.TestCase):
    def test_video_does_not_wait_for_the_slowest_addon(self):
        fast, slow = provider('fast'), provider('slow')
        release = threading.Event()
        self.addCleanup(release.set)

        def get_json(url, **kwargs):
            if '/slow/' in url:
                release.wait(5)
            return {'streams': [{'name': url.split('/')[3], 'url': 'https://v/' + url.split('/')[3]}]}
        with mock.patch.object(streams_mod, 'enabled', return_value=[slow, fast]), \
                mock.patch.object(client, 'get_json', side_effect=get_json), \
                mock.patch.object(api, 'STREAM_GRACE', .2):
            start = time.monotonic()
            source, rows = api.streams('movie', 'tt1')
            elapsed = time.monotonic() - start
        self.assertLess(elapsed, 2)
        self.assertEqual([r['name'] for r in rows], ['fast'])
        self.assertEqual(source['_nuvio_slow'], ['slow'])
        self.assertEqual(source['_nuvio_errors'], [])

    def test_results_keep_configured_order(self):
        first, second = provider('first'), provider('second')

        def get_json(url, **kwargs):
            if '/first/' in url:
                time.sleep(.15)
            return {'streams': [{'name': url.split('/')[3], 'url': 'https://v/x'}]}
        with mock.patch.object(streams_mod, 'enabled', return_value=[first, second]), \
                mock.patch.object(client, 'get_json', side_effect=get_json), \
                mock.patch.object(api, 'STREAM_GRACE', 1):
            _, rows = api.streams('movie', 'tt1')
        self.assertEqual([r['name'] for r in rows], ['first', 'second'])

    def test_all_failing_still_reports_an_error(self):
        with mock.patch.object(streams_mod, 'enabled', return_value=[provider('a'), provider('b')]), \
                mock.patch.object(client, 'get_json', side_effect=TimeoutError('x')):
            with self.assertRaises(ValueError):
                api.streams('movie', 'tt1')


class StreamSwitches(unittest.TestCase):
    def setUp(self):
        self.values = Settings()
        self.rows = [provider('torrentio'), provider('aio', 'AIOStreams'), provider('other')]
        for patch in (mock.patch.object(streams_mod.xbmcaddon, 'Addon', self.values.addon_class()),
                      mock.patch.object(store, 'list_providers', side_effect=lambda: list(self.rows)),
                      mock.patch.object(api, 'provider', return_value=None)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_never_configured_uses_one_preferred_addon(self):
        self.assertEqual([p['id'] for p in streams_mod.enabled()], ['aio'])

    def test_import_switches_on_one_only_when_none_is_on(self):
        nuvio_import = importlib.import_module('resources.lib.nuvio_import')
        self.values[streams_mod.SETTING] = json.dumps([{'id': p['id'], 'enabled': False} for p in self.rows])
        with mock.patch.object(importlib.import_module('resources.lib.metadata_providers'), 'entries', return_value=[]):
            nuvio_import.enable_imported(['torrentio', 'aio', 'other'])
            self.assertEqual([p['id'] for p in streams_mod.enabled()], ['aio'])
            self.values[streams_mod.SETTING] = json.dumps([{'id': 'other', 'enabled': True}])
            nuvio_import.enable_imported(['torrentio', 'aio'])
            self.assertEqual([p['id'] for p in streams_mod.enabled()], ['other'])

    def test_one_time_repair_of_the_all_on_state(self):
        self.values[streams_mod.SETTING] = json.dumps([{'id': p['id'], 'enabled': True} for p in self.rows])
        self.assertEqual(streams_mod.repair_all_on()['id'], 'aio')
        self.assertEqual([p['id'] for p in streams_mod.enabled()], ['aio'])
        self.values[streams_mod.SETTING] = json.dumps([{'id': p['id'], 'enabled': True} for p in self.rows])
        self.assertIsNone(streams_mod.repair_all_on(), 'runs only once; a later user choice is kept')

    def test_repair_keeps_a_partial_choice(self):
        self.values[streams_mod.SETTING] = json.dumps([{'id': 'torrentio', 'enabled': True}, {'id': 'aio', 'enabled': True}])
        self.assertIsNone(streams_mod.repair_all_on())


class Ratings(unittest.TestCase):
    def test_rating_label_from_metadata(self):
        with mock.patch('resources.lib.settings_cache.cached_addon', return_value=mock.Mock(getSetting=lambda k: '')):
            self.assertEqual(home_data.rating_label({'imdbRating': '7.84'}), 'IMDb 7.8')
            self.assertEqual(home_data.rating_label({'ratings': {'imdb': 6}}), 'IMDb 6.0')
            self.assertEqual(home_data.rating_label({'vote_average': 8.25}), 'TMDb 8.2')
            self.assertEqual(home_data.rating_label({'imdbRating': 'N/A'}), '')
            self.assertEqual(home_data.rating_label({}), '')

    def test_rating_can_be_switched_off(self):
        with mock.patch('resources.lib.settings_cache.cached_addon', return_value=mock.Mock(getSetting=lambda k: 'false')):
            self.assertEqual(home_data.rating_label({'imdbRating': '7.8'}), '')

    def test_card_shows_rating_under_the_title(self):
        with mock.patch('resources.lib.settings_cache.cached_addon', return_value=mock.Mock(getSetting=lambda k: '')):
            card = home_data.media_card({'id': 'tt1', 'name': 'X', 'year': 2024, 'imdbRating': '7.1'}, {'id': 'p'})
        self.assertEqual(card['meta_line'], '2024  |  Movie  |  IMDb 7.1')
        self.assertEqual(card['rating'], 'IMDb 7.1')


class TrailerPlayback(unittest.TestCase):
    def setUp(self):
        self.support = importlib.import_module('resources.lib.trailer_support')
        self.imdb = importlib.import_module(self.support.__package__ + '.imdb_trailers')

    def test_imdb_files_stream_directly_without_download(self):
        prepare = mock.Mock(return_value='/cache/clip.mp4')
        url = 'https://imdb-video.media-imdb.com/vi1/x.mp4?Expires=1&Signature=s'
        self.assertEqual(self.support.playable(url, prepare), url)
        prepare.assert_not_called()
        self.assertEqual(self.support.playable('https://cdn.invalid/t.mp4', prepare), '/cache/clip.mp4')
        self.assertFalse(self.imdb.direct_stream('https://evil.invalid/media-imdb.com/x.mp4'))

    def test_quality_setting_orders_files(self):
        nodes = [{'contentType': {'id': 'x.trailer'}, 'playbackURLs': [
            {'url': 'https://imdb-video.media-imdb.com/%s.mp4' % d, 'videoMimeType': 'MP4', 'videoDefinition': d}
            for d in ('DEF_SD', 'DEF_480p', 'DEF_720p', 'DEF_1080p')]}]
        self.assertTrue(self.imdb.pick_all(nodes, self.imdb.QUALITIES['1080'])[0].endswith('DEF_1080p.mp4'))
        self.assertTrue(self.imdb.pick_all(nodes, self.imdb.QUALITIES['480'])[0].endswith('DEF_480p.mp4'))
        self.assertEqual(self.imdb.quality_setting(mock.Mock(getSetting=lambda k: 'weird')), '480')

    def test_kodi_trailer_button_never_needs_youtube_it_cannot_use(self):
        plugin = importlib.import_module('resources.lib.plugin')
        support = importlib.import_module(plugin.__package__ + '.trailer_support')
        meta = {'id': 'tt1', 'name': 'X', 'trailers': [{'source': 'abcdefghijk'}]}
        with mock.patch.object(support, 'youtube_allowed', return_value=False):
            self.assertNotIn('trailer', plugin._meta_info(meta))
        with mock.patch.object(support, 'youtube_allowed', return_value=True):
            self.assertIn('plugin.video.youtube', plugin._meta_info(meta)['trailer'])

    def test_settings_declare_trailer_and_rating_options(self):
        text = (ROOT / 'plugin.video.nuviohub/resources/settings.xml').read_text(encoding='utf-8')
        for key in ('nuvio_imdb_trailer_quality', 'nuvio_show_ratings', 'nuvio_stream_switch_612'):
            self.assertIn('id="%s"' % key, text)
        self.assertIn('id="nuvio_trailer_source" type="text" default="youtube_imdb"', text)


class DetailsAndBackground(unittest.TestCase):
    def test_no_loading_episodes_banner(self):
        text = (ROOT / 'script.nuvio/nuvio_ui/details.py').read_text(encoding='utf-8')
        self.assertNotIn('Loading episodes', text)

    def test_background_work_waits_for_playback(self):
        home = {'nuvio.loading.active': '1'}
        window = mock.Mock(getProperty=lambda k: home.get(k, ''))
        with mock.patch('xbmcgui.Window', return_value=window):
            self.assertTrue(browse_cache.playback_busy())
            home.clear()
            with mock.patch('xbmc.Player', return_value=mock.Mock(isPlayingVideo=lambda: True)):
                self.assertTrue(browse_cache.playback_busy())
                home['nuvio.preview.active'] = 'token'
                self.assertFalse(browse_cache.playback_busy(), 'a Home trailer preview is not playback')

    def test_cold_art_warm_runs_once_and_only_when_ram_is_empty(self):
        home_window = importlib.import_module('nuvio_ui.home_window')
        props = {'nuvio.art_cache.base': 'http://127.0.0.1:1', 'nuvio.art_cache.usage': '3.0 MB · 12 images'}
        window = mock.Mock(getProperty=lambda k: props.get(k, ''), setProperty=lambda k, v: props.__setitem__(k, v))
        win = home_window.HomeWindow()
        win._shelves = [{'rows': [{'collection_id': 'a'}, {'collection_id': 'b'}]}]
        with mock.patch.object(home_window.xbmcgui, 'Window', return_value=window), \
                mock.patch.object(home_window.threading, 'Thread') as thread:
            win._start_cold_art_warm()
            win._cold_warm_started = False
            win._start_cold_art_warm()
        self.assertEqual(thread.call_count, 1)
        self.assertEqual(thread.call_args.kwargs['args'], (['a', 'b'], 'http://127.0.0.1:1'))
        props.pop('nuvio.art_warm.running', None)
        props.pop('nuvio.art_warm.session', None)
        props['nuvio.art_cache.usage'] = '150.0 MB · 900 images'  # 6.0.16: skip only when well filled
        win2 = home_window.HomeWindow()
        win2._shelves = win._shelves
        with mock.patch.object(home_window.xbmcgui, 'Window', return_value=window), \
                mock.patch.object(home_window.threading, 'Thread') as thread:
            win2._start_cold_art_warm()
        thread.assert_not_called()


if __name__ == '__main__':
    unittest.main()
