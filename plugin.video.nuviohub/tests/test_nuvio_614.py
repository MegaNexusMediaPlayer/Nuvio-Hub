"""6.0.14: hardware video layer for dialog video, restored hero shade, looping saver."""
import importlib
from pathlib import Path
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
FRONT = ROOT / 'script.nuvio/resources/skins/Default/1080i'


def hidden_videowindow(path):
    root = ET.parse(path).getroot()
    controls = root.find('controls')
    return [c for c in controls if c.get('type') == 'videowindow' and (c.findtext('visible') or '').strip() == 'false']


class HardwareVideoLayer(unittest.TestCase):
    """Kodi's RenderEx (which presents Amlogic/Android video) runs only for the
    active window; every window that can sit under a Nuvio video dialog needs a
    videowindow control of its own."""

    def test_session_window_under_all_nuvio_dialogs_has_one(self):
        self.assertEqual(len(hidden_videowindow(FRONT / 'nuvio_session.xml')), 1)

    def test_skin_windows_that_launch_nuvio_have_one(self):
        for name in ('Home.xml', 'SkinSettings.xml'):
            self.assertEqual(len(hidden_videowindow(ROOT / 'skin.nuvio/xml' / name)), 1, name)

    def test_the_session_window_is_a_real_window(self):
        session = importlib.import_module('nuvio_ui.session')
        self.assertTrue(issubclass(session.SessionWindow, session.xbmcgui.WindowXML))

    def test_video_dialogs_keep_their_own_videowindow(self):
        for name in ('nuvio_home.xml', 'nuvio_home_compact.xml', 'nuvio_iptv.xml', 'nuvio_trailer.xml',
                     'nuvio_screensaver.xml'):
            self.assertIn('type="videowindow"', (FRONT / name).read_text(encoding='utf-8'), name)

    def test_no_leftover_windowed_workaround(self):
        self.assertFalse((ROOT / 'plugin.video.nuviohub/resources/lib/video_window.py').exists())
        settings = (ROOT / 'plugin.video.nuviohub/resources/settings.xml').read_text(encoding='utf-8')
        self.assertNotIn('nuvio_windowed_video', settings)


class HeroShade(unittest.TestCase):
    def test_trailer_shade_is_the_full_6_0_12_look(self):
        for name in ('nuvio_home.xml', 'nuvio_home_compact.xml'):
            root = ET.parse(FRONT / name).getroot()
            shades = [c for c in root.iter('control') if 'nuvio_hero_' in (c.findtext('texture') or '')]
            self.assertTrue(shades)
            self.assertTrue(all(c.find('animation') is None for c in shades), name)


class ScreensaverLoop(unittest.TestCase):
    def test_clip_end_does_not_close_the_screensaver(self):
        saver = importlib.import_module('nuvio_ui.saver')
        player = saver.VideoPlayer()
        with mock.patch.object(saver.time, 'monotonic', return_value=100.0):
            player.onPlayBackEnded()
        self.assertTrue(player.ended)
        self.assertEqual(player.ended_at, 100.0)
        self.assertGreaterEqual(saver.LOOP_RESTART_GRACE, 2)


if __name__ == '__main__':
    unittest.main()
