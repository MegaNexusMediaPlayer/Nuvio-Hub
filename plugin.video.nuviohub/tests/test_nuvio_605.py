"""Slow metadata must not hold navigation; preview ownership and portable labels."""
import importlib
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import tempfile
import threading
import unittest
import frontend_test_support
frontend_test_support.install()
meta=importlib.import_module('nuvio_ui.browse_meta')
ui=importlib.import_module('nuvio_ui.playback')
details=importlib.import_module('nuvio_ui.details')
home=importlib.import_module('nuvio_ui.home_window')
preview=importlib.import_module('nuvio_ui.home_trailers')
catalog=importlib.import_module('nuvio_ui.catalog')

class ProgressiveDetails(unittest.TestCase):
    def setUp(self):
        import tempfile
        from resources.lib import browse_cache
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        patch=mock.patch.object(browse_cache,'_CACHE',browse_cache.Cache(Path(temp.name)/'cache.db'));patch.start();self.addCleanup(patch.stop)
        meta.clear(persistent=True);self.addCleanup(meta.clear)
        self.ctx={'media_type':'movie','canonical_id':'tt605'}
        self.row={'title':'Already visible','plot':'Catalog synopsis','poster':'local.jpg','fanart':'back.jpg'}
    def test_click_constructs_details_without_waiting_for_metadata(self):
        class Window:
            def __init__(win,*args,**kwargs):
                win.meta=kwargs['meta'];win.context=kwargs['context'];win._metadata_pending=kwargs['metadata_pending'];win.action=''
                self.assertEqual(win.meta['name'],self.row['title']);self.assertEqual(win.meta['description'],self.row['plot']);self.assertTrue(win._metadata_pending)
            def doModal(win):pass
            def close(win):pass
        with mock.patch.object(details,'Details',Window),mock.patch.object(meta.backend_api,'metadata',side_effect=AssertionError('UI made a blocking request')):
            self.assertEqual(details.open_context(self.ctx,row=self.row),'')
    def test_single_flight_and_cached_metadata_are_isolated_copies(self):
        entered=threading.Event();release=threading.Event()
        def load(*args):entered.set();release.wait(2);return {'id':'tt605','videos':[{'id':'one'}]}
        with mock.patch.object(meta.backend_api,'metadata',side_effect=load) as fetch:
            try:
                one=meta.request(self.ctx);self.assertTrue(entered.wait(1));two=meta.request(self.ctx);self.assertIs(one,two)
            finally:release.set()
            one.result(2);meta.cached(self.ctx)['videos'][0]['id']='mutated'
            self.assertEqual(meta.request(self.ctx).result()['videos'][0]['id'],'one');fetch.assert_called_once()
    def test_settings_clear_rejects_late_old_provider_cache_write(self):
        entered=threading.Event();release=threading.Event()
        def load(*args):entered.set();release.wait(2);return {'id':'old'}
        with mock.patch.object(meta.backend_api,'metadata',side_effect=load):
            future=meta.request(self.ctx);self.assertTrue(entered.wait(1));meta.clear();release.set();future.result(2)
        self.assertIsNone(meta.cached(self.ctx))
    def test_cache_bounds_titles_and_does_not_retain_a_failed_request(self):
        with mock.patch.object(meta.backend_api,'metadata',side_effect=lambda mt,mid:{'id':mid}):
            for n in range(34):meta.request(dict(self.ctx,canonical_id=str(n))).result(2)
        from resources.lib import browse_cache
        self.assertLessEqual(browse_cache.instance().bytes,browse_cache.RAM_LIMIT)
        self.assertIsNotNone(meta.cached(dict(self.ctx,canonical_id='33')))
        with mock.patch.object(meta.backend_api,'metadata',side_effect=ValueError('offline')):
            with self.assertRaises(ValueError):meta.request(self.ctx).result(2)
        with mock.patch.object(meta.backend_api,'metadata',return_value={'id':'retry'}):self.assertEqual(meta.request(self.ctx).result(2)['id'],'retry')
    def window(self,future):
        win=details.Details(meta=meta.seed(self.ctx,self.row),context=self.ctx,metadata_pending=True)
        win._metadata_job=future;win.setProperty=mock.Mock();win.getControl=lambda cid:mock.Mock();win.getFocusId=lambda:100
        return win
    def test_failure_keeps_page_open_and_play_retries_in_background(self):
        future=Future();future.set_exception(ValueError('offline'));win=self.window(future);win.tick()
        self.assertFalse(win.closed);self.assertTrue(win._metadata_error)
        retry=Future()
        with mock.patch.object(meta,'request',return_value=retry):win._play(manual=True)
        self.assertTrue(win._metadata_pending);self.assertTrue(win._after_metadata);self.assertIs(win._metadata_job,retry)
    def test_closed_page_cannot_be_repainted_by_late_result(self):
        future=Future();win=self.window(future);future.set_running_or_notify_cancel()
        with mock.patch.object(details.Dialog,'close'):win.close()
        future.set_result({'id':'other'});win.tick();win.setProperty.assert_not_called()
    def test_pending_play_runs_once_after_metadata_and_keeps_title(self):
        future=Future();win=self.window(future);win._play();win._play();win.onInit=mock.Mock();win._play=mock.Mock()
        future.set_result({'id':'tt605','type':'movie','runtime':'90 min'});win.tick();win.drain_events()
        self.assertEqual(win.meta['name'],'Already visible');win._play.assert_called_once_with(False)
    def test_recommendations_and_catalogs_cannot_hold_metadata_worker(self):
        release=threading.Event();workers=[ui._BACKGROUND.submit(lambda:release.wait(2))]+[ui._CATALOG.submit(lambda:release.wait(2)) for _ in range(2)]
        try:
            with mock.patch.object(meta.backend_api,'metadata',return_value={'id':'tt605'}):self.assertEqual(meta.request(self.ctx).result(.5)['id'],'tt605')
        finally:
            release.set()
            for f in workers:f.result(2)

