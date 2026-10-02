"""6.0.39: touch no longer breaks Home clicks, a failing action never closes
MegaNexus, speed-aware touch rows with a flick glide."""
import importlib
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()

dialog = importlib.import_module('nuvio_ui.dialog')
home = importlib.import_module('nuvio_ui.home_window')


def action(aid, x=0.0, y=0.0):
    return SimpleNamespace(getId=lambda: aid, getAmount1=lambda: x, getAmount2=lambda: y)


class Clock:
    def __init__(self, step):
        self.now, self.step = 100.0, step

    def __call__(self):
        self.now += self.step
        return self.now


class TouchThenClick(unittest.TestCase):
    def test_a_swipe_does_not_replace_the_home_window_methods(self):
        # 6.0.37: the touch state was stored as self._touch, which replaced
        # HomeWindow._touch(); the next click raised TypeError and Kodi showed
        # "Could not open the interface" (Android Kodi 22, opening a catalog).
        win = home.HomeWindow()
        win.onAction(action(dialog.GESTURE_BEGIN, 500, 500))
        win.onAction(action(dialog.GESTURE_END, 500, 300))
        self.assertTrue(callable(win._touch))
        self.assertNotIn('_touch', win.__dict__)
        win._touch()   # the method HomeWindow.onClick calls first

    def test_a_failing_action_keeps_the_window_open(self):
        win = dialog.Dialog()
        def broken():
            raise TypeError('boom')
        win.defer(broken)
        with mock.patch.object(dialog.xbmc, 'log') as log, mock.patch.object(dialog.xbmcgui, 'Dialog') as box:
            win.drain_events()   # must not raise
        self.assertIn('Traceback', log.call_args[0][0])
        box.return_value.notification.assert_called_once()
        self.assertFalse(win._dispatching)


class SpeedAwareTouch(unittest.TestCase):
    def window(self, can_step=True):
        class Rows(dialog.Dialog):
            TOUCH_ROWS = True
            def touch_can_step(self, down):
                return can_step or down
            def onAction(self, a):
                pass
        return Rows()

    def run_drag(self, win, points, step_seconds):
        sent = []
        clock = Clock(step_seconds)
        with mock.patch.object(dialog.xbmc, 'executebuiltin', side_effect=sent.append), \
                mock.patch.object(dialog.time, 'monotonic', side_effect=clock), \
                mock.patch.object(dialog.xbmcgui, 'getScreenHeight', return_value=1080, create=True):
            win.onAction(action(dialog.GESTURE_BEGIN, *points[0]))
            for point in points[1:]:
                win.onAction(action(dialog.GESTURE_PAN, *point))
            win.onAction(action(dialog.GESTURE_END, *points[-1]))
            for _ in range(200):   # the window loop
                win._touch_glide()
        return sent

    def test_slow_drag_moves_row_by_row_without_glide(self):
        sent = self.run_drag(self.window(), [(500, 900), (500, 870), (500, 600)], 0.4)
        self.assertEqual(sent, ['Action(Down)', 'Action(Down)'])
        self.assertFalse(self.window().touching())

    def test_fast_flick_glides_further(self):
        slow = self.run_drag(self.window(), [(500, 900), (500, 870), (500, 600)], 0.4)
        fast = self.run_drag(self.window(), [(500, 900), (500, 870), (500, 600)], 0.02)
        self.assertGreater(len(fast), len(slow))
        self.assertLessEqual(len(fast), 3 + dialog.TOUCH_FLING_MAX + 1)
        self.assertEqual(set(fast), {'Action(Down)'})

    def test_new_touch_stops_the_glide(self):
        win = self.window()
        self.run_drag(win, [(500, 900), (500, 870), (500, 600)], 0.02)
        win._touch_fling = {'down': True, 'left': 5, 'gap': 0.07, 'next': 0}
        win.onAction(action(dialog.GESTURE_BEGIN, 500, 500))
        self.assertIsNone(win._touch_fling)

    def test_touch_never_climbs_into_the_header(self):
        sent = self.run_drag(self.window(can_step=False), [(500, 200), (500, 230), (500, 900)], 0.02)
        self.assertEqual(sent, [])
        win = home.HomeWindow()
        win.getFocusId = lambda: home.ROW_BASE
        self.assertFalse(win.touch_can_step(False))   # first row: no Up into Home/Search
        self.assertTrue(win.touch_can_step(True))
        win.getFocusId = lambda: home.ROW_BASE + 2
        self.assertTrue(win.touch_can_step(False))


