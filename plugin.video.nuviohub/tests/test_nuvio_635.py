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
        self.assertTrue({'201', '202', '203'} | {str(500 + i) for i in range(14)} <= ids)
        labels = [c.findtext('label') for c in root.iter('control') if c.get('type') == 'button']
        self.assertEqual(labels, ['Local', '$INFO[Window.Property(nuvio.library.tracking_label)]', 'Calendar'])
        rows = [c.findtext('label') for c in root.iter('control') if c.get('type') == 'label' and 'nuvio.library.row' in (c.findtext('label') or '')]
        self.assertTrue(rows and all(r.startswith('[B]') for r in rows), 'row titles bold like Home')

    def test_tracking_tab_is_named_after_the_connected_services(self):
        fake = (('trakt', 'Trakt', lambda: True, list), ('simkl', 'Simkl', lambda: True, list), ('x', 'Other', lambda: False, list))
        with mock.patch.object(library, 'TRACKERS', fake):
            self.assertEqual(library.tracking_label(), 'Trakt · Simkl')
        with mock.patch.object(library, 'TRACKERS', fake[2:]):
            self.assertEqual(library.tracking_label(), 'Tracking')
            self.assertFalse(library.tracking_connected())

    def test_calendar_by_month_with_source_badges(self):
        oct1 = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1))
        sep = time.mktime((2026, 9, 3, 12, 0, 0, 0, 0, -1))
        local = [{'media_type': 'movie', 'canonical_id': 'tt1', 'title': 'A', 'added_at': oct1}]
        tracked = [{'media_type': 'movie', 'canonical_id': 'tt1', 'title': 'A', 'added_at': oct1},
                   {'media_type': 'series', 'canonical_id': 'tt2', 'title': 'B', 'added_at': sep}]
        with mock.patch.object(library, '_items', side_effect=lambda source: local if source == 'local' else tracked), \
                mock.patch.object(library, '_origins', return_value={'movie|tt1': ['trakt'], 'series|tt2': 'simkl'}):
            months = library.calendar()
        self.assertEqual([m for m, _ in months], ['October 2026', 'September 2026'])
        self.assertEqual(months[0][1][0]['badges'], ['Local', 'Trakt'])
        self.assertEqual(months[1][1][0]['badges'], ['Simkl'])   # first-build origins format still read

    def test_one_card_per_title_with_every_service_badge(self):
        tracked = [{'media_type': 'movie', 'canonical_id': 'tt9', 'title': 'Both', 'poster': ''}]
        with mock.patch.object(library, '_items', return_value=tracked), \
                mock.patch.object(library, '_origins', return_value={'movie|tt9': ['trakt', 'simkl']}):
            movies, series = library.rows(library.TRACKING)
        self.assertEqual(len(movies), 1)
        self.assertEqual(movies[0]['badges'], ['Trakt', 'Simkl'])
        self.assertEqual(movies[0]['poster'], 'https://images.metahub.space/poster/medium/tt9/img')  # Trakt sends no art
        xml = (SKINS / 'Default/1080i/nuvio_library.xml').read_text(encoding='utf-8')
        self.assertIn('ListItem.Property(badge.1)', xml)

    def test_trakt_watchlist_uses_imdb_ids_like_simkl(self):
        # Same title on Trakt and Simkl = one card; IMDb IDs also give posters.
        trakt = importlib.import_module('resources.lib.trakt')
        movie = {'movie': {'title': 'M', 'year': 2020, 'ids': {'tmdb': 77, 'imdb': 'tt0077', 'trakt': 5}}, 'listed_at': '2026-09-01T10:00:00.000Z'}
        only_tmdb = {'show': {'title': 'S', 'year': 2021, 'ids': {'tmdb': 88}}, 'listed_at': '2026-09-02T10:00:00.000Z'}
        with mock.patch.object(trakt, 'enabled', return_value=True), mock.patch.object(trakt, '_ensure_auth'), \
                mock.patch.object(trakt, '_request', side_effect=lambda path, **k: [movie] if 'movies' in path else [only_tmdb]), \
                mock.patch.object(trakt, '_art_bundle_for_ids', return_value={'poster': '', 'fanart': '', 'clearlogo': ''}):
            rows = trakt.fetch_watchlist()
        self.assertEqual([r['canonical_id'] for r in rows], ['tt0077', 'tmdb:88'])

    def test_mirror_lists_every_service_of_a_title(self):
        favorites = importlib.import_module('resources.lib.favorites_store')
        trakt = importlib.import_module('resources.lib.trakt')
        simkl = importlib.import_module('resources.lib.simkl')
        row = {'media_type': 'movie', 'canonical_id': 'tt9', 'title': 'Both'}
        written = {}
        with mock.patch.object(favorites, 'list_favorites', return_value=[]), \
                mock.patch.object(favorites, 'replace_trakt_mirror') as mirror, \
                mock.patch.object(trakt, 'enabled', return_value=True), mock.patch.object(trakt, 'fetch_watchlist', return_value=[row]), \
                mock.patch.object(simkl, 'enabled', return_value=True), mock.patch.object(simkl, 'authorized', return_value=True), \
                mock.patch.object(simkl, 'watchlist_mirror_rows', return_value=[dict(row)]), \
                mock.patch('resources.lib.nuviohub.safe_io.write_json', side_effect=lambda path, data: written.update(data)), \
                mock.patch('resources.lib.mdblist.configured', return_value=False):
            favorites.refresh_external_mirror()
        self.assertEqual(len(mirror.call_args.args[0]), 1)
        self.assertEqual(written['movie|tt9'], ['trakt', 'simkl'])


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


