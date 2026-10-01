# -*- coding: utf-8 -*-
"""v4.8.8 — subtitles reached the AI subtitles engine in a shape it cannot serve.

Verified against the engine's own source (ai_subtitles.js), which serves:

    GET /subtitles/stremio/:apiKey/manifest.json
    -> { id: <AI subtitles aggregator id>, resources: ["subtitles"],
         types: ["movie","series"], idPrefixes: ["tt"] }

`idPrefixes: ["tt"]` is the point: the addon answers IMDb ids only, and so
do most Stremio subtitle addons including OpenSubtitles. NuvioHub has
deferred IMDb resolution since 4.5.0, so the common case — a title opened
from a TMDb catalogue — asked for subtitles with `tmdb:...` and got
nothing back, silently. The broker now resolves the IMDb id on demand
(through the TMDb lookup it already caches) before giving up.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
br = kodi_stub.import_lib_module('subtitle_broker')
BROKER = io.open(os.path.join(ROOT, 'resources', 'lib', 'subtitle_broker.py'),
                 encoding='utf-8').read()


class TestImdbResolution(unittest.TestCase):
    def test_resolver_uses_the_tmdb_id(self):
        import types
        fake = types.SimpleNamespace(imdb_id_for=lambda tmdb_id, media_type='movie':
                                     'tt%s' % tmdb_id)
        import sys
        real = sys.modules.get('nuviohub_lib.tmdb_direct')
        try:
            mod = kodi_stub.import_lib_module('tmdb_direct')
            orig = mod.imdb_id_for
            mod.imdb_id_for = fake.imdb_id_for
            self.assertEqual(
                br._resolve_imdb_for_subtitles({'tmdb_id': '603', 'media_type': 'movie'}),
                'tt603')
            # and from a canonical id when the field is absent
            self.assertEqual(
                br._resolve_imdb_for_subtitles({'canonical_id': 'tmdb:1399',
                                                'media_type': 'series'}),
                'tt1399')
        finally:
            mod.imdb_id_for = orig
            if real is not None:
                sys.modules['nuviohub_lib.tmdb_direct'] = real

    def test_resolver_is_safe_without_a_tmdb_id(self):
        for ctx in ({}, {'canonical_id': 'tt123'}, {'tmdb_id': ''}, None):
            self.assertEqual(br._resolve_imdb_for_subtitles(ctx or {}), '')

    def test_resolution_only_runs_when_no_tt_candidate_exists(self):
        body = BROKER.split('candidates = _candidate_ids(ctx)', 1)[1][:900]
        self.assertIn("not any(c.startswith('tt') for c in candidates)", body)
        self.assertIn('_resolve_imdb_for_subtitles(', body)

    def test_the_engine_contract_is_documented(self):
        self.assertIn('idPrefixes ["tt"]', BROKER)


class TestCandidateIds(unittest.TestCase):
    def test_imdb_leads_when_present(self):
        ids = br._candidate_ids({'imdb_id': 'tt1981558', 'tmdb_id': '1399',
                                 'media_type': 'series', 'season': 1, 'episode': 2})
        self.assertEqual(ids[0], 'tt1981558:1:2')

    def test_episode_suffix_is_never_doubled(self):
        ids = br._candidate_ids({'canonical_id': 'imdb:tt1981558:1:1',
                                 'media_type': 'series', 'season': 1, 'episode': 1})
        for item in ids:
            self.assertLessEqual(item.count(':1:1'), 1, item)
            self.assertFalse(item.startswith('imdb:'), item)

    def test_movie_ids_carry_no_season_suffix(self):
        ids = br._candidate_ids({'imdb_id': 'tt0111161', 'media_type': 'movie'})
        self.assertEqual(ids, ['tt0111161'])

    def test_incomplete_episode_context_yields_nothing(self):
        self.assertEqual(
            br._candidate_ids({'imdb_id': 'tt1', 'media_type': 'series'}), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
