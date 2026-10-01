"""6.0.21: blue theme, sharp MegaNexus logo, skin-drawn screensaver, Ko-fi label, Kodi repository."""
import colorsys
import importlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
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
settings = importlib.import_module('nuvio_ui.settings')
saver = importlib.import_module('nuvio_ui.saver')
sys.path.insert(0, str(ROOT / 'review'))
theme = importlib.import_module('make_blue_theme')


def png_size(path):
    data = path.read_bytes()
    assert data.startswith(b'\x89PNG')
    return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')


class BlueTheme(unittest.TestCase):
    def test_no_violet_left_in_shipped_skin_xml(self):
        violet = []
        for path in theme.XML:
            for alpha, rgb in re.findall(r'\b([0-9A-Fa-f]{2})([0-9A-Fa-f]{6})\b', path.read_text(encoding='utf-8')):
                r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
                h, l, s = colorsys.rgb_to_hls(r, g, b)
                if 235 <= h * 360 <= 300 and s > 0.12 and l > 0.12:
                    violet.append((path.name, alpha + rgb))
        self.assertEqual(violet, [])

    def test_recolor_maps_violet_to_logo_blue_and_slate_to_space_navy(self):
        self.assertEqual(theme.recolor('B799FF'), '99C9FF')
        self.assertEqual(theme.recolor('202532'), '08204A')
        self.assertEqual(theme.recolor('090B11'), '040F22')
        self.assertIsNone(theme.recolor('99C9FF'))  # idempotent
        self.assertIsNone(theme.recolor('CAD0DB'))  # neutral text untouched

    def test_kodi_colour_theme_focus_is_blue(self):
        colors = {c.get('name'): c.text for c in ET.parse(ROOT / 'skin.nuvio/colors/defaults.xml').getroot()}
        r, g, b = (int(colors['button_focus'][i:i + 2], 16) for i in (2, 4, 6))
        self.assertGreater(b, r);self.assertGreater(b, g)


class Logo(unittest.TestCase):
    def test_logo_files_are_high_resolution(self):
        self.assertEqual(png_size(ROOT / 'script.nuvio/resources/media/nuvio_wordmark.png'), (1600, 507))
        self.assertEqual(png_size(ROOT / 'script.nuvio/resources/media/nuvio_banner.png'), (1920, 1080))
        self.assertEqual(png_size(ROOT / 'script.nuvio/resources/media/icon.png'), (1024, 1024))

    def test_home_header_logo_is_larger_and_hub_label_does_not_overlap(self):
        for name in ('nuvio_home.xml', 'nuvio_home_compact.xml'):
            root = ET.parse(SKIN / name).getroot()
            logo = next(c for c in root.iter('control') if 'nuvio_wordmark' in (c.findtext('texture') or ''))
            left, width, height = (int(logo.findtext(k)) for k in ('left', 'width', 'height'))
            self.assertEqual((width, height), (284, 90))
            hub = next(c for c in root.iter('control') if c.get('type') == 'label' and c.findtext('label') == 'HUB')
            self.assertGreaterEqual(int(hub.findtext('left')), left + width)
            self.assertLessEqual(int(hub.findtext('left')) + int(hub.findtext('width')), 420)


class AnimatedScreensaver(unittest.TestCase):
    def test_animation_is_skin_drawn_and_shipped(self):
        root = ET.parse(SKIN / 'nuvio_screensaver.xml').getroot()
        group = next(c for c in root.iter('control') if c.get('type') == 'group'
                     and 'animated' in (c.findtext('visible') or ''))
        textures = [t.text for t in group.iter('texture')]
        for layer in ('bg', 'logo', 'glow', 'spark'):
            name = 'meganexus_saver_%s.png' % layer
            self.assertTrue(any(t.endswith(name) for t in textures), name)
            self.assertTrue((ROOT / 'script.nuvio/resources/media' / name).is_file())
        self.assertTrue(all(a.get('condition') == 'true' for a in group.iter('animation')))
        self.assertFalse(list((ROOT / 'script.nuvio').rglob('*.mp4')))

    def test_animated_mode_never_starts_a_player_or_mutes(self):
        addon = SimpleNamespace(getSetting=lambda k: {'nuvio_screensaver_type': 'animated'}.get(k, ''))
        calls = []
        with mock.patch.object(saver.xbmcaddon, 'Addon', return_value=addon), \
                mock.patch.object(saver.saver_state, 'active', return_value=False), \
                mock.patch.object(saver, 'run_image', side_effect=lambda: calls.append('image')), \
                mock.patch.object(saver, 'rpc', side_effect=AssertionError('no mute / RPC')), \
                mock.patch.object(saver.xbmc, 'executebuiltin', side_effect=AssertionError('no video handoff')):
            saver.launch()
        self.assertEqual(calls, ['image'])

    def test_window_publishes_the_animated_mode(self):
        addon = SimpleNamespace(getSetting=lambda k: {'nuvio_screensaver_type': 'animated'}.get(k, ''))
        win = saver.SaverWindow.__new__(saver.SaverWindow);win.ready = saver.threading.Event()
        props = {}
        win.setProperty = props.__setitem__
        with mock.patch.object(saver.xbmcaddon, 'Addon', return_value=addon), \
                mock.patch.object(saver.presentation_settings, 'sync'):
            win.onInit()
        self.assertEqual(props.get('nuvio.saver.mode'), 'animated')
        self.assertEqual(props.get('nuvio.background'), saver.DEFAULT_ART)


