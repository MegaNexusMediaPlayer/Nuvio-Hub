"""6.0.35: GitHub issues #3-#9, Title options, Library, tracking services on the
phone, Sports screen, refresh-rate guard, Skip on the loading screen."""
import importlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
SKINS = ROOT / 'script.nuvio/resources/skins'
rules = importlib.import_module('resources.lib.continue_rules')
common = importlib.import_module('resources.lib.nuviohub.common')
library = importlib.import_module('resources.lib.library')
tracking = importlib.import_module('resources.lib.tracking_link')
sports = importlib.import_module('resources.lib.sports')
guard = importlib.import_module('resources.lib.refresh_guard')
ch = importlib.import_module('resources.lib.collections_home')
default_setup = importlib.import_module('resources.lib.default_setup')
details = importlib.import_module('nuvio_ui.details')


class Settings:
    def __init__(self, **values):
        self.values = dict(values)

    def getSetting(self, key):
        return self.values.get(key, '')

    def setSetting(self, key, value):
        self.values[key] = value


SPORT = {'id': 'sp', 'name': 'Sports Streams', 'manifest': {
    'id': 'community.sports.fly', 'name': 'Sports Streams', 'types': ['sport'],
    'resources': [{'name': 'catalog', 'types': ['sport']}, {'name': 'stream', 'types': ['sport'], 'idPrefixes': ['leaf']}],
    'catalogs': [{'type': 'sport', 'id': 'sports_football', 'name': 'Football'},
                 {'type': 'sport', 'id': 'sports_live', 'name': 'Live Now'},
                 {'type': 'sport', 'id': 'needs', 'name': 'Search', 'extra': [{'name': 'search', 'isRequired': True}]}]}}
MOVIES = {'id': 'aio', 'name': 'AIOMetadata', 'manifest': {
    'id': 'aiometadata', 'name': 'AIOMetadata', 'description': 'Movies and series', 'types': ['movie', 'series'],
    'resources': ['catalog', 'meta'], 'catalogs': [{'type': 'movie', 'id': 'popular', 'name': 'Popular'}]}}