class BrowseNavigation(unittest.TestCase):
    def test_collection_cache_separates_movies_series_and_search_filters(self):
        def shelf(kind,query):return {'path':'same','job':({'id':'p'},{'type':kind,'id':'catalog'}),'extra':{'search':query}}
        self.assertEqual(len({home.HomeWindow._shelf_key(shelf(mt,q)) for mt,q in [('movie','a'),('series','a'),('movie','b')]}),3)
    def test_home_prioritizes_focused_rows_and_does_not_queue_all_24(self):
        win=home.HomeWindow();win._shelves=[{'job':({},{}),'rows':[]} for _ in range(24)];win._pool=mock.Mock();win.getFocusId=lambda:7010
        win._queue_visible();win._queue_visible()
        self.assertEqual([call.args[1] for call in win._pool.submit.call_args_list],[10,11,12,0])
    def test_catalog_loading_does_not_consume_input_queue_and_back_cancels(self):
        future=Future();win=catalog.Catalog(params={});win.getControl=lambda cid:mock.Mock();win.setProperty=mock.Mock()
        with mock.patch.object(catalog.catalog_pages,'jobs_for',return_value=[{'done':False}]),mock.patch.object(catalog._CATALOG,'submit',return_value=future),mock.patch.object(catalog.Dialog,'close'):
            win.onInit();self.assertTrue(win._events.empty());win.onAction(importlib.import_module('nuvio_ui.dialog').Action(9))
        self.assertTrue(future.cancelled());self.assertFalse(win._alive)

