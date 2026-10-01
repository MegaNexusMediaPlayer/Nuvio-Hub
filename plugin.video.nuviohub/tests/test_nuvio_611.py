"""6.0.11 Home responsiveness contracts. HTTP and Kodi GUI are fakes, SQLite is real.

These tests prove cache/threading behaviour only; they are not device timings.
"""
from concurrent.futures import Future
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock
import frontend_test_support
frontend_test_support.install()
from resources.lib import (browse_cache as cache, home_data, metadata_providers as providers,
                           collection_profile as profiles, collections_home, art_cache)
from resources.lib.nuviohub import store, client
from nuvio_ui import home_window, startup
import kodi_stub

simkl_watched = importlib.import_module('resources.lib.simkl_watched')


def provider(pid='p'):
    return {'id': pid, 'name': pid, 'base_url': 'https://example.invalid/' + pid,
            'manifest_url': 'https://example.invalid/%s/manifest.json' % pid,
            'manifest': {'id': 'meta.' + pid, 'name': pid, 'version': '1', 'resources': ['meta', 'catalog'],
                         'types': ['movie', 'series'], 'idPrefixes': ['tt'],
                         'catalogs': [{'id': 'popular', 'type': 'movie'}, {'id': 'popular', 'type': 'series'}]}}


def page(*ids):
    return {'metas': [{'id': i, 'type': 'movie', 'name': 'Title ' + i, 'poster': 'https://img.invalid/%s.jpg' % i}
                      for i in ids]}


