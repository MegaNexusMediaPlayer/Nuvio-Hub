"""6.0.32: seamless silent screensaver loop, more RAM for catalogs and details,
details/next-page prefetch, plain header buttons."""
import importlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
CLIP = Path(__file__).resolve().parent / 'fixtures/saver_clip.mp4'   # 1 s, 12 frames, H.264 B-frames + AAC
mp4loop = importlib.import_module('nuvio_ui.mp4loop')
saver = importlib.import_module('nuvio_ui.saver')
browse_meta = importlib.import_module('nuvio_ui.browse_meta')
catalog_ui = importlib.import_module('nuvio_ui.catalog')
browse_cache = importlib.import_module('resources.lib.browse_cache')
catalog_pages = importlib.import_module('resources.lib.catalog_pages')


def loop_bytes(data, target):
    out = io.BytesIO()
    copies = mp4loop.write_loop(io.BytesIO(data), len(data), out, target=target)
    return copies, out.getvalue()


def samples(data):
    """Bytes of every video sample, in decode order."""
    _, track, _, _ = mp4loop.plan(io.BytesIO(data), len(data))
    result, index = [], 0
    chunks = track.offsets
    for i, (first, per_chunk, _) in enumerate(track.stsc):
        last = track.stsc[i + 1][0] - 1 if i + 1 < len(track.stsc) else len(chunks)
        for chunk in range(first, last + 1):
            pos = chunks[chunk - 1]
            for _ in range(per_chunk):
                size = track.sizes[index] if track.sizes else track.sample_size
                result.append(data[pos:pos + size]);pos += size;index += 1
    return track, result


