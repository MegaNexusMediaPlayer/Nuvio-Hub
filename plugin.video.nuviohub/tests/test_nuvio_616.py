"""6.0.16: GitHub updates, Ko-fi, Cinemeta rules, seamless saver, video frame, IPTV."""
import hashlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
SKIN = ROOT / 'script.nuvio/resources/skins/Default/1080i'
MEDIA = ROOT / 'script.nuvio/resources/media'
updater = importlib.import_module('resources.lib.updater')
setup = importlib.import_module('resources.lib.default_setup')
metadata = importlib.import_module(setup.__package__ + '.metadata_providers')


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def component_zip(aid, version):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr(aid + '/addon.xml', '<addon id="%s" version="%s"/>' % (aid, version))
    return buffer.getvalue()


def release_zip(version, extra_name=None):
    buffer = io.BytesIO()
    rows = []
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('plugin.video.nuviohub/addon.xml', '<addon id="plugin.video.nuviohub" version="%s"/>' % version)
        for aid in ('script.nuvio', 'skin.nuvio', 'screensaver.nuvio'):
            data = component_zip(aid, version)
            archive.writestr('plugin.video.nuviohub/resources/packages/%s.zip' % aid, data)
            rows.append({'id': aid, 'file': aid + '.zip', 'version': version, 'sha256': hashlib.sha256(data).hexdigest()})
        archive.writestr('plugin.video.nuviohub/resources/packages/bundle.json', json.dumps(rows))
        if extra_name:
            archive.writestr(extra_name, 'x')
    return buffer.getvalue()


def github(version, data, sha=None):
    name = 'Nuvio-Hub-Complete-%s.zip' % version
    release = {'tag_name': 'v' + version, 'html_url': 'https://github.com/x/releases/tag/v' + version,
               'assets': [{'name': 'notes.txt', 'browser_download_url': 'https://example.invalid/notes'},
                          {'name': name, 'browser_download_url': 'https://example.invalid/' + name},
                          {'name': name + '.sha256', 'browser_download_url': 'https://example.invalid/' + name + '.sha256'}]}
    digest = sha or hashlib.sha256(data).hexdigest()

    def opener(request, timeout):
        url = request.full_url
        if url == updater.API:
            return Response(json.dumps(release).encode())
        if url.endswith('.sha256'):
            return Response(('%s  %s\n' % (digest, name)).encode())
        return Response(data)
    return opener