class PreviewAndLabels(unittest.TestCase):
    def player(self):
        p=preview.PreviewPlayer();p.token='preview';p.path='/cache/clip.mp4';p.isPlayingVideo=lambda:True
        p.getPlayingItem=lambda:SimpleNamespace(getProperty=lambda key:'preview');p.getPlayingFile=lambda:'special://mapped/clip.mp4'
        return p
    def test_av_item_token_accepts_rewritten_path_but_never_another_movie(self):
        p=self.player()
        with mock.patch.object(preview.xbmcgui,'Window',return_value=SimpleNamespace(getProperty=lambda key:'preview')):
            p.onAVStarted();self.assertTrue(p.ready);self.assertTrue(p.owns())
            p.getPlayingFile=lambda:'https://movie/new.mkv';p.getPlayingItem=lambda:SimpleNamespace(getProperty=lambda key:'movie')
            p.onAVStarted();self.assertFalse(p.owns());self.assertFalse(p.ready)
    def test_translated_file_uri_matches_local_clip(self):
        self.assertEqual(preview.local_path('file:///tmp/trailer%20one.mp4'),preview.local_path('/tmp/trailer one.mp4'))
    def test_cancelled_resolution_is_not_cached_as_missing(self):
        controller=preview.Controller(mock.Mock());preview._CACHE.clear();row={'target':{'media_type':'movie','canonical_id':'tt605'},'trailer':'https://fixture/trailer.mp4'}
        cache=importlib.import_module('resources.lib.trailer_cache')
        with tempfile.NamedTemporaryFile() as clip,mock.patch.object(cache,'prepare',side_effect=['',clip.name]) as prepare:
            self.assertEqual(controller._resolve('key',row,False),'');self.assertEqual(controller._resolve('key',row,False),clip.name);self.assertEqual(prepare.call_count,2)
    def test_missing_cached_file_is_resolved_again(self):
        # 6.0.11: the preview cache key also carries the chosen trailer source.
        controller=preview.Controller(mock.Mock());preview._CACHE.clear();row={'target':{'media_type':'movie','canonical_id':'tt605'},'trailer':'https://fixture/trailer.mp4'}
        preview._CACHE[('movie','tt605',False,'youtube')]=(float('inf'),'/missing/clip.mp4')
        cache=importlib.import_module('resources.lib.trailer_cache')
        with mock.patch.object(cache,'prepare',return_value='fresh') as prepare:self.assertEqual(controller._resolve('key',row,False),'fresh');prepare.assert_called_once()
    def test_styled_badges_and_missing_font_letters_render_portable_text(self):
        row={'name':'🅰🅸🅾 ⚡ 𝟜ᴋ ᴅᴠ ᴅᴅ+ HEVC 🇭🇷','title':'čćžđš ꞯ𐌃 � □'}
        self.assertEqual(ui.plain_label(row['name']),'AIO 4K DV DD+ HEVC')
        self.assertEqual(ui.plain_label(row['title']),'čćžđš')
        self.assertEqual(ui.source_badges(row),['4K','Dolby Vision','DD+','HEVC','Cached','HR'])
        self.assertEqual(row['title'],'čćžđš ꞯ𐌃 � □')