class SportsPlayback(unittest.TestCase):
    def test_only_live_events_after_five_seconds(self):
        ui = importlib.import_module('nuvio_ui.sports')
        self.assertEqual(ui.DWELL, 5.0)
        source = (ROOT / 'script.nuvio/nuvio_ui/sports.py').read_text(encoding='utf-8')
        self.assertIn("if event.get('live') and key != self.stream_key and now - self.changed >= DWELL:", source)
        self.assertIn("Not live yet", source)

    def test_ownership_by_item_token_so_ok_goes_full_screen(self):
        ui = importlib.import_module('nuvio_ui.sports')
        player = ui.SportsPlayer();player.token = 'tok'
        item = SimpleNamespace(getProperty=lambda k: 'tok')
        with mock.patch.object(player, 'isPlayingVideo', return_value=True, create=True), \
                mock.patch.object(player, 'getPlayingItem', return_value=item, create=True), \
                mock.patch.object(ui.xbmcgui, 'Window', return_value=SimpleNamespace(getProperty=lambda k: 'tok')):
            self.assertTrue(player.owns())   # whatever file path Kodi reports for the HLS stream

    def test_sports_addons_get_metadata_and_streams_on(self):
        metadata = importlib.import_module('resources.lib.metadata_providers')
        streams = importlib.import_module('resources.lib.stream_providers')
        with mock.patch.object(metadata, 'entries', return_value=[(SPORT, False), (MOVIES, False)]), \
                mock.patch.object(streams, 'entries', return_value=[(SPORT, False)]), \
                mock.patch.object(metadata, 'set_enabled') as meta_on, mock.patch.object(streams, 'set_enabled') as stream_on:
            sports.ensure_enabled([SPORT, MOVIES])
        meta_on.assert_called_once_with('sp', True)
        stream_on.assert_called_once_with('sp', True)


