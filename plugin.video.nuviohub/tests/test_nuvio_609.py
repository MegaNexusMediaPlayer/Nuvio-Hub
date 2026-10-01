"""6.0.9 user-reported regression contracts; no Kodi/network credentials needed.

Real production methods are exercised with explicit native-API boundary fakes.
These tests do NOT replace a Windows/CoreELEC install and rendering test.
"""
import importlib
import json
from pathlib import Path
import threading
import time
import unittest
from unittest import mock
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import kodi_stub
import frontend_test_support
frontend_test_support.install()

api=importlib.import_module('resources.lib.backend_api')
switches=importlib.import_module('resources.lib.stream_providers')
client=importlib.import_module('resources.lib.nuviohub.client')
store=importlib.import_module('resources.lib.nuviohub.store')
models=importlib.import_module('resources.lib.title_details')
search=importlib.import_module('resources.lib.search_catalogs')
home_data=importlib.import_module('resources.lib.home_data')
tmdb=importlib.import_module('resources.lib.tmdb_direct')
presentation=importlib.import_module('resources.lib.presentation_settings')
saver_state=importlib.import_module('resources.lib.saver_state')
home=importlib.import_module('nuvio_ui.home_window')
tv=importlib.import_module('nuvio_ui.iptv')
details=importlib.import_module('nuvio_ui.details')
catalog=importlib.import_module('nuvio_ui.catalog')
settings=importlib.import_module('nuvio_ui.settings')
playback=importlib.import_module('nuvio_ui.playback')
saver=importlib.import_module('nuvio_ui.saver')
session=importlib.import_module('nuvio_ui.session')
ROOT=Path(kodi_stub.ADDON_ROOT).parent


def provider(pid,name=None,resources=None):
    return {'id':pid,'name':name or pid,'base_url':'https://'+pid+'.example.test',
            'manifest':{'id':pid,'name':name or pid,'resources':resources or ['stream'],'types':['movie','series']}}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.settings_patch=mock.patch.dict(kodi_stub._Addon._settings,{},clear=True);self.settings_patch.start();self.addCleanup(self.settings_patch.stop)
        self.home=home.xbmcgui.Window(10000)
        for key in ('nuvio.hide_weather_clock','nuvio.saver.active','nuvio.saver.pending','nuvio.saver.cancelled','nuvio.preview.active','nuvio.preview.silent'):
            self.home.clearProperty(key)
        models._PERSON_CACHE.clear()
    def iptv(self,rows=None):
        with mock.patch.object(tv,'current_id',return_value=None):win=tv.IPTV(rows=rows or [])
        self.addCleanup(win._pool.shutdown,wait=True)
        win.controls={cid:mock.Mock() for cid in (500,501,502,503,504,505)}
        win.getControl=lambda cid:win.controls[cid];win.setProperty=mock.Mock();win.setFocusId=mock.Mock();win.close=mock.Mock()
        return win
    def handoff(self,token='fixture-token',age=0):
        self.home.setProperty('nuvio.saver.active',token)
        self.home.setProperty('nuvio.saver.pending',json.dumps({'token':token,'issued':time.time()-age}))
        return token