class SimklSmartSync(unittest.TestCase):
    def setUp(self):
        self.watched = importlib.import_module('resources.lib.simkl_watched')
        self.simkl = self.watched.simkl   # the copy simkl_watched uses
        self.stored = {}
        self.calls = []

    def run_refresh(self, old, activities, lists):
        def request(path, **kw):
            self.calls.append(path)
            if path == '/sync/activities':
                return activities
            kind = path.split('/')[3]
            return lists.get(kind, {})
        with mock.patch.object(self.watched, '_remote_snapshot', side_effect=lambda: self.stored.get('data', old)), \
                mock.patch.object(self.watched, 'snapshot', return_value={}), \
                mock.patch.object(self.watched, '_account', return_value='acc'), \
                mock.patch.object(self.watched, '_invalidate_view'), \
                mock.patch.object(self.simkl, '_request', side_effect=request), \
                mock.patch.object(self.simkl, '_write_json', side_effect=lambda path, data: self.stored.update(data=data) or True):
            self.watched.refresh(force=True)
        return self.stored.get('data')

    ACT = {'all': 'T1', 'movies': {'all': 'M1', 'removed_from_list': 'R'}, 'tv_shows': {'all': 'S1', 'removed_from_list': 'R'},
           'anime': {'all': 'A1', 'removed_from_list': 'R'}}

    def test_nothing_changed_means_one_small_request(self):
        old = {'account': 'acc', 'updated': 0, 'activities': self.ACT, 'items': {'movie|tt1': {'watched': True}}}
        data = self.run_refresh(old, self.ACT, {})
        self.assertEqual(self.calls, ['/sync/activities'])
        self.assertEqual(data['items'], {'movie|tt1': {'watched': True}})

    def test_only_the_changed_list_since_the_last_sync(self):
        old = {'account': 'acc', 'updated': 0, 'activities': self.ACT, 'items': {'movie|tt1': {'watched': True}}}
        now = dict(self.ACT, movies={'all': 'M2', 'removed_from_list': 'R'})
        movie = {'movies': [{'movie': {'ids': {'imdb': 'tt2'}}, 'status': 'completed'}]}
        data = self.run_refresh(old, now, {'movies': movie})
        self.assertEqual(self.calls, ['/sync/activities', '/sync/all-items/movies/?extended=full&date_from=M1'])
        self.assertTrue(data['items']['movie|tt1']['watched'] and data['items']['movie|tt2']['watched'])

    def test_first_sync_reads_everything(self):
        old = {'account': 'acc', 'updated': 0, 'items': {}}
        data = self.run_refresh(old, self.ACT, {'movies': {'movies': []}, 'shows': {'shows': []}, 'anime': {'anime': []}})
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(data['activities'], self.ACT)

    def test_no_watched_download_while_a_video_plays(self):
        progress_sync = importlib.import_module('resources.lib.progress_sync')
        window = mock.Mock(getProperty=lambda key: '')
        lock = mock.Mock(acquire=lambda blocking=True: True)
        simkl = mock.Mock(enabled=lambda: True, authorized=lambda: True)
        settings = mock.Mock(getSetting=lambda key: '60')
        sync = mock.Mock(enabled_targets=lambda: [])
        trakt = importlib.import_module('resources.lib.trakt')
        scheduler = progress_sync.Scheduler(window, playing=lambda: True)
        with mock.patch.object(trakt, 'authorized', return_value=False), \
                mock.patch.object(progress_sync, 'time') as clock:
            clock.monotonic.return_value = 1000
            scheduler.clock = lambda: 1000
            scheduler.step(sync, simkl, settings, lock)
        simkl.sync_playback_progress.assert_not_called()
        simkl.flush_progress.assert_called_once()   # sending finished watches continues


