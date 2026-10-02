"""6.0.36: the update check looks at every component, not only the backend."""
import importlib
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()
import kodi_stub

settings = importlib.import_module('nuvio_ui.settings')
installer = importlib.import_module('resources.lib.bundle_installer')
restart = importlib.import_module('resources.lib.kodi_restart')


def row(aid, files, kodi=None, current=None, wanted='6.0.36'):
    return {'id': aid, 'wanted': wanted, 'files': files, 'kodi': kodi or files,
            'current': (files == wanted) if current is None else current}


class UpdateCheck(unittest.TestCase):
    def run_check(self, report, answer=False):
        dialog = mock.Mock()
        dialog.yesno.return_value = answer
        values = {}
        # Resolve the modules now: other suites may have replaced resources.lib.*
        live_installer = importlib.import_module('resources.lib.bundle_installer')
        live_restart = importlib.import_module('resources.lib.kodi_restart')
        with mock.patch.object(live_installer, 'component_report', return_value=report), \
                mock.patch.object(settings, 'ADDON', SimpleNamespace(setSetting=values.__setitem__)), \
                mock.patch.object(live_restart, 'plan', return_value=('Reboot', 'Reboot', '%s')), \
                mock.patch.object(settings.xbmc, 'executebuiltin') as builtin:
            settings.components_up_to_date('6.0.36', dialog, '6.0.36')
        return dialog, values, builtin

    def test_old_interface_is_not_called_up_to_date(self):
        report = [row('script.nuvio', '6.0.27'), row('skin.nuvio', '6.0.36'), row('screensaver.nuvio', '6.0.36')]
        dialog, values, builtin = self.run_check(report, answer=True)
        dialog.ok.assert_not_called()
        text = dialog.yesno.call_args.args[1]
        self.assertIn('interface 6.0.27', text)
        self.assertEqual(values[installer.VERSION_SETTING], '')   # the service installs it again
        builtin.assert_called_once_with('Reboot')                # platform restart (6.0.34)

    def test_kodi_still_running_the_old_version_needs_a_restart(self):
        report = [row('script.nuvio', '6.0.36', kodi='6.0.27'), row('skin.nuvio', '6.0.36')]
        dialog, values, builtin = self.run_check(report)
        self.assertIn('Kodi still uses interface 6.0.27', dialog.yesno.call_args.args[1])
        builtin.assert_not_called()

    def test_everything_current(self):
        dialog, _, _ = self.run_check([row('script.nuvio', '6.0.36'), row('skin.nuvio', '6.0.36')])
        dialog.ok.assert_called_once()
        self.assertIn('up to date', dialog.ok.call_args.args[1])
        dialog.yesno.assert_not_called()

    def test_maintenance_row_shows_an_older_interface(self):
        versions = {'plugin.video.nuviohub': '6.0.36', 'script.nuvio': '6.0.27'}
        with mock.patch.object(settings.xbmcaddon, 'Addon', side_effect=lambda aid: SimpleNamespace(getAddonInfo=lambda k: versions[aid])):
            self.assertEqual(settings.version_label(), '6.0.36 · interface 6.0.27')


def provider(pid, mid, catalogs, name=''):
    return {'id': pid, 'name': name or mid, 'manifest_url': 'https://x/%s/manifest.json' % pid,
            'manifest': {'id': mid, 'name': name or mid, 'version': '1', 'resources': ['catalog'], 'types': ['movie', 'series'],
                         'catalogs': [{'id': cid, 'type': ctype} for cid, ctype in catalogs]}}


