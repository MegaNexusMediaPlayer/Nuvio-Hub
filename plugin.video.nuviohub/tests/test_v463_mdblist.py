# -*- coding: utf-8 -*-
"""v4.6.3 — MDBList ratings contract, verified against TMDb Helper's source
(jurialmunkey/plugin.video.themoviedb.helper @ HEAD):

  lib/api/mdblist/api.py            → get_details(provider='tmdb', …)
  lib/…/concrete_classes/ratings.py → get_ratings(trakt_type, tmdb_id),
                                      rating_func scales, ratings_style

Facts pinned here:
  1. Path shape /{provider}/{movie|show}/{id}; TMDb Helper queries by TMDB
     id and uses 'show' for TV — NuvioHub prefers the same tmdb path (v4.5.0
     defers IMDb resolution, so tmdb_id is what we reliably hold) and keeps
     /imdb as fallback.
  2. MDBList serves trakt on /100 → display /10 one-decimal ("75.0" bug).
  3. MDBList's own score is the TOP-LEVEL 'score' field, not an array row.
  4. Letterboxd is a 5-star scale and is displayed /5 one-decimal.
  5. The warm-cache design from v4.2.2 finally has a warmer: nothing ever
     called fetch_ratings over the network, so the Letterboxd/MDBList/MAL
     chips (which have no TMDb Helper alias) never rendered.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
mdblist = kodi_stub.import_lib_module('mdblist')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
CTX = io.open(os.path.join(ROOT, 'resources', 'lib', 'tmdbh_context.py'), encoding='utf-8').read()
MDB_SRC = io.open(os.path.join(ROOT, 'resources', 'lib', 'mdblist.py'), encoding='utf-8').read()


class _Capture:
    """Route mdblist._request into a canned payload while recording the path."""

    def __init__(self, payload):
        self.payload = payload
        self.paths = []

    def __enter__(self):
        self._request = mdblist._request
        self._setting = mdblist._setting
        mdblist._request = self._req
        mdblist._setting = lambda key, default='': (
            'k' if key == 'mdblist_api_key' else self._setting(key, default))
        mdblist._RATINGS_CACHE.clear()
        return self

    def _req(self, path, params=None, timeout=20):
        self.paths.append(path)
        return self.payload, False

    def __exit__(self, *exc):
        mdblist._request = self._request
        mdblist._setting = self._setting
        mdblist._RATINGS_CACHE.clear()
        return False


class TestVerifiedEndpointShape(unittest.TestCase):
    def test_tmdb_path_preferred_and_show_segment(self):
        with _Capture({'ratings': []}) as cap:
            mdblist.fetch_ratings(media_type='series', tmdb_id='9340')
        self.assertEqual(cap.paths, ['/tmdb/show/9340'])

    def test_imdb_fallback_path(self):
        with _Capture({'ratings': []}) as cap:
            mdblist.fetch_ratings(imdb_id='1160419', media_type='movie')
        self.assertEqual(cap.paths, ['/imdb/movie/tt1160419'])

    def test_tvshow_alias_maps_to_show(self):
        self.assertEqual(mdblist._ratings_kind('tvshow'), 'show')
        self.assertEqual(mdblist._ratings_kind('anime'), 'show')
        self.assertEqual(mdblist._ratings_kind('movie'), 'movie')

    def test_verify_live_doubt_resolved(self):
        self.assertNotIn('[VERIFY-LIVE]', MDB_SRC)
        # the verification source must stay documented
        self.assertIn('plugin.video.themoviedb.helper', MDB_SRC)


class TestVerifiedScales(unittest.TestCase):
    PAYLOAD = {
        'score': 78,                     # TOP-LEVEL — MDBList's own rating
        'ratings': [
            {'source': 'imdb', 'value': 7.4},
            {'source': 'trakt', 'value': 75},          # /100 on the wire
            {'source': 'tomatoes', 'value': 94},
            {'source': 'tomatoesaudience', 'value': 88},
            {'source': 'metacritic', 'value': 61},
            {'source': 'letterboxd', 'value': 3.8},    # 5-star scale
            {'source': 'myanimelist', 'value': 8.7},
            {'source': 'score_average', 'value': 72},  # array row loses
        ],
    }

    def _fetch(self):
        with _Capture(dict(self.PAYLOAD)):
            return mdblist.fetch_ratings(imdb_id='tt1', media_type='movie')

    def test_trakt_is_divided_to_ten_scale(self):
        # the "75.0" render — same class as the v4.3.1 metacritic bug
        self.assertEqual(self._fetch()['trakt'], '7.5')

    def test_mdblist_score_comes_from_top_level(self):
        self.assertEqual(self._fetch()['mdblist'], '78')

    def test_top_level_score_average_fallback(self):
        payload = dict(self.PAYLOAD)
        del payload['score']
        payload['score_average'] = 74
        payload['ratings'] = [r for r in payload['ratings']
                              if r['source'] != 'score_average']
        with _Capture(payload):
            out = mdblist.fetch_ratings(imdb_id='tt1', media_type='movie')
        self.assertEqual(out['mdblist'], '74')

    def test_untouched_scales_stay_correct(self):
        out = self._fetch()
        self.assertEqual(out['imdb'], '7.4')
        self.assertEqual(out['letterboxd'], '3.8')     # /5 one-decimal
        self.assertEqual(out['mal'], '8.7')
        self.assertEqual(out['rt_crit'], '94')
        self.assertEqual(out['rt_aud'], '88')
        self.assertEqual(out['metacritic'], '61')


class TestCrossIdCache(unittest.TestCase):
    def test_warm_by_both_ids_read_by_either(self):
        with _Capture({'score': 70, 'ratings': []}) as cap:
            mdblist.fetch_ratings(imdb_id='tt9', media_type='movie', tmdb_id='555')
            by_tmdb = mdblist.cached_ratings(media_type='movie', tmdb_id='555')
            by_imdb = mdblist.cached_ratings(imdb_id='tt9', media_type='movie')
            # a second fetch must be a cache hit, not another request
            mdblist.fetch_ratings(media_type='movie', tmdb_id='555')
        self.assertEqual(by_tmdb.get('mdblist'), '70')
        self.assertEqual(by_imdb.get('mdblist'), '70')
        self.assertEqual(len(cap.paths), 1)


class TestWarmupWiring(unittest.TestCase):
    """The silent-failure fix: the warm cache finally has a warmer."""

    def test_warm_helper_runs_off_the_hot_path(self):
        # v5.x queues this in Nuvio Hub's bounded optional-work lane instead
        # of spawning a bare thread; either way it must not block the picker.
        self.assertIn('def warm_ratings_async(', MDB_SRC)
        body = MDB_SRC.split('def warm_ratings_async(', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('fetch_ratings(', body)
        self.assertTrue(any(k in body for k in ('daemon', 'submit', 'queue', 'lane')),
                        'warm-up is not dispatched asynchronously')

    def test_source_scan_fires_the_warmup(self):
        body = PLUGIN.split('def _collect_stream_entries(', 1)[1]
        body = body.split('def _run(', 1)[0]
        self.assertIn('warm_ratings_async(', body)
        self.assertIn("(ids or {}).get('tmdb_id')", body)

    def test_context_overlay_no_longer_gated_on_imdb(self):
        seg = CTX.split('imdb_for_ratings', 1)[1][:900]
        self.assertIn('tmdb_for_ratings', seg)
        self.assertIn('if imdb_for_ratings or tmdb_for_ratings:', CTX)
        self.assertIn('tmdb_id=tmdb_for_ratings', CTX)


if __name__ == '__main__':
    unittest.main(verbosity=2)
