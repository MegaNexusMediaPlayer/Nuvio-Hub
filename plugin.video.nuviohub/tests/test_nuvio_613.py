"""6.0.13: IPTV buttons and one loading screen (the 6.0.13 windowed-video
workaround was replaced in 6.0.14 by the real fix, see test_nuvio_614)."""
import importlib
from pathlib import Path
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
SKIN = ROOT / 'script.nuvio/resources/skins/Default/1080i'


class IptvButtons(unittest.TestCase):
    def test_refresh_setup_and_hub_fit_side_by_side(self):
        root = ET.parse(SKIN / 'nuvio_iptv.xml').getroot()
        buttons = {c.get('id'): c for c in root.iter('control') if c.get('id') in ('502', '503', '506')}
        spans = sorted((int(c.findtext('left')), int(c.findtext('left')) + int(c.findtext('width'))) for c in buttons.values())
        self.assertEqual(len(spans), 3)
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), spans)
        self.assertLessEqual(spans[-1][1], 1880)
        self.assertEqual(buttons['506'].findtext('label'), 'HUB')
        self.assertEqual(buttons['503'].findtext('onright'), '506')
        self.assertEqual(buttons['506'].findtext('onleft'), '503')

    def test_bottom_hub_button_leaves_like_the_top_one(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/iptv.py').read_text(encoding='utf-8')
        self.assertIn('elif cid in (505,506):', source)


class OneLoadingScreen(unittest.TestCase):
    def test_autoplay_keeps_one_loading_window_until_video_starts(self):
        playback = importlib.import_module('nuvio_ui.playback')
        created = []

        class FakeLoading:
            def __init__(self, *args, **kwargs):
                self.cancelled = False
                self.props = {}
                created.append(self)

            def show(self):
                pass

            def close(self):
                pass

            def setProperty(self, key, value):
                self.props[key] = value

        listener = mock.Mock(started=True, failed=False)
        addon = mock.Mock(getSetting=lambda k: 'true' if k == 'nuvio_autoplay' else '')
        with mock.patch.object(playback, 'Loading', FakeLoading), \
                mock.patch.object(playback.xbmcaddon, 'Addon', return_value=addon), \
                mock.patch.object(playback.backend_api, 'streams', return_value=({'id': 'aio'}, [{'url': 'https://v/1'}])), \
                mock.patch.object(playback.backend_api, 'playback_context', return_value={}), \
                mock.patch.object(playback.backend_api, 'queue_playback', return_value='plugin://x'), \
                mock.patch.object(playback, 'StartListener', return_value=listener), \
                mock.patch.object(playback.xbmc, 'executebuiltin'):
            self.assertTrue(playback.play({'id': 'tt1', 'type': 'movie'}, {}))
        self.assertEqual(len(created), 1)


if __name__ == '__main__':
    unittest.main()