class KoFi(unittest.TestCase):
    def test_support_labels_say_meganexus(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/settings.py').read_text(encoding='utf-8')
        self.assertNotIn('Support Nuvio Hub', source)
        self.assertEqual(source.count('Support MegaNexus · Ko-fi'), 2)
        self.assertIn('<label>Support MegaNexus</label>', (SKIN / 'nuvio_support.xml').read_text(encoding='utf-8'))


class Repository(unittest.TestCase):
    def test_repository_addon_points_at_the_pages_repo(self):
        root = ET.parse(ROOT / 'repository.meganexus/addon.xml').getroot()
        self.assertEqual(root.get('id'), 'repository.meganexus')
        directory = root.find("extension[@point='xbmc.addon.repository']/dir")
        base = 'https://meganexusmediaplayer.github.io/Nuvio-Hub/repo/'
        self.assertEqual(directory.findtext('info'), base + 'addons.xml')
        self.assertEqual(directory.findtext('checksum'), base + 'addons.xml.md5')
        self.assertEqual(directory.findtext('datadir'), base)

    def test_site_builder_makes_a_kodi_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            packages = tmp / 'packages';packages.mkdir()
            def addon_zip(path, aid, version='9.9.9'):
                with zipfile.ZipFile(path, 'w') as z:
                    z.writestr(aid + '/addon.xml', '<?xml version="1.0"?>\n<addon id="%s" name="x" version="%s">'
                               '<extension point="xbmc.addon.metadata"><assets><icon>icon.png</icon></assets></extension></addon>' % (aid, version))
                    z.writestr(aid + '/icon.png', b'\x89PNG')
            bundle = tmp / 'bundle.zip';addon_zip(bundle, 'plugin.video.nuviohub')
            for aid in ('script.nuvio', 'skin.nuvio', 'screensaver.nuvio'):
                addon_zip(packages / (aid + '.zip'), aid)
            site = importlib.import_module('build_repo_site')
            out = tmp / 'site'
            with mock.patch.object(site, 'PACKAGES', packages), \
                    mock.patch.object(sys, 'argv', ['x', str(bundle), '--output', str(out), '--base-url', 'https://example.test/r']), \
                    mock.patch('builtins.print'):
                site.main()
            addons = ET.parse(out / 'repo/addons.xml').getroot()
            ids = [a.get('id') for a in addons]
            self.assertEqual(ids, ['plugin.video.nuviohub', 'script.nuvio', 'skin.nuvio', 'screensaver.nuvio', 'repository.meganexus'])
            import hashlib
            self.assertEqual((out / 'repo/addons.xml.md5').read_text(), hashlib.md5((out / 'repo/addons.xml').read_bytes()).hexdigest())
            for aid in ids[:4]:
                self.assertTrue((out / 'repo' / aid / ('%s-9.9.9.zip' % aid)).is_file())
                self.assertTrue((out / 'repo' / aid / 'icon.png').is_file())
            repo_zip = out / 'repository.meganexus-1.0.0.zip'
            with zipfile.ZipFile(repo_zip) as z:
                xml = z.read('repository.meganexus/addon.xml').decode()
            self.assertIn('https://example.test/r/repo/addons.xml', xml)
            self.assertNotIn('github.io', xml)
            self.assertIn('href="repository.meganexus-1.0.0.zip"', (out / 'index.html').read_text())
            self.assertTrue((out / 'repo/repository.meganexus/repository.meganexus-1.0.0.zip').is_file())


if __name__ == '__main__':
    unittest.main()
