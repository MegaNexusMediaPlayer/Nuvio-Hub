"""6.0.13: windowed video on CoreELEC, IPTV buttons, one loading screen."""
import importlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
SKIN = ROOT / 'script.nuvio/resources/skins/Default/1080i'
video_window = importlib.import_module('resources.lib.video_window')


class WindowedVideo(unittest.TestCase):
    def test_switch_defaults_on_and_turns_off(self):
        values = {}
        addon = mock.Mock(getSetting=lambda k: values.get(k, ''), setSetting=lambda k, v: values.__setitem__(k, v))
        self.assertTrue(video_window.allowed(addon))
        video_window.set_allowed(False, addon)
        self.assertFalse(video_window.allowed(addon))

    def test_coreelec_is_detected_from_os_release(self):
        with tempfile.NamedTemporaryFile('w', delete=False) as f:
            f.write('NAME="CoreELEC"\n')
        self.addCleanup(Path(f.name).unlink)
        self.assertTrue(video_window.is_coreelec(f.name))
        Path(f.name).write_text('NAME="Arch Linux"\n')
        self.assertFalse(video_window.is_coreelec(f.name))

    def test_dolby_vision_settings_are_found_without_hardcoded_ids(self):
        rows = [{'id': 'videoplayer.usedisplayasclock', 'label': 'Sync', 'type': 'boolean', 'value': False},
                {'id': 'coreelec.amlogic.dolbyvision.vs10.sdr8', 'label': 'SDR8 mode', 'type': 'integer', 'value': 2},
                {'id': 'coreelec.amlogic.dolbyvision.skipwindowed', 'label': 'Skip DV for windowed playback',
                 'type': 'boolean', 'value': False}]
        found = video_window.dolby_vision_settings(rpc=lambda method, params: {'settings': rows})
        self.assertEqual([r['id'] for r in found], [rows[1]['id'], rows[2]['id']])
        self.assertEqual(video_window.windowed_skip_setting(found)['id'], rows[2]['id'])
        calls = []
        video_window.enable(rows[2]['id'], rpc=lambda method, params: calls.append((method, params)))
        self.assertEqual(calls, [('Settings.SetSettingValue', {'setting': rows[2]['id'], 'value': True})])

    def test_rpc_failure_means_no_settings(self):
        def broken(method, params):
            raise RuntimeError('no')
        self.assertEqual(video_window.dolby_vision_settings(rpc=broken), [])

    def test_trailer_opens_fullscreen_when_windowed_video_is_off(self):
        trailers = importlib.import_module('nuvio_ui.trailers')
        playback = importlib.import_module('nuvio_ui.playback')
        support = importlib.import_module('resources.lib.trailer_support')
        frontend_window = importlib.import_module('resources.lib.video_window')
        with mock.patch.object(support, 'trailer_candidates', return_value=['https://imdb-video.media-imdb.com/v/x.mp4']), \
                mock.patch.object(playback, 'job', side_effect=lambda fn, *a, **k: fn()), \
                mock.patch.object(trailers.xbmc, 'Player', return_value=mock.Mock(isPlayingVideo=lambda: False)), \
                mock.patch.object(frontend_window, 'allowed', return_value=False), \
                mock.patch.object(trailers, '_fullscreen_trailer', return_value=True) as full:
            self.assertTrue(trailers.show_trailer({'id': 'tt1', 'name': 'X'}))
        full.assert_called_once()

    def test_settings_declare_windowed_options(self):
        text = (ROOT / 'plugin.video.nuviohub/resources/settings.xml').read_text(encoding='utf-8')
        self.assertIn('id="nuvio_windowed_video" type="text" default="on"', text)
        self.assertIn('id="nuvio_coreelec_window_hint"', text)

    def test_preview_overlays_lighten_while_video_plays(self):
        for name in ('nuvio_home.xml', 'nuvio_home_compact.xml'):
            root = ET.parse(SKIN / name).getroot()
            shades = [c for c in root.iter('control') if 'nuvio_hero_shade' in (c.findtext('texture') or '')]
            self.assertTrue(shades)
            for control in shades:
                animation = control.find('animation')
                self.assertEqual(animation.get('condition'), 'String.IsEqual(Window.Property(nuvio.preview),1)')


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