class OptionalSettings(unittest.TestCase):
    def test_cancelled_native_install_returns_without_poll_or_error_dialog(self):
        setup=importlib.import_module('nuvio_ui.system_setup');remove=importlib.import_module('resources.lib.nuvio_uninstall')
        for aid in ('weather.openmeteo','plugin.video.youtube','pvr.iptvsimple'):
            with mock.patch.object(remove,'inventory',return_value={}),mock.patch.object(remove,'record_install') as record,mock.patch.object(setup.xbmc,'getCondVisibility',return_value=False),mock.patch.object(setup.xbmc,'executebuiltin') as builtin,mock.patch.object(setup.xbmc,'Monitor',side_effect=AssertionError('Cancel must not start a poll')),mock.patch.object(setup,'rpc') as rpc,mock.patch.object(setup.xbmcgui,'Dialog') as dialog:
                self.assertFalse(setup.ensure_addon(aid));builtin.assert_called_once_with('InstallAddon(%s)'%aid,True)
                rpc.assert_not_called();record.assert_not_called();dialog.assert_not_called()
    def test_successful_install_still_enables_and_records_owned_dependencies(self):
        setup=importlib.import_module('nuvio_ui.system_setup');remove=importlib.import_module('resources.lib.nuvio_uninstall')
        before={'old':{}};after=dict(before,new={})
        with mock.patch.object(remove,'inventory',side_effect=[before,after]),mock.patch.object(remove,'record_install') as record,mock.patch.object(setup.xbmc,'getCondVisibility',side_effect=[False,True]),mock.patch.object(setup.xbmc,'executebuiltin'),mock.patch.object(setup,'rpc') as rpc:
            self.assertTrue(setup.ensure_addon('new'));record.assert_called_once_with('new',before,after);rpc.assert_called_once_with('Addons.SetAddonEnabled',{'addonid':'new','enabled':True})
    def test_skipping_weather_does_not_change_provider_or_open_settings(self):
        setup=importlib.import_module('nuvio_ui.system_setup')
        with mock.patch.object(setup,'ensure_addon',return_value=False),mock.patch.object(setup,'rpc') as rpc,mock.patch.object(setup.xbmcaddon,'Addon') as addon,mock.patch.object(setup.xbmc,'executebuiltin') as builtin:
            setup.weather();rpc.assert_not_called();addon.assert_not_called();builtin.assert_not_called()
    def test_restored_window_waits_for_init_before_touching_controls(self):
        base=importlib.import_module('nuvio_ui.dialog');states=[]
        class Window(base.Dialog):
            def onInit(self):states.append('initialized')
        win=Window();win.show=mock.Mock();calls=[]
        def wait(delay):calls.append(delay);win.onInit();return False
        with mock.patch.object(base.xbmc,'Monitor',return_value=SimpleNamespace(waitForAbort=wait)):
            win.show_ready()
        self.assertTrue(win._xml_ready.is_set());self.assertEqual(states,['initialized']);self.assertEqual(calls,[.01])
    def test_settings_click_uses_displayed_rows_and_does_not_repeat_restored_refresh(self):
        page=importlib.import_module('nuvio_ui.settings_page');rows=mock.Mock(return_value=[page.item('One')]);win=page.SettingsPage(title='Test',rows=rows,choose=lambda i:None)
        win._rendered_rows=rows();win.getControl=lambda cid:SimpleNamespace(getSelectedPosition=lambda:0);win.refresh=mock.Mock()
        def child_restored(i):win._refresh_version+=1
        win.child=lambda fn,*a,**k:fn(*a,**k)  # 6.0.18: row actions run with the page hidden
        win.choose=child_restored;win.onClick(500);win.drain_events();rows.assert_called_once();win.refresh.assert_not_called()


class OptionalSetup(unittest.TestCase):
    def setUp(self):
        self.wizard=importlib.import_module('nuvio_ui.onboarding')
        self.values={};self.dialog=mock.Mock();self.dialog.select.return_value=-1
        addon=SimpleNamespace(getSetting=lambda k:self.values.get(k,''),setSetting=lambda k,v:self.values.__setitem__(k,v))
        for patch in (mock.patch.object(self.wizard,'ADDON',addon),mock.patch.object(self.wizard.xbmcgui,'Dialog',return_value=self.dialog),mock.patch.object(self.wizard.sync.Nuvio,'is_linked',return_value=False),mock.patch('resources.lib.simkl.authorized',return_value=False)):
            patch.start();self.addCleanup(patch.stop)
    def test_cancel_first_step_does_not_repeat_or_claim_completion(self):
        self.wizard.run();self.assertEqual(self.dialog.select.call_count,1)
        self.assertEqual(self.values.get('nuvio_setup_offered'),'true')
        self.assertNotEqual(self.values.get('nuvio_setup_v110_done'),'true')
        self.wizard.run();self.assertEqual(self.dialog.select.call_count,1)
    def test_old_connected_account_enters_home_without_setup(self):
        with mock.patch.object(self.wizard.sync.Nuvio,'is_linked',return_value=True),mock.patch.object(self.wizard.settings,'sign_in_nuvio') as signin:self.wizard.run()
        self.dialog.select.assert_not_called();signin.assert_not_called()
        self.assertEqual(self.values.get('nuvio_setup_offered'),'true')
    def test_old_partial_setup_and_provider_configuration_do_not_repeat(self):
        for saved in ({'nuvio_setup_v110_step':'2'},{'nuvio_metadata_provider':'saved-provider'},{'nuvio_streams_provider':'saved-streams'}):
            self.values.clear();self.values.update(saved);self.wizard.run()
            for key,value in saved.items():self.assertEqual(self.values[key],value)
        self.dialog.select.assert_not_called()
    def test_manual_wizard_remains_available_after_dismissal(self):
        self.values['nuvio_setup_offered']='true';self.wizard.run(force=True)
        self.dialog.select.assert_called_once();self.assertNotEqual(self.values.get('nuvio_setup_v110_done'),'true')
    def test_connected_account_step_opens_account_management(self):
        with mock.patch.object(self.wizard.sync.Nuvio,'is_linked',return_value=True):steps=self.wizard._steps()
        label,action=steps[0][1][0];self.assertIn('connected',label);self.assertIs(action,self.wizard.settings.accounts)

