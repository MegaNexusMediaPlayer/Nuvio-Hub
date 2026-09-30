# -*- coding: utf-8 -*-
"""Simkl module regression tests (v4.1.0) — pure logic, no network."""
import unittest

import kodi_stub

simkl = kodi_stub.import_lib_module('simkl')


class TestHistoryPayload(unittest.TestCase):
    def test_movie_payload_uses_ids(self):
        ctx = {'media_type': 'movie', 'title': 'Dune', 'imdb_id': 'tt1160419', 'tmdb_id': '438631'}
        payload = simkl.history_payload(ctx)
        self.assertIn('movies', payload)
        self.assertEqual(payload['movies'][0]['ids']['imdb'], 'tt1160419')
        self.assertEqual(payload['movies'][0]['ids']['tmdb'], '438631')

    def test_imdb_gets_tt_prefix(self):
        payload = simkl.history_payload({'media_type': 'movie', 'imdb_id': '1160419'})
        self.assertEqual(payload['movies'][0]['ids']['imdb'], 'tt1160419')

    def test_episode_payload_has_season_episode(self):
        ctx = {'media_type': 'series', 'show_title': 'Severance', 'imdb_id': 'tt11280740',
               'season': 2, 'episode': 5}
        payload = simkl.history_payload(ctx)
        show = payload['shows'][0]
        self.assertEqual(show['seasons'][0]['number'], 2)
        self.assertEqual(show['seasons'][0]['episodes'][0]['number'], 5)

    def test_no_ids_returns_none(self):
        self.assertIsNone(simkl.history_payload({'media_type': 'movie', 'title': 'X'}))

    def test_episode_without_numbers_returns_none(self):
        self.assertIsNone(simkl.history_payload({'media_type': 'series', 'imdb_id': 'tt1'}))


class TestWatchedThreshold(unittest.TestCase):
    def test_below_threshold_not_watched(self):
        self.assertFalse(simkl.should_mark_watched(50 * 60000, 100 * 60000, threshold=85))

    def test_at_threshold_watched(self):
        self.assertTrue(simkl.should_mark_watched(85 * 60000, 100 * 60000, threshold=85))

    def test_credits_stop_watched(self):
        # Real log pattern: user stops at ~96% when credits roll.
        self.assertTrue(simkl.should_mark_watched(96 * 60000, 100 * 60000, threshold=85))

    def test_zero_duration_only_natural_end(self):
        self.assertTrue(simkl.should_mark_watched(0, 0, threshold=85))
        self.assertFalse(simkl.should_mark_watched(120000, 0, threshold=85))


class TestNormalizeAllItems(unittest.TestCase):
    # Shape taken from Simkl's documented /sync/all-items response.
    SAMPLE = {
        'shows': [
            {'status': 'watching', 'show': {
                'title': 'Severance', 'year': 2022,
                'ids': {'simkl': 123, 'imdb': 'tt11280740', 'tvdb': 371980, 'tmdb': 95396}}},
            {'status': 'watching', 'show': {'title': 'No IDs here', 'ids': {}}},
        ],
        'movies': [
            {'status': 'completed', 'movie': {
                'title': 'Dune: Part Two', 'year': 2024,
                'ids': {'simkl': 9, 'imdb': 'tt15239678', 'tmdb': 693134}}},
        ],
    }

    def test_shows_normalized_to_idlist_shape(self):
        rows = simkl.normalize_all_items(self.SAMPLE, 'shows')
        self.assertEqual(len(rows), 1)  # the no-ids row is dropped
        row = rows[0]
        self.assertEqual(row['_type'], 'show')
        self.assertEqual(row['ids']['imdb'], 'tt11280740')
        self.assertEqual(str(row['ids']['tmdb']), '95396')
        self.assertEqual(row['release_year'], 2022)

    def test_movies_normalized(self):
        rows = simkl.normalize_all_items(self.SAMPLE, 'movies')
        self.assertEqual(rows[0]['_type'], 'movie')
        self.assertEqual(rows[0]['ids']['imdb'], 'tt15239678')

    def test_garbage_input_safe(self):
        self.assertEqual(simkl.normalize_all_items(None, 'shows'), [])
        self.assertEqual(simkl.normalize_all_items([], 'shows'), [])
        self.assertEqual(simkl.normalize_all_items({'shows': None}, 'shows'), [])


class TestAuthStatus(unittest.TestCase):
    # settings_cache.CachedAddon caches values per key, so tests patch
    # simkl._setting directly instead of fighting the cache.
    def _with_setting(self, value, fn):
        original = simkl._setting
        simkl._setting = lambda key, default='': value if key == 'simkl_client_id' else original(key, default)
        try:
            return fn()
        finally:
            simkl._setting = original

    def test_needs_api_without_client_id(self):
        simkl.DEFAULT_CLIENT_ID = ''
        self.assertEqual(self._with_setting('', simkl.authorization_status), 'needs_api')

    def test_ready_with_client_id(self):
        simkl.DEFAULT_CLIENT_ID = ''
        self.assertIn(self._with_setting('abc123', simkl.authorization_status), ('ready', 'connected'))


class TestSessionDedupe(unittest.TestCase):
    def test_session_key_prefers_video_id(self):
        key = simkl._session_key({'video_id': 'tt1:2:5', 'canonical_id': 'tt1'})
        self.assertEqual(key, 'tt1:2:5')


if __name__ == '__main__':
    unittest.main(verbosity=2)