class StreamSwitches(Fixture):
    def test_legacy_selection_is_kept_without_enabling_other_addons(self):
        a,b=provider('a'),provider('b')
        kodi_stub._Addon._settings['nuvio_streams_provider']='b'
        self.assertEqual([(p['id'],on) for p,on in switches.entries([a,b])],[('a',False),('b',True)])
    def test_new_provider_opt_in_and_explicit_all_off(self):
        a,b=provider('a'),provider('b')
        kodi_stub._Addon._settings[switches.SETTING]='[{"id":"a","enabled":true}]'
        self.assertEqual([(p['id'],on) for p,on in switches.entries([a,b])],[('a',True),('b',False)])
        kodi_stub._Addon._settings[switches.SETTING]='[]'
        self.assertFalse(any(on for _,on in switches.entries([a,b])))
    def test_malformed_setting_fails_closed(self):
        for raw in ('bad','{}','null','[{"id":"a","enabled":"true"}]'):
            kodi_stub._Addon._settings[switches.SETTING]=raw
            self.assertFalse(any(on for _,on in switches.entries([provider('a')])))
    def test_toggle_persists_independently_of_metadata(self):
        a,b=provider('a'),provider('b');kodi_stub._Addon._settings['nuvio_metadata_provider']='metadata'
        kodi_stub._Addon._settings[switches.SETTING]='[]'
        with mock.patch.object(store,'list_providers',return_value=[a,b]):
            switches.set_enabled('b',True);switches.set_enabled('a',True);switches.set_enabled('b',False)
            self.assertEqual([p['id'] for p in switches.enabled('movie','tt1')],['a'])
        self.assertEqual(kodi_stub._Addon._settings['nuvio_metadata_provider'],'metadata')
    def test_metadata_only_provider_cannot_be_enabled(self):
        with mock.patch.object(store,'list_providers',return_value=[provider('metadata',resources=['meta','catalog'])]):
            with self.assertRaises(ValueError):switches.set_enabled('metadata',True)
    def test_resource_type_and_id_prefix_filters(self):
        p=provider('a',resources=[{'name':'stream','types':['series'],'idPrefixes':['tt']}])
        self.assertTrue(switches.supports(p,'series','tt123:1:2'))
        self.assertFalse(switches.supports(p,'movie','tt123'))
        self.assertFalse(switches.supports(p,'series','tmdb:123'))
    def test_queries_only_enabled_and_compatible_providers(self):
        a,b,c=provider('a'),provider('b'),provider('c',resources=['meta'])
        kodi_stub._Addon._settings[switches.SETTING]='[{"id":"a","enabled":true},{"id":"b","enabled":false}]'
        with mock.patch.object(store,'list_providers',return_value=[a,b,c]),mock.patch.object(client,'get_json',return_value={'streams':[]}) as get:
            api.streams('movie','tt1')
        self.assertEqual(get.call_count,1);self.assertIn('a.example.test',get.call_args.args[0]);self.assertNotIn('b.example.test',get.call_args.args[0])
    def test_multiple_sources_keep_provider_order_duplicates_and_provenance(self):
        a,b=provider('a','Provider A'),provider('b','Provider B')
        rows=[{'name':'720 first','url':'https://media.test/1','behaviorHints':{'proxyHeaders':{'request':{'X-Test':'1'}}}},
              {'name':'4K duplicate','url':'https://media.test/1'}]
        original=json.dumps(rows)
        def get(url,**kw):
            return {'streams':rows if 'a.example.test' in url else [{'name':'Third','url':'https://media.test/3','_nuvio_source':{'id':'spoofed'}}]}
        with mock.patch.object(switches,'enabled',return_value=[a,b]),mock.patch.object(client,'get_json',side_effect=get):_,out=api.streams('movie','tt1')
        self.assertEqual([r['name'] for r in out],['720 first','4K duplicate','Third'])
        self.assertEqual([r['_nuvio_source']['id'] for r in out],['a','a','b'])
        self.assertEqual(json.dumps(rows),original)
    def test_one_failed_addon_does_not_hide_other_sources_or_leak_urls(self):
        a,b=provider('a','Bad'),provider('b','Good')
        def get(url,**kw):
            if 'a.example.test' in url:raise RuntimeError('https://secret-account-token')
            return {'streams':[{'url':'https://media.test/1'}]}
        with mock.patch.object(switches,'enabled',return_value=[a,b]),mock.patch.object(client,'get_json',side_effect=get):source,rows=api.streams('movie','tt1')
        self.assertEqual(source['_nuvio_errors'],['Bad']);self.assertEqual(len(rows),1)
        self.assertNotIn('secret-account-token',repr((source,rows)))
    def test_all_failed_or_all_disabled_are_clear_errors(self):
        with mock.patch.object(switches,'enabled',return_value=[]):
            with self.assertRaisesRegex(ValueError,'Enable a compatible'):api.streams('movie','tt1')
        with mock.patch.object(switches,'enabled',return_value=[provider('a')]),mock.patch.object(client,'get_json',return_value={'streams':'invalid'}):
            with self.assertRaisesRegex(ValueError,'could not respond'):api.streams('movie','tt1')
    def test_playback_uses_selected_row_provider_and_preserves_headers_subtitles(self):
        a,b=provider('a'),provider('b')
        row={'url':'https://media.test/clip','_nuvio_source':b,'behaviorHints':{'proxyHeaders':{'request':{'Referer':'https://ref.test'}}},'subtitles':[{'url':'https://sub.test/a.srt','lang':'en'}]}
        context=api.playback_context({'id':'tt1','type':'movie','name':'Movie'},row,a)
        self.assertEqual(context['provider_id'],'b');self.assertEqual(context['provider_base_url'],b['base_url'])
        self.assertIn('Referer=',context['stream_url']);self.assertEqual(context['subtitles'],row['subtitles'])
    def test_picker_labels_each_addon(self):
        win=playback.Sources(rows=[{'name':'Source','_nuvio_source':{'name':'Addon A'}}])
        win.getControl=lambda _:mock.Mock();win.setFocusId=mock.Mock()
        with mock.patch.object(playback.xbmcgui,'ListItem',return_value=mock.Mock()) as item:win.onInit()
        self.assertEqual(item.call_args.kwargs['label'],'Addon A · Source')


