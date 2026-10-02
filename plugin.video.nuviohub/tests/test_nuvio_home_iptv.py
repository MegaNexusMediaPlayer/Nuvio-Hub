"""Home exits, first-run skin confirmation, and the native IPTV browser."""
import importlib
from pathlib import Path
import queue
import unittest
from unittest import mock
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import kodi_stub
import frontend_test_support
frontend_test_support.install()
tv=importlib.import_module('nuvio_ui.iptv')
home=importlib.import_module('nuvio_ui.home_window')
settings=importlib.import_module('nuvio_ui.settings')
activation=importlib.import_module('resources.lib.skin_activation')
ROOT=Path(kodi_stub.ADDON_ROOT).parent


class HomeBack(unittest.TestCase):
    def test_launcher_never_automatically_reopens_home_or_iptv(self):
        root=ET.parse(ROOT/'skin.nuvio/xml/Home.xml').getroot()
        self.assertEqual(root.findall('onload'),[])
        actions=[c.text for c in root.findall('.//onclick')]
        self.assertIn('RunScript(script.nuvio)',actions)
        self.assertIn('RunScript(script.nuvio,iptv)',actions)

    def test_back_on_top_navigation_returns_home_without_exiting_to_hub(self):
        for cid in (101,105,107):
            win=home.HomeWindow();win._touch=mock.Mock();win._finish=mock.Mock();win._paint=mock.Mock()
            win.getFocusId=lambda:cid;win._bucket='collection:x'
            with mock.patch.object(home.home_data,'initial_shelves',return_value=['home']):
                win.onAction(SimpleNamespace(getId=lambda:92))
            win._finish.assert_not_called();win._paint.assert_called_once_with(['home'])
            self.assertEqual(win._bucket,'')

    def test_back_inside_collection_returns_to_home_rows(self):
        win=home.HomeWindow();win._touch=mock.Mock();win._finish=mock.Mock();win._paint=mock.Mock()
        win.getFocusId=lambda:7000;win._bucket='collection:x'
        with mock.patch.object(home.home_data,'initial_shelves',return_value=['home']):win.onAction(SimpleNamespace(getId=lambda:92))
        self.assertEqual(win._bucket,'');win._paint.assert_called_once_with(['home']);win._finish.assert_not_called()

    def test_back_from_settings_is_distinct_from_done(self):
        def show(title,rows,choose,back_result=None):
            self.assertEqual(back_result,'ActivateWindow(Home)')
            self.assertEqual(choose(15),settings.page.DONE)  # 6.0.35: 'Continue Watching' and 'Sport'; 6.0.37: 'Local storage'
            return back_result
        with mock.patch.object(settings.page,'show',side_effect=show):
            self.assertEqual(settings.run(back_command='ActivateWindow(Home)'),'ActivateWindow(Home)')

    def test_skin_change_is_deferred_until_settings_closes(self):
        with mock.patch.object(settings.page,'show',side_effect=lambda title,rows,choose:choose(0)),mock.patch.object(settings,'rpc') as rpc:
            self.assertEqual(settings.appearance(),'nuvio:activate_skin')
        rpc.assert_not_called()

    def test_skin_confirmation_waits_for_the_user_instead_of_opening_ui(self):
        clock=[0]
        monitor=SimpleNamespace(waitForAbort=lambda n:clock.__setitem__(0,clock[0]+n) or False)
        with mock.patch.object(activation.xbmc,'getSkinDir',side_effect=['skin.estuary','skin.nuvio'],create=True),mock.patch.object(activation.xbmc,'executeJSONRPC',return_value='{"result":true}',create=True),mock.patch.object(activation.xbmc,'getCondVisibility',side_effect=[False,True,True,False]),mock.patch.object(activation.xbmc,'Monitor',return_value=monitor),mock.patch.object(activation.time,'monotonic',side_effect=lambda:clock[0]),\
                mock.patch.object(activation,'check',return_value=''),mock.patch.object(activation,'persist') as persist:
            self.assertTrue(activation.activate(mock.Mock()))
        persist.assert_called_once()  # 6.0.33: saved at once, survives Android killing Kodi
        self.assertGreaterEqual(clock[0],.3)

    def test_declined_skin_is_respected(self):
        with mock.patch.object(activation.xbmc,'getSkinDir',return_value='skin.estuary',create=True),mock.patch.object(activation.xbmc,'executeJSONRPC',return_value='{"result":true}',create=True),mock.patch.object(activation.xbmc,'getCondVisibility',side_effect=[True,False]),mock.patch.object(activation.xbmc,'Monitor',return_value=SimpleNamespace(waitForAbort=lambda n:False)),\
                mock.patch.object(activation,'check',return_value=''),mock.patch.object(activation,'persist') as persist:
            self.assertEqual(activation.switch(mock.Mock()),'declined')
        persist.assert_not_called()


