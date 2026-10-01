"""6.0.27: poster preload for the first rows + background rest, 256 MiB image RAM, IMDb trailers by default."""
import importlib
from pathlib import Path
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
startup = importlib.import_module('nuvio_ui.startup')
imdb = importlib.import_module('resources.lib.imdb_trailers')
art_cache = importlib.import_module('resources.lib.art_cache')


class Settings:
    def __init__(self, **values):
        self.values = dict(values)

    def getSetting(self, key):
        return self.values.get(key, '')

    def setSetting(self, key, value):
        self.values[key] = value


class PosterPreload(unittest.TestCase):
    def test_pages_are_read_from_disk_not_only_ram(self):
        seen = []
        def peek(provider, catalog, extra, memory_only=True, revalidate=True):
            seen.append(memory_only)
            return {'metas': []}
        with mock.patch.object(startup.browse_cache, 'peek', side_effect=peek):
            startup.poster_urls([('k', {}, {}, {})])
        self.assertEqual(seen, [False])

    def test_start_screen_covers_only_the_first_rows(self):
        groups = [{'id': 'g%d' % i, 'title': str(i), 'folders': [{'id': 'f%d' % i, 'title': 'F', 'sources': []}]} for i in range(6)]
        captured = []
        with mock.patch.object(startup, 'shown_groups', return_value=groups), \
                mock.patch.object(startup, 'jobs', side_effect=lambda groups=None: captured.append(groups) or []):
            startup.jobs(startup.shown_groups()[:startup.FRONT_ROWS])
        self.assertEqual([g['id'] for g in captured[0]], ['g0', 'g1', 'g2'])
        source = (ROOT / 'script.nuvio/nuvio_ui/startup.py').read_text(encoding='utf-8')
        self.assertIn('poster_urls(jobs(shown_groups()[:FRONT_ROWS]))', source)
        self.assertIn("setProperty('nuvio.art_warm.front', base)", source)

    def test_home_continues_the_rest_even_when_many_images_are_cached(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/home_window.py').read_text(encoding='utf-8')
        self.assertIn("if images>=COLD_ART_IMAGES and home.getProperty('nuvio.art_warm.front')!=base:return", source)


class ImageRam(unittest.TestCase):
    def test_256_mib_is_the_default_and_older_ram_presets_move_up(self):
        self.assertEqual(art_cache.LIMITS['ram256'], 256 * 1024 * 1024)
        for previous in ('', 'ram150', 'ram200'):
            settings = Settings(nuvio_art_cache=previous)
            self.assertEqual(art_cache.selected_mode(settings), 'ram256')
        for kept in ('disk246', 'disk512', 'off'):
            self.assertEqual(art_cache.selected_mode(Settings(nuvio_art_cache=kept)), kept)
        text = (ROOT / 'plugin.video.nuviohub/resources/settings.xml').read_text(encoding='utf-8')
        self.assertIn('id="nuvio_art_cache" type="text" default="ram256"', text)
        self.assertIn("'RAM · 256 MiB'", (ROOT / 'script.nuvio/nuvio_ui/settings.py').read_text(encoding='utf-8'))


class Trailers(unittest.TestCase):
    def test_add_on_direct_trailer_still_plays_without_youtube(self):
        support = importlib.import_module('resources.lib.trailer_support')
        row = {'trailer': 'https://example.test/clip.mp4', 'target': {}}
        with mock.patch.object(imdb, 'source_setting', return_value='imdb_youtube'), \
                mock.patch.object(support.xbmc, 'getCondVisibility', return_value=False):
            self.assertEqual(list(support.selected_trailers(row)), ['https://example.test/clip.mp4'])
        yt = {'trailer': 'https://www.youtube.com/watch?v=abcdefghijk', 'target': {}}
        with mock.patch.object(imdb, 'source_setting', return_value='imdb_youtube'), \
                mock.patch.object(support.xbmc, 'getCondVisibility', return_value=False):
            self.assertEqual(list(support.selected_trailers(yt)), [], 'YouTube only with its add-on')

    def test_imdb_first_is_the_default_and_listed_first(self):
        self.assertEqual(imdb.source_setting(Settings()), 'imdb_youtube')
        self.assertEqual(imdb.SOURCES[0], 'imdb_youtube')
        self.assertEqual(imdb.order('imdb_youtube'), ('imdb', 'youtube'))
        text = (ROOT / 'plugin.video.nuviohub/resources/settings.xml').read_text(encoding='utf-8')
        self.assertIn('id="nuvio_trailer_source" type="text" default="imdb_youtube"', text)
        self.assertIn('id="nuvio_auto_trailers" type="bool" label="Automatic home trailers after 6 seconds" default="true"', text)

    def test_old_defaults_move_once_and_later_choices_stay(self):
        settings = Settings(nuvio_trailer_source='youtube_imdb', nuvio_auto_trailers='false')
        self.assertTrue(imdb.migrate_defaults(settings))
        self.assertEqual((settings.values['nuvio_trailer_source'], settings.values['nuvio_auto_trailers']), ('imdb_youtube', 'true'))
        settings.setSetting('nuvio_auto_trailers', 'false')  # the user turns them off again
        settings.setSetting('nuvio_trailer_source', 'youtube')
        self.assertFalse(imdb.migrate_defaults(settings))
        self.assertEqual((settings.values['nuvio_trailer_source'], settings.values['nuvio_auto_trailers']), ('youtube', 'false'))

    def test_an_explicit_youtube_choice_is_not_replaced(self):
        settings = Settings(nuvio_trailer_source='youtube', nuvio_auto_trailers='true')
        imdb.migrate_defaults(settings)
        self.assertEqual(settings.values['nuvio_trailer_source'], 'youtube')

    def test_service_runs_the_migration(self):
        self.assertIn('_trailer_defaults(_xa_trailers.Addon', (ROOT / 'plugin.video.nuviohub/service.py').read_text(encoding='utf-8'))


class RestartAfterAutomaticUpdate(unittest.TestCase):
    def setUp(self):
        self.installer = importlib.import_module('resources.lib.bundle_installer')
        self.values = {}
        addon = Settings()
        addon.values = self.values
        self.monitor = mock.Mock(waitForAbort=mock.Mock(return_value=False))
        self.asked = []
        updater = importlib.import_module(self.installer.__package__ + '.updater')
        for patch in (mock.patch('xbmcaddon.Addon', return_value=addon),
                      mock.patch('xbmc.Player', return_value=SimpleNamespace(isPlayingVideo=lambda: False)),
                      mock.patch('xbmcgui.Window', return_value=SimpleNamespace(getProperty=lambda k: '')),
                      mock.patch('xbmcgui.Dialog'),
                      mock.patch.object(self.installer, 'paths', return_value=('p', 'a')),
                      mock.patch.object(self.installer, 'backend_version', return_value='6.0.27'),
                      mock.patch.object(self.installer, 'outdated', return_value=['script.nuvio']),
                      mock.patch.object(self.installer, 'ensure_components', return_value=['script.nuvio']),
                      mock.patch.object(updater, 'mark_pending', side_effect=lambda a, v: self.asked.append(('mark', v))),
                      mock.patch.object(updater, 'prompt_when_safe', side_effect=lambda a, m: self.asked.append('ask'))):
            patch.start();self.addCleanup(patch.stop)

    def test_an_update_asks_to_restart_when_safe(self):
        self.values[self.installer.VERSION_SETTING] = '6.0.26'
        self.installer.auto_install(self.monitor, attempts=1)
        self.assertEqual(self.asked, [('mark', '6.0.27'), 'ask'])

    def test_first_install_does_not_ask(self):
        self.installer.auto_install(self.monitor, attempts=1)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.values[self.installer.VERSION_SETTING], '6.0.27')


if __name__ == '__main__':
    unittest.main()