class NavigationAndPVR(Fixture):
    def test_home_back_stays_home_on_each_root_nav_button(self):
        for cid in (101,105,107,108,7000):
            win=home.HomeWindow();win._touch=mock.Mock();win.getFocusId=lambda:cid;win.setFocusId=mock.Mock();win._finish=mock.Mock();win._paint=mock.Mock()
            win.onAction(SimpleNamespace(getId=lambda:92))
            win._finish.assert_not_called();win._paint.assert_not_called();win.setFocusId.assert_called_once_with(101)
    def test_hub_is_an_explicit_home_action(self):
        win=home.HomeWindow();win._touch=mock.Mock();win._finish=mock.Mock()
        win.onClick(108);win.drain_events();self.assertEqual(win._pending,'hub');win._finish.assert_called_once()
    def test_home_settings_back_does_not_request_kodi_home(self):
        win=home.HomeWindow();win.child=mock.Mock(return_value=None);win._paint=mock.Mock();win.setProperty=mock.Mock()
        with mock.patch('nuvio_ui.setup_gate.ready',return_value=True),mock.patch.object(home,'home_xml',return_value='same.xml'),mock.patch.object(home.home_data,'initial_shelves',return_value=[]):win._settings()
        win.child.assert_called_once_with(settings.run)
    def test_hub_nav_order_in_both_home_layouts(self):
        for file in ('nuvio_home.xml','nuvio_home_compact.xml'):
            root=ET.parse(ROOT/'script.nuvio/resources/skins/Default/1080i'/file).getroot()
            settings_btn=root.find(".//control[@id='107']");hub=root.find(".//control[@id='108']")
            self.assertEqual(settings_btn.findtext('onright'),'108');self.assertEqual(hub.findtext('onleft'),'107')
            self.assertEqual(hub.findtext('label'),'HUB')
    def test_session_base_is_native_nonmodal_and_has_no_hub_controls(self):
        self.assertTrue(issubclass(session.SessionWindow,home.xbmcgui.WindowXML))
        self.assertFalse(issubclass(session.SessionWindow,home.xbmcgui.WindowXMLDialog))
        win=session.SessionWindow();win.close=mock.Mock();win.onAction(SimpleNamespace(getId=lambda:92));win.close.assert_not_called()
        xml=(ROOT/'script.nuvio/resources/skins/Default/1080i/nuvio_session.xml').read_text()
        self.assertNotIn('RunScript',xml);self.assertNotIn('Open IPTV',xml);self.assertNotIn('nuvio_banner.png',xml)
    def rpc_fixture(self,old,fail=False):
        calls=[];state={'value':old}
        def rpc(method,params=None):
            calls.append((method,params))
            if method=='Settings.GetSettingValue':return dict(state)
            if method=='Settings.SetSettingValue':state['value']=params['value'];return True
            if method=='Player.Open':
                self.assertEqual(state['value'],0)
                self.assertEqual(params,{'item':{'channelid':55}})
                if fail:raise RuntimeError('PVR failed')
                return 'OK'
            raise AssertionError(method)
        return rpc,state,calls
    def test_pvr_first_click_temporarily_forces_preview_then_restores_preference(self):
        for old in (0,1,2,3):
            rpc,state,calls=self.rpc_fixture(old)
            with mock.patch.object(tv,'rpc',side_effect=rpc):tv.open_preview(55)
            self.assertEqual(state['value'],old)
            self.assertEqual([p['value'] for m,p in calls if m=='Settings.SetSettingValue'],[] if old==0 else [0,old])
    def test_pvr_failure_also_restores_preference(self):
        rpc,state,calls=self.rpc_fixture(3,True)
        with mock.patch.object(tv,'rpc',side_effect=rpc):
            with self.assertRaises(RuntimeError):tv.open_preview(55)
        self.assertEqual(state['value'],3)
    def test_unknown_pvr_setting_does_not_start_fullscreen(self):
        with mock.patch.object(tv,'rpc',return_value={}) as rpc:
            with self.assertRaises(ValueError):tv.open_preview(55)
        self.assertEqual(rpc.call_count,1)
    def test_pvr_rejected_setting_does_not_start(self):
        with mock.patch.object(tv,'rpc',side_effect=[{'value':3},False]) as rpc:
            with self.assertRaises(ValueError):tv.open_preview(55)
        self.assertEqual(rpc.call_count,2)
    def test_fullscreen_return_keeps_same_window_and_stop_does_not_autoplay(self):
        win=self.iptv([{'channelid':55,'label':'One'}]);win.playing=55
        monitor=SimpleNamespace(waitForAbort=lambda _:False)
        with mock.patch.object(tv.xbmc,'Monitor',return_value=monitor),mock.patch.object(tv.xbmc,'getCondVisibility',side_effect=[True,False]),mock.patch.object(tv.xbmc,'Player',return_value=SimpleNamespace(isPlayingVideo=lambda:False)),mock.patch.object(tv,'open_preview') as play:
            win._fullscreen()
        self.assertFalse(win.fullscreen);self.assertFalse(win.closed);self.assertIsNone(win.playing);play.assert_not_called();win.close.assert_not_called()
    def test_restore_rebuilds_guide_and_groups_without_replaying_saved_channel(self):
        win=self.iptv([{'channelid':55,'label':'One'}]);win._initialized=True;win._paint=mock.Mock();win._paint_epg=mock.Mock();win._epg=[{'title':'Now'}];win.restore_focus=mock.Mock();win._play=mock.Mock()
        with mock.patch.object(tv.xbmcgui,'ListItem',return_value=mock.Mock()):win.onInit()
        win.controls[501].reset.assert_called_once();win.controls[501].addItems.assert_called_once();win._paint_epg.assert_called_once();win._play.assert_not_called()
    def test_back_with_no_video_only_focuses_explicit_hub_button(self):
        win=self.iptv()
        with mock.patch.object(tv.xbmc,'getCondVisibility',return_value=False):win.onAction(SimpleNamespace(getId=lambda:92))
        # 6.0.16: the HUB button is the bottom one (506).
        self.assertFalse(win.closed);win.setFocusId.assert_called_once_with(506)
    def test_hub_button_closes_iptv_deliberately(self):
        win=self.iptv()
        with mock.patch.object(tv.xbmc,'getCondVisibility',return_value=False):win.onClick(506);win.drain_events()
        self.assertTrue(win.closed);win.close.assert_called_once()


