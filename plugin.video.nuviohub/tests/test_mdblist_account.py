# -*- coding: utf-8 -*-
"""MDBList account-feature regression tests (v4.1.0) — canned API shapes."""
import unittest

import kodi_stub

mdblist = kodi_stub.import_lib_module('mdblist')


class TestNormalizeItemsResponse(unittest.TestCase):
    def test_unified_dict_response(self):
        # api.mdblist.com unified items shape: movies + shows buckets.
        data = {
            'movies': [{'id': 438631, 'title': 'Dune', 'imdb_id': 'tt1160419', 'release_year': 2021}],
            'shows': [{'id': 95396, 'title': 'Severance', 'imdb_id': 'tt11280740', 'tvdb_id': 371980}],
        }
        rows, cursor = mdblist._normalize_items_response(data, False, 'auto')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['_type'], 'movie')
        self.assertEqual(rows[1]['_type'], 'show')
        self.assertEqual(cursor, '')

    def test_cursor_passthrough(self):
        data = {'movies': [{'id': 1, 'title': 'A'}], 'shows': [], 'next_cursor': 'abc'}
        rows, cursor = mdblist._normalize_items_response(data, True, 'auto')
        self.assertEqual(cursor, 'abc')

    def test_has_more_header_advances_offset_cursor(self):
        # v4.2.2 contract: X-Has-More without an API cursor now continues via
        # an opaque offset token that advances by the UNFILTERED row count —
        # this is what made private list paging actually work.
        data = {'movies': [{'id': 1, 'title': 'A'}], 'shows': []}
        _rows, cursor = mdblist._normalize_items_response(data, True, 'auto')
        self.assertEqual(cursor, 'offset:1')
        _rows, cursor = mdblist._normalize_items_response(
            data, True, 'auto', current_cursor='offset:100')
        self.assertEqual(cursor, 'offset:101')

    def test_plain_list_response_typed_by_filter(self):
        rows, _ = mdblist._normalize_items_response(
            [{'id': 1, 'title': 'A'}], False, 'movies')
        self.assertEqual(rows[0]['_type'], 'movie')
        rows, _ = mdblist._normalize_items_response(
            [{'id': 2, 'title': 'B'}], False, 'shows')
        self.assertEqual(rows[0]['_type'], 'show')


class TestItemsPathSuffix(unittest.TestCase):
    def test_movie_filter(self):
        self.assertEqual(mdblist._items_path_suffix('movies'), ('/items/movie', False))

    def test_show_filter(self):
        self.assertEqual(mdblist._items_path_suffix('anime'), ('/items/show', False))

    def test_auto_is_not_unified(self):
        # v4.4.1 contract flip: auto stays on the plain /items route with the
        # classic movies/shows buckets and flat ids.
        suffix, unified = mdblist._items_path_suffix('auto')
        self.assertEqual(suffix, '/items')
        self.assertFalse(unified)


def _with_key(value, fn):
    """settings_cache.CachedAddon caches values per key — patch _setting
    directly so tests can never leak a stale key into a live request."""
    original = mdblist._setting
    mdblist._setting = lambda key, default='': value if key == 'mdblist_api_key' else original(key, default)
    try:
        return fn()
    finally:
        mdblist._setting = original


class TestMyListsNormalization(unittest.TestCase):
    def test_rows_shaped_for_menu(self):
        # /lists/user documented row shape.
        raw = [{'id': 12345, 'name': 'My 4K picks', 'slug': 'my-4k-picks',
                'user_name': 'ahmed', 'items': 42, 'mediatype': 'movie',
                'description': 'best of'}]
        original = mdblist._request
        try:
            mdblist._request = lambda *a, **k: (raw, False)
            rows = _with_key('k', mdblist.fetch_my_lists)
        finally:
            mdblist._request = original
        self.assertEqual(rows[0]['slug'], 'my-4k-picks')
        self.assertEqual(rows[0]['user_name'], 'ahmed')
        self.assertEqual(rows[0]['items'], 42)

    def test_unconfigured_returns_empty(self):
        self.assertEqual(_with_key('', mdblist.fetch_my_lists), [])
        self.assertEqual(_with_key('', mdblist.fetch_watchlist_items), ([], ''))
        self.assertEqual(_with_key('', mdblist.authorization_status), 'needs_api')


class TestFetchByIdAndWatchlistPaths(unittest.TestCase):
    def test_request_paths(self):
        calls = []
        original = mdblist._request
        try:
            mdblist._request = lambda path, params=None, **k: (calls.append((path, dict(params or {}))), ({'movies': [], 'shows': []}, False))[1]
            _with_key('k', lambda: (
                mdblist.fetch_items_by_id('999', media_filter='auto', cursor='offset:100', limit=50),
                mdblist.fetch_watchlist_items(media_filter='movies', limit=25)))
        finally:
            mdblist._request = original
        self.assertEqual(calls[0][0], '/lists/999/items')
        # v4.2.2: continuation is offset-encoded; unknown cursor text is
        # ignored rather than forwarded to the API.
        self.assertNotIn('cursor', calls[0][1])
        self.assertEqual(calls[0][1].get('offset'), 100)
        # v4.4.1: unified=true is banned — it reshapes ids into an array and
        # every private list rendered empty on the device.
        self.assertNotIn('unified', calls[0][1])
        self.assertEqual(calls[1][0], '/watchlist/items/movie')
        self.assertNotIn('unified', calls[1][1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