class TempCache(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'browse.db'
        self.clock = [1000.0]
        self.cache = cache.Cache(self.path, clock=lambda: self.clock[0])
        patch = mock.patch.object(cache, 'instance', return_value=self.cache)
        patch.start()
        self.addCleanup(patch.stop)
        self.refreshes = []
        refresh = mock.patch.object(cache, 'refresh', side_effect=lambda *a, **k: self.refreshes.append(a))
        refresh.start()
        self.addCleanup(refresh.stop)


class StaleWhileRevalidate(TempCache):
    def test_stale_page_is_served_without_network_and_revalidated_once(self):
        p = provider()
        c = p['manifest']['catalogs'][0]
        self.cache.put(cache.catalog_key(p, c, {}), page('tt1'), ttl=10, stale=100)
        self.clock[0] += 50
        self.assertIsNone(self.cache.get(cache.catalog_key(p, c, {})), 'get() stays fresh-only')
        with mock.patch.object(client, 'fetch_catalog', side_effect=AssertionError('network on stale hit')):
            self.assertEqual(cache.catalog(p, c)['metas'][0]['id'], 'tt1')
        self.assertEqual(len(self.refreshes), 1)

    def test_hard_expiry_removes_stale_page(self):
        p = provider()
        c = p['manifest']['catalogs'][0]
        self.cache.put(cache.catalog_key(p, c, {}), page('tt1'), ttl=10, stale=100)
        self.clock[0] += 200
        self.assertEqual(self.cache.lookup(cache.catalog_key(p, c, {})), (None, False))

    def test_forced_refresh_replaces_stale_page(self):
        p = provider()
        c = p['manifest']['catalogs'][0]
        key = cache.catalog_key(p, c, {})
        self.cache.put(key, page('old'), ttl=10, stale=100)
        self.clock[0] += 50
        with mock.patch.object(client, 'fetch_catalog', return_value=page('new')) as get:
            self.assertEqual(cache.catalog(p, c, force=True)['metas'][0]['id'], 'new')
        get.assert_called_once()
        value, fresh = self.cache.lookup(key)
        self.assertTrue(fresh)
        self.assertEqual(value['metas'][0]['id'], 'new')

    def test_search_results_have_no_stale_window(self):
        p = provider()
        c = p['manifest']['catalogs'][0]
        with mock.patch.object(client, 'fetch_catalog', return_value=page('tt1')):
            cache.catalog(p, c, {'search': 'x'})
        self.clock[0] += 121
        self.assertIsNone(cache.peek(p, c, {'search': 'x'}))

    def test_peek_never_fetches_and_revalidates_stale(self):
        p = provider()
        c = p['manifest']['catalogs'][0]
        with mock.patch.object(client, 'fetch_catalog', side_effect=AssertionError('peek used network')):
            self.assertIsNone(cache.peek(p, c))
            self.cache.put(cache.catalog_key(p, c, {}), page('tt1'), ttl=10, stale=100)
            self.assertIsNotNone(cache.peek(p, c))
            self.assertEqual(self.refreshes, [])
            self.clock[0] += 50
            self.assertIsNotNone(cache.peek(p, c))
        self.assertEqual(len(self.refreshes), 1)

    def test_restart_keeps_stale_window(self):
        self.cache.put('a', {'x': 1}, ttl=10, stale=100)
        self.clock[0] += 50
        second = cache.Cache(self.path, clock=lambda: self.clock[0])
        self.assertEqual(second.lookup('a'), ({'x': 1}, False))

    def test_lookup_many_promotes_with_one_connection(self):
        self.cache.put('a', {'x': 1}, ttl=10, stale=100)
        self.cache.put('b', {'x': 2}, ttl=100)
        self.clock[0] += 50
        second = cache.Cache(self.path, clock=lambda: self.clock[0])
        with mock.patch.object(second, '_connect', wraps=second._connect) as connect:
            self.assertEqual(second.lookup_many(['a', 'b', 'missing']), {'a': False, 'b': True})
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(second.lookup('a', memory_only=True), ({'x': 1}, False))

    def test_6010_database_is_migrated_in_place(self):
        legacy = self.path.with_name('legacy.db')
        conn = sqlite3.connect(str(legacy))
        conn.execute('CREATE TABLE cache (key TEXT PRIMARY KEY, value BLOB NOT NULL, expires REAL NOT NULL, touched REAL NOT NULL, bytes INTEGER NOT NULL)')
        conn.execute('INSERT INTO cache VALUES(?,?,?,?,?)', ('k', b'{"x":1}', 2000.0, 1000.0, 7))
        conn.commit()
        conn.close()
        migrated = cache.Cache(legacy, clock=lambda: 1500.0)
        self.assertEqual(migrated.lookup('k'), ({'x': 1}, True))
        self.assertTrue(migrated.put('n', {'y': 2}, ttl=10))


class LegacyCacheFile(unittest.TestCase):
    def test_6010_pages_are_imported_once_and_old_file_removed(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        old = Path(temp.name) / 'browse610.db'
        conn = sqlite3.connect(str(old))
        conn.execute('CREATE TABLE cache (key TEXT PRIMARY KEY, value BLOB NOT NULL, expires REAL NOT NULL, touched REAL NOT NULL, bytes INTEGER NOT NULL)')
        conn.executemany('INSERT INTO cache VALUES(?,?,?,?,?)', [('live', b'{"x":1}', 2000.0, 1.0, 7),
                                                                 ('dead', b'{"x":2}', 10.0, 1.0, 7)])
        conn.commit()
        conn.close()
        new = cache.Cache(Path(temp.name) / 'browse611.db', clock=lambda: 1500.0)
        self.assertEqual(new.import_legacy(old), 1)
        self.assertFalse(old.exists(), 'rollback to 6.0.10 starts from its own empty file')
        self.assertEqual(new.lookup('live'), ({'x': 1}, True))
        self.assertEqual(new.lookup('dead'), (None, False))
        self.assertEqual(new.import_legacy(old), 0)

    def test_unreadable_legacy_file_is_ignored(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        old = Path(temp.name) / 'browse610.db'
        old.write_bytes(b'not a database')
        new = cache.Cache(Path(temp.name) / 'browse611.db')
        self.assertEqual(new.import_legacy(old), 0)
        self.assertTrue(new.put('a', {'ok': True}))


class RefreshQueue(unittest.TestCase):
    def test_refresh_is_bounded_and_deduplicated_against_inflight(self):
        import queue
        jobs = queue.Queue(maxsize=1)
        p = provider()
        c = p['manifest']['catalogs'][0]
        with mock.patch.object(cache, '_refresher', return_value=jobs):
            self.assertTrue(cache.refresh(p, c))
            self.assertFalse(cache.refresh(p, c, {'genre': 'x'}), 'full queue drops instead of blocking')
            with cache._FLIGHT_LOCK:
                cache._FLIGHTS[cache.catalog_key(p, c, {'a': 1})] = Future()
            try:
                self.assertFalse(cache.refresh(p, c, {'a': 1}))
            finally:
                with cache._FLIGHT_LOCK:
                    cache._FLIGHTS.clear()


class CachedShelves(TempCache):
    def shelf(self, *jobs):
        return {'path': 'plugin://x', 'collection_job': list(jobs)}

    def test_cached_only_collection_needs_every_source(self):
        p = provider()
        movie, series = p['manifest']['catalogs']
        shelf = self.shelf((p, movie, {}), (p, series, {}))
        self.cache.put(cache.catalog_key(p, movie, {}), page('tt1', 'tt2'), ttl=100)
        with mock.patch.object(client, 'fetch_catalog', side_effect=AssertionError('network while painting')):
            self.assertIsNone(home_data.load_catalog(shelf, cached_only=True))
            self.cache.put(cache.catalog_key(p, series, {}), page('tt3'), ttl=100)
            rows = home_data.load_catalog(shelf, cached_only=True)
        self.assertEqual([r['target']['canonical_id'] for r in rows if r.get('target')], ['tt1', 'tt3', 'tt2'])
        self.assertEqual(rows[-1]['title'], 'Browse all')

    def test_memory_seed_mode_never_opens_sqlite(self):
        p = provider()
        movie = p['manifest']['catalogs'][0]
        with mock.patch.object(self.cache, '_connect', side_effect=AssertionError('disk read')):
            self.assertIsNone(home_data.load_catalog({'job': (p, movie), 'path': 'x'}, cached_only='memory'))

    def test_collection_sources_load_concurrently_and_tolerate_one_failure(self):
        p = provider()
        movie, series = p['manifest']['catalogs']
        both = threading.Barrier(2, timeout=2)

        def fetch(prov, media_type, catalog_id, **kwargs):
            both.wait()  # Serial loading would deadlock here and time out.
            if media_type == 'series':
                raise TimeoutError('slow provider')
            return page('tt1')
        with mock.patch.object(client, 'fetch_catalog', side_effect=fetch):
            rows = home_data.load_catalog(self.shelf((p, movie, {}), (p, series, {})))
        self.assertEqual([r['target']['canonical_id'] for r in rows if r.get('target')], ['tt1'])

    def test_all_sources_failing_still_reports_failure(self):
        p = provider()
        movie, series = p['manifest']['catalogs']
        with mock.patch.object(client, 'fetch_catalog', side_effect=TimeoutError('offline')):
            with self.assertRaises(TimeoutError):
                home_data.load_catalog(self.shelf((p, movie, {}), (p, series, {})))


class StartupWarmup(TempCache):
    def test_stale_pages_skip_loading_screen_and_queue_revalidation(self):
        p = provider()
        c = p['manifest']['catalogs'][0]
        key = cache.catalog_key(p, c, {})
        self.cache.put(key, page('tt1'), ttl=10, stale=100)
        self.clock[0] += 50
        with mock.patch.object(startup, 'jobs', return_value=[(key, p, c, {})]), \
                mock.patch.object(startup, 'Loading', side_effect=AssertionError('loading screen shown')):
            self.assertEqual(startup.prepare()['cached'], 1)
        self.assertEqual(len(self.refreshes), 1)


class FakeList:
    def __init__(self):
        self.items, self.position, self.resets = [], 0, 0

    def reset(self):
        self.resets += 1
        self.items = []

    def addItems(self, items):
        self.items.extend(items)

    def getSelectedPosition(self):
        return self.position

    def getSelectedItem(self):
        return self.items[self.position] if self.items else None

    def selectItem(self, pos):
        self.position = pos

    def getListItem(self, pos):
        return self.items[pos]

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class FakeItem:
    def __init__(self, label='', label2=''):
        self.label, self.props = label, {}

    def getLabel(self):
        return self.label

    def setProperty(self, key, value):
        self.props[key] = value

    def getProperty(self, key):
        return self.props.get(key, '')

    def setArt(self, art):
        self.art = art


class HomeWindowResponsiveness(TempCache):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(home_window.xbmcgui, 'ListItem', FakeItem)
        patch.start()
        self.addCleanup(patch.stop)

    def window(self, focus=home_window.ROW_BASE):
        win = home_window.HomeWindow()
        controls = {}
        win.getControl = lambda cid: controls.setdefault(cid, FakeList())
        win.getFocusId = lambda: focus
        win.setFocusId = lambda cid: None
        win.setProperty = lambda *args: None
        win._pool = mock.Mock()
        win._watch_loaded = True
        win.controls = controls
        return win

    def collection(self, p):
        movie = p['manifest']['catalogs'][0]
        return {'title': 'Films', 'path': 'plugin://x', 'collection_job': [(p, movie, {})],
                'rows': [home_data.placeholder('Loading titles', 'Loading your collection.')]}

    def test_opened_collection_paints_cached_titles_without_a_worker(self):
        p = provider()
        self.cache.put(cache.catalog_key(p, p['manifest']['catalogs'][0], {}), page('tt1', 'tt2'), ttl=100)
        win = self.window()
        with mock.patch.object(client, 'fetch_catalog', side_effect=AssertionError('GUI network')):
            win._paint([self.collection(p)])
        titles = [li.getLabel() for li in win.controls[home_window.ROW_BASE].items]
        self.assertEqual(titles, ['Title tt1', 'Title tt2', 'Browse all'])
        win._pool.submit.assert_not_called()

    def test_uncached_collection_still_loads_in_background(self):
        win = self.window()
        win._paint([self.collection(provider())])
        self.assertEqual(win._pool.submit.call_count, 1)

    def test_identical_reload_does_not_rebuild_the_list(self):
        p = provider()
        self.cache.put(cache.catalog_key(p, p['manifest']['catalogs'][0], {}), page('tt1'), ttl=100)
        win = self.window()
        win._paint([self.collection(p)])
        control = win.controls[home_window.ROW_BASE]
        resets = control.resets
        win._updates.put((win._generation, 0, list(win._shelves[0]['rows']), None))
        win.drain_updates()
        self.assertEqual(control.resets, resets)
        changed = [dict(win._shelves[0]['rows'][0], title='Renamed')] + win._shelves[0]['rows'][1:]
        win._updates.put((win._generation, 0, changed, None))
        win.drain_updates()
        self.assertEqual(control.resets, resets + 1)

    def test_prefetch_waits_for_dwell_and_runs_once(self):
        win = self.window()
        tiles = [dict(home_data.placeholder('A', ''), collection_id='a'),
                 dict(home_data.placeholder('B', ''), collection_id='b')]
        win._shelves = [{'title': 'Collections', 'rows': tiles, '_loaded': True}]
        win.controls[home_window.ROW_BASE] = control = FakeList()
        control.items = [object(), object()]
        submitted = []
        win._prefetch_pool = mock.Mock(submit=lambda fn, cid, epoch: submitted.append(cid) or Future())
        win._maybe_prefetch()
        self.assertEqual(submitted, [], 'first observation only starts the dwell timer')
        win._hover = (win._hover[0], time.monotonic() - 1)
        win._maybe_prefetch()
        win._maybe_prefetch()
        self.assertEqual(submitted, ['a', 'b'])

    def test_moving_on_drops_queued_prefetch_for_tiles_left_behind(self):
        win = self.window()
        tiles = [dict(home_data.placeholder(c, ''), collection_id=c) for c in 'abcdef']
        win._shelves = [{'title': 'Collections', 'rows': tiles, '_loaded': True}]
        win.controls[home_window.ROW_BASE] = control = FakeList()
        control.items = [object()] * len(tiles)
        queued = []
        win._prefetch_pool = mock.Mock(submit=lambda fn, cid, epoch: queued.append((cid, Future())) or queued[-1][1])
        win._hover = ((0, 0), time.monotonic() - 1)
        win._maybe_prefetch()
        queued[0][1].set_running_or_notify_cancel()  # 'a' already running; 'b' still queued
        control.position = 4
        win._hover = ((0, 4), time.monotonic() - 1)
        win._maybe_prefetch()
        self.assertFalse(queued[0][1].cancelled())
        self.assertTrue(queued[1][1].cancelled())
        self.assertNotIn('b', win._prefetched, 'a dropped tile can be prefetched again later')
        self.assertEqual([cid for cid, _ in queued[2:]], ['e', 'f', 'd'])

    def test_prefetched_rows_are_used_when_the_collection_opens(self):
        p = provider()
        shelf = self.collection(p)
        win = self.window()
        frontend_collections = importlib.import_module('resources.lib.collections_home')
        with mock.patch.object(frontend_collections, 'collection_shelves', return_value=[dict(shelf)]), \
                mock.patch.object(client, 'fetch_catalog', return_value=page('tt9')):
            win._prefetch_collection('films', win._memory_epoch)
        self.cache.clear()
        with mock.patch.object(client, 'fetch_catalog', side_effect=AssertionError('refetched')):
            win._paint([dict(shelf)])
        self.assertEqual(win.controls[home_window.ROW_BASE].items[0].getLabel(), 'Title tt9')
        win._pool.submit.assert_not_called()

    def test_settings_change_discards_late_prefetch(self):
        win = self.window()
        epoch = win._memory_epoch
        win._forget_rows()
        win._remember_rows('k', [{'target': {'canonical_id': 'x'}}], epoch)
        self.assertIsNone(win._remembered('k'))


class WatchedSnapshot(unittest.TestCase):
    def test_snapshot_is_reused_until_a_source_changes(self):
        remote = {'account': 'a', 'items': {'movie|tt1': {'watched': True}}}
        local = {'movie|tt2': {'watched': True, 'episodes': []}}
        playback_store = importlib.import_module('resources.lib.playback_store')
        with mock.patch.object(simkl_watched, '_remote_snapshot', return_value=remote), \
                mock.patch.object(playback_store, 'watched_snapshot', return_value=local):
            first = simkl_watched.snapshot()
            self.assertIs(first, simkl_watched.snapshot())
            self.assertTrue(first['items']['movie|tt2']['watched'])
            self.assertNotIn('movie|tt2', remote['items'], 'remote cache is never mutated')
        changed = {'movie|tt3': {'watched': True, 'episodes': []}}
        with mock.patch.object(simkl_watched, '_remote_snapshot', return_value=remote), \
                mock.patch.object(playback_store, 'watched_snapshot', return_value=changed):
            second = simkl_watched.snapshot()
        self.assertIsNot(first, second)
        self.assertIn('movie|tt3', second['items'])


class SignatureMemo(unittest.TestCase):
    def test_signature_is_reused_until_store_or_switches_change(self):
        rows = [provider()]
        values = {providers.SETTING: json.dumps([{'id': 'p', 'enabled': True}])}

        class Addon(kodi_stub._Addon):
            def getSetting(self, key):
                return values.get(key, '')
        with mock.patch.object(providers.xbmcaddon, 'Addon', Addon), \
                mock.patch.object(store, 'list_providers', side_effect=lambda: list(rows)), \
                mock.patch.object(store, '_PROVIDERS_MTIME', 1.0), \
                mock.patch.object(store, '_PROVIDERS_CACHE', rows):
            providers._SIGNATURE.clear()
            first = providers.signature()
            with mock.patch.object(providers, 'entries', side_effect=AssertionError('recomputed')):
                self.assertEqual(providers.signature(), first)
            values[providers.SETTING] = json.dumps([{'id': 'p', 'enabled': False}])
            self.assertNotEqual(providers.signature(), first)
            with mock.patch.object(store, '_PROVIDERS_MTIME', 2.0):
                rows[0] = dict(rows[0], base_url='https://example.invalid/changed')
                self.assertNotEqual(providers.signature(), first)
        providers._SIGNATURE.clear()


class CollectionProfileCache(unittest.TestCase):
    def test_profile_is_parsed_once_and_callers_get_copies(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'nuvio_collections.json'
        path.write_text(json.dumps([{'id': 'g', 'title': 'G', 'folders': [{'id': 'f', 'title': 'F',
                        'sources': [{'addonId': 'a', 'catalogId': 'c', 'type': 'movie'}]}]}]))
        profiles._LOADED.clear()
        with mock.patch.object(profiles, 'profile_file', return_value=path):
            first = profiles.load()
            first[0]['folders'].clear()
            with mock.patch.object(profiles, 'normalize', side_effect=AssertionError('parsed again')):
                self.assertEqual(len(profiles.load()[0]['folders']), 1)
            path.unlink()
            self.assertEqual(profiles.load(), [])
        profiles._LOADED.clear()


class ImageProxy(unittest.TestCase):
    def test_proxy_queues_a_full_screen_of_artwork(self):
        server = art_cache.Server(('127.0.0.1', 0), mock.Mock())
        try:
            self.assertGreaterEqual(server.slots._value, 32)
        finally:
            server.server_close()

    def test_image_fetch_uses_keep_alive_pool(self):
        body = b'\x89PNG\r\n\x1a\n' + b'0' * 10
        response = mock.Mock(status=200, headers={'Content-Length': str(len(body))})
        response.read.return_value = body
        pool = mock.Mock()
        pool.request.return_value = response
        with mock.patch.object(art_cache, '_pool', return_value=pool):
            self.assertEqual(art_cache.fetch('https://img.invalid/a.png'), body)
        response.release_conn.assert_called_once()

    def test_image_fetch_rejects_http_errors(self):
        response = mock.Mock(status=404, headers={})
        with mock.patch.object(art_cache, '_pool', return_value=mock.Mock(request=mock.Mock(return_value=response))):
            with self.assertRaises(ValueError):
                art_cache.fetch('https://img.invalid/a.png')
        response.release_conn.assert_called_once()


class ContinueWatchingEntry(unittest.TestCase):
    def open(self, built_revision, current_revision, focus='{"home":[0,5]}'):
        from types import SimpleNamespace
        preview = importlib.import_module('nuvio_ui.home_trailers')
        props = {'nuvio.progress.revision': current_revision, 'nuvio.home.focus': focus}
        window = SimpleNamespace(getProperty=lambda k: props.get(k, ''), setProperty=lambda k, v: props.__setitem__(k, v))
        fresh = {'title': 'Continue Watching', 'continue_job': True, 'rows': [{'title': 'Rebuilt'}]}
        self.control = mock.Mock()
        stack = [mock.patch.object(home_window.xbmcgui, 'Window', return_value=window),
                 mock.patch.object(home_window.home_data, 'continue_shelf', return_value=fresh),
                 mock.patch.object(preview, 'Controller')]
        for patch in stack:
            patch.start()
            self.addCleanup(patch.stop)
        self.rebuild = home_window.home_data.continue_shelf
        win = home_window.HomeWindow(shelves=[{'continue_job': True, 'rows': [{'title': 'Built'}]}],
                                     progress_revision=built_revision)
        win._paint = mock.Mock()
        win.setProperty = mock.Mock()
        win.getControl = lambda cid: self.control
        win.restore_focus = mock.Mock()
        return win

    def test_entry_reuses_the_shelf_open_home_just_built(self):
        win = self.open('r1', 'r1')
        win.onInit()
        self.rebuild.assert_not_called()
        self.assertEqual(win._shelves[0]['rows'][0]['title'], 'Built')
        self.control.selectItem.assert_called_with(0)
        self.assertEqual(win._focus_memory['home'], [0, 0])

    def test_progress_written_during_the_build_is_not_missed(self):
        win = self.open('r1', 'r2')
        win.onInit()
        self.assertEqual(win._shelves[0]['rows'][0]['title'], 'Rebuilt')

    def test_returning_from_details_keeps_the_selected_title(self):
        win = self.open('r1', 'r1')
        win.onInit()
        win._focus_memory['home'] = [0, 5]
        self.control.reset_mock()
        win.onInit()
        self.control.selectItem.assert_not_called()
        self.assertEqual(win._focus_memory['home'], [0, 5])


class BrowseAllPages(TempCache):
    def jobs(self):
        p = provider()
        movie, series = p['manifest']['catalogs']
        for c in (movie, series):
            c['extra'] = [{'name': 'skip'}]
        return [{'provider': p, 'catalog': c, 'extra': {}, 'offset': 0, 'done': False} for c in (movie, series)]

    def test_sources_page_concurrently_and_failed_source_retries_later(self):
        pages = importlib.import_module('resources.lib.catalog_pages')
        both = threading.Barrier(2, timeout=2)

        def fetch(prov, media_type, catalog_id, **kwargs):
            both.wait()
            if media_type == 'series':
                raise TimeoutError('slow')
            return page('tt1', 'tt2')
        jobs = self.jobs()
        with mock.patch.object(client, 'fetch_catalog', side_effect=fetch):
            rows, state = pages.fetch_page(jobs)
        self.assertEqual([r['target']['canonical_id'] for r in rows], ['tt1', 'tt2'])
        self.assertEqual([(s['offset'], s['done']) for s in state], [(2, False), (0, False)])

    def test_every_source_failing_reports_the_error(self):
        pages = importlib.import_module('resources.lib.catalog_pages')
        with mock.patch.object(client, 'fetch_catalog', side_effect=TimeoutError('offline')):
            with self.assertRaises(TimeoutError):
                pages.fetch_page(self.jobs())


class LatentNameErrors(unittest.TestCase):
    def test_missing_cinematic_window_falls_back_to_native_dialog(self):
        import sys
        plugin = importlib.import_module('resources.lib.plugin')
        native = importlib.import_module(plugin.__package__ + '.native_loading')
        with mock.patch.dict(sys.modules, {plugin.__package__ + '.sources_loading': None}), \
                mock.patch.object(plugin, '_setting', return_value='0'), \
                mock.patch.object(native, 'SourcesLoadingDialog', return_value='native') as dialog:
            self.assertEqual(plugin.SourcesLoadingDialog(title='x'), 'native')
        dialog.assert_called_once_with(title='x')

    def test_watchlist_mirror_failure_is_logged_not_a_name_error(self):
        favorites = importlib.import_module('resources.lib.favorites_store')
        self.assertTrue(hasattr(favorites, 'xbmc'))


class RetiredNameMigration(unittest.TestCase):
    """Old identifiers keep working after the rename, without being spelled out."""
    def names(self):
        return importlib.import_module('resources.lib.legacy_names')

    class Addon:
        def __init__(self, values):
            self.values = values

        def getSetting(self, key):
            return self.values.get(key, '')

        def setSetting(self, key, value):
            self.values[key] = value

    def test_source_never_spells_the_retired_prefix(self):
        import re
        names = self.names()
        text = Path(names.__file__).read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'(?<![nN])' + bytes((100, 101, 120)).decode(), text, re.I))
        self.assertTrue(names.OLD_ADDON_ID.startswith('plugin.video.'))

    def test_old_sentinels_and_folder_flag_are_carried_forward(self):
        names = self.names()
        values = {old: ('520' if kind == 'text' else 'true') for old, _, kind in names.SETTING_ALIASES}
        addon = self.Addon(values)
        self.assertTrue(names.carry_forward(addon))
        for _, new, kind in names.SETTING_ALIASES:
            self.assertEqual(values[new], '520' if kind == 'text' else 'true')
        self.assertFalse(names.carry_forward(addon), 'second run changes nothing')

    def test_existing_profile_without_readable_sentinels_is_not_reset(self):
        names = self.names()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        values = {}
        self.assertFalse(names.carry_forward(self.Addon(values), temp.name), 'fresh profile applies defaults')
        Path(temp.name, 'providers.json').write_text('[]')
        self.assertTrue(names.carry_forward(self.Addon(values), temp.name))
        self.assertEqual(values['nuviohub_defaults_rev'], '470-release-defaults')
        self.assertEqual(values['nuviohub_v510_defaults_applied'], 'true')
        self.assertNotIn('nuviohub_iptv_force_folders', values, 'user preference is not invented')

    def test_old_config_backup_keys_map_to_current_settings(self):
        names = self.names()
        self.assertEqual(set(names.SETTING_ALIAS_MAP.values()),
                         {'nuviohub_defaults_rev', 'nuviohub_v510_defaults_applied',
                          'nuviohub_v520_defaults_applied', 'nuviohub_iptv_force_folders'})

    def test_renamed_settings_are_declared(self):
        root = Path(kodi_stub.ADDON_ROOT) / 'resources' / 'settings.xml'
        text = root.read_text(encoding='utf-8')
        for key in ('nuviohub_iptv_force_folders', 'nuviohub_service_api_key', 'nuviohub_service_base_url',
                    'nuviohub_defaults_rev', 'nuviohub_v510_defaults_applied', 'nuviohub_v520_defaults_applied'):
            self.assertIn('id="%s"' % key, text)


class RenamedServiceFeatures(unittest.TestCase):
    def setUp(self):
        self.plugin = importlib.import_module('resources.lib.plugin')
        self.names = importlib.import_module('resources.lib.legacy_names')

    def dispatch(self, action):
        import sys
        with mock.patch.object(sys, 'argv', ['plugin://x', '1', '?action=' + action]):
            return self.plugin._dispatch()

    def test_routes_reach_the_renamed_functions(self):
        for action in ('subtitle_service_info', 'subtitle_service_link', 'subtitle_service_unlink'):
            with mock.patch.object(self.plugin, action, return_value=action) as target, \
                    mock.patch.object(self.plugin, 'first_run_wizard', side_effect=AssertionError('redirected')):
                self.assertEqual(self.dispatch(action), action)
            target.assert_called_once_with()
        with mock.patch.object(self.plugin, 'subs_feedback_bad', return_value='fb') as feedback:
            self.assertEqual(self.dispatch('subs_feedback_bad'), 'fb')
        feedback.assert_called_once()

    def test_link_asks_for_a_key_and_registers_both_manifests(self):
        values = {}
        addon = mock.Mock(getSetting=lambda k: values.get(k, ''), setSetting=lambda k, v: values.__setitem__(k, v))
        api = importlib.import_module('resources.lib.nuviohub.api')
        dialog = mock.Mock()
        dialog.return_value.input.return_value = 'key123'
        with mock.patch.object(self.plugin, 'ADDON', addon), \
                mock.patch.object(self.plugin.xbmcgui, 'Dialog', dialog), \
                mock.patch.object(self.plugin.store, 'list_providers', return_value=[]), \
                mock.patch.object(self.plugin, 'notify'), \
                mock.patch.object(api, 'add_provider_from_url') as add:
            self.plugin.subtitle_service_link()
        self.assertEqual(values['nuviohub_service_api_key'], 'key123')
        urls = [call.args[0] for call in add.call_args_list]
        self.assertEqual(len(urls), 2)
        self.assertTrue(all(u.startswith(self.names.SERVICE_BASE_URL) and 'key123' in u for u in urls))
        self.assertEqual([call.kwargs['name'] for call in add.call_args_list], ['AI Subtitles', 'IPTV Service'])

    def test_unlink_removes_only_service_manifests(self):
        providers = [{'id': 'a', 'manifest': {'id': self.names.SERVICE_MANIFEST_IDS[0]}},
                     {'id': 'b', 'manifest': {'id': 'other'}}]
        with mock.patch.object(self.plugin.store, 'list_providers', return_value=providers), \
                mock.patch.object(self.plugin.store, 'remove_provider') as remove, \
                mock.patch.object(self.plugin.xbmcgui, 'Dialog') as dialog, \
                mock.patch.object(self.plugin, 'notify'):
            dialog.return_value.yesno.return_value = True
            self.plugin.subtitle_service_unlink()
        remove.assert_called_once_with('a')

    def test_pro_iptv_folder_view_follows_renamed_setting(self):
        pro = {'name': self.names.SERVICE_MARKER + ' Pro'}
        for value, expected in (('false', False), ('true', True)):
            addon = mock.Mock(getSetting=lambda k, v=value: v if k == 'nuviohub_iptv_force_folders' else '')
            with mock.patch.object(self.plugin, 'ADDON', addon):
                self.assertEqual(self.plugin._force_folders_for_provider(pro), expected)
        self.assertFalse(self.plugin._provider_is_pro_iptv({'name': 'Other IPTV'}))

    def test_ai_rows_from_the_service_are_still_classified(self):
        policy = importlib.import_module('resources.lib.subtitle_policy')
        self.assertTrue(policy.is_ai_subtitle({'provider': self.names.SERVICE_MARKER, 'title': 'translated'}))
        self.assertFalse(policy.is_ai_subtitle({'provider': self.names.SERVICE_MARKER, 'title': 'English'}))

    def test_feedback_is_renamed_and_posts_to_the_service(self):
        feedback = importlib.import_module('resources.lib.subtitle_feedback')
        self.assertTrue(feedback._FEEDBACK_URL.startswith(self.names.SERVICE_BASE_URL))
        with mock.patch.object(feedback, '_post_async') as post:
            self.assertTrue(feedback.report_bad('sub1', 'stream'))
        self.assertEqual(post.call_args.args[0]['sub_id'], 'sub1')


if __name__ == '__main__':
    unittest.main()
