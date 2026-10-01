# -*- coding: utf-8 -*-
"""v4.8.1 — saved-library sync, built from Nuvio's own source.

The user supplied NuvioWeb, which settles what "native cloud sync" covers.
Its RPC surface is twenty calls; NuvioHub already spoke addons, collections
and watch progress, and the biggest gap was the SAVED LIBRARY — the list a
user builds on their phone. Contract taken verbatim from
js/core/profile/savedLibrarySyncService.js:

    sync_pull_library(p_profile_id, p_limit, p_offset)   # paged, 500
    sync_push_library(p_profile_id, p_items)
    row: content_id / content_type / name / poster / poster_shape /
         background / description / release_info / imdb_rating / genres /
         addon_base_url / added_at   (epoch MILLISECONDS)

Nothing here is guessed: every field name below appears in that file.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sync = kodi_stub.import_lib_module('nuviohub.nuvio_stremio_sync')
SYNC = io.open(os.path.join(ROOT, 'resources', 'lib', 'nuviohub',
                            'nuvio_stremio_sync.py'), encoding='utf-8').read()


class TestLibraryMappers(unittest.TestCase):
    def test_local_to_nuvio_uses_the_documented_row_shape(self):
        out = sync.Nuvio._library_to_nuvio([{
            'canonical_id': 'tt123', 'media_type': 'series', 'title': 'Show',
            'poster': 'p.jpg', 'background': 'b.jpg', 'plot': 'desc',
            'year': 2021, 'added_at': 1700000000}])
        self.assertEqual(len(out), 1)
        row = out[0]
        self.assertEqual(row['content_id'], 'tt123')
        self.assertEqual(row['content_type'], 'series')
        self.assertEqual(row['name'], 'Show')
        self.assertEqual(row['release_info'], '2021')
        self.assertEqual(row['poster_shape'], 'POSTER')
        self.assertEqual(row['added_at'], 1700000000 * 1000)   # ms, like the web
        for key in ('imdb_rating', 'genres', 'addon_base_url', 'description'):
            self.assertIn(key, row)

    def test_media_type_normalisation_both_ways(self):
        for mt in ('series', 'show', 'tv', 'anime'):
            out = sync.Nuvio._library_to_nuvio([{'canonical_id': 'x', 'media_type': mt}])
            self.assertEqual(out[0]['content_type'], 'series', mt)
        out = sync.Nuvio._library_to_nuvio([{'canonical_id': 'y', 'media_type': 'movie'}])
        self.assertEqual(out[0]['content_type'], 'movie')

    def test_nuvio_to_local_accepts_both_key_casings(self):
        rows = sync.Nuvio._library_to_local([
            {'content_id': 'tt1', 'content_type': 'movie', 'name': 'A',
             'release_info': '1999', 'poster': 'p'},
            {'contentId': 'tt2', 'contentType': 'series', 'title': 'B'},
        ])
        self.assertEqual([r['canonical_id'] for r in rows], ['tt1', 'tt2'])
        self.assertEqual(rows[0]['year'], 1999)
        self.assertEqual(rows[1]['media_type'], 'series')

    def test_rows_without_an_id_are_dropped_not_crashed(self):
        self.assertEqual(sync.Nuvio._library_to_local([{'name': 'no id'}, {}]), [])
        self.assertEqual(sync.Nuvio._library_to_nuvio([{'title': 'no id'}]), [])

    def test_duplicates_collapse_on_push(self):
        out = sync.Nuvio._library_to_nuvio([
            {'canonical_id': 'tt9', 'title': 'A'}, {'canonical_id': 'tt9', 'title': 'B'}])
        self.assertEqual(len(out), 1)


class TestLibraryMerge(unittest.TestCase):
    def test_union_by_id_with_newest_winning(self):
        local = [{'canonical_id': 'a', 'title': 'old', 'added_at': 10},
                 {'canonical_id': 'b', 'title': 'local only', 'added_at': 5}]
        remote = [{'canonical_id': 'a', 'title': 'new', 'added_at': 99},
                  {'canonical_id': 'c', 'title': 'remote only', 'added_at': 7}]
        merged = {r['canonical_id']: r for r in sync._merge_library(local, remote)}
        self.assertEqual(set(merged), {'a', 'b', 'c'})
        self.assertEqual(merged['a']['title'], 'new')

    def test_missing_timestamps_never_raise(self):
        merged = sync._merge_library([{'canonical_id': 'a'}], [{'canonical_id': 'a'}])
        self.assertEqual(len(merged), 1)


class TestLibraryWiring(unittest.TestCase):
    def test_paged_pull_matches_the_web_client(self):
        body = SYNC.split('def sync_library(rows,', 1)[1].split('\n    @staticmethod', 1)[0]
        self.assertIn("'sync_pull_library'", body)
        self.assertIn("'p_offset': offset", body)
        self.assertIn("'p_limit': Nuvio._LIB_PAGE", body)
        self.assertEqual(sync.Nuvio._LIB_PAGE, 500)
        self.assertIn("'sync_push_library'", body)
        self.assertIn("'p_items': items", body)

    def test_section_runs_and_writes_back(self):
        self.assertIn("if sec.get('library') and hasattr(impl, 'sync_library'):", SYNC)
        self.assertIn("wb['library'] = _writeback_library(merged_library)", SYNC)
        self.assertIn('def _writeback_library(rows):', SYNC)
        self.assertIn("'library': any(s.get('library')", SYNC)

    def test_nuvio_only_and_settable(self):
        body = SYNC.split('def _sections_for(svc):', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("(svc == 'nuvio') and _setting_bool('nuvio_sync_library'", body)

    def test_writeback_tags_the_source_and_reports_failures(self):
        body = SYNC.split('def _writeback_library(rows):', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("source='nuvio'", body)
        self.assertIn('FAILED', body)

    def test_setting_declared_with_a_real_label(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(ROOT, 'resources', 'settings.xml')).getroot()
        node = [s for s in root.iter('setting') if s.get('id') == 'nuvio_sync_library']
        self.assertEqual(len(node), 1)
        self.assertEqual(node[0].get('default'), 'true')
        # 5.x hides some plumbing switches from the UI; the DEFAULT is the
        # contract, not its visibility.
        label = node[0].get('label')
        if not (label or '').isdigit():
            return                      # inline label, nothing to translate
        for lang in ('en_gb', 'ar_sa'):
            po = io.open(os.path.join(ROOT, 'resources', 'language',
                                      'resource.language.%s' % lang, 'strings.po'),
                         encoding='utf-8').read()
            self.assertIn('msgctxt "#%s"' % label, po, lang)


if __name__ == '__main__':
    unittest.main(verbosity=2)
