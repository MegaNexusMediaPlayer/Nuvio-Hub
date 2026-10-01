"""6.0.22: phone setup - a local web page served by Kodi, opened from a QR code."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
phone = importlib.import_module('resources.lib.phone_setup')
profiles = importlib.import_module('resources.lib.collection_profile')


def request(service, path, body=None, key=None, method=None):
    headers = {}
    if key is not False:
        headers['X-Setup-Key'] = service.key if key is None else key
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8');headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(service.address + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read()


class Server(unittest.TestCase):
    def setUp(self):
        self.service = phone.SetupService(host='127.0.0.1').start()
        self.addCleanup(self.service.stop)

    def test_url_carries_a_random_key_and_the_lan_address(self):
        other = phone.SetupService(host='127.0.0.1')
        self.addCleanup(other.stop)
        self.assertNotEqual(self.service.key, other.key)
        self.assertGreaterEqual(len(self.service.key), 20)
        self.assertEqual(self.service.url, 'http://127.0.0.1:%d/?k=%s' % (self.service.port, self.service.key))

    def test_page_needs_the_key_from_the_qr_code(self):
        code, body = request(self.service, '/', key=False)
        self.assertEqual(code, 403)
        self.assertNotIn(self.service.key.encode(), body)
        code, body = request(self.service, '/?k=wrong', key=False)
        self.assertEqual(code, 403)
        code, body = request(self.service, '/?k=' + self.service.key, key=False)
        self.assertEqual(code, 200)
        self.assertIn(b'Save &amp; start MegaNexus', body)
        self.assertTrue(self.service.connected)

    def test_api_rejects_missing_or_wrong_key(self):
        for key in (False, 'nope'):
            code, body = request(self.service, '/api/state', key=key)
            self.assertEqual(code, 403)
            code, body = request(self.service, '/api/save', {}, key=key)
            self.assertEqual(code, 403)
        self.assertFalse(self.service.saved)

    def test_state_is_served_with_the_key(self):
        with mock.patch.object(phone, 'state', return_value={'nuvio': {'linked': False}}):
            code, body = request(self.service, '/api/state')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {'nuvio': {'linked': False}, 'ok': True})

    def test_save_answers_the_phone_then_marks_the_session_finished(self):
        seen = []
        with mock.patch.object(phone, 'save', side_effect=lambda body: seen.append(body) or {}):
            code, body = request(self.service, '/api/save', {'display': {'card_shape': 'landscape'}})
        self.assertEqual((code, json.loads(body)), (200, {'ok': True}))
        self.assertEqual(seen, [{'display': {'card_shape': 'landscape'}}])
        self.assertTrue(self.service.saved)

    def test_failed_action_reports_and_does_not_finish(self):
        with mock.patch.object(phone, 'save', side_effect=ValueError('Nothing to save.')):
            code, body = request(self.service, '/api/save', {})
        self.assertEqual(json.loads(body), {'ok': False, 'error': 'Nothing to save.'})
        self.assertFalse(self.service.saved)
        with mock.patch.object(phone, 'add_manifest', side_effect=RuntimeError('https://secret.example/abc/manifest.json')):
            code, body = request(self.service, '/api/addons/add', {'url': 'x'})
        self.assertNotIn(b'secret', body)  # unexpected errors never echo details

    def test_oversized_or_invalid_body_is_rejected(self):
        code, body = request(self.service, '/api/save', key=None, method='POST')
        self.assertEqual(code, 200)  # empty body = {} -> handled by save()
        req = urllib.request.Request(self.service.address + '/api/save', data=b'[1,2]',
                                     headers={'X-Setup-Key': self.service.key}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 400)

    def test_stop_closes_the_port(self):
        address = self.service.address
        self.service.stop()
        with self.assertRaises(OSError):
            urllib.request.urlopen(address + '/', timeout=2)

    def test_idle_timeout(self):
        self.assertFalse(self.service.idle())
        self.service.last_seen -= phone.IDLE_TIMEOUT + 1
        self.assertTrue(self.service.idle())


class ManifestInput(unittest.TestCase):
    def test_only_complete_manifest_links_are_accepted(self):
        for value in ('', 'ftp://x/manifest.json', 'https://example.test/config', 'manifest.json'):
            with self.assertRaises(ValueError):
                phone.add_manifest(value)

    def test_validation_failure_never_echoes_the_link(self):
        client = importlib.import_module('resources.lib.nuviohub.client')
        with mock.patch.object(client, 'validate_manifest', side_effect=RuntimeError('boom')):
            with self.assertRaises(ValueError) as caught:
                phone.add_manifest('https://example.test/SECRET-TOKEN/manifest.json')
        self.assertNotIn('SECRET', str(caught.exception))


class SaveCollections(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'nuvio_collections.json'
        for module in {profiles, importlib.import_module('nuviolib.collection_profile')}:
            module._LOADED.clear()
            patch = mock.patch.object(module, 'profile_file', return_value=path);patch.start()
            self.addCleanup(patch.stop);self.addCleanup(module._LOADED.clear)
        source = lambda c: {'addonId': 'a', 'catalogId': c, 'type': 'movie'}
        profiles.save([
            {'id': 'g1', 'title': 'One', 'folders': [
                {'id': 'f1', 'title': 'A', 'sources': [source('c1'), source('c2')]},
                {'id': 'f2', 'title': 'B', 'sources': [source('c3')]}]},
            {'id': 'g2', 'title': 'Two', 'folders': [{'id': 'f3', 'title': 'C', 'sources': [source('c4')]}]}])

    def test_order_visibility_titles_and_catalog_switches(self):
        changed = phone._apply_groups([
            {'id': 'g2', 'hidden': True, 'folders': [{'id': 'f3', 'title': 'C', 'hidden': False, 'hideTitle': False, 'sources': [True]}]},
            {'id': 'g1', 'hidden': False, 'folders': [
                {'id': 'f2', 'title': '  Renamed  ', 'hidden': True, 'hideTitle': True, 'sources': [True]},
                {'id': 'f1', 'title': 'A', 'hidden': False, 'hideTitle': False, 'sources': [True, False]}]}])
        self.assertTrue(changed)
        groups = profiles.load()
        self.assertEqual([g['id'] for g in groups], ['g2', 'g1'])
        self.assertTrue(groups[0]['hidden'])
        self.assertEqual([f['id'] for f in groups[1]['folders']], ['f2', 'f1'])
        self.assertEqual(groups[1]['folders'][0]['title'], 'Renamed')
        self.assertTrue(groups[1]['folders'][0]['hidden'] and groups[1]['folders'][0]['hideTitle'])
        self.assertEqual([s['enabled'] for s in groups[1]['folders'][1]['sources']], [True, False])

    def test_unknown_or_missing_rows_never_drop_collections(self):
        phone._apply_groups([{'id': 'ghost', 'folders': []}, {'id': 'g2', 'folders': []}])
        groups = profiles.load()
        self.assertEqual([g['id'] for g in groups], ['g2', 'g1'])
        self.assertEqual([f['id'] for f in groups[0]['folders']], ['f3'])  # unsent cards stay
        self.assertEqual(len(groups[1]['folders']), 2)

    def test_mismatched_catalog_list_is_ignored_and_unchanged_layout_is_not_rewritten(self):
        with mock.patch.object(profiles, 'save') as save:
            self.assertFalse(phone._apply_groups([
                {'id': 'g1', 'hidden': False, 'folders': [
                    {'id': 'f1', 'title': 'A', 'sources': [False]},  # wrong length
                    {'id': 'f2', 'title': 'B', 'sources': [True]}]},
                {'id': 'g2', 'hidden': False, 'folders': [{'id': 'f3', 'title': 'C', 'sources': [True]}]}]))
        save.assert_not_called()


class SaveSettings(unittest.TestCase):
    def setUp(self):
        self.values = {}
        addon = mock.Mock()
        addon.getSetting.side_effect = lambda k: self.values.get(k, '')
        addon.setSetting.side_effect = lambda k, v: self.values.__setitem__(k, v)
        patch = mock.patch.object(phone, '_addon', return_value=addon);patch.start();self.addCleanup(patch.stop)

    def test_display_values_are_validated(self):
        phone._apply_display({'card_shape': 'landscape', 'show_ratings': False, 'auto_trailers': True,
                              'continue_row': False, 'screensaver': 'animated'})
        self.assertEqual(self.values, {'nuvio_card_shape': 'landscape', 'nuvio_show_ratings': 'false',
                                       'nuvio_auto_trailers': 'true', 'nuvio_home_continue': 'false',
                                       'nuvio_screensaver_type': 'animated', 'nuvio_screensaver_art': '',
                                       'nuvio_screensaver_video': ''})
        self.values.clear()
        phone._apply_display({'card_shape': 'circle', 'screensaver': 'http://evil'})
        self.assertEqual(self.values, {})

    def test_provider_switches_change_only_known_ids_that_differ(self):
        module = mock.Mock()
        module.entries.return_value = [({'id': 'a'}, True), ({'id': 'b'}, False)]
        phone._apply_switches(module, [{'id': 'a', 'enabled': True}, {'id': 'b', 'enabled': True},
                                       {'id': 'zzz', 'enabled': True}, 'junk'])
        module.set_enabled.assert_called_once_with('b', True)

    def test_state_never_contains_manifest_urls_or_tokens(self):
        provider = {'id': 'p1', 'name': 'Meta', 'manifest_url': 'https://x.test/SECRET/manifest.json',
                    'manifest': {'id': 'meta.test', 'resources': ['meta', 'stream'], 'catalogs': []}}
        store = importlib.import_module('resources.lib.nuviohub.store')
        sync = importlib.import_module('resources.lib.nuviohub.nuvio_stremio_sync')
        meta = importlib.import_module('resources.lib.metadata_providers')
        streams = importlib.import_module('resources.lib.stream_providers')
        with mock.patch.object(store, 'list_providers', return_value=[provider]), \
                mock.patch.object(sync.Nuvio, 'token', return_value={'access_token': 'TOKEN123', 'email': 'a@b.c', 'profile_name': 'Me'}), \
                mock.patch.object(meta, 'entries', return_value=[(provider, True)]), \
                mock.patch.object(streams, 'entries', return_value=[(provider, False)]), \
                mock.patch.object(profiles, 'load', return_value=[]):
            data = phone.state()
        text = json.dumps(data)
        self.assertNotIn('SECRET', text);self.assertNotIn('TOKEN123', text)
        self.assertEqual(data['nuvio'], {'linked': True, 'profile': 'Me', 'email': 'a@b.c'})
        self.assertEqual(data['metadata'][0]['enabled'], True)
        self.assertEqual(data['streams'][0]['enabled'], False)


class Wiring(unittest.TestCase):
    def test_entries(self):
        settings = (ROOT / 'script.nuvio/nuvio_ui/settings.py').read_text(encoding='utf-8')
        self.assertIn("('Set up on phone · QR code',phone_setup)", settings)
        self.assertIn("page.item('Sign in with phone · QR code')", settings)
        onboarding = (ROOT / 'script.nuvio/nuvio_ui/onboarding.py').read_text(encoding='utf-8')
        self.assertIn('Set up on your phone · QR code', onboarding)
        default = (ROOT / 'script.nuvio/default.py').read_text(encoding='utf-8')
        self.assertIn("mode == 'phone'", default)

    def test_old_qr_login_route_opens_phone_setup(self):
        qr = importlib.import_module('resources.lib.qr_pair')
        with mock.patch.object(qr.xbmc, 'executebuiltin') as run:
            self.assertTrue(qr.qr_pair('nuvio'))
            self.assertFalse(qr.qr_pair('stremio'))
        run.assert_called_once_with('RunScript(script.nuvio,phone)')

    def test_page_ships_and_escapes_by_building_dom_nodes(self):
        page = (ROOT / 'plugin.video.nuviohub/resources/phone_setup/index.html').read_text(encoding='utf-8')
        self.assertIn("'X-Setup-Key'", page)
        self.assertNotIn('innerHTML', page)
        self.assertEqual(Path(phone.PAGE), ROOT / 'plugin.video.nuviohub/resources/phone_setup/index.html')

    def test_tv_window_stops_the_service_and_removes_the_qr(self):
        tv = importlib.import_module('nuvio_ui.phone_setup')
        plex = importlib.import_module('resources.lib.plex_qr')
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        qr_file = Path(temp.name) / 'qr.png';qr_file.write_bytes(b'png')
        service = mock.Mock(url='http://1.2.3.4:5/?k=x', connected=True, saved=True)
        service.idle.return_value = False
        window = mock.Mock(cancelled=False)
        with mock.patch.object(phone, 'SetupService') as cls, \
                mock.patch.object(phone, 'lan_ip', return_value='192.168.1.50'), \
                mock.patch.object(plex, 'qr_png', return_value=str(qr_file)), \
                mock.patch.object(tv, 'PhoneWindow', return_value=window), \
                mock.patch.object(tv.xbmcgui, 'Dialog'), \
                mock.patch.object(tv.xbmc, 'Monitor', return_value=mock.Mock(abortRequested=lambda: False, waitForAbort=lambda t: False)):
            cls.return_value.start.return_value = service
            self.assertTrue(tv.run())
        service.stop.assert_called_once_with()
        window.close.assert_called_once_with()
        self.assertFalse(qr_file.exists())
        cls.assert_called_once_with(host='192.168.1.50')

    def test_no_network_means_no_service(self):
        tv = importlib.import_module('nuvio_ui.phone_setup')
        with mock.patch.object(phone, 'lan_ip', return_value='127.0.0.1'), \
                mock.patch.object(phone, 'SetupService') as cls, \
                mock.patch.object(tv.xbmcgui, 'Dialog') as dialog:
            self.assertFalse(tv.run())
        cls.assert_not_called()
        dialog.return_value.ok.assert_called_once()


if __name__ == '__main__':
    unittest.main()
