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


if __name__ == '__main__':
    unittest.main()