class TraktWatched(unittest.TestCase):
    def setUp(self):
        self.trakt = importlib.import_module('resources.lib.trakt')
        self.tw = importlib.import_module('resources.lib.trakt_watched')

    def test_parse_movies_and_shows(self):
        movies = self.tw.parse_movies([{'movie': {'ids': {'imdb': 'tt1', 'tmdb': 5}}, 'last_watched_at': '2026-01-01T00:00:00.000Z'}])
        self.assertTrue(movies['movie|tt1']['watched'] and movies['movie|tmdb:5']['watched'])
        shows = self.tw.parse_shows([{'show': {'ids': {'imdb': 'tt9'}, 'aired_episodes': 2},
                                      'seasons': [{'number': 1, 'episodes': [{'number': 1}, {'number': 2}]}]},
                                     {'show': {'ids': {'imdb': 'tt8'}, 'aired_episodes': 10},
                                      'seasons': [{'number': 1, 'episodes': [{'number': 1}]}]}])
        self.assertTrue(shows['series|tt9']['watched'])
        self.assertFalse(shows['series|tt8']['watched'])
        self.assertEqual(shows['series|tt8']['episodes'], ['1:1'])

    def test_refresh_downloads_only_changed_sections(self):
        stored = {}
        old = {'account': 'acc', 'updated': 0, 'items': {'movie|tt1': {'watched': True}},
               'activities': {'all': 'x', 'movies': {'watched_at': 'A'}, 'episodes': {'watched_at': 'B'}}}
        calls = []
        def request(path, **kw):
            calls.append(path)
            if path == '/sync/last_activities':
                return {'all': 'y', 'movies': {'watched_at': 'A'}, 'episodes': {'watched_at': 'C'}}
            return [{'show': {'ids': {'imdb': 'tt9'}, 'aired_episodes': 1}, 'seasons': [{'number': 1, 'episodes': [{'number': 1}]}]}]
        with mock.patch.object(self.trakt, 'authorized', return_value=True), \
                mock.patch.object(self.tw, 'snapshot', return_value=old), \
                mock.patch.object(self.tw, 'account', return_value='acc'), \
                mock.patch.object(self.trakt, '_request', side_effect=request), \
                mock.patch.object(self.trakt, '_write_json', side_effect=lambda p, d: stored.update(d)), \
                mock.patch('resources.lib.simkl_watched._invalidate_view'):
            self.tw.refresh(force=True)
        self.assertEqual(calls, ['/sync/last_activities', '/sync/watched/shows?extended=full'])
        self.assertTrue(stored['items']['movie|tt1']['watched'] and stored['items']['series|tt9']['watched'])

    def test_trakt_marks_show_in_the_watched_view(self):
        sw = importlib.import_module('resources.lib.simkl_watched')
        items = {'movie|tt77': {'watched': True, 'episodes': [], 'seasons': []}}
        with mock.patch.object(sw, '_trakt_items', return_value=items), \
                mock.patch.object(sw, '_remote_snapshot', return_value={'items': {}}):
            sw._MERGED.clear()
            self.assertTrue(sw.state(sw.snapshot(), 'movie', 'tt77').get('watched'))
        sw._MERGED.clear()

    def test_mark_watched_goes_to_trakt_history(self):
        sent = []
        with mock.patch.object(self.trakt, 'authorized', return_value=True), \
                mock.patch.object(self.trakt, '_request', side_effect=lambda path, **kw: sent.append((path, kw['payload'])) or {'added': {'episodes': 1}}), \
                mock.patch.object(self.tw, 'snapshot', return_value={'account': 'acc', 'items': {}}), \
                mock.patch.object(self.trakt, '_write_json'), \
                mock.patch('resources.lib.simkl_watched._invalidate_view'):
            self.assertTrue(self.tw.mark({'media_type': 'series', 'imdb_id': 'tt9'}, 'episode', 2, 5))
        self.assertEqual(sent, [('/sync/history', {'shows': [{'ids': {'imdb': 'tt9'}, 'seasons': [{'number': 2, 'episodes': [{'number': 5}]}]}]})])

    def test_details_mark_uses_every_connected_service(self):
        import kodi_stub
        text = open(kodi_stub.ADDON_ROOT + '/../script.nuvio/nuvio_ui/details.py', encoding='utf-8').read()
        self.assertIn("'Trakt':trakt_watched.mark", text)