class SportsFullScreen(unittest.TestCase):
    def window(self, full=False, channels=False):
        ui = importlib.import_module('nuvio_ui.sports')
        props = {'nuvio.sport.full': '1' if full else '', 'nuvio.sport.channels': '1' if channels else ''}
        focus = []
        win = ui.SportsWindow.__new__(ui.SportsWindow)
        win.getProperty = lambda k: props.get(k, '')
        win.setProperty = props.__setitem__
        win.setFocusId = focus.append
        win.getFocusId = lambda: 1003
        win.close = mock.Mock()
        win._child_active = win._dialog_closed = win._dispatching = False
        return ui, win, props, focus

    def test_same_player_enlarged_in_the_window(self):
        root = ET.parse(SKINS / 'Default/1080i/nuvio_sports.xml').getroot()
        full = next(c for c in root.iter('control') if c.get('id') == '950')
        self.assertIsNotNone(full.find('texturenofocus'))   # explicit empty: no skin default box
        videos = [c for c in root.iter('control') if c.get('type') == 'videowindow']
        self.assertEqual([(v.findtext('width'), v.findtext('height')) for v in videos], [('1280', '610'), ('1920', '1080')])
        self.assertIn('!String.IsEqual(Window.Property(nuvio.sport.full),1)', videos[0].findtext('visible'))
        xml = (SKINS / 'Default/1080i/nuvio_sports.xml').read_text(encoding='utf-8')
        self.assertNotIn('small video</label>', xml, 'no OK / Back notice on the big player')
        self.assertIn('<control type="list" id="960">', xml)
        source = (ROOT / 'script.nuvio/nuvio_ui/sports.py').read_text(encoding='utf-8')
        self.assertEqual(source.count("ActivateWindow(fullscreenvideo)"), 1, "Kodi's player only from _native")

    def test_ok_on_the_enlarged_video_opens_live_channels(self):
        ui, win, props, focus = self.window(full=True)
        live = {'id': 'a', 'title': 'Live A', 'live': True}
        later = {'id': 'b', 'title': 'Later', 'live': False}
        win.rows = [('Football', None, None, [live, later]), ('Today', None, None, [dict(live)])]
        win.selection = (0, 0)
        control = mock.Mock()
        win.getControl = lambda cid: control
        with mock.patch.object(ui.xbmcgui, 'ListItem', mock.Mock()):
            win._show_channels()
        self.assertEqual([c[1]['title'] for c in win.channels], ['Live A'])   # live only, no duplicates
        self.assertEqual((props['nuvio.sport.channels'], focus[-1]), ('1', ui.CHANNEL_LIST))

    def test_back_never_leaves_sports(self):
        ui, win, props, focus = self.window(full=True, channels=True)
        back = SimpleNamespace(getId=lambda: 92)
        original = ui.SportsWindow.__dict__['onAction']
        handler = getattr(original, '__wrapped__', None)
        # The Dialog wrapper runs Back at once; call the window's own handler.
        for _ in range(3):
            ui.SportsWindow.onAction(win, back) if handler is None else handler(win, back)
        win.close.assert_not_called()
        self.assertEqual((props['nuvio.sport.channels'], props['nuvio.sport.full']), ('', ''))
        self.assertEqual(focus[-1], 108)   # the HUB button is the way out

    def test_moving_to_another_event_clears_the_stream_names(self):
        ui, win, props, focus = self.window()
        live = {'id': 'a', 'title': 'Live A', 'live': True, 'info': 'LIVE'}
        later = {'id': 'b', 'title': 'Later', 'live': False}
        win.rows = [('Football', None, None, [live, later])]
        win.streams = [{'label': 'S1', 'detail': ''}]
        win.stream_key = ((0, 0), 'a')
        win.playing_index = 0
        win.selection = (0, 0)
        win.changed = 0
        win.results = ui.queue.Queue()
        win.player = SimpleNamespace(token='')
        shown = []
        win._show_streams = lambda rows, status='': shown.append((len(rows), status))
        win._describe = lambda selection: None
        win._selected = lambda: (0, 1)
        win.getFocusId = lambda: ui.STREAM_LIST   # no new stream request in this tick
        win.tick()
        self.assertEqual(shown[-1], (0, 'Not live yet. Streams appear when the event starts.'))
        win._selected = lambda: (0, 0)
        win.tick()
        self.assertEqual(shown[-1], (1, ''))      # back on the playing event: its streams again

    def test_hold_ok_and_big_player_use_kodis_player(self):
        ui, win, props, focus = self.window()
        self.assertEqual(ui.player_mode(), 'small')
        with mock.patch.object(ui, 'cached_addon', return_value=Settings(nuvio_sport_player='big')):
            self.assertEqual(ui.player_mode(), 'big')
        source = (ROOT / 'script.nuvio/nuvio_ui/sports.py').read_text(encoding='utf-8')
        self.assertIn("'native' if player_mode() == 'big' else ''", source)
        self.assertIn('if aid in CONTEXT:', source)

    def test_a_dropped_stream_reconnects(self):
        ui, win, props, focus = self.window()
        win.playing_index, win.attempts, win.reconnect_at, win.use_ia, win.started_at = 0, 0, 0.0, True, 5.0
        win.player = SimpleNamespace(failed=False, token='t')
        win.after_ready = ''
        with mock.patch.object(win, '_play', create=True) as play:
            win._reconnect(100.0)
            self.assertEqual(props['nuvio.sport.video_status'], 'Reconnecting…')
            play.assert_not_called()
            win._reconnect(100.0 + ui.RECONNECT_DELAYS[0])
        play.assert_called_once()
        self.assertTrue(play.call_args.kwargs['reconnect'])
        win.attempts = len(ui.RECONNECT_DELAYS)
        win._reconnect(500.0)
        self.assertIn('stopped', props['nuvio.sport.video_status'])

    def test_live_hls_uses_inputstream_adaptive_when_installed(self):
        ui = importlib.import_module('nuvio_ui.sports')
        item = mock.Mock()
        with mock.patch.object(ui.xbmc, 'getCondVisibility', return_value=True), \
                mock.patch.object(ui.xbmc, 'getInfoLabel', return_value='21.2 (21.2.0) Git'):
            url = ui._hls_item(item, 'https://h/live.m3u8|Referer=x')
        self.assertEqual(url, 'https://h/live.m3u8')
        item.setProperty.assert_any_call('inputstream', 'inputstream.adaptive')
        item.setProperty.assert_any_call('inputstream.adaptive.stream_headers', 'Referer=x')


