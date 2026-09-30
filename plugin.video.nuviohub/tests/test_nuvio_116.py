"""Regression coverage for real playback ownership and title interactions."""
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import frontend_test_support
frontend_test_support.install()
models=importlib.import_module('resources.lib.title_details')
plugin=importlib.import_module('resources.lib.plugin')
companion=importlib.import_module('resources.lib.companion')
details=importlib.import_module('nuvio_ui.details')
play=importlib.import_module('nuvio_ui.playback')
backend=importlib.import_module('resources.lib.backend_api')


class TitleModels(unittest.TestCase):
    def test_specials_are_last_and_numeric_seasons_sort_numerically(self):
        meta={'videos':[None,{},*({'id':str(i),'season':i,'episode':'1'} for i in ('0','10','2','1'))]}
        self.assertEqual(models.seasons(meta),[1,2,10,0])
        self.assertEqual(models.season_label(0),'Specials')
        self.assertEqual(len(models.episodes(meta,0)),1)

    def test_aiometadata_photos_directors_cast_writers_and_missing_art(self):
        m={'cast':['fallback'],'app_extras':{'directors':[{'name':'Director','character':'Director','photo':'https://img/director.jpg'}], 'cast':[{'name':'Actor','character':'Role','photo':'/cast.jpg'}], 'writers':['Writer']}}
        value=models.normalize_people_art(m,{'base_url':'https://provider/config'})['nuvio_people']
        self.assertEqual([p['role'] for p in value],['Director','Role','Writer'])
        self.assertEqual(value[1]['photo'],'https://provider/cast.jpg')
        self.assertEqual(value[2]['photo'],'')

    def test_related_uses_advertised_genre_and_excludes_self_duplicates_other_type(self):
        source={'id':'metadata','manifest':{'catalogs':[{'id':'genre-movies','type':'movie','extra':[{'name':'genre','options':['Drama']}]}]}}
        rows=[{'id':'tt1','name':'Self'},{'id':'tt2','name':'Related','genres':['Drama']},{'id':'tt2','name':'Duplicate'},{'id':'tt3','name':'Wrong type','type':'series'}]
        client=importlib.import_module('resources.lib.dexhub.client')
        tmdb=importlib.import_module('resources.lib.tmdb_direct')
        with mock.patch.object(backend,'provider',return_value=source),mock.patch.object(tmdb,'_api_key',return_value=''),mock.patch.object(client,'fetch_catalog',return_value={'metas':rows}) as fetch:
            result=models.related({'id':'tt1','type':'movie','genres':['Drama']})
        self.assertEqual([r['target']['canonical_id'] for r in result],['tt2'])
        self.assertEqual(fetch.call_args.kwargs['extra'],{'genre':'Drama'})

    def test_info_on_continue_episode_does_not_start_playback(self):
        meta={'id':'tt1','type':'series','videos':[{'id':'tt1:0:1','season':0,'episode':1,'description':'Special plot'}]}
        ctx={'canonical_id':'tt1','media_type':'series','video_id':'tt1:0:1','resume_seconds':90,'details_view':'info'}
        with mock.patch.object(play,'job',return_value=meta),mock.patch.object(details,'show_info') as info,mock.patch.object(details,'choose_stream') as choose:
            details.open_context(ctx)
        self.assertEqual(info.call_args.args[1]['description'],'Special plot')
        choose.assert_not_called()

    def test_manual_picker_overrides_autoplay_without_mutating_setting(self):
        addon=mock.Mock();addon.getSetting.return_value='true'
        with mock.patch.object(play.xbmcaddon,'Addon',return_value=addon),mock.patch.object(play,'job',return_value=({'id':'provider'},[{'url':'https://stream/one'}])),mock.patch.object(play,'select_source',return_value=-1) as picker,mock.patch.object(backend,'queue_playback') as queue:
            self.assertFalse(play.play({'id':'tt1','type':'movie'},{'force_manual':True}))
        picker.assert_called_once();queue.assert_not_called();addon.setSetting.assert_not_called()

    def test_context_menu_cancel_is_noop_and_manual_keeps_exact_episode(self):
        dialog=mock.Mock()
        context={'canonical_id':'tt1','media_type':'series','video_id':'tt1:2:3','season':2,'episode':3,'resume_seconds':77}
        with mock.patch.object(details,'context_choice',side_effect=['','manual']),mock.patch.object(details,'open_context',return_value='playing') as open_:
            self.assertEqual(details.context_menu(context),'');open_.assert_not_called()
            self.assertEqual(details.context_menu(context),'playing')
        sent=open_.call_args.args[0]
        self.assertTrue(sent['force_manual']);self.assertEqual(sent['video_id'],'tt1:2:3');self.assertEqual(sent['resume_seconds'],77)
        self.assertNotIn('force_manual',context)

    def test_play_uses_new_season_and_does_not_reuse_other_episode_resume(self):
        win=object.__new__(details.Details);win._metadata_pending=False;win._metadata_error=False
        win.meta={'id':'tt1','type':'series'};win.seasons=[1,2]
        win.context={'video_id':'tt1:1:1','resume_seconds':90,'resume_percent':3}
        win.episodes=[{'id':'tt1:1:1','season':1,'episode':1}]
        season_control=mock.Mock();season_control.getSelectedPosition.return_value=1
        ep_control=mock.Mock();ep_control.getSelectedPosition.return_value=0
        win.getControl=lambda cid:season_control if cid==501 else ep_control
        def select(index):win.episodes=[{'id':'tt1:2:1','season':2,'episode':1}]
        win._episodes=mock.Mock(side_effect=select);win.close=mock.Mock()
        with mock.patch.object(details,'choose_stream',return_value=True) as choose:win._play()
        ctx=choose.call_args.args[1]
        win._episodes.assert_called_once_with(1)
        self.assertEqual(ctx['video_id'],'tt1:2:1');self.assertNotIn('resume_seconds',ctx)