class TraktRequests(unittest.TestCase):
    def setUp(self):
        self.trakt = importlib.import_module('resources.lib.trakt')

    def error(self, code, retry=None):
        import urllib.error
        return urllib.error.HTTPError('https://api.trakt.tv/x', code, 'x', {'Retry-After': retry} if retry else {}, None)

    def test_401_refreshes_once_and_retries(self):
        replies = [self.error(401), {'ok': 1}]
        def send(*a):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        with mock.patch.object(self.trakt, '_send', side_effect=send), \
                mock.patch.object(self.trakt, 'token_data', return_value={'refresh_token': 'r'}), \
                mock.patch.object(self.trakt, '_refresh_token_if_needed') as refresh:
            self.assertEqual(self.trakt._request('/x', auth=True), {'ok': 1})
        refresh.assert_called_once_with(force=True)

    def test_429_waits_as_asked(self):
        replies = [self.error(429, '2'), {'ok': 1}]
        def send(*a):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        with mock.patch.object(self.trakt, '_send', side_effect=send), \
                mock.patch.object(self.trakt.time, 'sleep') as sleep:
            self.assertEqual(self.trakt._request('/x'), {'ok': 1})
        sleep.assert_called_once_with(2.0)

    def test_offline_watch_is_queued_and_sent_as_history(self):
        import urllib.error
        queued = []
        ctx = {'media_type': 'movie', 'imdb_id': 'tt1', 'title': 'X', 'duration_ms': 1000}
        with mock.patch.object(self.trakt, 'enabled', return_value=True), \
                mock.patch.object(self.trakt, 'scrobble_enabled', return_value=True), \
                mock.patch.object(self.trakt, '_ensure_auth', return_value={'access_token': 't'}), \
                mock.patch.object(self.trakt, '_request', side_effect=urllib.error.URLError('offline')), \
                mock.patch.object(self.trakt, '_queue_scrobble', side_effect=queued.append):
            self.assertIsNone(self.trakt.scrobble('stop', ctx, 950))
        self.assertEqual(queued[0]['movie']['ids'], {'imdb': 'tt1'})
        store = {'rows': [{'at': 1767225600, 'payload': queued[0]}]}
        sent = []
        with mock.patch.object(self.trakt, 'authorized', return_value=True), \
                mock.patch.object(self.trakt, '_read_json', side_effect=lambda p, d: store['rows']), \
                mock.patch.object(self.trakt, '_write_json', side_effect=lambda p, rows: store.update(rows=rows)), \
                mock.patch.object(self.trakt, '_request', side_effect=lambda path, **kw: sent.append((path, kw['payload']))):
            self.assertEqual(self.trakt.flush_outbox(), 1)
        self.assertEqual(sent[0][0], '/sync/history')
        self.assertEqual(sent[0][1]['movies'][0]['watched_at'], '2026-01-01T00:00:00.000Z')
        self.assertEqual(store['rows'], [])


class RamProfile(unittest.TestCase):
    def test_budgets_follow_device_memory(self):
        ram = importlib.import_module('resources.lib.ram_profile')
        self.assertEqual([ram.for_device(mb) for mb in (1024, 2048, 3072, 4096, 8192, 0)],
                         ['ram96', 'ram96', 'ram160', 'ram160', 'ram256', 'ram160'])
        with mock.patch.object(ram, 'device_mb', return_value=1900):
            self.assertEqual(ram.effective('auto'), 'ram96')
            self.assertEqual(ram.pages('auto', 1), 32 * ram.MIB)
            self.assertEqual(ram.effective('disk512'), 'disk512')

    def test_kodi_memory_label_is_read(self):
        ram = importlib.import_module('resources.lib.ram_profile')
        ram._DEVICE.clear()
        with mock.patch('xbmc.getInfoLabel', return_value='3814MB', create=True):
            self.assertEqual(ram.device_mb(), 3814)
        ram._DEVICE.clear()