class SimklApplication(unittest.TestCase):
    def setUp(self):
        self.simkl=importlib.import_module('resources.lib.simkl')
        self.account=importlib.import_module('nuvio_ui.simkl_account')
        patch=mock.patch.object(self.simkl,'DEFAULT_CLIENT_ID','nuvio-public-id');patch.start();self.addCleanup(patch.stop)
    def test_old_client_override_cannot_create_another_legacy_pin(self):
        with mock.patch.object(self.simkl,'_setting',return_value=self.simkl.LEGACY_CLIENT_ID):self.assertEqual(self.simkl.client_id(),'nuvio-public-id')
    def test_old_token_keeps_original_client_while_new_pin_uses_nuvio(self):
        with mock.patch.object(self.simkl,'_setting',return_value=''),mock.patch.object(self.simkl,'token_data',return_value={'access_token':'old-test-token'}):
            self.assertEqual(self.simkl._headers(auth=True)['simkl-api-key'],self.simkl.LEGACY_CLIENT_ID)
            self.assertEqual(self.simkl._headers()['simkl-api-key'],'nuvio-public-id');self.assertTrue(self.simkl.needs_app_relink())
    def test_new_token_stores_issuing_client_and_honors_custom_app(self):
        with mock.patch.object(self.simkl,'_setting',return_value='custom-public-id'),mock.patch.object(self.simkl,'_write_json',return_value=True) as write:
            self.simkl.save_token({'access_token':'new-test-token'})
        value=write.call_args.args[1];self.assertEqual(value['client_id'],'custom-public-id')
        with mock.patch.object(self.simkl,'token_data',return_value=value),mock.patch.object(self.simkl,'_setting',return_value='changed-setting'):
            self.assertEqual(self.simkl._headers(auth=True)['simkl-api-key'],'custom-public-id')
    def test_cancel_reconnect_keeps_the_existing_account(self):
        dialog=mock.Mock();dialog.iscanceled.return_value=True
        with mock.patch.object(self.simkl,'authorized',return_value=True),mock.patch.object(self.account,'job',return_value={'user_code':'TEST'}),mock.patch.object(self.account.xbmcgui,'DialogProgress',return_value=dialog),mock.patch.object(self.simkl,'save_token') as save,mock.patch.object(self.simkl,'clear_token') as clear:
            self.assertFalse(self.account.link(replace=True));save.assert_not_called();clear.assert_not_called()
    def test_requests_identify_nuvio_and_preserve_query_without_public_token(self):
        from urllib.parse import parse_qs,urlsplit
        response=mock.MagicMock();response.__enter__.return_value.read.return_value=b'{}'
        with mock.patch.object(self.simkl,'_setting',return_value=''),mock.patch.object(self.simkl.urllib.request,'urlopen',return_value=response) as send:
            self.simkl._request('/oauth/pin?client_id=previous&limit=5')
        request=send.call_args.args[0];query=parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(query['client_id'],['nuvio-public-id']);self.assertEqual(query['app-name'],['nuvio-hub']);self.assertEqual(query['limit'],['5'])
        self.assertNotIn('Authorization',request.headers)

