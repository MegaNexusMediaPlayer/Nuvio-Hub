import importlib,json,tempfile,unittest
from pathlib import Path
from unittest import mock
import kodi_stub,frontend_test_support
frontend_test_support.install()
watched=importlib.import_module('resources.lib.simkl_watched')
remove=importlib.import_module('resources.lib.nuvio_uninstall')
play=importlib.import_module('nuvio_ui.playback')
trailers=importlib.import_module('resources.lib.trailer_support')

class Watched(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=mock.patch.object(watched,'_path',return_value=str(Path(self.tmp.name)/'watched.json'));p.start();self.addCleanup(p.stop)
        p=mock.patch.object(watched.simkl,'token_data',return_value={'access_token':'fake-account'});p.start();self.addCleanup(p.stop)
        watched._MEM.clear()
    def test_exact_episode_history_never_infers_gaps(self):
        data={'shows':[{'show':{'ids':{'imdb':'tt123','tmdb':9}},'status':'watching','last_watched':'S01E04','seasons':[{'number':1,'episodes':[{'number':1},{'number':4}]}]}]}
        result=watched.parse(data,'shows');entry=result['series|tt123']
        self.assertTrue(watched.is_episode_watched(entry,1,4));self.assertFalse(watched.is_episode_watched(entry,1,2));self.assertFalse(entry['watched'])
        self.assertEqual(entry,result['series|tmdb:9'])
    def test_manual_title_season_episode_have_distinct_payloads(self):
        for scope in ('title','season','episode'):
            with mock.patch.object(watched.simkl,'_request',return_value={'added':{'episodes':1}}) as req:
                watched.mark({'media_type':'series','imdb_id':'tt123','canonical_id':'tt123'},scope,2,3)
                node=req.call_args.kwargs['payload']['shows'][0]
                if scope=='title':self.assertNotIn('seasons',node)
                elif scope=='season':self.assertEqual(node['seasons'],[{'number':2}])
                else:self.assertEqual(node['seasons'],[{'number':2,'episodes':[{'number':3}]}])
    def test_failure_does_not_paint_a_false_watched_badge(self):
        for response in ({},{'added':{'movies':0}},{'added':{'movies':1},'not_found':{'movies':[{}]}}):
            with mock.patch.object(watched.simkl,'_request',return_value=response):
                with self.assertRaises(ValueError):watched.mark({'media_type':'movie','imdb_id':'tt123'})
        self.assertFalse(watched.snapshot()['items'])
    def test_mark_persists_and_is_scoped_to_current_account(self):
        with mock.patch.object(watched.simkl,'_request',return_value={'added':{'movies':1}}):
            watched.mark({'media_type':'movie','imdb_id':'tt123'})
        watched._MEM.clear();self.assertTrue(watched.state(watched.snapshot(),'movie','tt123')['watched'])
        with mock.patch.object(watched.simkl,'token_data',return_value={'access_token':'different'}):self.assertFalse(watched.snapshot()['items'])
    def test_failed_refresh_retains_previous_confirmed_status(self):
        watched.record({'media_type':'movie','imdb_id':'tt123'})
        with mock.patch.object(watched.simkl,'_request',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):watched.refresh(force=True)
        self.assertTrue(watched.state(watched.snapshot(),'movie','tt123')['watched'])
    def test_refresh_merges_exact_remote_titles_and_caches(self):
        def response(path,**kw):
            kind=path.split('/')[3]
            return {kind:[{'movie':{'ids':{'imdb':'tt9'}},'status':'completed'}] if kind=='movies' else []}
        with mock.patch.object(watched.simkl,'_request',side_effect=response) as req:
            watched.refresh();watched.refresh()
            self.assertEqual(req.call_count,3)
        self.assertTrue(watched.state(watched.snapshot(),'movie','tt9')['watched'])

class OtherFixes(unittest.TestCase):
    def test_fullscreen_source_has_size_even_when_title_is_long(self):
        self.assertEqual(play.source_size({'behaviorHints':{'videoSize':12500000000}}),'12.50 GB')
        self.assertEqual(play.source_size({'title':'long release\n12.5 GiB HDR'}),'12.5 GiB')
    def test_direct_preview_rejects_raw_youtube_page(self):
        self.assertEqual(trailers.selected_trailer({'trailer':'https://www.youtube.com/watch?v=abcdefghijk'},direct_only=True),'')
    def test_explicit_profile_purge_keeps_dependency_and_other_accounts(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for aid in ('plugin.video.nuviohub','script.nuvio','plugin.video.youtube','other.addon'):
                (root/aid).mkdir();(root/aid/'account.json').write_text('keep unless nuvio')
            remove.purge_bundle_profiles(root)
            self.assertFalse((root/'plugin.video.nuviohub').exists());self.assertTrue((root/'plugin.video.youtube/account.json').exists());self.assertTrue((root/'other.addon/account.json').exists())