class IPTVBrowser(unittest.TestCase):
    def window(self,rows=None):
        with mock.patch.object(tv,'current_id',return_value=None):win=tv.IPTV(rows=rows or [])
        self.addCleanup(win._pool.shutdown,wait=True)
        win.controls={cid:mock.Mock() for cid in (500,501,504)}
        win.getControl=lambda cid:win.controls[cid];win.setProperty=mock.Mock();win.setFocusId=mock.Mock();win.close=mock.Mock()
        return win

    def test_channels_sort_numerically_without_altering_playback_identity(self):
        rows=[{'channelnumber':10,'channelid':5},{'channelnumber':2,'channelid':9},{'channelnumber':2,'subchannelnumber':1,'channelid':4}]
        with mock.patch.object(tv,'rpc',return_value={'channels':rows}):result=tv.channels(8)
        self.assertEqual([r['channelid'] for r in result],[9,4,5])

    def test_group_numbers_are_contiguous_but_stable_ids_are_preserved(self):
        rows=[{'channelnumber':101,'channelid':55,'label':'One'},{'channelnumber':987,'channelid':99,'label':'Two'}]
        win=self.window(rows)
        with mock.patch.object(tv.xbmcgui,'ListItem',return_value=mock.Mock()) as item:win._paint()
        self.assertEqual([c.kwargs['label'] for c in item.call_args_list],['1  One','2  Two'])
        self.assertEqual([r['channelid'] for r in win.rows],[55,99])

    def test_epg_times_are_utc_and_full_schedule_is_sorted(self):
        self.assertEqual(tv.epg_time('2026-09-29 10:00:00').timestamp(),1790676000)
        self.assertIsNone(tv.epg_time('bad'))
        rows=[{'starttime':'2026-09-29 12:00:00'},{'starttime':'2026-09-29 11:00:00'}]
        with mock.patch.object(tv,'rpc',return_value={'broadcasts':rows}):result=tv.broadcasts(5)
        self.assertEqual(result,list(reversed(rows)))

    def test_first_click_previews_second_click_uses_retained_fullscreen_child(self):
        row={'channelid':55,'uniqueid':999,'clientid':2,'label':'One'};win=self.window([row]);win.controls[500].getSelectedPosition.return_value=0
        win.child=mock.Mock()
        with mock.patch.object(tv,'open_preview') as preview,mock.patch.object(tv,'current_id',return_value=55),mock.patch.object(tv.ADDON,'setSetting'):
            win.onClick(500);win.drain_events()
            preview.assert_called_once_with(55);win.child.assert_not_called()
            win.onClick(500);win.drain_events()
            win.child.assert_called_once_with(win._fullscreen)
            self.assertFalse(win.closed)
        win.close.assert_not_called()

    def test_back_or_stop_returns_to_guide_without_closing_iptv(self):
        for action in (92,13):
            win=self.window()
            with mock.patch.object(tv.xbmc,'getCondVisibility',return_value=True),mock.patch.object(tv.xbmc,'Player') as player:
                win.onAction(SimpleNamespace(getId=lambda:action))
            self.assertFalse(win.closed);player.return_value.stop.assert_called_once()
            win.close.assert_not_called();win.setFocusId.assert_called_once_with(500)

    def test_layout_has_categories_channels_then_video_and_guide_below(self):
        root=ET.parse(ROOT/'script.nuvio/resources/skins/Default/1080i/nuvio_iptv.xml').getroot()
        cats=root.find(".//control[@id='501']");channels=root.find(".//control[@id='500']");epg=root.find(".//control[@id='504']");video=root.find(".//control[@type='videowindow']")
        self.assertEqual(cats.get('type'),'list');self.assertEqual(epg.get('type'),'list')
        self.assertLess(int(cats.findtext('left')),int(channels.findtext('left')))
        self.assertLess(int(channels.findtext('left')),int(video.findtext('left')))
        self.assertGreater(int(epg.findtext('top')),int(video.findtext('top'))+int(video.findtext('height')))

    def test_late_epg_does_not_replace_new_channel_or_touch_closed_window(self):
        win=self.window();win._ready=True;win._select_channel=mock.Mock();win._selection=3;win._selected_at=10**20;win._paint_epg=mock.Mock()
        win._updates.put(('epg',0,2,[{'title':'Old'}]));win.tick();win._paint_epg.assert_not_called()
        win.closed=True;win._updates.put(('epg',0,3,[{'title':'Late'}]));win.tick();win._paint_epg.assert_not_called()


