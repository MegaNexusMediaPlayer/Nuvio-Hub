# -*- coding: utf-8 -*-
"""v4.2.0 regression tests — one test per reported symptom:

  * MDBList own lists route by id (private lists returned empty via the
    public username/slug endpoint),
  * my-lists parser accepts wrapped responses,
  * Simkl rows carry posters + renderer has row-poster and MetaHub fallbacks,
  * Simkl full import parses SxxEyy markers and stays season-scoped,
  * Continue Watching / service sync / merged watchlist mirror are wired,
  * AIOStreams usenet rows (indexer names, type fields) classify as USENET,
  * ratings pipeline: MDBList source map + extended publish keys + skin chips,
  * brand icons exist and are actually referenced.
"""
import io
import os
import re
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
simkl = kodi_stub.import_lib_module('simkl')
mdblist = kodi_stub.import_lib_module('mdblist')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SERVICE = io.open(os.path.join(ROOT, 'service.py'), encoding='utf-8').read()
FAVSTORE = io.open(os.path.join(ROOT, 'resources', 'lib', 'favorites_store.py'), encoding='utf-8').read()
TMDBHCTX = io.open(os.path.join(ROOT, 'resources', 'lib', 'tmdbh_context.py'), encoding='utf-8').read()
SKIN = io.open(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'sources_results.xml'), encoding='utf-8').read()


class TestMdblistPrivateLists(unittest.TestCase):
    def test_my_lists_menu_routes_by_id_only(self):
        start = PLUGIN.index('def mdblist_my_lists')
        body = PLUGIN[start:PLUGIN.index('\ndef ', start + 10)]
        self.assertIn("mdblist_list_browse_id", body)
        self.assertNotIn("action='mdblist_list_browse'", body,
                         'own lists must never route through the public username/slug endpoint')

    def test_my_lists_parser_accepts_wrapped_payload(self):
        raw = {'lists': [{'id': 7, 'name': 'Private picks', 'slug': 'x',
                          'user_name': 'ahmed', 'items': 3}]}
        original = mdblist._request
        try:
            mdblist._request = lambda *a, **k: (raw, False)
            orig_setting = mdblist._setting
            mdblist._setting = lambda key, default='': 'k' if key == 'mdblist_api_key' else orig_setting(key, default)
            rows = mdblist.fetch_my_lists()
            mdblist._setting = orig_setting
        finally:
            mdblist._request = original
        self.assertEqual(rows[0]['name'], 'Private picks')


class TestSimklPosters(unittest.TestCase):
    SAMPLE = {'shows': [{'status': 'watching', 'last_watched': 's2e5',
                         'next_to_watch': 's2e6', 'last_watched_at': '2026-08-01T10:00:00Z',
                         'show': {'title': 'Severance', 'year': 2022, 'poster': '17/1730279',
                                  'ids': {'imdb': 'tt11280740', 'tmdb': 95396}}}]}

    def test_rows_carry_poster_url(self):
        rows = simkl.normalize_all_items(self.SAMPLE, 'shows')
        self.assertTrue(rows[0]['poster'].startswith('https://simkl.in/posters/'))
        self.assertIn('17/1730279', rows[0]['poster'])

    def test_rows_carry_watch_state(self):
        rows = simkl.normalize_all_items(self.SAMPLE, 'shows')
        self.assertEqual(rows[0]['last_watched'], 's2e5')
        self.assertEqual(rows[0]['next_to_watch'], 's2e6')

    def test_renderer_has_row_poster_and_metahub_fallbacks(self):
        start = PLUGIN.index('def _render_idlist_rows')
        body = PLUGIN[start:PLUGIN.index('\ndef mdblist_list_browse(', start)]
        self.assertIn("meta.get('poster')", body)
        self.assertIn('_METAHUB_POSTER', body)


class TestSimklImportAndMarkers(unittest.TestCase):
    def test_episode_marker_variants(self):
        self.assertEqual(simkl.parse_episode_marker('s2e5'), (2, 5))
        self.assertEqual(simkl.parse_episode_marker('S12E03'), (12, 3))
        self.assertEqual(simkl.parse_episode_marker('S 3 E 11'), (3, 11))
        self.assertIsNone(simkl.parse_episode_marker(''))
        self.assertIsNone(simkl.parse_episode_marker('finished'))

    def test_import_is_marker_season_scoped(self):
        start = io.open(os.path.join(kodi_stub.LIB, 'simkl.py'), encoding='utf-8').read()
        body = start[start.index('def import_watched('):start.index('def sync_continue_watching(')]
        self.assertIn('range(1, episode + 1)', body)
        self.assertNotIn('_SEASON_FILL_EPISODES', body,
                         'earlier-season back-fill was removed on purpose — unknown season lengths')

    def test_watchlist_mirror_rows_shape(self):
        original = simkl.fetch_all_items
        try:
            simkl.fetch_all_items = lambda kind, status: ([{
                '_type': 'movie', 'title': 'Dune', 'year': 2021, 'overview': 'sand',
                'ids': {'imdb': 'tt1160419', 'tmdb': '438631', 'tvdb': ''},
                'poster': 'https://simkl.in/posters/x_m.jpg'}]
                if (kind, status) == ('movies', 'plantowatch') else [])
            simkl.enabled = lambda: True
            simkl.authorized = lambda: True
            rows = simkl.watchlist_mirror_rows()
        finally:
            simkl.fetch_all_items = original
        self.assertEqual(rows[0]['canonical_id'], 'tt1160419')
        self.assertEqual(rows[0]['media_type'], 'movie')
        self.assertIn('poster', rows[0])