class JellyfinTwelve(unittest.TestCase):
    def setUp(self):
        self.emby = importlib.import_module('resources.lib.emby_client')

    def test_jellyfin_uses_the_standard_header_root_paths_and_apikey(self):
        headers = self.emby._headers('TOKEN', self.emby.JELLYFIN)
        self.assertIn('Token="TOKEN"', headers['Authorization'])
        self.assertTrue(headers['Authorization'].startswith('MediaBrowser Client="MegaNexus"'))
        self.assertFalse({'X-Emby-Token', 'X-Emby-Authorization', 'X-MediaBrowser-Token'} & set(headers))
        server = {'url': 'http://nas:8096', 'token': 'TOKEN', 'flavor': 'jellyfin'}
        art = self.emby.artwork_url(server, 'abc')
        self.assertTrue(art.startswith('http://nas:8096/Items/abc/Images/Primary?'))
        self.assertIn('ApiKey=TOKEN', art)
        self.assertNotIn('api_key', art)
        self.assertIn('maxWidth=500', art)
        self.assertTrue(self.emby.playback_url(server, 'abc').startswith('http://nas:8096/Videos/abc/stream?'))

    def test_emby_keeps_its_own_scheme(self):
        headers = self.emby._headers('TOKEN', self.emby.EMBY)
        self.assertEqual(headers['X-Emby-Token'], 'TOKEN')
        self.assertNotIn('Authorization', headers)
        server = {'url': 'http://nas:8096', 'token': 'TOKEN', 'flavor': 'emby'}
        self.assertIn('/emby/Items/abc/Images/Primary?', self.emby.artwork_url(server, 'abc'))
        self.assertIn('api_key=TOKEN', self.emby.artwork_url(server, 'abc'))

    def test_flavor_detection(self):
        import json
        replies = {'http://nas:8096/System/Info/Public': {'ProductName': 'Jellyfin Server', 'ServerName': 'Home', 'Version': '12.1.0'}}
        def request(url, **kw):
            if url not in replies:
                raise self.emby.EmbyError('404')
            return json.dumps(replies[url]).encode()
        with mock.patch.object(self.emby, '_request', side_effect=request):
            found = self.emby.detect('nas:8096')
        self.assertEqual((found['flavor'], found['name'], found['url']), ('jellyfin', 'Home', 'http://nas:8096'))

    def test_quick_connect(self):
        import json
        calls = []
        def request(url, method='GET', token='', data=None, timeout=None, flavor='jellyfin'):
            calls.append((method, url.split('8096')[1], data))
            if url.endswith('/QuickConnect/Enabled'):
                return b'true'
            if url.endswith('/QuickConnect/Initiate'):
                return json.dumps({'Secret': 'S', 'Code': '123456'}).encode()
            if '/QuickConnect/Connect' in url:
                return json.dumps({'Authenticated': True}).encode()
            return json.dumps({'AccessToken': 'T', 'User': {'Id': 'U', 'Name': 'me'}, 'ServerName': 'Home'}).encode()
        server = {'flavor': 'jellyfin', 'name': 'Home', 'version': '12.1', 'url': 'http://nas:8096'}
        with mock.patch.object(self.emby, 'detect', return_value=server), \
                mock.patch.object(self.emby, '_request', side_effect=request), \
                mock.patch.object(self.emby, '_save_json_setting') as save:
            state = self.emby.quick_connect_start('nas')
            self.assertEqual(state['code'], '123456')
            auth = self.emby.quick_connect_poll(state)
        self.assertEqual((auth['token'], auth['flavor'], auth['user_id']), ('T', 'jellyfin', 'U'))
        self.assertIn(('POST', '/QuickConnect/Initiate', None), calls)   # GET Initiate is gone in Jellyfin 12
        self.assertIn(('POST', '/Users/AuthenticateWithQuickConnect', {'Secret': 'S'}), calls)
        save.assert_called_once()

    def test_reporter_follows_the_server(self):
        companion = importlib.import_module('resources.lib.companion')
        sent = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b''
        def urlopen(req, timeout=None):
            sent.append((req.full_url, dict(req.header_items())))
            return Response()
        ctx = {'server_url': 'http://nas:8096', 'token': 'T', 'item_id': 'I', 'server_flavor': 'jellyfin'}
        with mock.patch.object(companion.urllib.request, 'urlopen', side_effect=urlopen):
            companion.EmbyReporter().started(ctx, 1000)
        url, headers = sent[0]
        self.assertEqual(url, 'http://nas:8096/Sessions/Playing')
        self.assertIn('Token="T"', headers.get('Authorization', ''))


