"""6.0.1 regression cases: local playback, airing, subtitles and async UI."""
import importlib
import json
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
import frontend_test_support
frontend_test_support.install()
companion=importlib.import_module('resources.lib.companion')
store=importlib.import_module('nuviohub.playback_store')
watched=importlib.import_module('resources.lib.simkl_watched')
nextup=importlib.import_module('resources.lib.watch_nextup')
subs=importlib.import_module('resources.lib.nuvio_subtitles')
home=importlib.import_module('nuvio_ui.home_window')
tv=importlib.import_module('nuvio_ui.iptv')
preview=importlib.import_module('nuvio_ui.home_trailers')

class LocalProgress(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        for patch in (mock.patch.object(store,'DB_PATH',str(Path(temp.name)/'playback.db')),mock.patch.object(store,'_DB_READY',False),mock.patch.object(companion,'_invalidate_nextup_cache'),mock.patch.object(companion,'_refresh_cw_containers')):
            patch.start();self.addCleanup(patch.stop)
    def save(self,mid,position,clock,episode=None):
        ctx={'media_type':'series' if episode else 'movie','canonical_id':mid,'video_id':mid+(':1:%s'%episode if episode else ''),'title':mid}
        if episode:ctx.update(season=1,episode=episode)
        with mock.patch.object(store.time,'time',return_value=clock):companion._save_local_progress(ctx,position*1000,1000*1000)
    def test_fifteen_second_saves_move_recent_title_to_front(self):
        self.save('ttone',100,100);self.save('tttwo',120,110);self.save('ttone',115,120)
        rows=store.list_continue_items();self.assertEqual([r['canonical_id'] for r in rows],['ttone','tttwo'])
        self.assertEqual(rows[0]['updated_at'],120)
    def test_95_percent_marks_watched_locally_without_account(self):
        self.save('ttone',949,100);self.assertEqual(len(store.list_continue_items()),1)
        self.save('ttone',950,110);self.assertEqual(store.list_continue_items(),[])
        with mock.patch.object(watched,'_remote_snapshot',return_value={'items':{}}):
            self.assertTrue(watched.state(watched.snapshot(),'movie','ttone')['watched'])
    def test_completed_latest_episode_does_not_resurrect_old_episode(self):
        self.save('ttshow',100,100,1);self.save('ttshow',950,120,2)
        self.assertEqual(store.list_continue_items(),[])
        self.assertEqual(store.watched_snapshot()['series|ttshow']['episodes'],['1:2'])
    def test_slow_tracker_does_not_hold_local_clock_or_change_session(self):
        player=companion.CompanionPlayer();entered=threading.Event();release=threading.Event();seen=[]
        class Reporter:
            def started(self,ctx,pos):entered.set();release.wait(2);seen.append((ctx['playback_uid'],pos))
        player.ctx={'playback_uid':'old'};player.reporter=Reporter()
        try:
            with mock.patch.object(companion,'companion_enabled',return_value=True):player._report('started',1000)
            self.assertTrue(entered.wait(.5));player.ctx={'playback_uid':'new'}
            self.save('tttwo',120,120);self.assertEqual(len(store.list_continue_items()),1)
        finally:release.set();player._report_queue.join()
        self.assertEqual(seen,[('old',1000)])
    def test_nuvio_cloud_history_uses_the_same_95_percent_threshold(self):
        simkl=companion.simkl
        with mock.patch.object(simkl,'enabled',return_value=True),mock.patch.object(simkl,'authorized',return_value=True),mock.patch.object(simkl,'mark_watched_enabled',return_value=True),mock.patch.object(simkl,'watched_threshold_percent',return_value=85),mock.patch.object(simkl,'_request') as request:
            self.assertFalse(simkl.mark_watched_from_ctx({'nuvio_request_id':'test','duration_ms':100000,'canonical_id':'tt1'},90000))
            request.assert_not_called()

class Airing(unittest.TestCase):
    def card(self,released,watched_episode=False,percent=100):
        meta={'name':'Show','videos':[{'id':'tt1:0:1','season':0,'episode':1,'released':released},{'id':'tt1:1:2','season':1,'episode':2,'released':released}]}
        history={'canonical_id':'tt1','season':1,'episode':1,'percent':percent}
        return nextup.next_card(meta,history,{'episodes':['1:2'] if watched_episode else []},date(2026,9,29))
    def test_tomorrow_promotes_only_unwatched_regular_episode(self):
        card=self.card('2026-09-30');self.assertEqual(card['tomorrow'],'1')
        self.assertEqual(card['target']['video_id'],'tt1:1:2');self.assertTrue(card['target']['details_view'])
        self.assertIsNone(self.card('2026-09-30',True))
    def test_unknown_date_does_not_invent_release_and_next_aired_requires_completion(self):
        self.assertIsNone(self.card(None));self.assertIsNone(self.card('2026-09-28',percent=20))
        self.assertEqual(self.card('2026-09-28')['airing_banner'],'Next episode')
    def test_new_release_survives_previous_completed_season_status(self):
        from datetime import datetime
        meta={'videos':[{'id':'tt1:1:2','season':1,'episode':2,'released':'2026-09-30'}]}
        history={'canonical_id':'tt1','season':1,'episode':1,'percent':100,'updated_at':datetime(2026,9,28).timestamp()}
        entry={'watched':True,'seasons':['1'],'episodes':['1:1']}
        self.assertEqual(nextup.next_card(meta,history,entry,date(2026,9,29))['tomorrow'],'1')
        self.assertEqual(nextup.next_card(meta,history,entry,date(2026,9,30))['airing_banner'],'Next episode')

class SubtitleSelection(unittest.TestCase):
    def test_language_choices_come_from_kodi_and_exclude_reserved_modes(self):
        rows=[{'label':v,'value':v} for v in ['none','forced_only','original','default','Croatian','Zulu','Abkhazian']]
        response={'result':{'settings':[{'id':'locale.subtitlelanguage','options':rows}]}}
        with mock.patch.object(subs.xbmc,'executeJSONRPC',return_value=json.dumps(response),create=True):
            self.assertEqual([r['value'] for r in subs.languages()],['Croatian','Zulu','Abkhazian'])
    def auto(self,manual=False,changed=False):
        session=importlib.import_module('resources.lib.session_store')
        player=mock.Mock();player.getPlayingItem.return_value.getProperty.return_value='request'
        window=mock.Mock();window.getProperty.side_effect=lambda key:'request' if key=='nuvio.playback.started' or (key=='nuvio.subtitle.manual' and manual) else ''
        context={'playback_uid':'uid','nuvio_request_id':'request','nuvio_subtitle_language':'Croatian'}
        rows=[{'lang':'English','id':'en'},{'lang':'Croatian','id':'01.release'},{'lang':'hrv','id':'02.release'}]
        with mock.patch.object(session,'load_session',side_effect=[{'playback_uid':'uid'},{'playback_uid':'other' if changed else 'uid'},{'playback_uid':'uid'}]),mock.patch.object(subs.xbmcgui,'Window',return_value=window),mock.patch.object(subs,'external_rows',return_value=rows) as search,mock.patch.object(subs,'prepare_selected',return_value='first.hr.srt') as download:
            result=subs.auto_apply(context,player)
        return result,player,search,download
    def test_first_matching_release_only_is_downloaded_and_enabled(self):
        result,player,search,download=self.auto();self.assertTrue(result)
        self.assertEqual(download.call_args.args[0]['id'],'01.release');self.assertEqual(download.call_count,1)
        player.setSubtitles.assert_called_once_with('first.hr.srt');player.showSubtitles.assert_called_once_with(True)
    def test_user_override_and_changed_playback_cancel_automatic_selection(self):
        for options in ({'manual':True},{'changed':True}):
            result,player,search,download=self.auto(**options);self.assertFalse(result)
            download.assert_not_called();player.setSubtitles.assert_not_called()

class AsyncUI(unittest.TestCase):
    def test_manual_cloud_watched_change_invalidates_live_continue_row(self):
        with mock.patch.object(watched,'snapshot',return_value={'items':{}}),mock.patch.object(watched.simkl,'_ids_from_ctx',return_value={'imdb':'tt1'}),mock.patch.object(watched.simkl,'_write_json',return_value=True),mock.patch.object(watched,'_invalidate_view') as invalidate:
            watched.record({'media_type':'movie','canonical_id':'tt1'})
        invalidate.assert_called_once()
    def test_continue_enrichment_closes_executor_on_kodi_python38(self):
        from concurrent import futures
        enrich=importlib.import_module('resources.lib.continue_metadata');calls=[]
        class Pool:
            def __init__(self,max_workers):pass
            def submit(self,fn,*args):
                f=futures.Future();f.set_result(fn(*args));return f
            def shutdown(self,wait=True):calls.append(wait)
        row={'title':'Title','poster':'poster','target':{'canonical_id':'tt1'}}
        with mock.patch.object(futures,'ThreadPoolExecutor',Pool):self.assertEqual(enrich.enrich([row])[0]['title'],'Title')
        self.assertEqual(calls,[False]);self.assertEqual(enrich.metadata_identity({'tmdb_id':'123'}),('movie','tmdb:123'))
    def test_trailer_retains_details_until_modal_playback_returns(self):
        details=importlib.import_module('nuvio_ui.details');trailers=importlib.import_module('nuvio_ui.trailers')
        w=details.Details(meta={'id':'tt1'});w.close=mock.Mock()
        with mock.patch.object(trailers,'show_trailer') as show:
            w.onClick(103);w.drain_events();show.assert_called_once_with(w.meta);w.close.assert_not_called()
    def test_stopped_preview_does_not_ask_kodi_to_stat_the_old_stream(self):
        p=preview.PreviewPlayer();p.token='preview';p.isPlayingVideo=lambda:False;p.getPlayingItem=mock.Mock()
        self.assertFalse(p.owns());p.getPlayingItem.assert_not_called()
    def test_cached_preview_is_owned_by_path_and_token_without_playing_item_lookup(self):
        p=preview.PreviewPlayer();p.token='preview';p.isPlayingVideo=lambda:True
        window=mock.Mock();window.getProperty.return_value='preview';item=mock.Mock();item.getProperty.return_value=''
        p.path='local-preview.mp4';p.getPlayingFile=lambda:'local-preview.mp4';p.getPlayingItem=mock.Mock()
        with mock.patch.object(preview.xbmcgui,'Window',return_value=window):
            self.assertTrue(p.owns());p.getPlayingFile=lambda:'real-movie.mp4'
            self.assertFalse(p.owns());p.getPlayingItem.assert_not_called()
    def test_stale_continue_result_cannot_overwrite_fresh_progress(self):
        w=home.HomeWindow();w._progress_revision='new';w._last_progress_check=time.monotonic();w._set_rows=mock.Mock();w._shelves=[{'rows':[]}]
        w._updates.put((w._generation,0,[{'title':'stale'}],'old'));w.drain_updates();w._set_rows.assert_not_called()
    def test_channel_cache_avoids_repeated_bulk_epg_fetch_and_refresh_bypasses_cache(self):
        tv._CHANNEL_CACHE.clear()
        with mock.patch.object(tv,'rpc',return_value={'channels':[{'channelid':1,'channelnumber':1,'thumbnail':'logo.png'}]}) as rpc:
            tv.channels(99);tv.channels(99);self.assertEqual(rpc.call_count,1)
            self.assertNotIn('broadcastnow',rpc.call_args.args[1]['properties'])
            tv.channels(99,refresh=True);self.assertEqual(rpc.call_count,2)
        tv._CHANNEL_CACHE.clear()
    def test_fast_category_changes_keep_last_request(self):
        with mock.patch.object(tv,'current_id',return_value=None):w=tv.IPTV(rows=[])
        self.addCleanup(w._pool.shutdown,wait=True);w.setProperty=mock.Mock();w._submit=mock.Mock(side_effect=[False,True])
        w._request_group(2);w._load_pending_group();w._request_group(3);w._load_pending_group()
        self.assertEqual(w._requested_group,3);self.assertEqual(w._submit.call_args.args[1],3);self.assertIsNone(w._pending_group)

if __name__=='__main__':unittest.main()
