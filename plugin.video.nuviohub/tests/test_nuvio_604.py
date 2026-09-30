"""Native seek migration, nested modal ownership, delayed AV and bounded image I/O."""
import importlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock
from urllib.request import urlopen
import frontend_test_support
frontend_test_support.install()
art=importlib.import_module('resources.lib.art_cache')
dialog=importlib.import_module('nuvio_ui.dialog')
preview=importlib.import_module('nuvio_ui.home_trailers')
seek=importlib.import_module('resources.lib.seek_profile')
post=importlib.import_module('resources.lib.playback.post_start')


class ImageCache(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.data=b'\x89PNG\r\n\x1a\n'+b'x'*42
        self.fetch=mock.Mock(return_value=self.data)
        self.limits={'ram150':100,'disk246':100,'disk512':200}
    def cache(self,mode='ram150'):
        return art.Cache(self.folder.name,mode,self.limits,self.fetch)
    def test_ram_lru_enforces_byte_budget_without_preallocation(self):
        cache=self.cache();self.assertEqual(cache.stats()[1],0)
        for key in ('one','two','one','three'):cache.get(key)
        self.assertEqual(cache.stats(),('ram150',100,2));cache.get('one')
        self.assertEqual(self.fetch.call_count,3);cache.get('two');self.assertEqual(self.fetch.call_count,4)
        self.assertEqual(list(Path(self.folder.name).glob('*.img')),[])
    def test_disk_survives_restart_offline_and_smaller_budget_evicts(self):
        cache=self.cache('disk512')
        for key in ('one','two','three','four'):cache.get(key)
        restarted=self.cache('disk246');self.assertEqual(restarted.stats(),('disk246',100,2))
        self.fetch.side_effect=OSError('Offline');self.assertEqual(restarted.get('four'),self.data)
        self.assertEqual(sum(p.stat().st_size for p in Path(self.folder.name).glob('*.img')),100)
    def test_concurrent_same_image_downloads_once(self):
        def download(url):time.sleep(.06);return self.data
        self.fetch.side_effect=download;cache=self.cache()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(cache.get,['same']*4))
        self.assertEqual(results,[self.data]*4);self.fetch.assert_called_once()
    def test_clear_or_mode_change_rejects_inflight_old_cache_write(self):
        entered=threading.Event();release=threading.Event()
        def download(url):entered.set();release.wait(1);return self.data
        self.fetch.side_effect=download;cache=self.cache('disk246')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(cache.get,'image');self.assertTrue(entered.wait(1));cache.clear();release.set();future.result()
        self.assertEqual(cache.stats()[1],0);self.assertFalse(list(Path(self.folder.name).glob('*.img')))
    def test_html_is_not_cached_and_failures_do_not_repeat_per_frame(self):
        self.fetch.return_value=b'<html>Error</html>';cache=self.cache()
        for _ in range(3):
            with self.assertRaises(ValueError):cache.get('bad')
        self.fetch.assert_called_once();self.assertEqual(cache.stats()[1],0)
    def test_proxy_http_returns_same_image_cold_and_warm(self):
        cache=self.cache();server=art.Server(('127.0.0.1',0),cache)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:%s/image?url=https%%3A%%2F%%2Ffixture%%2Fimage.png'%server.server_port
            for _ in range(2):
                with urlopen(url,timeout=2) as response:self.assertEqual(response.read(),self.data)
            self.fetch.assert_called_once_with('https://fixture/image.png')
        finally:server.shutdown();server.server_close();thread.join(2)
    def test_url_mapping_is_cheap_and_preserves_original_metadata(self):
        art._BASE=('http://127.0.0.1:1234',time.monotonic()+60)
        try:
            source={'poster':'https://test/poster.jpg','thumb':'special://home/local.png'}
            mapped=art.art(source);self.assertTrue(mapped['poster'].startswith(art._BASE[0]))
            self.assertEqual(source['poster'],'https://test/poster.jpg');self.assertEqual(mapped['thumb'],source['thumb'])
            self.assertEqual(art.url('https://test/img.jpg|Authorization=secret'),'https://test/img.jpg|Authorization=secret')
        finally:art._BASE=('',0)