class PlexResources(unittest.TestCase):
    def test_v2_json_resources_first(self):
        import json
        plex = importlib.import_module('resources.lib.plex_client')
        rows = [{'name': 'Home', 'provides': 'server', 'clientIdentifier': 'abc', 'accessToken': 'T', 'owned': True,
                 'httpsRequired': False, 'connections': [{'uri': 'https://1-2-3-4.x.plex.direct:32400', 'local': True,
                                                          'relay': False, 'protocol': 'https', 'address': '1.2.3.4', 'port': 32400}]}]
        urls = []
        def request(url, **kw):
            urls.append(url)
            return json.dumps(rows).encode()
        with mock.patch.object(plex, 'account', return_value={'token': 'acc'}), \
                mock.patch.object(plex, '_parse_json_setting', return_value={}), \
                mock.patch.object(plex.plex_state, 'load_server_cache', return_value={}), \
                mock.patch.object(plex, '_cache_servers'), \
                mock.patch.object(plex, '_request', side_effect=request):
            found = plex.servers(force=True)
        self.assertTrue(urls[0].startswith('https://clients.plex.tv/api/v2/resources'))
        self.assertEqual((found[0]['id'], found[0]['token'], found[0]['owned']), ('abc', 'T', True))
        self.assertTrue(found[0]['connections'][0]['local'])
        self.assertTrue(plex.is_local_connection(found[0], 'https://1-2-3-4.x.plex.direct:32400'))

    def test_posters_are_resized_by_the_server(self):
        plex = importlib.import_module('resources.lib.plex_client')
        url = plex.poster_url({'server_url': 'http://nas:32400', 'token': 'T'}, '/library/metadata/1/thumb/2')
        self.assertTrue(url.startswith('http://nas:32400/photo/:/transcode?width=500&height=750'))


