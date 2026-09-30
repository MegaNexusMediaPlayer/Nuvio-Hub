"""Remote repeats, paused resume and video-plane startup regressions."""
import importlib
import unittest
from types import SimpleNamespace
from unittest import mock
import frontend_test_support
frontend_test_support.install()
preview=importlib.import_module('nuvio_ui.home_trailers')
cache=importlib.import_module('resources.lib.trailer_cache')


class PreviewStartup(unittest.TestCase):
    def test_av_ready_reveals_video_even_if_hardware_clock_is_still_zero(self):
        window=mock.Mock();window.preview_selection.return_value=('selection',{})
        controller=preview.Controller(window);controller.previous='selection';controller.attempted=True;controller.play_started=1
        controller.player=SimpleNamespace(ready=True,failed=False,cancelled=False,token='token',owns=lambda:True,isPlayingVideo=lambda:True,getTime=lambda:0)
        settings={'nuvio_auto_trailers':'true','nuvio_trailer_duration':'30'}
        with mock.patch.object(preview.time,'monotonic',return_value=2),mock.patch.object(preview,'cached_addon',return_value=SimpleNamespace(getSetting=lambda k:settings.get(k,''))):controller.tick()
        self.assertIn(mock.call('nuvio.preview','1'),window.setProperty.call_args_list)
    def test_h264_mp4_is_preferred_to_a_higher_resolution_webm(self):
        streams=[{'container':'webm','video':{'height':480,'encoding':'vp9'},'audio':{'encoding':'opus'},'url':'https://test/webm'},
                 {'container':'mp4','video':{'height':360,'encoding':'avc1.42001E'},'audio':{'encoding':'aac'},'url':'https://test/mp4'}]
        self.assertEqual(cache.select_stream(streams)[0],'https://test/mp4')
    def test_audio_only_and_adaptive_formats_never_become_local_preview(self):
        rows=[{'container':'mp4','video':{'height':360},'audio':{},'url':'https://test/no-audio'},
              {'container':'mp4','video':{},'audio':{'encoding':'aac'},'url':'https://test/no-video'},
              {'container':'mp4','adaptive':True,'video':{'height':360},'audio':{'encoding':'aac'},'url':'https://test/adaptive'}]
        self.assertEqual(cache.select_stream(rows),('',{}))