class NestedDialogs(unittest.TestCase):
    def test_direction_events_cannot_consume_click_queue(self):
        clicked=[]
        class Window(dialog.Dialog):
            def onAction(self,action):pass
            def onClick(self,cid):clicked.append(cid)
        window=Window()
        for _ in range(20):window.onAction(dialog.Action(2))
        window.onClick(7000);window.drain_events();self.assertEqual(clicked,[7000])
    def test_parent_closes_natively_while_child_owns_input_and_restores(self):
        class Window(dialog.Dialog):
            def onClick(self,cid):raise AssertionError('Hidden parent received click')
        window=Window();window.getFocusId=lambda:500;window.show=mock.Mock()
        def child():
            self.assertTrue(window._child_active);self.assertFalse(window._dialog_closed)
            window.onClick(500);self.assertTrue(window._events.empty());return 'returned'
        with mock.patch.object(dialog.xbmcgui.WindowXMLDialog,'close',create=True) as close:
            self.assertEqual(window.child(child),'returned');close.assert_called_once()
        window.show.assert_called_once();self.assertFalse(window._dialog_closed)
        self.assertFalse(window._child_active);self.assertEqual(window._restore_focus,500)
    def test_child_exception_still_restores_parent(self):
        window=dialog.Dialog();window.getFocusId=lambda:503;window.show=mock.Mock()
        with mock.patch.object(dialog.xbmcgui.WindowXMLDialog,'close',create=True):
            with self.assertRaises(ValueError):window.child(lambda:(_ for _ in ()).throw(ValueError()))
        window.show.assert_called_once();self.assertFalse(window._child_active)


class SubtitleStart(unittest.TestCase):
    def test_real_media_before_av_confirmation_does_not_lose_auto_subtitles(self):
        props={};home=SimpleNamespace(getProperty=lambda key:props.get(key,''),setProperty=lambda k,v:props.__setitem__(k,v))
        waits=[]
        def wait(delay):
            waits.append(delay)
            if len(waits)==4:props['nuvio.playback.started']='request'
            return False
        monitor=SimpleNamespace(abortRequested=lambda:False,waitForAbort=wait)
        session=importlib.import_module('resources.lib.session_store');subs=importlib.import_module('resources.lib.nuvio_subtitles')
        ctx={'playback_uid':'uid','nuvio_request_id':'request','nuvio_subtitle_language':'Croatian'}
        with mock.patch.object(post.xbmc,'Monitor',return_value=monitor),mock.patch.object(post,'_window',return_value=home),mock.patch.object(post,'_player_has_real_media',return_value=True),mock.patch.object(session,'load_session',return_value={'playback_uid':'uid'}),mock.patch.object(subs,'auto_apply',return_value=True) as apply:
            post.run_job({'ctx':ctx});apply.assert_called_once();self.assertEqual(len(waits),4)
        self.assertEqual(props['nuvio.subtitle.status'],'Applied')
    def test_old_job_exits_before_applying_to_replacement_movie(self):
        session=importlib.import_module('resources.lib.session_store');subs=importlib.import_module('resources.lib.nuvio_subtitles')
        monitor=SimpleNamespace(abortRequested=lambda:False,waitForAbort=lambda delay:False)
        home=SimpleNamespace(getProperty=lambda key:'',setProperty=lambda *a:None)
        with mock.patch.object(post.xbmc,'Monitor',return_value=monitor),mock.patch.object(post,'_window',return_value=home),mock.patch.object(session,'load_session',return_value={'playback_uid':'new'}),mock.patch.object(subs,'auto_apply') as apply:
            post.run_job({'ctx':{'playback_uid':'old','nuvio_request_id':'old-request','nuvio_subtitle_language':'hr'}})
        apply.assert_not_called()


class NativeSeeking(unittest.TestCase):
    def test_upgrade_restores_previous_settings_and_removes_only_owned_keymap(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);keys=root/'keymaps/nuvio-playback.xml';keys.parent.mkdir();keys.write_text('<!-- Nuvio owned playback keys --><keymap/>')
            previous={'videoplayer.seeksteps':[-30,-10,10,30],'videoplayer.seekdelay':750}
            (root/'nuvio_seek_backup.json').write_text(json.dumps(previous));values=dict(seek.VALUES)
            def rpc(method,**params):
                if method=='Settings.GetSettingValue':return {'value':values[params['setting']]}
                values[params['setting']]=params['value'];return True
            import xbmcvfs
            with mock.patch.object(seek,'profile_path',return_value=folder),mock.patch.object(seek,'rpc',side_effect=rpc),mock.patch.object(xbmcvfs,'translatePath',return_value=str(keys)),mock.patch.object(seek.xbmc,'executebuiltin') as builtin:
                seek.apply();seek.apply()
                self.assertEqual(values,previous);self.assertFalse(keys.exists());builtin.assert_called_once_with('Action(ReloadKeymaps)')
    def test_user_changed_seek_settings_and_unowned_keymap_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);keys=root/'keys.xml';keys.write_text('<keymap>user</keymap>')
            (root/'nuvio_seek_backup.json').write_text(json.dumps({'videoplayer.seekdelay':750}))
            import xbmcvfs
            with mock.patch.object(seek,'profile_path',return_value=folder),mock.patch.object(seek,'rpc',return_value={'value':500}) as rpc,mock.patch.object(xbmcvfs,'translatePath',return_value=str(keys)):
                seek.apply();self.assertEqual(rpc.call_count,1);self.assertEqual(keys.read_text(),'<keymap>user</keymap>')


if __name__=='__main__':unittest.main()
