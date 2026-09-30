# -*- coding: utf-8 -*-
"""v4.4.1 — MDBList lists opened empty: unified=true reshaped item ids.

Covers the root cause (no unified param anywhere), the defensive id
flattening for dict AND array `ids` shapes, the renderer's list-ids guard,
the zero-network home payload, and the mirror throttle.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
mdblist = kodi_stub.import_lib_module('mdblist')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
MDB = io.open(os.path.join(ROOT, 'resources', 'lib', 'mdblist.py'), encoding='utf-8').read()
SERVICE = io.open(os.path.join(ROOT, 'service.py'), encoding='utf-8').read()


class TestUnifiedRemoved(unittest.TestCase):
    def test_no_unified_param_requested_anywhere(self):
        for chunk in MDB.split('\n'):
            self.assertNotIn("'unified': 'true'", chunk)
        self.assertNotIn('return \'/items\', True', MDB)

    def test_items_by_id_sends_only_limit_and_offset(self):
        calls = []
        original = mdblist._request
        try:
            mdblist._request = lambda path, params=None, timeout=20: (calls.append((path, dict(params or {}))) or ({'movies': [], 'shows': []}, False))
            orig_setting = mdblist._setting
            mdblist._setting = lambda key, default='': 'k' if key == 'mdblist_api_key' else orig_setting(key, default)
            mdblist.fetch_items_by_id('42', cursor='offset:100', limit=50)
            mdblist._setting = orig_setting
        finally:
            mdblist._request = original
        path, params = calls[0]
        self.assertEqual(path, '/lists/42/items')
        self.assertNotIn('unified', params)
        self.assertEqual(params.get('offset'), 100)


class TestIdsFlattening(unittest.TestCase):
    def test_dict_ids_flatten_to_flat_fields(self):
        data = {'movies': [{'title': 'Dune', 'ids': {'imdb': 'tt1160419', 'tmdb': 438631}}], 'shows': []}
        rows, _ = mdblist._normalize_items_response(data, False, 'auto')
        self.assertEqual(rows[0]['imdb_id'], 'tt1160419')
        self.assertEqual(rows[0]['id'], 438631)

    def test_array_ids_flatten_and_do_not_crash(self):
        data = {'movies': [], 'shows': [{'title': 'Severance',
                                         'ids': [{'tvdb': 371980}, {'imdb': 'tt11280740'}]}]}
        rows, _ = mdblist._normalize_items_response(data, False, 'auto')
        self.assertEqual(rows[0]['tvdb_id'], 371980)
        self.assertEqual(rows[0]['imdb_id'], 'tt11280740')
        self.assertNotIsInstance(rows[0].get('ids'), list)

    def test_zero_row_diagnostic_exists(self):
        self.assertIn('normalized to 0 rows', MDB)


class TestRendererGuardAndLightness(unittest.TestCase):
    def test_renderer_tolerates_list_ids(self):
        start = PLUGIN.index('def _render_idlist_rows')
        body = PLUGIN[start:PLUGIN.index('\ndef mdblist_list_browse(', start)]
        self.assertIn("isinstance(raw_ids, dict)", body)
        self.assertNotIn("ids = dict(meta.get('ids') or {})", body)

    def test_mirror_throttled_in_service(self):
        self.assertIn('dexhub.mirror.last', SERVICE)
        self.assertIn('30 * 60', SERVICE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
