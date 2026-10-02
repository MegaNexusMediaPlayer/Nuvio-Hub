"""6.0.31: crisp corners - 2x card masks/focus rings and per-size pill textures,
sharp per-size logos, screensaver clip loops without a black break."""
import importlib
import json
import threading
import time
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()
from pathlib import Path
import re
import sys
import unittest
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
MEDIA = ROOT / 'script.nuvio/resources/media'
sys.path.insert(0, str(ROOT / 'review'))
crisp = importlib.import_module('make_crisp_shapes')


def png_size(path):
    data = path.read_bytes()
    return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')


def xml_files():
    for folder in ('Default', 'Dark', 'Dim'):
        yield from sorted((ROOT / 'script.nuvio/resources/skins' / folder / '1080i').glob('*.xml'))
    yield ROOT / 'skin.nuvio/xml/Home.xml'
    yield ROOT / 'skin.nuvio/xml/SkinSettings.xml'


class Cards(unittest.TestCase):
    def test_masks_and_rings_are_drawn_at_2x(self):
        self.assertEqual(png_size(MEDIA / 'nuvio_tile_mask_v2.png'), (608, 342))
        self.assertEqual(png_size(MEDIA / 'nuvio_poster_mask_v2.png'), (384, 576))
        self.assertEqual(png_size(MEDIA / 'nuvio_tile_focus_v2.png'), (624, 358))
        self.assertEqual(png_size(MEDIA / 'nuvio_poster_focus_v2.png'), (400, 592))
        self.assertEqual(png_size(MEDIA / 'nuvio_tile_glass.png'), (608, 342))


class Pills(unittest.TestCase):
    def test_every_referenced_pill_texture_exists_at_2x(self):
        seen = set()
        for path in xml_files():
            text = path.read_text(encoding='utf-8')
            for prefix, w, h, r in re.findall(r'(special://home/addons/script\.nuvio/resources/media/|nuvio/)nuvio_pill_(\d+)x(\d+)_r(\d+)\.png', text):
                folder = MEDIA if prefix.startswith('special') else ROOT / 'skin.nuvio/media/nuvio'
                target = folder / ('nuvio_pill_%sx%s_r%s.png' % (w, h, r))
                self.assertTrue(target.is_file(), (path.name, target.name))
                self.assertEqual(png_size(target), (int(w) * 2, int(h) * 2), target.name)
                seen.add((w, h))
        self.assertGreater(len(seen), 10)

    def test_nothing_left_to_convert(self):
        for path in xml_files():
            text = path.read_text(encoding='utf-8')
            self.assertEqual(crisp.convert(text, set()), text, path.name)
            self.assertNotIn('nuvio_pill_glass', text, path.name)

    def test_hub_glass_pills_tint_white(self):
        home = (ROOT / 'skin.nuvio/xml/Home.xml').read_text(encoding='utf-8')
        self.assertEqual(home.count('<texturenofocus colordiffuse="%s">' % crisp.GLASS_REST), 6)
        self.assertEqual(home.count('<texturefocus colordiffuse="%s">' % crisp.GLASS_FOCUS), 6)

    def test_capsule_removed(self):
        for path in xml_files():
            self.assertNotIn('Glass capsule', path.read_text(encoding='utf-8'), path.name)


class Logos(unittest.TestCase):
    def test_every_logo_uses_a_2x_texture_of_its_drawn_size(self):
        ratio = 1600 / 507
        seen = set()
        for path in xml_files():
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('nuvio_wordmark.png', text, path.name)  # master is 5-10x too large
            for block in crisp.LOGO.findall(text):
                name = re.search(r'nuvio_wordmark_(\d+)x(\d+)\.png', block)
                size = (int(name.group(1)), int(name.group(2)))
                self.assertEqual(size, crisp.logo_size(block, ratio), path.name)
                self.assertEqual(png_size(MEDIA / name.group(0)), size)
                seen.add(size)
        self.assertEqual(seen, {(568, 180), (454, 144), (303, 96)})

    def test_master_stays_for_the_phone_page(self):
        self.assertEqual(png_size(MEDIA / crisp.WORDMARK), (1600, 507))


class SaverLoop(unittest.TestCase):
    def test_15s_clip_rewinds_a_second_early_with_fast_polling(self):
        saver = importlib.import_module('nuvio_ui.saver')
        self.assertGreaterEqual(saver.LOOP_SEEK_BEFORE_END, 1.0)
        win = mock.Mock(closed=False, ready=threading.Event());win.ready.set()
        props, seeks, waits, players = {}, [], [], []
        win.setProperty = props.__setitem__

        class Player:
            def __init__(self):
                self.token = self.path = '';self.ended = self.failed = False;self.ready = False;self.position = 12.0
                players.append(self)
            def play(self, path, item, windowed=False):self.ready = True
            def owns(self):return self.ready
            def isPlayingVideo(self):return self.ready
            def getTotalTime(self):return 15.0
            def getTime(self):
                self.position += .25;return self.position
            def seekTime(self, seconds):
                seeks.append((seconds, self.position));self.position = 0.0
            def cancel(self):pass
            def stop_owned(self):pass
            def _ended(self):pass

        class Monitor:
            def abortRequested(self):return False
            def waitForAbort(self, secs):
                waits.append(secs)
                if len(waits) >= 20:win.closed = True
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
        self.assertEqual(len(players), 1, 'the file is never reopened')
        self.assertTrue(seeks)
        self.assertEqual(seeks[0][0], 0)
        self.assertGreater(seeks[0][1], 15.0 - saver.LOOP_SEEK_BEFORE_END - .01)
        self.assertLess(seeks[0][1], 15.0)
        self.assertIn(saver.LOOP_FAST_POLL, waits, 'polls fast near the end')


if __name__ == '__main__':
    unittest.main()
