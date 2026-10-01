"""Real failure boundaries introduced by remote playback and cancelled UI work."""
import importlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import frontend_test_support
frontend_test_support.install()
local=importlib.import_module('resources.lib.continue_local')
simkl=importlib.import_module('resources.lib.simkl')
companion=importlib.import_module('resources.lib.companion')
store=local.db
ui=importlib.import_module('nuvio_ui.playback')
models=importlib.import_module('resources.lib.title_details')

class Progress(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        for p in (mock.patch.object(store,'DB_PATH',str(Path(temp.name)/'progress.db')),mock.patch.object(store,'_DB_READY',False),mock.patch.object(simkl,'enabled',return_value=True),mock.patch.object(simkl,'token_data',return_value={'access_token':'test-account'}),mock.patch.object(simkl,'_SCROBBLE_RETRY_AT',0)):
            p.start();self.addCleanup(p.stop)
        self.ctx={'canonical_id':'tt123','video_id':'tt123:1:1','media_type':'series','season':1,'episode':1,'imdb_id':'tt123','duration_ms':1000000,'title':'Fixture'}
    def test_local_last_50_are_durable_and_do_not_store_playback_secrets(self):
        with mock.patch.object(simkl,'queue_progress'):
            for i in range(53):local.save(dict(self.ctx,canonical_id='tt%d'%i,stream_url='secret',token='secret'),120,1000)
        rows=local.recent();self.assertEqual(len(rows),50);self.assertEqual(rows[0]['canonical_id'],'tt52')
        self.assertFalse(any('secret' in json.dumps(r) for r in rows))
    def test_new_local_resume_survives_stale_remote_watched_state(self):
        home=importlib.import_module('resources.lib.home_data');watched=importlib.import_module('resources.lib.simkl_watched');nextup=importlib.import_module('resources.lib.watch_nextup')
        local.save(self.ctx,121,1000)
        with mock.patch.object(watched,'snapshot',return_value={'items':{}}),mock.patch.object(watched,'is_episode_watched',return_value=True),mock.patch.object(nextup,'augment',side_effect=lambda rows:rows):
            rows=home.continue_shelf()['rows']
        self.assertEqual(rows[0]['target']['resume_seconds'],121)
    def test_newer_remote_completion_hides_only_the_matching_local_episode(self):
        home=importlib.import_module('resources.lib.home_data');watched=importlib.import_module('resources.lib.simkl_watched');nextup=importlib.import_module('resources.lib.watch_nextup')
        local.save(self.ctx,121,1000)
        entry={'episodes':['1:1','1:2'],'episode_watched_at':{'1:1':time.time()+100}}
        with mock.patch.object(watched,'snapshot',return_value={'items':{'series|tt123':entry}}),mock.patch.object(nextup,'augment',side_effect=lambda rows:rows):
            rows=home.continue_shelf()['rows']
        self.assertFalse(any(r.get('target',{}).get('canonical_id')=='tt123' for r in rows))
        entry['episode_watched_at']={'1:2':time.time()+100}
        with mock.patch.object(watched,'snapshot',return_value={'items':{'series|tt123':entry}}),mock.patch.object(nextup,'augment',side_effect=lambda rows:rows):
            self.assertEqual(home.continue_shelf()['rows'][0]['target']['video_id'],'tt123:1:1')
    def test_80_to_94_percent_uses_pause_and_95_uses_stop(self):
        for position,action in [(800000,'pause'),(940000,'pause'),(950000,'stop')]:
            simkl.queue_progress(self.ctx,position,'stop')
            with mock.patch.object(simkl,'_request',return_value={}) as send:self.assertEqual(simkl.flush_progress(),1)
            self.assertEqual(send.call_args.args[0],'/scrobble/'+action)
    def test_outro_completion_stays_complete_on_later_heartbeat(self):
        ctx=dict(self.ctx,nuvio_completed_by_user=True)
        with mock.patch.object(companion,'_refresh_cw_containers'),mock.patch.object(companion,'_invalidate_nextup_cache'):
            companion._save_local_progress(ctx,700000,1000000)
            companion._save_local_progress(ctx,702000,1000000)
        self.assertEqual(local.recent()[0]['percent'],100)
        with mock.patch.object(simkl,'_request',return_value={}) as send:simkl.flush_progress()
        self.assertEqual(send.call_args.args[1]['progress'],100)
    def test_failed_sync_remains_durable_and_retries_later(self):
        simkl.queue_progress(self.ctx,120000)
        with mock.patch.object(simkl,'_request',side_effect=OSError):self.assertEqual(simkl.flush_progress(),0)
        simkl._SCROBBLE_RETRY_AT=0
        with mock.patch.object(simkl,'_request',return_value={}) as send:self.assertEqual(simkl.flush_progress(),1)
        self.assertEqual(send.call_args.args[1]['episode'],{'season':1,'number':1})
    def test_starting_next_episode_does_not_erase_pending_completion(self):
        local.save(self.ctx,750,1000,finished=True)
        local.save(dict(self.ctx,episode=2,video_id='tt123:1:2'),120,1000)
        with mock.patch.object(simkl,'_request',return_value={}) as send:
            self.assertEqual(simkl.flush_progress(),2)
        self.assertEqual([c.args[0] for c in send.call_args_list],['/scrobble/stop','/scrobble/pause'])
    def test_manual_mark_watched_removes_local_resume_and_pending_partial(self):
        local.save(self.ctx,120,1000)
        local.complete_matching(['tt123'],'series','episode',1,1)
        self.assertEqual(local.recent()[0]['event_type'],'watched')
        with mock.patch.object(simkl,'_request') as send:
            self.assertEqual(simkl.flush_progress(),0);send.assert_not_called()
    def test_account_switch_never_sends_another_accounts_queue(self):
        simkl.queue_progress(self.ctx,120000)
        with mock.patch.object(simkl,'token_data',return_value={'access_token':'second'}),mock.patch.object(simkl,'_request') as send:
            self.assertEqual(simkl.flush_progress(),0);send.assert_not_called()
    def test_sync_reply_does_not_delete_newer_local_event(self):
        simkl.queue_progress(self.ctx,120000)
        def send(*args,**kwargs):simkl.queue_progress(self.ctx,130000)
        with mock.patch.object(simkl,'_request',side_effect=send):simkl.flush_progress()
        with mock.patch.object(simkl,'_request',return_value={}) as send:simkl.flush_progress()
        self.assertEqual(send.call_args.args[1]['progress'],13)
    def test_delayed_reporter_never_overwrites_a_newer_local_stop(self):
        local.save(self.ctx,140,1000)
        with mock.patch.object(simkl,'_request',return_value={}) as send:
            companion.SimklReporter().progress(self.ctx,80000)
        self.assertEqual(send.call_args.args[1]['progress'],14)
    def test_true_remote_partial_import_has_percent_resume_not_invented_seconds(self):
        data=[{'progress':42.5,'paused_at':'2026-09-29T12:00:00.000Z','type':'episode','show':{'title':'Show','ids':{'imdb':'tt123'}},'episode':{'season':1,'episode':2}}]
        with mock.patch.object(simkl,'authorized',return_value=True),mock.patch.object(simkl,'_request',return_value=data):simkl.sync_playback_progress()
        row=store.list_continue_items()[0];self.assertEqual(row['percent'],42.5);self.assertEqual(row['position'],0)
        self.assertEqual(row['video_id'],'tt123:1:2')
    def test_active_adaptive_video_wins_over_unresolved_plugin_path(self):
        p=companion.CompanionPlayer()
        with mock.patch.object(p,'_current_playing_file',return_value='plugin://plugin.video.nuviohub/?action=play'),mock.patch.object(p,'isPlayingVideo',return_value=True,create=True):
            self.assertTrue(p._player_looks_active(require_real_media=True))
    def test_late_av_start_restarts_timed_out_probe(self):
        p=companion.CompanionPlayer();p.ctx=dict(self.ctx,playback_uid='uid',nuvio_request_id='req');p._active_playback_uid='uid';p._foreign_active=False;p._started_probe_pending=False
        item=SimpleNamespace(getProperty=lambda key:'req' if key=='nuvio.request' else '')
        with mock.patch.object(companion,'load_session',return_value=p.ctx),mock.patch.object(p,'getPlayingItem',return_value=item,create=True),mock.patch.object(p,'_start_progress_heartbeat') as restart:
            p.onAVStarted();restart.assert_called_once()
    def test_resume_click_reads_final_stop_commit_instead_of_opening_snapshot(self):
        details=importlib.import_module('nuvio_ui.details')
        win=object.__new__(details.Details);win._metadata_pending=False;win._metadata_error=False
        win.meta={'id':'ttmovie','type':'movie'}
        win.context={'resume_seconds':110,'nuvio_refresh_local_resume':True}
        win.close=mock.Mock()
        local.save({'canonical_id':'ttmovie','media_type':'movie','video_id':'ttmovie'},124,600)
        with mock.patch.object(details,'choose_stream',return_value=True) as choose:win._play()
        self.assertEqual(choose.call_args.args[1]['resume_seconds'],124)

class SourcesAndMetadata(unittest.TestCase):
    def test_background_workers_can_close_and_restart_with_reused_invoker(self):
        pool=ui.JobPool()
        try:
            self.assertEqual(pool.submit(lambda:1).result(timeout=1),1)
            pool.shutdown();self.assertIsNone(pool.pool)
            self.assertEqual(pool.submit(lambda:2).result(timeout=1),2)
        finally:pool.shutdown()
    def test_badges_normalize_stylized_text_without_missing_font_symbols(self):
        row={'name':'⚡ 𝟒𝐊 HEVC 🇭🇷','title':'Dolby Vision · REMUX 18 GB'}
        self.assertEqual(ui.plain_label(row['name']),'4K HEVC')
        self.assertEqual(ui.source_badges(row),['4K','Dolby Vision','HEVC','Remux','Cached','HR'])
    def test_episode_uses_own_plot_before_season_and_series(self):
        meta={'description':'Series','seasons':[{'number':1,'overview':'Season'}]}
        self.assertEqual(models.episode_plot({'season':1,'plot':'Episode'},meta),'Episode')
        self.assertEqual(models.episode_plot({'season':1},meta),'Season')
        self.assertEqual(models.episode_plot({'season':2},meta,'Fetched season'),'Fetched season')
    def test_nested_provider_plot_is_never_replaced_by_season_fallback(self):
        episode={'season':1,'description':'   ','app_extras':{'synopsis':'Specific episode'}}
        self.assertEqual(models.episode_description(episode),'Specific episode')
        self.assertEqual(models.episode_plot(episode,{'description':'Whole series'},'Season'),'Specific episode')
    def test_fetched_season_is_used_without_inventing_an_episode_synopsis(self):
        episode={'season':2}
        meta={'description':'Whole series','nuvio_season_overviews':{'2':'Second season'}}
        self.assertEqual(models.episode_plot(episode,meta),'Second season')
        self.assertEqual(models.episode_description(episode),'')
    def test_next_episode_does_not_skip_a_future_episode_to_later_season(self):
        meta={'id':'tt1','videos':[{'id':'a','season':1,'episode':1},{'id':'b','season':1,'episode':2,'released':'2999-01-01'},{'id':'c','season':2,'episode':1}]}
        self.assertIsNone(models.next_episode(meta,'a'))
    def test_person_credits_include_directed_movies_and_tv_without_duplicates(self):
        tmdb=importlib.import_module('resources.lib.tmdb_direct');home=importlib.import_module('resources.lib.home_data');api=importlib.import_module('resources.lib.backend_api')
        data={'cast':[{'id':1,'media_type':'movie','title':'One'}],'crew':[{'id':2,'media_type':'tv','name':'Two'},{'id':1,'media_type':'movie','title':'One'}]}
        with mock.patch.object(tmdb,'_api_key',return_value='fixture-key'),mock.patch.object(tmdb,'_request',return_value=data),mock.patch.object(home,'media_card',side_effect=lambda row,*args:row),mock.patch.object(api,'provider',return_value={}):rows=models.person_titles({'name':'Test','tmdb_id':98765})
        self.assertEqual([r['type'] for r in rows],['movie','series'])
    def test_people_catalogs_work_without_a_separate_tmdb_key(self):
        tmdb=importlib.import_module('resources.lib.tmdb_direct');home=importlib.import_module('resources.lib.home_data');api=importlib.import_module('resources.lib.backend_api');client=importlib.import_module('resources.lib.nuviohub.client')
        source={'id':'people-provider','manifest':{'catalogs':[{'id':'people_search.'+kind,'type':kind,'extra':[{'name':'search','isRequired':True}]} for kind in ('movie','series')]}}
        def fetch(source,kind,catalog,**kwargs):
            self.assertEqual(kwargs['extra'],{'search':'Person fixture'})
            return {'metas':[{'id':'tt-'+kind,'type':kind,'name':'Credit'}]}
        with mock.patch.object(tmdb,'_api_key',return_value=''),mock.patch('resources.lib.metadata_providers.enabled',return_value=[source]),mock.patch.object(client,'fetch_catalog',side_effect=fetch),mock.patch.object(home,'media_card',side_effect=lambda row,*args:row):
            rows=models.person_titles({'name':'Person fixture'})
        self.assertEqual({row['type'] for row in rows},{'movie','series'})


class Trailers(unittest.TestCase):
    def test_old_preview_does_not_stat_a_later_remote_movie(self):
        preview=importlib.import_module('nuvio_ui.home_trailers')
        player=preview.PreviewPlayer();player.token='old-preview';player.isPlayingVideo=lambda:True
        player.getPlayingItem=mock.Mock();player.stop=mock.Mock();player.cancel()
        with mock.patch.object(preview.xbmcgui,'Window',return_value=SimpleNamespace(getProperty=lambda key:'')):
            player.onAVStarted();self.assertFalse(player.owns())
        player.getPlayingItem.assert_not_called();player.stop.assert_not_called()
    def setUp(self):
        self.cache=importlib.import_module('resources.lib.trailer_cache')
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        for p in (mock.patch.object(self.cache,'profile_path',return_value=temp.name),mock.patch.object(self.cache,'_MISSES',{})):
            p.start();self.addCleanup(p.stop)
    def response(self,data):
        r=io.BytesIO(data);r.headers={'Content-Length':str(len(data))};return r
    def test_html_error_response_never_becomes_a_playable_trailer(self):
        with mock.patch.object(self.cache,'urlopen',return_value=self.response(b'<html>error</html>')):
            self.assertEqual(self.cache.prepare({'trailer':'https://example.test/bad.mp4'}),'')
    def test_incomplete_file_is_not_committed(self):
        response=self.response(b'0000ftyp'+b'0'*2048);response.headers['Content-Length']='9000'
        with mock.patch.object(self.cache,'urlopen',return_value=response):self.assertEqual(self.cache.prepare({'trailer':'https://example.test/a.mp4'}),'')
    def test_cancel_does_not_start_network_or_return_late_media(self):
        cancelled=threading.Event();cancelled.set()
        with mock.patch.object(self.cache,'urlopen') as request:
            self.assertEqual(self.cache.prepare({'trailer':'https://example.test/a.mp4'},cancelled),'');request.assert_not_called()
    def test_finished_clip_is_local_and_second_open_has_no_network(self):
        with mock.patch.object(self.cache,'urlopen',return_value=self.response(b'0000ftyp'+b'0'*2048)) as request:
            first=self.cache.prepare({'trailer':'https://example.test/a.mp4'})
            second=self.cache.prepare({'trailer':'https://example.test/a.mp4'})
        self.assertEqual(first,second);self.assertTrue(Path(first).is_file());request.assert_called_once()
