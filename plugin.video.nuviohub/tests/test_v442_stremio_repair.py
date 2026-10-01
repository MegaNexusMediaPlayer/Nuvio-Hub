# -*- coding: utf-8 -*-
"""v4.4.2 — Stremio 'LibraryItemsPulledFromAPI … _ctime invalid characters'.

One poisoned datetime in one library item makes stremio-core reject the whole
library pull, and dict(prev) cloning re-pushed old poison forever. These tests
pin the sanitizer, the push-time healing, and the repair sweep.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
sync = kodi_stub.import_lib_module('nuviohub.nuvio_stremio_sync')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()


class TestIsoValidation(unittest.TestCase):
    def test_valid_strict_iso_passes(self):
        self.assertTrue(sync._iso_is_valid('2026-08-04T21:15:00.000Z'))
        self.assertTrue(sync._iso_is_valid('2026-08-04T21:15:00Z'))

    def test_bad_shapes_fail(self):
        for bad in ('2026-08-04 21:15:00.000Z',      # space — the observed poison class
                    '2026-08-04T21:15:00',           # no Z
                    '', None, '١٤٤٧-٠١-٠١T00:00:00Z',  # localized digits
                    1754321234):
            self.assertFalse(sync._iso_is_valid(bad), repr(bad))


class TestSanitizer(unittest.TestCase):
    def test_space_datetime_is_healed_preserving_moment(self):
        item = {'_id': 'tt1', '_ctime': '2024-03-05 10:20:30.000Z',
                '_mtime': '2026-08-04T21:15:00.000Z', 'state': {}}
        fixed, changed = sync._sanitize_stremio_item(item)
        self.assertTrue(changed)
        self.assertEqual(fixed['_ctime'], '2024-03-05T10:20:30.000Z')
        self.assertEqual(fixed['_mtime'], '2026-08-04T21:15:00.000Z')

    def test_garbage_ctime_falls_back_to_mtime_moment(self):
        item = {'_id': 'tt2', '_ctime': '١٤٤٧-غير-صالح',
                '_mtime': '2026-08-04T21:15:00.000Z', 'state': {}}
        fixed, changed = sync._sanitize_stremio_item(item)
        self.assertTrue(changed)
        self.assertEqual(fixed['_ctime'], '2026-08-04T21:15:00.000Z')

    def test_state_datetimes_healed_and_watched_stringified(self):
        item = {'_id': 'tt3', '_ctime': '2026-08-04T21:15:00.000Z',
                '_mtime': '2026-08-04T21:15:00.000Z',
                'state': {'lastWatched': '2026-08-04 09:00:00.000Z',
                          'lastVidReleased': 'not-a-date', 'watched': 0}}
        fixed, changed = sync._sanitize_stremio_item(item)
        self.assertTrue(changed)
        self.assertEqual(fixed['state']['lastWatched'], '2026-08-04T09:00:00.000Z')
        self.assertNotIn('lastVidReleased', fixed['state'])
        # Falsy non-string junk becomes '' (unset) — safer than a fake
        # bitfield string for stremio-core's Option<String> watched field.
        self.assertEqual(fixed['state']['watched'], '')

    def test_clean_item_untouched(self):
        item = {'_id': 'tt4', '_ctime': '2026-08-04T21:15:00.000Z',
                '_mtime': '2026-08-04T21:15:00.000Z',
                'state': {'lastWatched': '2026-08-04T09:00:00.000Z', 'watched': ''}}
        fixed, changed = sync._sanitize_stremio_item(item)
        self.assertFalse(changed)
        self.assertEqual(fixed, item)


class TestRepairAndWiring(unittest.TestCase):
    def test_repair_pushes_only_broken_items(self):
        calls = []
        original = sync.Stremio._api
        orig_key = sync.Stremio._auth_key
        try:
            library = [
                {'_id': 'ok', '_ctime': '2026-08-04T21:15:00.000Z',
                 '_mtime': '2026-08-04T21:15:00.000Z', 'state': {}},
                {'_id': 'bad', '_ctime': '2026-08-04 21:15:00.000Z',
                 '_mtime': '2026-08-04T21:15:00.000Z', 'state': {}},
            ]
            def fake_api(op, payload):
                calls.append((op, payload))
                return library if op == 'datastoreGet' else {}
            sync.Stremio._api = staticmethod(fake_api)
            sync.Stremio._auth_key = staticmethod(lambda: 'k')
            scanned, repaired = sync.Stremio.repair_library()
        finally:
            sync.Stremio._api = original
            sync.Stremio._auth_key = orig_key
        self.assertEqual((scanned, repaired), (2, 1))
        put_ops = [payload for op, payload in calls if op == 'datastorePut']
        self.assertEqual(len(put_ops), 1)
        self.assertEqual([c['_id'] for c in put_ops[0]['changes']], ['bad'])
        self.assertEqual(put_ops[0]['changes'][0]['_ctime'], '2026-08-04T21:15:00.000Z')

    def test_push_path_sanitizes_every_change(self):
        src = io.open(os.path.join(ROOT, 'resources', 'lib', 'nuviohub', 'nuvio_stremio_sync.py'), encoding='utf-8').read()
        self.assertIn('_sanitize_stremio_item(c)[0] for c in (changes or [])', src)

    def test_menu_action_and_dispatcher(self):
        self.assertEqual(PLUGIN.count("if action == 'stremio_repair_library':"), 1)
        self.assertEqual(PLUGIN.count('def stremio_repair_library'), 1)
        self.assertGreaterEqual(PLUGIN.count('إصلاح مكتبة Stremio'), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