class GithubUpdates(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.addons = self.root / 'addons'
        (self.addons / 'plugin.video.nuviohub').mkdir(parents=True)
        (self.addons / 'plugin.video.nuviohub/addon.xml').write_text('<addon id="plugin.video.nuviohub" version="6.0.16"/>')

    def test_versions_compare_numerically(self):
        self.assertTrue(updater.newer('6.0.17', '6.0.16'))
        self.assertTrue(updater.newer('v6.1.0', '6.0.99'))
        self.assertFalse(updater.newer('6.0.7', '6.0.16'))

    def test_latest_release_asset_is_found(self):
        info = updater.latest(github('6.0.17', b'zip'))
        self.assertEqual(info['version'], '6.0.17')
        self.assertTrue(info['url'].endswith('Nuvio-Hub-Complete-6.0.17.zip'))
        self.assertTrue(info['sha256_url'].endswith('.sha256'))

    def test_install_replaces_backend_and_components_with_backup(self):
        data = release_zip('6.0.17')
        opener = github('6.0.17', data)
        changed = updater.install(updater.latest(opener), self.addons, self.root / 'profile', opener)
        self.assertEqual(changed[0], 'plugin.video.nuviohub')
        for aid in ('plugin.video.nuviohub', 'script.nuvio', 'skin.nuvio', 'screensaver.nuvio'):
            self.assertEqual(ET.parse(self.addons / aid / 'addon.xml').getroot().get('version'), '6.0.17', aid)
        backups = list((self.root / 'profile/installation-backups').iterdir())
        self.assertTrue(any(b.name.startswith('backend-') for b in backups))
        self.assertFalse(list((self.root / 'profile/updates').iterdir()), 'downloaded zip removed')

    def test_checksum_mismatch_keeps_current_version(self):
        data = release_zip('6.0.17')
        opener = github('6.0.17', data, sha='0' * 64)
        with self.assertRaises(ValueError):
            updater.install(updater.latest(opener), self.addons, self.root / 'profile', opener)
        self.assertIn('6.0.16', (self.addons / 'plugin.video.nuviohub/addon.xml').read_text())

    def test_unsafe_or_wrong_version_archive_is_rejected(self):
        for data, version in ((release_zip('6.0.17', extra_name='../evil.py'), '6.0.17'),
                              (release_zip('6.0.18'), '6.0.17')):
            path = self.root / 'u.zip'
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                updater.validate(path, version)

    def test_failed_component_install_restores_previous_backend(self):
        data = release_zip('6.0.17')
        opener = github('6.0.17', data)
        bundle = importlib.import_module('resources.lib.bundle_installer')
        with mock.patch.object(bundle, 'install_components', side_effect=ValueError('bad package')):
            with self.assertRaises(ValueError):
                updater.install(updater.latest(opener), self.addons, self.root / 'profile', opener)
        self.assertIn('6.0.16', (self.addons / 'plugin.video.nuviohub/addon.xml').read_text())

    def test_old_backups_are_pruned(self):
        folder = self.root / 'b'
        for n in range(6):
            (folder / ('backend-%d' % n)).mkdir(parents=True)
            (folder / str(n)).mkdir()
        updater.prune_backups(folder, keep=3)
        self.assertEqual(len([p for p in folder.iterdir() if p.name.startswith('backend-')]), 3)
        self.assertEqual(len([p for p in folder.iterdir() if not p.name.startswith('backend-')]), 3)

    def test_service_update_waits_for_playback_and_respects_switch(self):
        values = {}
        addon = mock.Mock(getSetting=lambda k: values.get(k, ''), setSetting=lambda k, v: values.__setitem__(k, v),
                          getAddonInfo=lambda k: '6.0.16')
        with mock.patch.object(updater, 'latest', return_value={'version': '6.0.17', 'url': 'u', 'sha256_url': ''}), \
                mock.patch('xbmc.Player', return_value=mock.Mock(isPlayingVideo=lambda: True)):
            self.assertEqual(updater.check_and_update(addon)[0], 'busy')
            values[updater.AUTO_SETTING] = 'false'
            self.assertEqual(updater.check_and_update(addon)[0], 'available')
        self.assertFalse(updater.due(addon))

    def test_settings_declare_update_switch(self):
        text = (ROOT / 'plugin.video.nuviohub/resources/settings.xml').read_text(encoding='utf-8')
        self.assertIn('id="nuvio_auto_update" type="bool" default="true"', text)


class KoFi(unittest.TestCase):
    def test_qr_and_support_page_ship(self):
        self.assertTrue((MEDIA / 'kofi_qr.png').is_file())
        root = ET.parse(SKIN / 'nuvio_support.xml').getroot()
        textures = [c.findtext('texture') for c in root.iter('control')]
        self.assertTrue(any('kofi_qr.png' in (t or '') for t in textures))
        self.assertIn("'kofi_qr.png'", (ROOT / 'review/build_bundle.py').read_text())
        source = (ROOT / 'script.nuvio/nuvio_ui/settings.py').read_text()
        self.assertIn("https://ko-fi.com/master100janovic", source)
        self.assertIn("('Support Nuvio Hub · Ko-fi',support)", source)


class CinemetaRules(unittest.TestCase):
    def setUp(self):
        self.values = {}
        self.addon = mock.Mock(getSetting=lambda k: self.values.get(k, ''), setSetting=lambda k, v: self.values.__setitem__(k, v))
        self.saved = []
        self.enabled = set()
        stack = [mock.patch.object(metadata, 'candidates', side_effect=lambda providers=None: [p for p in providers if 'meta' in p['manifest']['resources']]),
                 mock.patch.object(metadata, 'enabled', side_effect=lambda *a, **k: [p for p in k.get('providers') or [] if p['id'] in self.enabled]),
                 mock.patch.object(metadata, 'set_enabled', side_effect=lambda pid, on: (self.enabled.add if on else self.enabled.discard)(pid))]
        for patch in stack:
            patch.start()
            self.addCleanup(patch.stop)

    def save(self, groups, auto=False):
        self.saved.append((groups, auto))

    @staticmethod
    def provider(pid, mid, catalogs=(('top', 'movie'),), resources=('catalog', 'meta')):
        return {'id': pid, 'name': pid.title(), 'manifest': {'id': mid, 'resources': list(resources),
                'catalogs': [{'id': c, 'type': t, 'name': c.title()} for c, t in catalogs]}}

    def test_nothing_configured_uses_cinemeta(self):
        installed = []
        setup.apply_defaults(self.addon, [], [], self.save, install=lambda: installed.append(1))
        self.assertEqual(installed, [1])
        self.assertEqual(self.values[setup.CINEMETA_AUTO], 'true')
        self.assertEqual(self.values[setup.AUTO_LAYOUT], 'cinemeta')
        self.assertTrue(self.saved[-1][1])

    def test_own_catalog_addon_replaces_automatic_cinemeta(self):
        cinemeta = self.provider('cm', setup.CINEMETA_ID)
        own = self.provider('aio', 'aio-metadata', (('trending', 'movie'), ('trending', 'series'), ('search', 'movie')))
        own['manifest']['catalogs'][2]['extra'] = [{'name': 'search', 'isRequired': True}]
        self.enabled = {'cm', 'aio'}
        self.values.update({setup.CINEMETA_AUTO: 'true', setup.AUTO_LAYOUT: 'cinemeta'})
        setup.apply_defaults(self.addon, [cinemeta, own], [{'id': 'cinemeta.discover'}], self.save, install=lambda: None)
        self.assertNotIn('cm', self.enabled, 'automatic Cinemeta switched off')
        groups = self.saved[-1][0]
        self.assertEqual(groups[0]['title'], 'Aio')
        self.assertEqual([len(f['sources']) for f in groups[0]['folders']], [2], 'movies+series share a card; search skipped')
        self.assertEqual(self.values[setup.AUTO_LAYOUT], 'catalogs')

    def test_user_owned_collections_are_never_replaced(self):
        own = self.provider('aio', 'aio-metadata')
        setup.apply_defaults(self.addon, [own], [{'id': 'mine'}], self.save, install=lambda: None)
        self.assertEqual(self.saved, [])

    def test_manual_cinemeta_choice_is_kept(self):
        cinemeta = self.provider('cm', setup.CINEMETA_ID)
        own = self.provider('aio', 'aio-metadata')
        self.enabled = {'cm', 'aio'}
        setup.apply_defaults(self.addon, [cinemeta, own], [{'id': 'mine'}], self.save, install=lambda: None)
        self.assertIn('cm', self.enabled, 'switched on by the user (no auto flag)')
        installed = []
        self.values[setup.CINEMETA_AUTO] = 'off'
        setup.apply_defaults(self.addon, [cinemeta], [{'id': 'mine'}], self.save, install=lambda: installed.append(1))
        self.assertEqual(installed, [], 'switched off by the user stays off')

    def test_6015_cinemeta_layout_is_recognised(self):
        groups = setup.cinemeta_collections()
        self.assertTrue(setup.is_cinemeta_layout(groups))
        setup.apply_defaults(self.addon, [self.provider('aio', 'aio-metadata')], groups, self.save, install=lambda: None)
        self.assertEqual(self.values[setup.AUTO_LAYOUT], 'catalogs')

    def test_bundled_manifest_works_offline(self):
        manifest = setup.bundled_manifest()
        self.assertEqual(manifest['id'], setup.CINEMETA_ID)
        self.assertTrue(manifest['catalogs'])

    def test_user_save_clears_the_automatic_mode(self):
        profiles = importlib.import_module('resources.lib.collection_profile')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        values = {'nuvio_auto_layout': 'cinemeta'}
        addon = mock.Mock(setSetting=lambda k, v: values.__setitem__(k, v), getSetting=lambda k: values.get(k, ''))
        with mock.patch.object(profiles, 'profile_file', return_value=Path(temp.name) / 'c.json'), \
                mock.patch.object(profiles.xbmcaddon, 'Addon', return_value=addon):
            profiles.save(setup.cinemeta_collections(), auto=True)
            self.assertEqual(values['nuvio_auto_layout'], 'cinemeta')
            profiles.save(setup.cinemeta_collections())
            self.assertEqual(values['nuvio_auto_layout'], '')
        profiles._LOADED.clear()


class SeamlessScreensaver(unittest.TestCase):
    def test_clip_rewinds_before_its_end_and_never_restarts(self):
        saver = importlib.import_module('nuvio_ui.saver')
        home = kodi_stub.xbmcgui.Window(10000) if hasattr(kodi_stub, 'xbmcgui') else None
        win = mock.Mock()
        win.closed = False
        win.ready = threading.Event()
        win.ready.set()
        players, seeks, props = [], [], {}
        win.setProperty = lambda k, v: props.__setitem__(k, v)

        class Player:
            def __init__(self):
                self.token = ''
                self.path = ''
                self.ended = False
                self.failed = False
                self.ready = False
                self.cancelled = False
                self.position = 9.0
                players.append(self)

            def play(self, path, item, windowed=False):
                self.ready = True

            def owns(self):
                return self.ready

            def isPlayingVideo(self):
                return self.ready

            def getTotalTime(self):
                return 10.0

            def getTime(self):
                self.position += .3
                return self.position

            def seekTime(self, seconds):
                seeks.append(seconds)
                self.position = 0.0

            def cancel(self):
                self.cancelled = True

            def stop_owned(self):
                pass

            def _ended(self):
                pass

        class Monitor:
            loops = 0

            def abortRequested(self):
                return False

            def waitForAbort(self, secs):
                Monitor.loops += 1
                if Monitor.loops >= 8:
                    win.closed = True
                return False
        token = 'tok'
        window = saver.xbmcgui.Window(10000)
        window.setProperty('nuvio.saver.active', token)
        window.setProperty('nuvio.saver.pending', json.dumps({'token': token, 'issued': time.time()}))
        with mock.patch.object(saver, 'video_file', return_value='/clip.mp4'), \
                mock.patch.object(saver, 'window', return_value=win), \
                mock.patch.object(saver, 'VideoPlayer', Player), \
                mock.patch.object(saver.xbmc, 'Monitor', Monitor), \
                mock.patch.object(saver.xbmc, 'Player', return_value=SimpleNamespace(isPlaying=lambda: False)), \
                mock.patch.object(saver, 'rpc', side_effect=lambda m, p=None: {'muted': True} if m == 'Application.GetProperties' else True):
            saver.run_video(token)
        self.assertEqual(len(players), 1, 'no reopen of the file')
        self.assertTrue(seeks and all(s == 0 for s in seeks))
        self.assertEqual(props.get('nuvio.saver.mode'), 'video')

    def test_artwork_is_hidden_in_video_mode(self):
        root = ET.parse(SKIN / 'nuvio_screensaver.xml').getroot()
        art = [c for c in root.iter('control') if 'nuvio.background' in (c.findtext('texture') or '')][0]
        self.assertIn('nuvio.saver.mode', art.findtext('visible'))


class VideoFrame(unittest.TestCase):
    def png_alpha(self, path):
        import struct
        import zlib
        data = path.read_bytes()
        pos, idat = 8, b''
        while pos < len(data):
            n, = struct.unpack('>I', data[pos:pos + 4])
            kind = data[pos + 4:pos + 8]
            if kind == b'IHDR':
                w, h = struct.unpack('>II', data[pos + 8:pos + 16])
            if kind == b'IDAT':
                idat += data[pos + 8:pos + 8 + n]
            pos += 12 + n
        raw = zlib.decompress(idat)
        stride = w * 4 + 1
        return lambda x, y: raw[y * stride + 1 + x * 4 + 3], w, h

    def test_vignette_is_opaque_at_the_rim_and_clear_in_the_middle(self):
        alpha, w, h = self.png_alpha(MEDIA / 'nuvio_video_vignette.png')
        self.assertGreaterEqual(alpha(0, h // 2), 250)
        self.assertGreaterEqual(alpha(w // 2, 0), 250)
        self.assertEqual(alpha(w // 2, h // 2), 0)

    def test_home_frame_only_on_video_layer_devices_iptv_everywhere(self):
        for name in ('nuvio_home.xml', 'nuvio_home_compact.xml'):
            frames = [c for c in ET.parse(SKIN / name).getroot().iter('control') if 'nuvio_video_vignette' in (c.findtext('texture') or '')]
            self.assertEqual(len(frames), 1, name)
            self.assertIn('nuvio.videolayer', frames[0].findtext('visible'))
        frames = [c for c in ET.parse(SKIN / 'nuvio_iptv.xml').getroot().iter('control') if 'nuvio_video_vignette' in (c.findtext('texture') or '')]
        self.assertEqual((frames[0].findtext('left'), frames[0].findtext('width')), ('1010', '860'))

    def test_video_layer_detection(self):
        session = importlib.import_module('nuvio_ui.session')
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            f.write('NAME="CoreELEC"\n')
        self.addCleanup(Path(f.name).unlink)
        with mock.patch.object(session.xbmc, 'getCondVisibility', return_value=False):
            self.assertTrue(session.has_video_layer(f.name))
            Path(f.name).write_text('NAME="Windows"')
            self.assertFalse(session.has_video_layer(f.name))


class Caching(unittest.TestCase):
    def test_background_refresh_yields_to_foreground_pages(self):
        cache = importlib.import_module('resources.lib.browse_cache')
        with mock.patch.object(cache, '_FOREGROUND', [1, 0.0]):
            self.assertTrue(cache.foreground_busy())
        with mock.patch.object(cache, '_FOREGROUND', [0, time.monotonic()]):
            self.assertTrue(cache.foreground_busy())
        with mock.patch.object(cache, '_FOREGROUND', [0, time.monotonic() - 10]):
            self.assertFalse(cache.foreground_busy())
        self.assertGreaterEqual(cache.FRESH_SECONDS, 3 * 3600)


if __name__ == '__main__':
    unittest.main()