class MediaServersInMegaNexus(unittest.TestCase):
    def setUp(self):
        self.ms = importlib.import_module('resources.lib.media_servers')
        self.ms.forget()

    def addon(self, **values):
        return mock.Mock(getSetting=lambda key: values.get(key, ''))

    def test_everything_is_off_by_default(self):
        with mock.patch.object(self.ms, 'signed_in', return_value=True):
            self.assertFalse(self.ms.enabled('plex', self.addon()))
            self.assertEqual(self.ms.source_jobs('movie', 'tt1', self.addon()), [])
            self.assertEqual(self.ms.shelves(self.addon(nuvio_plex_enabled='true')), [])   # Home rows: own switch
        with mock.patch.object(self.ms, 'signed_in', return_value=False):
            self.assertFalse(self.ms.enabled('plex', self.addon(nuvio_plex_enabled='true')))
        import kodi_stub
        text = open(kodi_stub.ADDON_ROOT + '/resources/settings.xml', encoding='utf-8').read()
        for key in ('nuvio_plex_enabled', 'nuvio_jellyfin_enabled', 'nuvio_home_plex', 'nuvio_home_jellyfin', 'nuvio_home_local'):
            self.assertIn('id="%s" type="bool" default="false"' % key, text)

    def test_video_ids(self):
        self.assertEqual(self.ms.parse_video_id('movie', 'tt1'), ({'imdb_id': 'tt1'}, None, None))
        self.assertEqual(self.ms.parse_video_id('series', 'tmdb:9:2:3'), ({'tmdb_id': '9'}, 2, 3))
        self.assertEqual(self.ms.parse_video_id('series', 'tt1'), (None, None, None))
        self.assertEqual(self.ms.parse_video_id('movie', 'kitsu:1'), (None, None, None))

    def test_own_server_copies_come_first(self):
        import sys
        def live(name):
            # The module object backend_api's "from . import name" resolves to;
            # importing other copies would confuse later test modules.
            importlib.import_module('resources.lib.' + name)
            return getattr(sys.modules['resources.lib'], name)
        backend = live('backend_api')
        media = live('media_servers')
        stream_providers = live('stream_providers')
        client = sys.modules[backend.__package__ + '.nuviohub.client']
        addon_row = {'name': 'Add-on', 'url': 'http://a/1.mkv'}
        server_row = {'name': 'Plex · Home', 'url': 'http://nas/1.mkv', '_nuvio_server': {'server_type': 'plex'}}
        with mock.patch.object(stream_providers, 'enabled', return_value=[{'id': 'a', 'name': 'A', 'base_url': 'http://a'}]), \
                mock.patch.object(media, 'source_jobs', return_value=[('Plex', lambda: [server_row])]), \
                mock.patch.object(client, 'build_resource_url', return_value='http://a/stream'), \
                mock.patch.object(client, 'get_json', return_value={'streams': [addon_row]}):
            source, rows = backend.streams('movie', 'tt1')
        self.assertEqual([r['name'] for r in rows], ['Plex · Home', 'Add-on'])
        with mock.patch.object(stream_providers, 'enabled', return_value=[]), \
                mock.patch.object(media, 'source_jobs', return_value=[('Plex', lambda: [server_row])]):
            source, rows = backend.streams('movie', 'tt1')   # no stream add-on needed
        self.assertEqual(len(rows), 1)

    def test_cards_use_server_posters_and_open_our_page_only_with_ids(self):
        movie = {'media_type': 'movie', 'raw_title': 'Heat', 'year': 1995, 'ids': {'imdb_id': 'tt0113277'}, 'duration_ms': 100}
        card = self.ms._card('plex', movie, 'http://nas/p.jpg', 'http://nas/f.jpg', 'plugin://x')
        self.assertEqual(card['target']['canonical_id'], 'tt0113277')
        self.assertEqual(card['poster'], 'http://nas/p.jpg')   # no second poster download
        home_video = {'media_type': 'movie', 'raw_title': 'Holiday', 'ids': {}}
        self.assertEqual(self.ms._card('plex', home_video, '', '', 'plugin://x')['server_play'], 'plugin://x')
        resumed = self.ms._card('plex', dict(movie, duration_ms=1000), '', '', 'plugin://x', resume_ms=500)
        self.assertEqual((resumed['percent_value'], resumed['server_play']), (50, 'plugin://x'))

    def test_plex_row_says_when_it_needs_a_pass(self):
        plex = importlib.import_module(self.ms.__package__ + '.plex_client')
        health = importlib.import_module(self.ms.__package__ + '.servers.health')
        item = {'server_name': 'Home', 'server_url': 'https://far:32400', 'token': 'T', 'rating_key': '1',
                'duration_ms': 5, 'versions': [{'part_key': '/p', 'info_line': '4K'}]}
        with mock.patch.object(plex, 'servers', return_value=[{'id': 's', 'connections': [{'uri': 'http://lan:32400', 'local': True}]}]), \
                mock.patch.object(health, 'should_query', return_value=True), \
                mock.patch.object(plex, 'find_all_by_ids', return_value=[item]), \
                mock.patch.object(plex, 'client_identifier', return_value='cid'):
            rows = self.ms._plex_rows({'imdb_id': 'tt1'}, 'movie', None, None)
        self.assertIn('Plex Pass', rows[0]['title'])
        self.assertEqual(rows[0]['_nuvio_server']['rating_key'], '1')

    def test_settings_and_phone(self):
        import kodi_stub
        root = kodi_stub.ADDON_ROOT + '/../script.nuvio/nuvio_ui/'
        settings_text = open(root + 'settings.py', encoding='utf-8').read()
        self.assertIn("Plex (beta)", settings_text)
        self.assertIn("Jellyfin / Emby (beta)", settings_text)
        self.assertIn("Local storage (beta)", settings_text)
        page = open(kodi_stub.ADDON_ROOT + '/resources/phone_setup/index.html', encoding='utf-8').read()
        self.assertIn('/api/jellyfin/signin', page)
        link = importlib.import_module('resources.lib.tracking_link')
        self.assertIn('plex', link.SERVICES)
        phone = importlib.import_module('resources.lib.phone_setup')
        with self.assertRaises(ValueError):
            phone.jellyfin_sign_in('', 'me', 'pw')

    def test_home_server_card_plays_from_the_server(self):
        sent = []
        with mock.patch.object(home.xbmc, 'executebuiltin', side_effect=sent.append), \
                mock.patch.object(home.xbmc, 'Player') as player, \
                mock.patch.object(home.xbmc, 'Monitor') as monitor:
            monitor.return_value.waitForAbort.return_value = False
            player.return_value.isPlayingVideo.return_value = True
            self.assertEqual(home._server_play('plugin://plugin.video.nuviohub/?action=plex_play&server_id=a&rating_key=1'), 'playing')
        self.assertEqual(sent, ['RunPlugin("plugin://plugin.video.nuviohub/?action=plex_play&server_id=a&rating_key=1")'])
        self.assertEqual(home._server_play('plugin://other/?x'), '')


if __name__ == '__main__':
    unittest.main()
