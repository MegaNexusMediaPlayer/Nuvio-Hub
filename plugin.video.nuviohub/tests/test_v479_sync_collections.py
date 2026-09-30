# -*- coding: utf-8 -*-
"""v4.7.9 — why Nuvio never synced, and the ready-made collections.

NUVIO: linking by QR saved the token and the menu showed "connected", but
only the PASSWORD login path ever wrote the service's master sync toggle.
`enabled_targets()` requires that toggle, so every sync run returned "no
linked/enabled accounts" and did nothing — addons included. The QR path now
writes it, an account that is linked with the toggle never written heals
itself (an explicit 'false' is still respected), and the provider writeback
no longer swallows per-addon failures with a bare `continue`.

COLLECTIONS: ready-made sets built on TMDb-native endpoints, so every row
arrives with a TMDb id and poster — no id conversion, no per-item lookup —
and clicking one goes through the same _content_click_path as any catalog
row.
"""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
td = kodi_stub.import_lib_module('tmdb_direct')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SYNC = io.open(os.path.join(ROOT, 'resources', 'lib', 'dexhub', 'nuvio_stremio_sync.py'), encoding='utf-8').read()
QR = io.open(os.path.join(ROOT, 'resources', 'lib', 'qr_pair.py'), encoding='utf-8').read()
ACCOUNTS = io.open(os.path.join(ROOT, 'resources', 'lib', 'routes', 'accounts.py'), encoding='utf-8').read()


class TestSyncActuallyEnabled(unittest.TestCase):
    def test_qr_pairing_enables_the_master_toggle(self):
        seg = QR.split('sync.Stremio.login(email, password)', 1)[1][:900]
        self.assertIn("setSetting('%s_sync_enabled' % service, 'true')", seg)

    def test_password_login_still_enables_it(self):
        self.assertIn("addon.setSetting('%s_sync_enabled' % service, 'true')", ACCOUNTS)

    def test_linked_account_with_unwritten_toggle_heals(self):
        """v4.8.4: behavioural. This is the bug that made every sync a
        no-op — a QR-paired account was linked but its toggle was never
        written, and enabled_targets() therefore returned nothing."""
        sync = kodi_stub.import_lib_module('dexhub.nuvio_stremio_sync')
        store = {}
        written = []

        class _FakeAddon(object):
            def getSetting(self, key):
                return store.get(key, '')

            def setSetting(self, key, value):
                store[key] = value
                written.append((key, value))

        orig_addon, orig_nu, orig_st = sync.addon, sync.Nuvio.is_linked, sync.Stremio.is_linked
        try:
            sync.addon = lambda: _FakeAddon()
            sync.Nuvio.is_linked = staticmethod(lambda: True)
            sync.Stremio.is_linked = staticmethod(lambda: False)

            store.clear(); written[:] = []
            self.assertEqual(sync.enabled_targets(), ['nuvio'])      # heals
            self.assertIn(('nuvio_sync_enabled', 'true'), written)

            store['nuvio_sync_enabled'] = 'false'                    # explicit off
            written[:] = []
            self.assertEqual(sync.enabled_targets(), [])
            self.assertEqual(written, [])                            # not overridden

            store['nuvio_sync_enabled'] = 'true'
            self.assertEqual(sync.enabled_targets(), ['nuvio'])

            sync.Nuvio.is_linked = staticmethod(lambda: False)       # unlinked
            self.assertEqual(sync.enabled_targets(), [])
        finally:
            sync.addon = orig_addon
            sync.Nuvio.is_linked = orig_nu
            sync.Stremio.is_linked = orig_st

    def test_writeback_reports_failures_instead_of_swallowing(self):
        body = SYNC.split('def _writeback_providers(providers):', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('failed.append(', body)
        self.assertIn('%d FAILED', body)
        self.assertNotIn('except Exception:\n            continue', body)


class TestReadySetsData(unittest.TestCase):
    def test_every_set_is_tmdb_native_and_well_formed(self):
        self.assertGreaterEqual(len(td.READY_SETS), 8)
        seen = set()
        for set_id, label, path, media_type in td.READY_SETS:
            self.assertNotIn(set_id, seen, set_id)
            seen.add(set_id)
            self.assertTrue(label.strip(), set_id)
            self.assertTrue(path.startswith('/'), path)
            self.assertIn(media_type, ('movie', 'series'), set_id)

    def test_lookup(self):
        self.assertEqual(td.ready_set_def('trending_movie')[3], 'movie')
        self.assertEqual(td.ready_set_def('trending_tv')[3], 'series')
        self.assertIsNone(td.ready_set_def('does_not_exist'))
        self.assertIsNone(td.ready_set_def(''))

    def test_row_normalization_carries_tmdb_id_and_art(self):
        row = td._row_from_tmdb({
            'id': 42, 'name': 'A Show', 'first_air_date': '2019-03-04',
            'poster_path': '/p.jpg', 'backdrop_path': '/b.jpg',
            'overview': 'plot', 'vote_average': 8.1}, 'series')
        self.assertEqual(row['tmdb_id'], '42')
        self.assertEqual(row['title'], 'A Show')
        self.assertEqual(row['year'], '2019')
        self.assertEqual(row['media_type'], 'series')
        self.assertTrue(row['poster'] and row['backdrop'])

    def test_missing_dates_and_art_never_raise(self):
        row = td._row_from_tmdb({'id': 7, 'title': 'B'}, 'movie')
        self.assertEqual((row['year'], row['poster'], row['backdrop']), ('', '', ''))

    def test_unknown_set_and_no_api_key_return_empty(self):
        self.assertEqual(td.ready_set_items('nope'), [])
        self.assertEqual(td.ready_set_items('trending_movie'), [])   # stub has no key


class TestReadyCollectionsWiring(unittest.TestCase):
    def test_actions_registered(self):
        self.assertIn("if action == 'ready_collections_menu':", PLUGIN)
        self.assertIn("if action == 'ready_collection':", PLUGIN)
        self.assertIn('def ready_collections_menu():', PLUGIN)
        self.assertIn('def ready_collection(set_id=\'\', page=\'1\'):', PLUGIN)

    def test_surfaced_in_the_collection_menu(self):
        body = PLUGIN.split('def hub_collection():', 1)[1].split('\ndef ', 1)[0]
        self.assertIn("build_url(action='ready_collections_menu')", body)

    def test_rows_open_through_the_normal_click_path(self):
        body = PLUGIN.split("def ready_collection(set_id='', page='1'):", 1)[1].split('\ndef ', 1)[0]
        self.assertIn('_content_click_path(', body)
        self.assertIn("canonical_id='tmdb:%s' % tmdb_id", body)
        self.assertIn('_build_source_picker_menu(', body)
        self.assertIn("action='ready_collection'", body)          # paging

    def test_missing_api_key_explains_itself(self):
        body = PLUGIN.split('def ready_collections_menu():', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('_api_key()', body)
        self.assertIn("action='open_settings'", body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