class PlaybackOwnership(unittest.TestCase):
    def test_home_uses_seconds_for_runtime_and_retains_special_season_zero(self):
        rows=[{'media_type':'series','canonical_id':'tt1','video_id':'tt1:0:1','title':'Special','season':0,'episode':1,'position':10,'duration':126},
              {'media_type':'movie','canonical_id':'tt2','video_id':'tt2','title':'Long movie','position':100,'duration':10800}]
        with mock.patch.object(plugin.playback_store,'list_continue_items',return_value=rows),mock.patch.object(plugin,'_tmdb_art_db',mock.Mock(get_meta_bundle_from_db=mock.Mock(return_value={}))),mock.patch.object(plugin,'_hub_catalog_entries',return_value=[]):
            result=plugin._home_payload()['continue']
        self.assertIn('2 min',result[0]['meta_line']);self.assertEqual(result[0]['target']['season'],0)
        self.assertIn('180 min',result[1]['meta_line'])

    def test_real_handoff_identity_reaches_service_and_arms_monitor(self):
        context={'media_type':'movie','canonical_id':'tt123','video_id':'tt123','title':'Movie','stream_url':'http://127.0.0.1/test.mp4','playback_uid':'real-handoff','playback_created_at':123,'nuvio_request_id':'request'}
        with mock.patch.object(plugin,'_source_picker_url_from_ctx',return_value=''),mock.patch.object(plugin,'_compute_next_episode_hint',return_value=None):
            saved=plugin._augment_session_ctx({},context,[])
        self.assertEqual(saved['playback_uid'],'real-handoff')
        player=companion.CompanionPlayer()
        player.getPlayingItem=mock.Mock(return_value=mock.Mock(getProperty=lambda key:''))
        player._current_playing_file=lambda:context['stream_url']
        with mock.patch.object(companion,'load_session',return_value=saved),mock.patch.object(companion,'get_reporter',return_value=None),mock.patch.object(companion,'_clear_tmdbh_handoff_flag'),mock.patch.object(player,'_publish_artwork_async'),mock.patch.object(player,'_apply_resume_async'),mock.patch.object(player,'_restore_switched_subtitle_async'),mock.patch.object(player,'_run_post_start_async'),mock.patch.object(player,'_schedule_next_episode_precache'),mock.patch.object(player,'_start_progress_heartbeat') as start:
            player.onPlayBackStarted()
        self.assertFalse(player._foreign_active);start.assert_called_once();self.assertEqual(player.ctx['canonical_id'],'tt123')

    def test_new_session_resets_previous_movie_clock(self):
        p=companion.CompanionPlayer();p._last_position_ms=900000;p._last_duration_ms=1000000
        p._current_playing_file=lambda:'new.mp4'
        with mock.patch.object(companion,'load_session',return_value={'playback_uid':'new'}),mock.patch.object(companion,'get_reporter',return_value=None):p._refresh_context()
        self.assertEqual(p._last_position_ms,0);self.assertEqual(p._last_duration_ms,0)

    def test_same_url_restart_after_stop_is_a_new_session(self):
        import time
        p=companion.CompanionPlayer()
        p._last_started_file='http://fixture/movie.mp4';p._last_started_at=time.time()
        p._current_playing_file=lambda:p._last_started_file
        p.getPlayingItem=mock.Mock(return_value=mock.Mock(getProperty=lambda key:''))
        pending={'playback_uid':'new-after-stop','canonical_id':'tt1','stream_url':p._last_started_file}
        with mock.patch.object(companion,'load_session',return_value=pending),mock.patch.object(companion,'get_reporter',return_value=None),mock.patch.object(companion,'_clear_tmdbh_handoff_flag'),mock.patch.object(p,'_publish_artwork_async'),mock.patch.object(p,'_apply_resume_async'),mock.patch.object(p,'_restore_switched_subtitle_async'),mock.patch.object(p,'_run_post_start_async'),mock.patch.object(p,'_schedule_next_episode_precache'),mock.patch.object(p,'_start_progress_heartbeat') as start:
            p.onPlayBackStarted()
        start.assert_called_once();self.assertEqual(p.ctx['playback_uid'],'new-after-stop')

    def test_short_play_is_saved_before_thirty_second_mark(self):
        p=companion.CompanionPlayer();p.ctx={'canonical_id':'ttshort','media_type':'movie','playback_uid':'short'};p._active_playback_uid='short'
        p._player_looks_active=lambda **kw:True;p._current_playing_file=lambda:'short.mp4';p._report=mock.Mock()
        p._position_ms=mock.Mock(side_effect=[1000,2000,3000,4000,5000]);p._duration_ms=lambda:7200000
        class Event:
            def __init__(self):self.ticks=0
            def set(self):pass
            def is_set(self):return False
            def wait(self,seconds):self.ticks+=1;return self.ticks>5
        class Thread:
            def __init__(self,target,**kw):self.target=target
            def start(self):self.target()
        with mock.patch.object(companion.threading,'Event',Event),mock.patch.object(companion.threading,'Thread',Thread),mock.patch.object(companion,'_monitor'),mock.patch.object(companion,'_save_local_progress') as save:
            p._start_progress_heartbeat()
        self.assertEqual(save.call_count,1);self.assertEqual(save.call_args.args[1],3000)

    def test_preview_cannot_record_movie_progress(self):
        p=companion.CompanionPlayer()
        home=companion.xbmcgui.Window(10000);home.setProperty('nuvio.preview.active','1')
        try:
            with mock.patch.object(companion,'load_session',return_value={'playback_uid':'stale','canonical_id':'tt1'}),mock.patch.object(p,'_start_progress_heartbeat') as start:
                p.onPlayBackStarted()
            self.assertTrue(p._foreign_active);start.assert_not_called()
        finally:home.clearProperty('nuvio.preview.active')

    def test_local_record_is_visible_without_any_tracking_account(self):
        store=importlib.import_module('dexhub.playback_store')
        with tempfile.TemporaryDirectory() as temp,mock.patch.object(store,'DB_PATH',str(Path(temp)/'playback.db')),mock.patch.object(store,'_DB_READY',False),mock.patch.object(companion,'_invalidate_nextup_cache'),mock.patch.object(companion,'_refresh_cw_containers'):
            companion._save_local_progress({'media_type':'movie','canonical_id':'ttshort','video_id':'ttshort','title':'Short start'},4500,7200000)
            rows=store.list_continue_items()
            self.assertEqual(rows[0]['canonical_id'],'ttshort');self.assertEqual(rows[0]['position'],4.5)
            companion._save_local_progress({'media_type':'movie','canonical_id':'ttshort','video_id':'ttshort'},7200000,7200000,finished=True)
            self.assertEqual(store.list_continue_items(),[])