class SeamlessLoopFile(unittest.TestCase):
    def setUp(self):
        self.clip = CLIP.read_bytes()

    def test_copy_repeats_the_clip_back_to_back_without_audio(self):
        copies, data = loop_bytes(self.clip, target=10)
        self.assertEqual(copies, 10)
        original, frames = samples(self.clip)
        track, looped = samples(data)
        self.assertEqual(looped, frames * copies)                      # frame k of every copy = frame k
        self.assertEqual(track.media_duration, original.media_duration * copies)
        self.assertEqual(track.stss, [s + k * original.samples for k in range(copies) for s in original.stss])
        moov = next(b for b in mp4loop._top_level(io.BytesIO(data), len(data)) if b[0] == 'moov')
        traks = [k for k, *_ in mp4loop._boxes(data, moov[2], moov[3]) if k == 'trak']
        self.assertEqual(len(traks), 1, 'only the video track: no sound, no mute')
        self.assertNotIn(b'soun', data[moov[1]:moov[3]])

    def test_index_first_input_and_edit_list(self):
        _, once = loop_bytes(self.clip, target=3)                    # moov before mdat now
        copies, twice = loop_bytes(once, target=6)
        self.assertEqual(copies, 2)                                  # 2 x the 3 s input
        self.assertEqual(samples(twice)[1], samples(self.clip)[1] * 6)
        track = mp4loop.plan(io.BytesIO(twice), len(twice))[1]
        if track.edits:
            normal = [e for e in track.edits if e[1] != -1]
            clip = round(mp4loop.plan(io.BytesIO(self.clip), len(self.clip))[1].media_duration * track.movie_scale / track.media_scale)
            self.assertGreaterEqual(normal[0][0], clip * 5)

    def test_one_hour_by_default_and_bounded_index(self):
        track = mp4loop.plan(io.BytesIO(self.clip), len(self.clip))[1]
        self.assertEqual(mp4loop.repeats(track), 3600)
        track.samples = 1000
        self.assertEqual(mp4loop.repeats(track), mp4loop.MAX_SAMPLES // 1000)

    def test_fragmented_or_foreign_files_are_unsupported(self):
        ftyp = struct.pack('>I4s', 16, b'ftyp') + b'isom\x00\x00\x02\x00'
        for data in (ftyp + struct.pack('>I4s', 8, b'moof'), b'\x1aE\xdf\xa3' + b'\x00' * 40, ftyp):
            with self.assertRaises(mp4loop.Unsupported):
                mp4loop.write_loop(io.BytesIO(data), len(data), io.BytesIO())


class SaverUsesTheLoop(unittest.TestCase):
    def run_saver(self, loop):
        win = mock.Mock(closed=False, ready=threading.Event());win.ready.set()
        props, players, rpcs = {}, [], []
        win.setProperty = props.__setitem__

        class Player:
            def __init__(self):
                self.token = self.path = '';self.ended = self.failed = False;self.ready = False
                players.append(self)
            def play(self, path, item, windowed=False):self.played = path;self.ready = True
            def owns(self):return self.ready
            def isPlayingVideo(self):return self.ready
            def getTotalTime(self):return 3600.0
            def getTime(self):return 5.0
            def seekTime(self, seconds):pass
            def cancel(self):pass
            def stop_owned(self):pass
            def _ended(self):pass

        class Monitor:
            n = 0
            def abortRequested(self):return False
            def waitForAbort(self, secs):
                Monitor.n += 1
                if Monitor.n >= 6:win.closed = True
                return False
        def rpc(method, params=None):
            rpcs.append(method)
            return {'muted': False} if method == 'Application.GetProperties' else True
        token = 'tok'
        home = saver.xbmcgui.Window(10000)
        home.setProperty('nuvio.saver.active', token)
        home.setProperty('nuvio.saver.pending', json.dumps({'token': token, 'issued': time.time()}))
        with mock.patch.object(saver, 'video_file', return_value='/clip.mp4'), \
                mock.patch.object(saver, 'prepare_loop', return_value=loop), \
                mock.patch.object(saver, 'window', return_value=win), \
                mock.patch.object(saver, 'VideoPlayer', Player), \
                mock.patch.object(saver.xbmc, 'Monitor', Monitor), \
                mock.patch.object(saver.xbmc, 'Player', return_value=SimpleNamespace(isPlaying=lambda: False)), \
                mock.patch.object(saver, 'rpc', side_effect=rpc):
            saver.run_video(token)
        return players, rpcs

    def test_loop_copy_plays_and_kodi_is_never_muted(self):
        players, rpcs = self.run_saver('/profile/saver_loop/abc.mp4')
        self.assertEqual(players[0].played, '/profile/saver_loop/abc.mp4')
        self.assertNotIn('Application.SetMute', rpcs)

    def test_other_formats_keep_the_muted_seek_loop(self):
        players, rpcs = self.run_saver('')
        self.assertEqual(players[0].played, '/clip.mp4')
        self.assertIn('Application.SetMute', rpcs)

    def test_prepare_loop_writes_once_and_cleans_old_copies(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'old.mp4').write_bytes(b'x')
            clip = folder / 'clip.mp4';clip.write_bytes(CLIP.read_bytes())

            class Handle:
                def __init__(self, path):self.f = open(path, 'rb')
                def seek(self, pos, whence=0):return self.f.seek(pos, whence)
                def readBytes(self, n):return bytearray(self.f.read(n))
                def size(self):return clip.stat().st_size
                def close(self):self.f.close()
            stat = SimpleNamespace(st_size=lambda: 1, st_mtime=lambda: 2)
            with mock.patch.object(saver.xbmcvfs, 'Stat', return_value=stat, create=True), \
                    mock.patch.object(saver.xbmcvfs, 'File', Handle, create=True), \
                    mock.patch.object(saver.xbmcvfs, 'translatePath', return_value=str(folder) + '/', create=True), \
                    mock.patch.object(mp4loop, 'write_loop', wraps=mp4loop.write_loop) as write:
                first = saver.prepare_loop(str(clip))
                second = saver.prepare_loop(str(clip))
            self.assertEqual(first, second)
            self.assertEqual(write.call_count, 1)
            self.assertFalse((folder / 'old.mp4').exists())
            self.assertEqual(saver.prepare_loop('/x.mkv'), '')

    def test_choosing_a_clip_prepares_the_loop(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/settings.py').read_text(encoding='utf-8')
        self.assertIn('if video:prepare_saver_loop(path)', source)


class CatalogRam(unittest.TestCase):
    def test_pages_get_96_mib_with_the_default_preset(self):
        for mode, limit in (('ram256', 96), ('', 96), ('ram150', 40), ('disk512', 40)):
            addon = mock.Mock(getSetting=lambda key, m=mode: m)
            with mock.patch('xbmcaddon.Addon', return_value=addon):
                self.assertEqual(browse_cache.page_ram(), limit * 1024 * 1024, mode)

    def test_details_do_not_enter_the_page_ram(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = browse_cache.Cache(Path(temp) / 'b.db')
            cache.put('meta', {'x': 1}, ttl=60, remember=False)
            self.assertNotIn('meta', cache.memory)
            self.assertEqual(cache.get('meta', remember=False), {'x': 1})
            self.assertNotIn('meta', cache.memory)
            self.assertEqual(cache.get('meta'), {'x': 1})
            self.assertIn('meta', cache.memory)


class DetailsPrefetch(unittest.TestCase):
    def setUp(self):
        browse_meta.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.cache = browse_cache.Cache(Path(self.temp.name) / 'b.db')
        self.patches = [mock.patch.object(browse_cache, 'instance', return_value=self.cache),
                        mock.patch.object(browse_cache, 'foreground_busy', return_value=False),
                        mock.patch.object(browse_cache, 'playback_busy', return_value=False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        browse_meta.clear()
        self.temp.cleanup()

    def wait(self):
        future = browse_meta._WANTED[1]
        if future is not None:
            future.result(5)

    def test_title_under_the_cursor_is_ready_before_select(self):
        context = {'media_type': 'movie', 'canonical_id': 'tt1'}
        with mock.patch.object(browse_meta.backend_api, 'metadata', return_value={'id': 'tt1', 'name': 'A'}) as get:
            browse_meta.prefetch(context);self.wait()
            browse_meta.prefetch(context);self.wait()
            self.assertEqual(browse_meta.cached(context)['name'], 'A')
            self.assertEqual(browse_meta.request(context).result(1)['name'], 'A')
        get.assert_called_once()
        self.assertEqual(self.cache.memory, {}, 'details live in their own RAM pool')

    def test_repeated_ticks_queue_one_job_and_failures_are_not_retried(self):
        context = {'media_type': 'movie', 'canonical_id': 'tt2'}
        release = threading.Event()
        def slow(*args, **kwargs):
            release.wait(2);return None
        with mock.patch.object(browse_meta.backend_api, 'metadata', side_effect=slow) as get:
            for _ in range(20):
                browse_meta.prefetch(context)
            release.set();self.wait()
            for _ in range(20):
                browse_meta.prefetch(context)
            self.wait()
        get.assert_called_once()

    def test_cursor_moved_on_skips_the_old_title(self):
        hold = threading.Event()
        with mock.patch.object(browse_cache, 'foreground_busy', side_effect=lambda: not hold.is_set()), \
                mock.patch.object(browse_meta, 'PREFETCH_WAIT', .01), \
                mock.patch.object(browse_meta.backend_api, 'metadata', side_effect=lambda t, i, **k: {'id': i}) as get:
            browse_meta.prefetch({'media_type': 'movie', 'canonical_id': 'tt3'})
            browse_meta.prefetch({'media_type': 'movie', 'canonical_id': 'tt4'})
            hold.set();self.wait()
            time.sleep(.05)
        self.assertEqual([c.args[1] for c in get.call_args_list], ['tt4'])

    def test_people_are_not_prefetched(self):
        with mock.patch.object(browse_meta.backend_api, 'metadata') as get:
            browse_meta.prefetch({'media_type': 'movie', 'canonical_id': 'nm1', 'person': True})
        get.assert_not_called()


class CatalogScreen(unittest.TestCase):
    def test_next_page_is_queued_only_when_missing(self):
        jobs = [{'provider': {'id': 'p'}, 'catalog': {'id': 'c', 'type': 'movie'}, 'extra': {}, 'offset': 100, 'done': False},
                {'provider': {'id': 'p'}, 'catalog': {'id': 'd', 'type': 'movie'}, 'extra': {}, 'offset': 0, 'done': True},
                {'provider': {'id': 'p'}, 'catalog': {'id': 'e', 'type': 'movie'}, 'extra': {}, 'offset': 50, 'done': False}]
        peeks = {'c': None, 'e': {'metas': []}}
        with mock.patch.object(browse_cache, 'peek', side_effect=lambda p, c, extra, revalidate=True: peeks[c['id']]), \
                mock.patch.object(browse_cache, 'refresh', return_value=True) as refresh:
            self.assertEqual(catalog_pages.prefetch_next(jobs), 1)
        self.assertEqual(refresh.call_args.args[2], {'skip': 100})

    def test_resting_on_a_title_prefetches_its_details(self):
        win = catalog_ui.Catalog.__new__(catalog_ui.Catalog)
        win.rows = [{'target': {'media_type': 'movie', 'canonical_id': 'tt9'}}]
        win._hover = (None, 0.0)
        win.getFocusId = lambda: 500
        win.getControl = lambda cid: SimpleNamespace(getSelectedPosition=lambda: 0)
        with mock.patch.object(browse_meta, 'prefetch') as prefetch:
            win._hover_prefetch()
            prefetch.assert_not_called()
            win._hover = (0, time.monotonic() - 1)
            win._hover_prefetch()
        prefetch.assert_called_once_with(win.rows[0]['target'])

    def test_home_title_rows_prefetch_details(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/home_window.py').read_text(encoding='utf-8')
        self.assertIn("browse_meta.prefetch(rows[pos]['target'])", source)


class HeaderButtons(unittest.TestCase):
    def test_home_search_settings_hub_have_no_pill_at_rest(self):
        for folder in ('Default', 'Dark', 'Dim'):
            for name in ('nuvio_home.xml', 'nuvio_home_compact.xml'):
                root = ET.parse(ROOT / 'script.nuvio/resources/skins' / folder / '1080i' / name).getroot()
                for cid in ('101', '105', '107', '108'):
                    button = next(c for c in root.iter('control') if c.get('id') == cid)
                    # Explicitly empty: a missing tag gets skin.nuvio's dark default
                    # button texture (dark rectangles behind the labels).
                    rest = button.find('texturenofocus')
                    self.assertIsNotNone(rest, (folder, name, cid))
                    self.assertFalse((rest.text or '').strip(), (folder, name, cid))
                    self.assertIn('nuvio_pill_', button.findtext('texturefocus'), (folder, name, cid))

    def test_no_button_falls_back_to_the_skin_default_texture(self):
        for folder in ('Default', 'Dark', 'Dim'):
            for path in sorted((ROOT / 'script.nuvio/resources/skins' / folder / '1080i').glob('*.xml')):
                for c in ET.parse(path).getroot().iter('control'):
                    if c.get('type') in ('button', 'radiobutton', 'togglebutton'):
                        for tag in ('texturefocus', 'texturenofocus'):
                            self.assertIsNotNone(c.find(tag), (folder, path.name, c.get('id'), tag))


if __name__ == '__main__':
    unittest.main()