class PersistentSettings(unittest.TestCase):
    def test_toggle_updates_in_place_without_closing_and_preserves_selection(self):
        page=settings.page;values={'on':False};control=mock.Mock();control.getSelectedPosition.return_value=1
        rows=lambda:[page.item('Other'),page.item('Toggle',enabled=values['on'])]
        win=page.SettingsPage(title='Preferences',rows=rows,choose=lambda i:values.update(on=not values['on']))
        win.getControl=lambda cid:control;win.setProperty=mock.Mock();win.close=mock.Mock();win._rendered_rows=win.rows()
        with mock.patch.object(page.xbmcgui,'ListItem',return_value=mock.Mock()):win.onClick(500);win.drain_events()
        self.assertTrue(values['on']);control.selectItem.assert_called_once_with(1);win.close.assert_not_called()

    def test_external_action_closes_settings_before_execution(self):
        page=settings.page;win=page.SettingsPage(title='Skin',rows=lambda:[page.item('Use skin')],choose=lambda i:'nuvio:activate_skin')
        control=mock.Mock();control.getSelectedPosition.return_value=0;win.getControl=lambda cid:control;win.close=mock.Mock();win._rendered_rows=win.rows()
        win.child=mock.Mock(side_effect=lambda fn,*a,**k:fn(*a,**k))  # 6.0.18: row actions run with the page hidden
        win.onClick(500);win.drain_events();self.assertEqual(win.result,'nuvio:activate_skin');win.close.assert_called_once()
        win.child.assert_called_once()

    def test_playback_switch_reflects_saved_state_immediately(self):
        values={'nuvio_autoplay':'false'}
        addon=SimpleNamespace(getSetting=lambda k:values.get(k,''),setSetting=lambda k,v:values.__setitem__(k,v))
        def show(title,rows,choose):
            self.assertFalse(rows()[0]['enabled']);choose(0);self.assertTrue(rows()[0]['enabled'])
            self.assertEqual(rows()[0]['value'],'On');choose(0);self.assertEqual(rows()[0]['value'],'Off')
        with mock.patch.object(settings,'ADDON',addon),mock.patch.object(settings.page,'show',side_effect=show):settings.playback()

    def test_collection_toggles_keep_current_card_and_persist(self):
        editor=importlib.import_module('nuvio_ui.collection_editor')
        folder={'id':'f','title':'Films','sources':[]};group={'folders':[folder]}
        def show(title,rows,choose):
            self.assertTrue(rows()[4]['enabled']);choose(4);self.assertFalse(rows()[4]['enabled'])
            self.assertTrue(rows()[9]['enabled']);choose(9);self.assertFalse(rows()[9]['enabled'])
        with mock.patch.object(settings.page,'show',side_effect=show),mock.patch.object(settings,'commit_collections',return_value=True) as save:
            editor.edit_card([group],group,folder)
        self.assertEqual(save.call_count,2)

if __name__=='__main__':unittest.main()