class AppearanceAndSearch(Fixture):
    def test_old_hide_flag_migrates_and_survives_skin_change(self):
        with mock.patch.object(presentation.xbmc,'getSkinDir',return_value='skin.nuvio'),mock.patch.object(presentation.xbmc,'getCondVisibility',return_value=True):self.assertTrue(presentation.sync())
        self.assertEqual(kodi_stub._Addon._settings[presentation.KEY],'true')
        with mock.patch.object(presentation.xbmc,'getSkinDir',return_value='skin.estuary'),mock.patch.object(presentation.xbmc,'getCondVisibility',return_value=False):self.assertTrue(presentation.sync())
        self.assertEqual(self.home.getProperty(presentation.PROPERTY),'1')
    def test_toggle_is_persistent_and_clears_legacy_skin_hide(self):
        with mock.patch.object(presentation.xbmc,'executebuiltin') as call:
            presentation.set_hidden(True);self.assertEqual(self.home.getProperty(presentation.PROPERTY),'1')
            presentation.set_hidden(False)
        self.assertEqual(kodi_stub._Addon._settings[presentation.KEY],'false')
        self.assertEqual(self.home.getProperty(presentation.PROPERTY),'')
        self.assertEqual(call.call_args.args,('Skin.Reset(nuvio.hideweather)',True))
    def test_all_rendered_weather_clock_controls_share_visibility_gate(self):
        count=0
        for path in (ROOT/'script.nuvio/resources/skins/Default/1080i').glob('*.xml'):
            for control in ET.parse(path).getroot().iter('control'):
                text=(control.findtext('label') or '')+(control.findtext('texture') or '')
                if any(key in text for key in ('System.Time','System.Date','Weather.Temperature','Weather.FanartCode')):
                    self.assertIn('nuvio.hide_weather_clock',control.findtext('visible') or '',path.name);count+=1
        self.assertGreater(count,15)
        # HUB itself has no clock/weather widgets to bypass the preference.
        self.assertNotIn('System.Time',(ROOT/'skin.nuvio/xml/Home.xml').read_text())
    def test_person_ids_do_not_confuse_imdb_or_tvdb_with_tmdb(self):
        self.assertEqual(search.person_id({'id':'tmdb:person:123'}),'123')
        self.assertEqual(search.person_id({'tmdb_id':123}),'123')
        for value in ('nm123','tvdb:123',123):self.assertEqual(search.person_id({'id':value}),'')
    def test_search_supports_legacy_extras_and_does_not_invent_required_values(self):
        c={'id':'actors','type':'movie','extraSupported':['search'],'extraRequired':['search']}
        source={'manifest':{'catalogs':[c,dict(c,id='requiresGenre',extraRequired=['search','genre'])]}}
        self.assertEqual(list(search.entries(source)),[c]);self.assertTrue(search.is_people(c))
    def test_universal_search_retains_query_and_supports_people_anime_types(self):
        catalogs=[{'id':'find'+kind,'type':kind,'extra':['search']} for kind in ('movie','series','person','anime.series')]
        source={'id':'meta','manifest':{'catalogs':catalogs}}
        with mock.patch('resources.lib.metadata_providers.enabled',return_value=[source]),mock.patch.object(tmdb,'_api_key',return_value=''):
            shelves=home_data.search_shelves('Name & surname')
        self.assertEqual(len(shelves),4)
        self.assertTrue(all(s['extra']=={'search':'Name & surname'} for s in shelves))
        self.assertTrue(all('search=' in s['path'] for s in shelves))
    def test_extra_search_catalogs_are_accessible_not_silently_dropped(self):
        catalogs=[{'id':'find'+str(i),'type':'movie','extra':['search']} for i in range(32)]
        with mock.patch('resources.lib.metadata_providers.enabled',return_value=[{'id':'meta','manifest':{'catalogs':catalogs}}]),mock.patch.object(tmdb,'_api_key',return_value=''):
            shelves=home_data.search_shelves('Name')
        self.assertEqual(len(shelves),home_data.MAX_ROWS)
        self.assertEqual(len(shelves[-1]['rows']),32-home_data.MAX_ROWS+1)
        self.assertTrue(all('search=Name' in row['path'] for row in shelves[-1]['rows']))
    def test_actor_cards_have_person_route_not_a_movie_playback(self):
        card=home_data.media_card({'id':'tmdb:22','type':'person','name':'Actor'},None,'person')
        self.assertEqual(card['person']['tmdb_id'],'22');self.assertEqual(card['target']['media_type'],'person')
    def test_person_click_uses_actor_browser_from_catalog(self):
        row=search.person_card({'name':'Actor','tmdb_id':22});win=catalog.Catalog(params={});win.rows=[row]
        control=mock.Mock();control.getSelectedPosition.return_value=0;win.getControl=lambda _:control;win.child=mock.Mock(return_value='')
        win.onClick(500);win.drain_events()
        win.child.assert_called_once_with(details.open_person,row['person'])
    def test_actor_failure_is_shown_instead_of_empty_catalog(self):
        with mock.patch.object(playback,'job',side_effect=ValueError('Enable People Search')),mock.patch.object(details.xbmcgui,'Dialog',return_value=mock.Mock()) as dialog,mock.patch.object(catalog,'open_catalog') as opened:
            details.open_person({'name':'Actor'})
        dialog.return_value.ok.assert_called_once_with('Actor filmography','Enable People Search');opened.assert_not_called()
    def test_cancelled_actor_lookup_does_not_open_late_empty_page(self):
        with mock.patch.object(playback,'job',return_value=None),mock.patch.object(catalog,'open_catalog') as opened:details.open_person({'name':'Actor'})
        opened.assert_not_called()
    def test_no_unauthenticated_tmdb_calls_when_people_catalog_absent(self):
        with mock.patch.object(api,'provider',return_value={}),mock.patch.object(tmdb,'_api_key',return_value=''),mock.patch.object(tmdb,'_request') as request:
            with self.assertRaisesRegex(ValueError,'Enable People Search'):models.person_titles({'name':'Actor'})
        request.assert_not_called()
    def test_provider_movie_and_series_credits_use_string_extra_specs(self):
        source={'id':'meta','base_url':'https://meta.test','manifest':{'catalogs':[{'id':'tmdb.people.search.'+kind,'type':kind,'extra':['search']} for kind in ('movie','series')]}}
        def fetch(source,kind,cid,**kw):return {'metas':[{'id':'tt-'+kind,'type':kind,'name':'Credit'}]}
        with mock.patch('resources.lib.metadata_providers.enabled',return_value=[source]),mock.patch.object(tmdb,'_api_key',return_value=''),mock.patch.object(client,'fetch_catalog',side_effect=fetch):rows=models.person_titles({'name':'Actor'})
        self.assertEqual({r['target']['media_type'] for r in rows},{'movie','series'})
    def test_provider_timeout_is_an_error_not_cached_empty_success(self):
        source={'id':'meta','manifest':{'catalogs':[{'id':'people_search.movie','type':'movie','extra':['search']}]}}
        with mock.patch('resources.lib.metadata_providers.enabled',return_value=[source]),mock.patch.object(tmdb,'_api_key',return_value=''),mock.patch.object(client,'fetch_catalog',side_effect=TimeoutError):
            with self.assertRaisesRegex(ValueError,'could not load'):models.person_titles({'name':'Actor'})
        self.assertFalse(models._PERSON_CACHE)