class GlassSettings(unittest.TestCase):
    def test_hub_settings_are_translucent_over_the_screen_behind(self):
        for folder in ('Default', 'Dark', 'Dim'):
            root = ET.parse(SKINS / folder / '1080i/nuvio_settings.xml').getroot()
            textures = [c.find('texture') for c in root.iter('control') if c.findtext('texture')]
            self.assertFalse(any('white.png' in (tex.text or '') for tex in textures), folder)  # no full-screen backdrop
            alphas = {tex.get('colordiffuse', '')[:2] for tex in textures if 'nuvio_pill.png' in (tex.text or '') and tex.get('border') == '18'}
            self.assertEqual(alphas, {'C4', '1A'}, folder)
        dialog = (ROOT / 'script.nuvio/nuvio_ui/dialog.py').read_text(encoding='utf-8')
        self.assertIn('def over(self, fn', dialog)


class CardShapes(unittest.TestCase):
    def test_every_card_size_has_its_own_2x_texture(self):
        import re as _re
        media = ROOT / 'script.nuvio/resources/media'
        def size(path):
            data = path.read_bytes()
            return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
        seen = 0
        for folder in ('Default', 'Dark', 'Dim'):
            for path in (SKINS / folder / '1080i').glob('*.xml'):
                text = path.read_text(encoding='utf-8')
                for name, w, h in _re.findall(r'(nuvio_(?:tile|poster)_(?:mask|glass|focus|focus_glass)_(\d+)x(\d+)\.png)', text):
                    self.assertEqual(size(media / name), (int(w) * 2, int(h) * 2), name)
                    seen += 1
        self.assertGreater(seen, 10)

    def test_glass_box_is_smooth_not_an_eroded_mask(self):
        source = (ROOT / 'review/make_crisp_shapes.py').read_text(encoding='utf-8')
        self.assertIn("glass_box(MEDIA / 'nuvio_tile_glass.png', 304, 171)", source)
        self.assertNotIn('glass.glass_from_mask(', source)


class PhoneCopy(unittest.TestCase):
    def test_copy_works_on_the_plain_http_page(self):
        page = (ROOT / 'plugin.video.nuviohub/resources/phone_setup/index.html').read_text(encoding='utf-8')
        self.assertIn("document.execCommand('copy')", page)
        self.assertIn('window.isSecureContext', page)


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

    def test_catalog_rows_movies_and_series_under_each_other(self):
        both = [{'type': 'movie'}, {'type': 'series'}]
        folders = [{'id': 'f%d' % i, 'title': 'Cat %d' % i, 'sources': both if i == 0 else [{'type': 'movie'}]} for i in range(4)]
        store = importlib.import_module('resources.lib.nuviohub.store')
        with mock.patch.object(ch, 'groups', return_value=[{'id': 'g', 'title': 'G', 'folders': folders}]), \
                mock.patch.object(store, 'list_providers', return_value=[]), \
                mock.patch.object(ch, 'folder_shelf', side_effect=lambda f, p, mt, title: {'title': title, 'type': mt, 'rows': []}), \
                mock.patch.object(ch, 'tiles', side_effect=lambda g: {'title': g['title'], 'rows': g['folders']}):
            shelves = ch.catalog_rows(4)
        self.assertEqual([s['title'] for s in shelves], ['Cat 0 · Movies', 'Cat 0 · Series', 'Cat 1', 'More catalogs'])
        self.assertEqual([s.get('type') for s in shelves[:2]], ['movie', 'series'])
        self.assertEqual([f['id'] for f in shelves[-1]['rows']], ['f2', 'f3'])


class StreamSwitches(unittest.TestCase):
    def test_no_repair_runs_at_entry(self):
        gate = (ROOT / 'script.nuvio/nuvio_ui/setup_gate.py').read_text(encoding='utf-8')
        self.assertNotIn('repair_all_on', gate)


if __name__ == '__main__':
    unittest.main()