class ContinueWatching(unittest.TestCase):
    def test_watched_at_90_percent_like_nuvio(self):
        self.assertEqual((common.WATCHED_PERCENT, common.SIMKL_WATCHED_PERCENT), (90, 80))

    def test_remove_hides_until_played_again(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch('resources.lib.nuviohub.common.profile_path', return_value=temp):
            rules._MEM.clear()
            rules.hide('movie', 'tt1', now=1000)
            self.assertTrue(rules.hidden('movie', 'tt1', 999))
            self.assertTrue(rules.hidden('movie', 'tt1', 1000))
            self.assertFalse(rules.hidden('movie', 'tt1', 1001), 'played again: back in the row')
            self.assertFalse(rules.hidden('series', 'tt1', 10))
            rules._MEM.clear()

    def test_period_default_60_days(self):
        addon = Settings()
        self.assertEqual(rules.period_days(addon), 60)
        now = 100 * 86400
        self.assertTrue(rules.recent_enough(now - 59 * 86400, addon, now))
        self.assertFalse(rules.recent_enough(now - 61 * 86400, addon, now))
        self.assertTrue(rules.recent_enough(1, Settings(nuvio_cw_days='0'), now))
        self.assertTrue(rules.show_unaired(Settings()))
        self.assertFalse(rules.show_unaired(Settings(nuvio_cw_unaired='false')))

    def test_continue_cards_are_marked_for_title_options(self):
        source = (ROOT / 'plugin.video.nuviohub/resources/lib/home_data.py').read_text(encoding='utf-8')
        self.assertIn("continue_card='resume'", source)
        self.assertIn("'continue_card':'next'", (ROOT / 'plugin.video.nuviohub/resources/lib/watch_nextup.py').read_text(encoding='utf-8'))


class TitleOptions(unittest.TestCase):
    def test_continue_card_options(self):
        row = {'continue_card': 'resume', 'target': {'resume_seconds': 300}}
        with mock.patch.object(library, 'contains', return_value=False):
            keys = [k for k, _ in details.title_options({'media_type': 'movie', 'canonical_id': 'tt1', 'resume_seconds': 300}, row)]
        self.assertEqual(keys, ['start', 'manual', 'remove', 'library', 'related', 'info'])

    def test_other_cards_have_no_remove_and_library_toggles(self):
        with mock.patch.object(library, 'contains', return_value=True):
            keys = [k for k, _ in details.title_options({'media_type': 'movie', 'canonical_id': 'tt1'}, {})]
        self.assertEqual(keys, ['manual', 'unlibrary', 'related', 'info'])

    def test_remove_keeps_progress_and_refreshes_the_row(self):
        props = {}
        with mock.patch.object(rules, 'hide') as hide, \
                mock.patch.object(details.xbmcgui, 'Window', return_value=SimpleNamespace(setProperty=props.__setitem__)), \
                mock.patch.object(details.xbmcgui, 'Dialog'):
            self.assertTrue(details.quick_choice('remove', {'media_type': 'series', 'canonical_id': 'tt2'}))
        hide.assert_called_once_with('series', 'tt2')
        self.assertIn('nuvio.progress.revision', props)

    def test_play_from_the_beginning_starts_at_zero(self):
        with mock.patch.object(details, 'open_context', return_value='playing') as opened:
            details.run_choice({'media_type': 'movie', 'canonical_id': 'tt1', 'resume_seconds': 300}, 'start')
        ctx = opened.call_args.args[0]
        self.assertEqual((ctx['resume_seconds'], ctx['play_from_start']), (0, True))
        self.assertNotIn('details_view', ctx)

    def test_more_like_this_opens_the_grid(self):
        with mock.patch.object(details, 'more_like_this', return_value='') as grid:
            details.run_choice({'media_type': 'movie', 'canonical_id': 'tt1'}, 'related')
        grid.assert_called_once()

    def test_menu_floats_without_dimming(self):
        for folder in ('Default', 'Dark', 'Dim'):
            root = ET.parse(SKINS / folder / '1080i/nuvio_context.xml').getroot()
            textures = [c.findtext('texture') or '' for c in root.iter('control')]
            self.assertFalse(any('white.png' in t for t in textures), folder)  # no full-screen dim layer
            buttons = [c for c in root.iter('control') if c.get('type') == 'button']
            self.assertEqual([b.get('id') for b in buttons], [str(100 + i) for i in range(7)])

    def test_home_shows_options_before_hiding(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/home_window.py').read_text(encoding='utf-8')
        self.assertIn('context_choice(target,rows[pos])', source)
        self.assertIn('self.child(run_choice,target,choice,rows[pos])', source)


class Library(unittest.TestCase):
    def test_add_saves_locally_and_to_connected_trackers(self):
        favorites = importlib.import_module('resources.lib.favorites_store')
        with mock.patch.object(favorites, 'add') as add, \
                mock.patch.object(library, '_trakt_add', return_value=True), \
                mock.patch.object(library, '_simkl_add', side_effect=RuntimeError('offline')):
            reached = library.add({'media_type': 'movie', 'canonical_id': 'tt1', 'title': 'A'})
        self.assertEqual(reached, ['Trakt'])
        self.assertEqual(add.call_args.kwargs['source'], 'local')

    def test_rows_split_movies_and_series(self):
        favorites = importlib.import_module('resources.lib.favorites_store')
        items = [{'media_type': 'movie', 'canonical_id': 'tt1', 'title': 'M'}, {'media_type': 'series', 'canonical_id': 'tt2', 'title': 'S'}]
        with mock.patch.object(favorites, 'list_favorites', return_value=items) as listing:
            movies, series = library.rows(library.TRACKING)
        self.assertEqual(listing.call_args.kwargs['source'], 'trakt')
        self.assertEqual(([m['title'] for m in movies], [s['title'] for s in series]), (['M'], ['S']))

    def test_header_has_library_between_home_and_search(self):
        for folder in ('Default', 'Dark', 'Dim'):
            for name in ('nuvio_home.xml', 'nuvio_home_compact.xml'):
                root = ET.parse(SKINS / folder / '1080i' / name).getroot()
                buttons = {c.get('id'): c for c in root.iter('control') if c.get('type') == 'button' and c.get('id') in ('101', '105', '106', '107', '108')}
                lefts = [int(buttons[i].findtext('left')) for i in ('101', '106', '105', '107', '108')]
                self.assertEqual(lefts, sorted(lefts), (folder, name))
                self.assertEqual(buttons['106'].findtext('label'), 'Library')
                gaps = [lefts[i + 1] - lefts[i] - int(buttons[k].findtext('width')) for i, k in enumerate(('101', '106', '105', '107'))]
                self.assertEqual(set(gaps), {20}, 'same spacing')

    def test_library_window(self):
        root = ET.parse(SKINS / 'Default/1080i/nuvio_library.xml').getroot()
        ids = {c.get('id') for c in root.iter('control')}
        self.assertTrue({'201', '202', '500', '501'} <= ids)
        labels = [c.findtext('label') for c in root.iter('control') if c.get('type') == 'button']
        self.assertEqual(labels, ['Local', 'Tracking Services'])


class TrackingOnPhone(unittest.TestCase):
    def tearDown(self):
        tracking._PENDING.clear()

    def test_trakt_code_opens_activation_and_token_is_saved(self):
        trakt = importlib.import_module('resources.lib.trakt')
        answers = [{'user_code': 'ABCD1234', 'device_code': 'dev', 'verification_url': 'https://trakt.tv/activate', 'interval': 5, 'expires_in': 600},
                   {'access_token': 'tok'}]
        with mock.patch.object(trakt, '_request', side_effect=lambda *a, **k: answers.pop(0)), \
                mock.patch.object(trakt, 'save_token') as save, mock.patch.object(trakt, 'ensure_enabled'), \
                mock.patch.object(tracking.threading, 'Thread', side_effect=lambda target, **k: SimpleNamespace(start=target)):
            result = tracking.start('trakt', sleep=lambda s: None)
        self.assertEqual(result, {'url': 'https://trakt.tv/activate', 'code': 'ABCD1234'})
        save.assert_called_once()
        self.assertNotIn('trakt', tracking._PENDING)

    def test_foreign_activation_hosts_are_not_opened(self):
        trakt = importlib.import_module('resources.lib.trakt')
        with mock.patch.object(trakt, '_request', return_value={'user_code': 'X', 'device_code': 'd', 'verification_url': 'https://evil.example/'}), \
                mock.patch.object(trakt, 'ensure_enabled'), mock.patch.object(tracking.threading, 'Thread'):
            self.assertEqual(tracking.start('trakt')['url'], 'https://trakt.tv/activate')
        with self.assertRaises(ValueError):
            tracking.start('netflix')

    def test_phone_page_has_tracking_services_after_the_account(self):
        page = (ROOT / 'plugin.video.nuviohub/resources/phone_setup/index.html').read_text(encoding='utf-8')
        self.assertIn("renderTracking(box);", page)
        self.assertIn("window.open('about:blank', '_blank')", page)
        server = (ROOT / 'plugin.video.nuviohub/resources/lib/phone_setup.py').read_text(encoding='utf-8')
        self.assertIn("'/api/tracking/start'", server)
        self.assertIn("'tracking': _tracking_status()", server)

    def test_tv_settings_list_trakt(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/settings.py').read_text(encoding='utf-8')
        self.assertIn("Trakt · tracking service", source)
        self.assertTrue((ROOT / 'script.nuvio/nuvio_ui/trakt_account.py').is_file())


class Sports(unittest.TestCase):
    def test_detection(self):
        self.assertTrue(sports.is_sports_provider(SPORT))
        self.assertFalse(sports.is_sports_provider(MOVIES))
        named = {'id': 'x', 'name': 'Live Sports', 'manifest': {'id': 'x', 'name': 'Live Sports', 'types': ['tv']}}
        self.assertTrue(sports.is_sports_provider(named))

    def test_sports_never_reach_the_movie_home_or_search(self):
        self.assertEqual([p['id'] for p in default_setup.catalog_providers([SPORT, MOVIES])], ['aio'])
        source = (ROOT / 'plugin.video.nuviohub/resources/lib/home_data.py').read_text(encoding='utf-8')
        self.assertIn('if is_sports_provider(source):continue', source)

    def test_catalogs_live_first_and_no_required_extras(self):
        names = [c['name'] for _, c in sports.catalogs([SPORT, MOVIES])]
        self.assertEqual(names, ['Live Now', 'Football'])

    def test_stream_headers_are_kept(self):
        url = sports._play_url({'url': 'https://h/live.m3u8', 'behaviorHints': {'proxyHeaders': {'request': {'Referer': 'https://r/'}}}})
        self.assertEqual(url, 'https://h/live.m3u8|Referer=https%3A%2F%2Fr%2F')
        self.assertEqual(sports._play_url({'url': 'magnet:?x'}), '')

    def test_screen_and_hub_button(self):
        root = ET.parse(SKINS / 'Default/1080i/nuvio_sports.xml').getroot()
        controls = {c.get('id'): c for c in root.iter('control') if c.get('id')}
        self.assertEqual([controls[i].findtext('label') for i in ('101', '107', '108')], ['Home', 'Settings', 'HUB'])
        self.assertIn('700', controls)
        self.assertTrue(any(c.get('type') == 'videowindow' for c in root.iter('control')))
        for folder in ('Dark', 'Dim'):
            self.assertTrue((SKINS / folder / '1080i/nuvio_sports.xml').is_file())
        hub = (ROOT / 'skin.nuvio/xml/Home.xml').read_text(encoding='utf-8')
        self.assertLess(hub.index('RunScript(script.nuvio,iptv)'), hub.index('RunScript(script.nuvio,sports)'))
        self.assertLess(hub.index('RunScript(script.nuvio,sports)'), hub.index('RunScript(script.nuvio,settings)'))

    def test_sports_playback_is_a_preview_never_tracked(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/sports.py').read_text(encoding='utf-8')
        self.assertIn("home.setProperty('nuvio.preview.active', token)", source)
        companion = (ROOT / 'plugin.video.nuviohub/resources/lib/companion.py').read_text(encoding='utf-8')
        self.assertIn("self._enter_foreign_playback('home-preview')", companion)


class RefreshGuard(unittest.TestCase):
    def run_guard(self, value):
        calls, props, addon = [], {}, Settings()
        def rpc(method, params):
            calls.append((method, params))
            return {'value': value} if method == 'Settings.GetSettingValue' else 'OK'
        home = SimpleNamespace(getProperty=lambda k: props.get(k, ''), setProperty=props.__setitem__, clearProperty=lambda k: props.pop(k, None))
        with mock.patch.object(guard, '_rpc', side_effect=rpc), mock.patch.object(guard, '_home', return_value=home), \
                mock.patch.object(guard, '_addon', return_value=addon):
            suspended = guard.suspend()
            restored = guard.restore()
        return suspended, restored, calls, addon

    def test_switching_on_is_paused_for_the_preview_and_put_back(self):
        suspended, restored, calls, addon = self.run_guard(1)
        self.assertTrue(suspended and restored)
        self.assertIn(('Settings.SetSettingValue', {'setting': guard.SETTING, 'value': 0}), calls)
        self.assertEqual(calls[-1], ('Settings.SetSettingValue', {'setting': guard.SETTING, 'value': 1}))
        self.assertEqual(addon.values[guard.STORE], '')

    def test_off_means_nothing_is_touched(self):
        suspended, restored, calls, _ = self.run_guard(0)
        self.assertFalse(suspended or restored)
        self.assertEqual([c[0] for c in calls], ['Settings.GetSettingValue'])


class LoadingSkip(unittest.TestCase):
    def test_loops_wait_in_kodi_so_back_skips(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/startup.py').read_text(encoding='utf-8')
        self.assertNotIn('wait(pending', source)
        self.assertEqual(source.count('if monitor.waitForAbort(.05)'), 2)


class HomeLayout(unittest.TestCase):
    def test_collections_stay_the_default_and_rows_is_an_option(self):
        self.assertEqual(ch.layout(Settings()), 'collections')
        self.assertEqual(ch.layout(Settings(nuvio_home_layout='rows')), 'rows')
        onboarding = (ROOT / 'script.nuvio/nuvio_ui/onboarding.py').read_text(encoding='utf-8')
        self.assertNotIn('home_layout', onboarding, 'an option, not a setup question')

    def test_catalog_rows_with_overflow(self):
        folders = [{'id': 'f%d' % i, 'title': 'Cat %d' % i, 'sources': []} for i in range(5)]
        store = importlib.import_module('resources.lib.nuviohub.store')
        with mock.patch.object(ch, 'groups', return_value=[{'id': 'g', 'title': 'G', 'folders': folders}]), \
                mock.patch.object(store, 'list_providers', return_value=[]), \
                mock.patch.object(ch, 'folder_shelf', side_effect=lambda f, p, mt, title: {'title': title, 'rows': []}), \
                mock.patch.object(ch, 'tiles', side_effect=lambda g: {'title': g['title'], 'rows': g['folders']}):
            shelves = ch.catalog_rows(3)
        self.assertEqual([s['title'] for s in shelves], ['Cat 0', 'Cat 1', 'More catalogs'])
        self.assertEqual(len(shelves[-1]['rows']), 3)


class StreamSwitches(unittest.TestCase):
    def test_no_repair_runs_at_entry(self):
        gate = (ROOT / 'script.nuvio/nuvio_ui/setup_gate.py').read_text(encoding='utf-8')
        self.assertNotIn('repair_all_on', gate)


if __name__ == '__main__':
    unittest.main()
