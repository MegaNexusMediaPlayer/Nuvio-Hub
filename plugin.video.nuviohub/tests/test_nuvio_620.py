"""6.0.20: MegaNexus branding, HUB labels, built-in MegaNexus screensaver media."""
import importlib
from pathlib import Path
import unittest
from unittest import mock
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
settings = importlib.import_module('nuvio_ui.settings')
saver = importlib.import_module('nuvio_ui.saver')


class Labels(unittest.TestCase):
    def test_hub_buttons(self):
        root = ET.parse(ROOT / 'skin.nuvio/xml/Home.xml').getroot()
        labels = {c.get('id'): c.findtext('label') for c in root.iter('control') if c.get('id')}
        self.assertEqual(labels['100'], 'MegaNexus')
        self.assertEqual(labels['101'], 'IPTV Channels')
        self.assertEqual(labels['102'], 'HUB Settings')
        skin_settings = (ROOT / 'skin.nuvio/xml/SkinSettings.xml').read_text(encoding='utf-8')
        self.assertIn('<label>HUB Settings</label>', skin_settings)

    def test_settings_page_title_is_hub_settings(self):
        titles = []
        with mock.patch.object(settings.page, 'show', side_effect=lambda title, *a, **k: titles.append(title)):
            settings.run()
        self.assertEqual(titles, ['HUB Settings'])

    def test_ram_preset_has_no_breakdown_and_usage_row_opens_nothing(self):
        captured = {}
        def show(title, rows, choose, **kwargs):
            captured['rows'] = rows();captured['choose'] = choose
        dialog = mock.Mock()
        with mock.patch.object(settings.page, 'show', side_effect=show), \
                mock.patch.object(settings.xbmcgui, 'Dialog', return_value=dialog):
            settings.performance()
            self.assertEqual(captured['rows'][0]['value'], 'RAM · 256 MiB')  # 6.0.27 preset
            captured['choose'](1)
        dialog.ok.assert_not_called()
        source = (ROOT / 'script.nuvio/nuvio_ui/settings.py').read_text(encoding='utf-8')
        self.assertNotIn('160 images', source)


class ScreensaverMedia(unittest.TestCase):
    def setUp(self):
        self.values = {}
        addon = SimpleNamespace(getSetting=lambda k: self.values.get(k, ''),
                                setSetting=lambda k, v: self.values.__setitem__(k, v))
        patch = mock.patch.object(settings, 'ADDON', addon);patch.start();self.addCleanup(patch.stop)

    def page(self):
        captured = {}
        def show(title, rows, choose, **kwargs):
            captured['rows'] = rows;captured['choose'] = choose
        with mock.patch.object(settings.page, 'show', side_effect=show):
            settings.screensaver_media()
        return captured

    def selected(self, captured):
        return [i for i, row in enumerate(captured['rows']()) if row['value'] == 'Selected']

    def test_default_is_the_standard_meganexus_image(self):
        self.assertEqual(self.selected(self.page()), [0])

    def test_animated_meganexus_is_a_skin_animation_not_a_video(self):
        # 6.0.21 contract: the built-in animation is drawn by the skin; the
        # 6.0.20 bundled MP4 was replaced (player muted Kodi, showed the OSD).
        captured = self.page()
        captured['choose'](1)
        self.assertEqual(self.values['nuvio_screensaver_type'], saver.ANIMATED)
        self.assertEqual(self.values['nuvio_screensaver_video'], '')
        self.assertEqual(self.selected(captured), [1])
        captured['choose'](0)
        self.assertEqual((self.values['nuvio_screensaver_type'], self.values['nuvio_screensaver_video']), ('image', ''))
        self.assertEqual(self.selected(captured), [0])

    def test_custom_choices_still_browse(self):
        captured = self.page()
        dialog = mock.Mock();dialog.browseSingle.return_value = '/media/loop.mkv'
        with mock.patch.object(settings.xbmcgui, 'Dialog', return_value=dialog):
            captured['choose'](3)
        self.assertEqual(self.values['nuvio_screensaver_video'], '/media/loop.mkv')
        self.assertEqual(self.selected(captured), [3])

    def test_6020_bundled_mp4_setting_reads_as_the_animation(self):
        values = {'nuvio_screensaver_type': 'video',
                  'nuvio_screensaver_video': 'special://home/addons/script.nuvio/resources/media/meganexus_saver.mp4'}
        addon = SimpleNamespace(getSetting=lambda k: values.get(k, ''))
        self.assertEqual(saver.saver_mode(addon), saver.ANIMATED)
        with mock.patch.object(saver.xbmcvfs, 'exists', return_value=True):
            self.assertEqual(saver.video_file(addon), '')


class Logos(unittest.TestCase):
    def test_all_logo_copies_are_the_same_meganexus_files(self):
        groups = {
            'banner': ['script.nuvio/resources/media/nuvio_banner.png', 'plugin.video.nuviohub/resources/media/nuvio_banner.png',
                       'skin.nuvio/media/nuvio/nuvio_banner.png', 'skin.nuvio/resources/fanart.png', 'screensaver.nuvio/resources/fanart.png'],
            'icon': ['script.nuvio/resources/media/icon.png', 'plugin.video.nuviohub/resources/media/icon.png', 'skin.nuvio/resources/icon.png',
                     'screensaver.nuvio/resources/icon.png', 'script.nuvio/resources/media/nuvio_mark.png', 'plugin.video.nuviohub/resources/media/nuvio_mark.png'],
            'wordmark': ['script.nuvio/resources/media/nuvio_wordmark.png', 'plugin.video.nuviohub/resources/media/nuvio_wordmark.png',
                         'skin.nuvio/media/nuvio/nuvio_wordmark.png'],
        }
        for name, paths in groups.items():
            data = {(ROOT / p).read_bytes() for p in paths}
            self.assertEqual(len(data), 1, name)
            self.assertTrue(next(iter(data)).startswith(b'\x89PNG'), name)


if __name__ == '__main__':
    unittest.main()