class PlaybackExitAndOrder(unittest.TestCase):
    def test_real_watch_timestamps_order_local_and_cloud_entries(self):
        data=importlib.import_module('resources.lib.home_data');local=importlib.import_module('resources.lib.continue_local');watched=importlib.import_module('resources.lib.simkl_watched');nextup=importlib.import_module('resources.lib.watch_nextup')
        def row(title,stamp,**extra):
            return dict(media_type='movie',canonical_id=title,video_id=title,title=title,position=120,duration=1000,percent=12,updated_at=stamp,**extra)
        local_rows=[row('Unabomber',300),row('F1',200),row('Jurassic',100),row('Completed',400,event_type='watched')]
        cloud=[row('Garfield',9000),row('ps:unknown',8000),row('Unabomber',10000),row('Completed',100)]
        cloud[2]['position']=345
        with mock.patch.object(local,'recent',return_value=local_rows),mock.patch.object(local.db,'list_continue_items',return_value=cloud),mock.patch.object(watched,'snapshot',return_value={}),mock.patch.object(nextup,'augment',side_effect=lambda rows:rows):
            result=data.continue_shelf()['rows']
        self.assertEqual([r['title'] for r in result],['Unabomber','Garfield','ps:unknown','F1','Jurassic'])
        self.assertEqual(result[0]['target']['resume_seconds'],345)

    def test_reopening_home_resets_continue_even_without_new_revision(self):
        for revision in ('','already-seen'):
            props={'nuvio.progress.revision':revision,'nuvio.home.progress_seen':revision,'nuvio.home.focus':'{"home":[0,12]}'}
            window=SimpleNamespace(getProperty=lambda k:props.get(k,''),setProperty=lambda k,v:props.__setitem__(k,v))
            fresh={'title':'Continue Watching','continue_job':True,'rows':[{'title':'Newest'}]}
            with mock.patch.object(home.xbmcgui,'Window',return_value=window),mock.patch.object(home.home_data,'continue_shelf',return_value=fresh),mock.patch.object(preview,'Controller'):
                win=home.HomeWindow(shelves=[{'continue_job':True,'rows':[]}]);win._paint=mock.Mock();win.setProperty=mock.Mock();control=mock.Mock();win.getControl=lambda cid:control;win.restore_focus=mock.Mock();win.onInit()
            self.assertEqual(win._shelves[0],fresh);self.assertEqual(win._focus_memory['home'],[0,0]);control.selectItem.assert_called_with(0)

    def test_closed_home_cannot_queue_progress_refresh(self):
        win=home.HomeWindow();win._queue_visible=mock.Mock()
        win.drain_events=lambda:setattr(win,'_closed',True)
        win.drain_updates();win._queue_visible.assert_not_called()

    def test_back_stops_playback_but_closing_osd_does_not(self):
        trailers=importlib.import_module('nuvio_ui.trailers')
        for visibility,stopped in (([True,False],True),([True,True],False)):
            player=mock.Mock();player.isPlayingVideo.return_value=True;player.isPlaying.return_value=False
            monitor=mock.Mock();monitor.waitForAbort.side_effect=[False,False,True]
            with mock.patch.object(trailers.xbmc,'Player',return_value=player),mock.patch.object(trailers.xbmc,'Monitor',return_value=monitor),mock.patch.object(trailers.xbmc,'getCondVisibility',side_effect=visibility),mock.patch.object(trailers.xbmcgui,'Window',return_value=SimpleNamespace(getProperty=lambda k:'request',clearProperty=lambda k:None)):
                trailers.wait_for_playback()
            self.assertEqual(player.stop.call_count,1 if stopped else 0)
    def test_restore_rebuilds_continue_and_selects_new_first_card(self):
        props={'nuvio.progress.revision':'new-stop','nuvio.home.progress_seen':'old-stop','nuvio.home.focus':'{"home":[0,7]}'}
        window=SimpleNamespace(getProperty=lambda k:props.get(k,''),setProperty=lambda k,v:props.__setitem__(k,v))
        fresh={'title':'Continue Watching','continue_job':True,'rows':[{'title':'Just stopped'}]}
        with mock.patch.object(home.xbmcgui,'Window',return_value=window),mock.patch.object(home.home_data,'continue_shelf',return_value=fresh),mock.patch.object(preview,'Controller'):
            win=home.HomeWindow(shelves=[{'continue_job':True,'rows':[{'title':'Old'}]}]);win._paint=mock.Mock();win.setProperty=mock.Mock();control=mock.Mock();win.getControl=lambda cid:control;win.restore_focus=mock.Mock();win.onInit()
        self.assertEqual(win._shelves[0],fresh);self.assertEqual(win._focus_memory['home'],[0,0]);control.selectItem.assert_called_with(0)
    def test_airing_banner_does_not_displace_recently_stopped_title(self):
        nextup=importlib.import_module('resources.lib.watch_nextup')
        rows=[{'target':{'canonical_id':'movie'}},{'target':{'canonical_id':'series'}}]
        cards=[{'target':{'canonical_id':'series'},'tomorrow':'1','airing_banner':'Tomorrow'}, {'target':{'canonical_id':'other'},'tomorrow':'1'}]
        history=[{'canonical_id':'series','episode':1},{'canonical_id':'other','episode':1}]
        cache={key:{'provider':'p','meta':{'id':key}} for key in ('series','other')}
        with mock.patch.object(nextup.backend_api if hasattr(nextup,'backend_api') else importlib.import_module('resources.lib.backend_api'),'provider',return_value={'id':'p'}),mock.patch.object(nextup,'_read',return_value=cache),mock.patch.object(nextup.playback_store,'list_recent_items',return_value=history),mock.patch.object(nextup.simkl_watched,'snapshot',return_value={}),mock.patch.object(nextup,'next_card',side_effect=cards):
            result=nextup.augment(rows)
        self.assertEqual([r['target']['canonical_id'] for r in result],['movie','series','other']);self.assertEqual(result[1]['tomorrow'],'1')
    def test_each_new_stop_promotes_that_title_and_completed_title_is_removed(self):
        local=importlib.import_module('resources.lib.continue_local');simkl=importlib.import_module('resources.lib.simkl');data=importlib.import_module('resources.lib.home_data');nextup=importlib.import_module('resources.lib.watch_nextup');watched=importlib.import_module('resources.lib.simkl_watched')
        with tempfile.TemporaryDirectory() as folder,mock.patch.object(local.db,'DB_PATH',str(Path(folder)/'progress.db')),mock.patch.object(local.db,'_DB_READY',False),mock.patch.object(simkl,'queue_progress'),mock.patch.object(watched,'snapshot',return_value={}),mock.patch.object(nextup,'augment',side_effect=lambda rows:rows):
            for title in ('A','B','C','A'):
                local.save({'canonical_id':title,'video_id':title,'media_type':'movie','title':title},120,1000)
                self.assertEqual(data.continue_shelf()['rows'][0]['target']['canonical_id'],title)
            self.assertEqual([r['target']['canonical_id'] for r in data.continue_shelf()['rows']],['A','C','B'])
            local.save({'canonical_id':'A','video_id':'A','media_type':'movie'},950,1000,True)
            self.assertEqual([r['target']['canonical_id'] for r in data.continue_shelf()['rows']],['C','B'])

if __name__=='__main__':unittest.main()