class TestUsenetClassification(unittest.TestCase):
    def _classify(self):
        import test_source_type
        return test_source_type.classify

    def test_nzb_indexer_names_hit(self):
        classify = self._classify()
        for name in ('NZBGeek', 'abNZB', 'DrunkenSlug', 'NZBFinder', 'althub'):
            row = {'name': 'Dexstreams', 'description': 'via %s | 12.3 GB' % name}
            self.assertEqual(classify(row, 'Dexstreams')[0], 'usenet', name)

    def test_structural_type_field_hits(self):
        classify = self._classify()
        row = {'name': '[TB+] Dexstreams 4K', 'type': 'usenet',
               'description': '4K REMUX | 60 GB'}
        self.assertEqual(classify(row, 'Dexstreams')[0], 'usenet')
        row2 = {'name': '[TB+] Dexstreams', 'behaviorHints': {'sourceType': 'Usenet'}}
        self.assertEqual(classify(row2, 'Dexstreams')[0], 'usenet')

    def test_debrid_rows_still_debrid(self):
        classify = self._classify()
        row = {'name': '[RD+] Dexstreams', 'description': 'WEB-DL | Instant'}
        self.assertEqual(classify(row, 'Dexstreams')[0], 'debrid')


class TestWiringV420(unittest.TestCase):
    def test_sync_now_action_dispatched(self):
        self.assertIn("if action == 'simkl_sync_now':", PLUGIN)
        self.assertIn('def simkl_sync_now', PLUGIN)

    def test_service_runs_simkl_and_merged_mirror(self):
        self.assertIn('_sync_simkl_state', SERVICE)
        self.assertIn("_sync_simkl_state(reason='service')", SERVICE)
        self.assertIn('refresh_external_mirror', SERVICE)
        self.assertNotIn('favorites_store.replace_trakt_mirror(rows)', SERVICE,
                         'service must not write a trakt-only snapshot anymore')

    def test_shared_mirror_lives_in_favorites_store(self):
        self.assertIn('def refresh_external_mirror', FAVSTORE)
        for probe in ('watchlist_merge_simkl', 'watchlist_merge_mdblist',
                      'watchlist_mirror_rows'):
            self.assertIn(probe, FAVSTORE)

    def test_plugin_delegates_to_shared_mirror(self):
        start = PLUGIN.index('def _refresh_external_watchlist_mirror')
        body = PLUGIN[start:PLUGIN.index('\ndef favorites():', start)]
        self.assertIn('favorites_store.refresh_external_mirror', body)

    def test_provider_badge_twelve_chars(self):
        self.assertIn("cleaned.upper()[:12]", PLUGIN)
        self.assertNotIn("cleaned.upper()[:8]", PLUGIN)


class TestRatingsPipeline(unittest.TestCase):
    def test_source_map_covers_requested_services(self):
        for source, key in (('tomatoes', 'rt_crit'), ('tomatoesaudience', 'rt_aud'),
                            ('letterboxd', 'letterboxd'), ('metacritic', 'metacritic'),
                            ('myanimelist', 'mal'), ('score_average', 'mdblist')):
            self.assertEqual(mdblist._RATING_SOURCE_MAP.get(source), key)

    def test_fetch_ratings_normalizes(self):
        raw = {'ratings': [
            {'source': 'imdb', 'value': 7.4}, {'source': 'metacritic', 'value': 61},
            {'source': 'letterboxd', 'value': 3.8}, {'source': 'score_average', 'value': 72},
            {'source': 'unknown', 'value': 5}]}
        original = mdblist._request
        try:
            mdblist._request = lambda *a, **k: (raw, False)
            orig_setting = mdblist._setting
            mdblist._setting = lambda key, default='': 'k' if key == 'mdblist_api_key' else orig_setting(key, default)
            mdblist._RATINGS_CACHE.clear()
            out = mdblist.fetch_ratings('tt1160419', 'movie')
            mdblist._setting = orig_setting
        finally:
            mdblist._request = original
        self.assertEqual(out['imdb'], '7.4')
        self.assertEqual(out['metacritic'], '61')
        self.assertEqual(out['letterboxd'], '3.8')
        self.assertEqual(out['mdblist'], '72')
        self.assertNotIn('unknown', out)

    def test_context_publishes_extended_keys(self):
        self.assertIn("'letterboxd', 'mdblist', 'mal'", TMDBHCTX)
        self.assertIn('fetch_ratings', TMDBHCTX)

    def test_skin_has_new_chips_and_icon_priority(self):
        for prop in ('dexhub.rating.metacritic', 'dexhub.rating.letterboxd',
                     'dexhub.rating.mdblist', 'dexhub.rating.mal'):
            self.assertIn(prop, SKIN)
        # bundled icon is now the primary texture, skin extras the fallback
        # (v4.3.1 moved the bundled set to media/ratings/ for cache-busting)
        self.assertIn('fallback="special://skin/extras/flags/color/ratings/imdb.png">special://home/addons/plugin.video.nuviohub/resources/media/ratings/imdb.png', SKIN)

    def test_brand_icons_exist_and_are_used(self):
        for icon in ('simkl.png', 'mdblist.png', 'letterboxd.png', 'mal.png'):
            self.assertTrue(os.path.exists(os.path.join(ROOT, 'resources', 'media', icon)), icon)
        art_py = io.open(os.path.join(ROOT, 'resources', 'lib', 'art.py'), encoding='utf-8').read()
        # v4.2.2 moved brand icons into the art registry (root_art('simkl')).
        self.assertIn("'simkl.png'", art_py)
        self.assertIn("'mdblist.png'", art_py)
        self.assertIn("root_art('simkl')", PLUGIN)


if __name__ == '__main__':
    unittest.main(verbosity=2)