class CollectionMatching(unittest.TestCase):
    def setUp(self):
        self.ch = importlib.import_module('resources.lib.collections_home')
        patch = mock.patch('resources.lib.metadata_providers.entries', side_effect=lambda providers: [(p, True) for p in providers])
        patch.start();self.addCleanup(patch.stop)

    def test_other_peoples_instance_connects_by_catalog(self):
        mine = provider('x1', 'xperience.metadata.mine', [('streaming.netflix', 'movie')], 'Xperience')
        source = {'addonId': 'xperience.metadata.someone-else', 'catalogId': 'streaming.netflix', 'type': 'movie'}
        self.assertEqual(self.ch.matching_catalog(source, [mine])[0]['id'], 'x1')

    def test_comma_ids_and_type_aliases_like_nuvio(self):
        mine = provider('x1', 'aiometadata', [('mdblist.123', 'series')])
        source = {'addonId': 'aiometadata', 'catalogId': 'mdblist.123,genre=Drama', 'type': 'tv'}
        self.assertEqual(self.ch.matching_catalog(source, [mine])[1]['id'], 'mdblist.123')
        self.assertEqual(self.ch.kind('tv'), 'series')

    def test_most_similar_addon_wins_and_general_ids_stay_put(self):
        cinemeta = provider('c', 'com.linvo.cinemeta', [('top', 'movie'), ('streaming.netflix', 'movie')], 'Cinemeta')
        xp = provider('x', 'xperience.v2', [('streaming.netflix', 'movie')], 'Xperience')
        source = {'addonId': 'xperience.v1', 'catalogId': 'streaming.netflix', 'type': 'movie'}
        self.assertEqual(self.ch.matching_catalog(source, [cinemeta, xp])[0]['id'], 'x')
        general = {'addonId': 'some.other.addon', 'catalogId': 'top', 'type': 'movie'}
        self.assertIsNone(self.ch.matching_catalog(general, [cinemeta]))


class ManifestRefresh(unittest.TestCase):
    def test_changed_manifests_are_stored(self):
        refresh = importlib.import_module('resources.lib.manifest_refresh')
        store = importlib.import_module('resources.lib.nuviohub.store')
        old = provider('x1', 'xperience', [('a', 'movie')])
        new_manifest = dict(old['manifest'], catalogs=[{'id': 'a', 'type': 'movie'}, {'id': 'streaming.netflix', 'type': 'movie'}])
        with mock.patch.object(store, 'list_providers', return_value=[old]), \
                mock.patch.object(refresh, 'fetch', return_value=new_manifest), \
                mock.patch.object(store, 'refresh_provider_manifest') as saved:
            changed = refresh.refresh_all()
        saved.assert_called_once_with('x1', new_manifest)
        self.assertEqual(changed, ['xperience'])

    def test_nuvio_import_reads_the_current_manifest(self):
        source = open(kodi_stub.ADDON_ROOT + '/resources/lib/nuvio_import.py', encoding='utf-8').read()
        self.assertIn("fetch_manifest(url, timeout=6) or", source)

    def test_service_and_settings_refresh(self):
        root = kodi_stub.ADDON_ROOT
        self.assertIn('NuvioHubManifests', open(root + '/service.py', encoding='utf-8').read())
        settings_source = open(root + '/../script.nuvio/nuvio_ui/settings.py', encoding='utf-8').read()
        self.assertIn('Refresh add-on catalogs now', settings_source)


class AutoInstall(unittest.TestCase):
    def test_a_failed_install_is_retried(self):
        addon = SimpleNamespace(getSetting=lambda k: '', setSetting=lambda k, v: None)
        monitor = SimpleNamespace(waitForAbort=lambda s: False)
        with mock.patch('xbmcaddon.Addon', return_value=addon), \
                mock.patch.object(installer, 'paths', return_value=('p', 'a')), \
                mock.patch.object(installer, 'backend_version', return_value='6.0.36'), \
                mock.patch.object(installer, 'outdated', return_value=['script.nuvio']), \
                mock.patch.object(installer, 'ensure_components', side_effect=[RuntimeError('Kodi has not discovered script.nuvio'), ['script.nuvio']]) as ensure, \
                mock.patch('xbmc.Player', return_value=SimpleNamespace(isPlayingVideo=lambda: False)), \
                mock.patch('xbmcgui.Window', return_value=SimpleNamespace(getProperty=lambda k: '')), \
                mock.patch('xbmcgui.Dialog'):
            self.assertEqual(installer.auto_install(monitor, wait=0, retry=0), ['script.nuvio'])
        self.assertEqual(ensure.call_count, 2)

    def test_waits_much_longer_than_an_hour_while_the_interface_is_open(self):
        import inspect
        defaults = inspect.signature(installer.auto_install).parameters
        self.assertGreaterEqual(defaults['attempts'].default * defaults['retry'].default, 24 * 3600)


if __name__ == '__main__':
    unittest.main()