class VideoScreensaver(Fixture):
    def test_video_formats_local_vfs_and_configured_type(self):
        settings={'nuvio_screensaver_type':'video','nuvio_screensaver_video':''}
        addon=SimpleNamespace(getSetting=lambda key:settings.get(key,''))
        with mock.patch.object(saver.xbmcvfs,'exists',return_value=True):
            for ext in ('.mp4','.mkv','.webm','.mov','.m4v','.avi','.ts','.m2ts'):
                settings['nuvio_screensaver_video']='smb://server/share/clip'+ext
                self.assertTrue(saver.video_file(addon))
            settings['nuvio_screensaver_video']='plugin://plugin.video.example/?play=1'
            self.assertEqual(saver.video_file(addon),'')
    def test_missing_file_falls_back_to_image(self):
        kodi_stub._Addon._settings.update(nuvio_screensaver_type='video',nuvio_screensaver_video='/missing.mp4')
        with mock.patch.object(saver.xbmcvfs,'exists',return_value=False):self.assertEqual(saver.video_file(kodi_stub._Addon()),'')
    def test_paused_or_active_media_is_not_replaced(self):
        with mock.patch.object(saver,'video_file',return_value='/clip.mp4'),mock.patch.object(saver.xbmc,'Player',return_value=SimpleNamespace(isPlaying=lambda:True)),mock.patch.object(saver,'run_image') as image,mock.patch.object(saver,'rpc') as rpc:
            saver.launch()
        image.assert_called_once();rpc.assert_not_called()
    def test_wrong_or_expired_handoff_is_rejected(self):
        token=self.handoff(age=20);self.assertFalse(saver.consume_handoff(token))
        token=self.handoff();self.assertFalse(saver.consume_handoff('other'))
        self.assertTrue(saver.consume_handoff(token));self.assertFalse(saver.consume_handoff(token))
    def test_expired_unstarted_worker_cannot_disable_previews_forever(self):
        self.handoff(age=20);self.assertFalse(saver_state.active());self.assertEqual(self.home.getProperty('nuvio.saver.active'),'')
    def test_new_media_between_handoff_and_start_is_untouched(self):
        token=self.handoff()
        with mock.patch.object(saver,'video_file',return_value='/clip.mp4'),mock.patch.object(saver.xbmc,'Player',return_value=SimpleNamespace(isPlaying=lambda:True)),mock.patch.object(saver,'VideoPlayer') as player,mock.patch.object(saver,'window') as window:
            saver.run_video(token)
        player.assert_not_called();window.assert_not_called();self.assertEqual(self.home.getProperty('nuvio.saver.active'),'')
    def test_video_eof_sets_repeat_signal_without_starting_in_callback(self):
        player=saver.VideoPlayer();player.play=mock.Mock();player.onPlayBackEnded()
        self.assertTrue(player.ended);player.play.assert_not_called()
    def test_any_real_input_closes_video_window(self):
        win=saver.SaverWindow();win.close=mock.Mock()
        win.onAction(SimpleNamespace(getId=lambda:92));win.close.assert_called_once()
    def test_late_cancel_stops_only_matching_item_token(self):
        saver_state.cancel_play('mine')
        player=SimpleNamespace(getPlayingItem=lambda:SimpleNamespace(getProperty=lambda _: 'other'))
        with mock.patch.object(saver_state.xbmc,'executebuiltin') as stop:
            self.assertFalse(saver_state.stop_cancelled_preview(player));stop.assert_not_called()
            player.getPlayingItem=lambda:SimpleNamespace(getProperty=lambda _:'mine')
            self.assertTrue(saver_state.stop_cancelled_preview(player));stop.assert_called_once_with('PlayerControl(Stop)')
    def test_stale_cancel_marker_expires(self):
        self.home.setProperty('nuvio.saver.cancelled',json.dumps({'token':'mine','issued':time.time()-90}))
        player=mock.Mock();self.assertFalse(saver_state.stop_cancelled_preview(player));player.getPlayingItem.assert_not_called()
    def test_video_view_is_full_canvas_and_clock_keeps_its_gate(self):
        root=ET.parse(ROOT/'script.nuvio/resources/skins/Default/1080i/nuvio_screensaver.xml').getroot()
        video=root.find(".//control[@type='videowindow']")
        self.assertEqual(video.findtext('width'),'1920');self.assertEqual(video.findtext('height'),'1080')
        self.assertIn('nuvio.saver.video',video.findtext('visible'))
    def test_full_video_lifecycle_loops_silently_and_restores_audio(self):
        token=self.handoff();events=[];players=[];win=mock.Mock();win.closed=False;win.ready=threading.Event();win.ready.set()
        class Player:
            def __init__(self):self.token='';self.path='';self.ended=False;self.failed=False;self.ready=False;self.cancelled=False;players.append(self)
            def play(self,path,item,windowed=False):self.ready=True;events.append(('play',path,windowed))
            def owns(self):return self.ready and not self.ended
            def isPlayingVideo(self):return self.ready and not self.ended
            def cancel(self):self.cancelled=True
            def stop_owned(self):events.append(('stop_owned',self.token))
            def _ended(self):events.append(('cleanup',self.token))
        class Monitor:
            loops=0
            def abortRequested(self):return False
            def waitForAbort(self,secs):
                self.loops+=1
                if self.loops==1:players[0].ended=True
                if self.loops>=3:win.closed=True
                return False
        muted={'value':False}
        def rpc(method,params=None):
            if method=='Application.GetProperties':return {'muted':muted['value']}
            if method=='Application.SetMute':muted['value']=params['mute'];events.append(('mute',params['mute']));return muted['value']
            raise AssertionError(method)
        with mock.patch.object(saver,'video_file',return_value='/clip.mp4'),mock.patch.object(saver,'window',return_value=win),mock.patch.object(saver,'VideoPlayer',Player),mock.patch.object(saver.xbmc,'Monitor',Monitor),mock.patch.object(saver.xbmc,'Player',return_value=SimpleNamespace(isPlaying=lambda:False)),mock.patch.object(saver,'rpc',side_effect=rpc):
            saver.run_video(token)
        self.assertEqual([e for e in events if e[0]=='play'],[('play','/clip.mp4',True)]*2)
        self.assertFalse(muted['value']);self.assertEqual([e for e in events if e[0]=='mute'],[('mute',True),('mute',False)])
        self.assertTrue(players[-1].cancelled);self.assertEqual(self.home.getProperty('nuvio.saver.active'),'')
        self.assertEqual(len(players),2)


if __name__=='__main__':unittest.main()
