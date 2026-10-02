"""Account restart, empty Home, Simkl writes and complete removal regressions."""
import importlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import kodi_stub
import frontend_test_support
frontend_test_support.install()
settings=importlib.import_module('nuvio_ui.settings')
sync=importlib.import_module('resources.lib.nuviohub.nuvio_stremio_sync')
imp=importlib.import_module('resources.lib.nuvio_import')
home=importlib.import_module('nuvio_ui.home_window')
play=importlib.import_module('nuvio_ui.playback')
simkl=importlib.import_module('nuvio_ui.details').simkl
remove=importlib.import_module('resources.lib.nuvio_uninstall')
ROOT=Path(kodi_stub.ADDON_ROOT).parent


class AccountPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'nuvio_token.json'
        self.patch=mock.patch.object(sync,'_NUVIO_TOKEN',str(self.path));self.patch.start();self.addCleanup(self.patch.stop)

    def test_authenticate_has_no_disk_side_effect_until_commit(self):
        with mock.patch.object(sync,'_http',return_value={'access_token':'new','user':{'id':'user'}}):
            data=sync.Nuvio.authenticate('test@example.invalid','test-only')
        self.assertFalse(self.path.exists())
        sync.Nuvio.save_token(data)
        self.assertEqual(json.loads(self.path.read_text())['access_token'],'new')

    def test_cancelled_login_does_not_accept_previous_account(self):
        sync.Nuvio.save_token({'access_token':'old'})
        dialog=mock.Mock();dialog.input.side_effect=['new@example.invalid','password']
        with mock.patch.object(settings.xbmcgui,'ALPHANUM_HIDE_INPUT',2,create=True),mock.patch.object(settings.xbmcgui,'Dialog',return_value=dialog),mock.patch.object(play,'job',return_value=None):
            self.assertFalse(settings.sign_in_nuvio())
        self.assertEqual(sync.Nuvio.token()['access_token'],'old')

    def test_profile_survives_restart_and_refresh(self):
        sync.Nuvio.save_token({'access_token':'old','refresh_token':'refresh','created_at':1})
        sync.Nuvio.select_profile({'profile_index':2,'profile_name':'TV','uses_primary_addons':True})
        self.assertEqual(json.loads(self.path.read_text())['profile_index'],2)
        with mock.patch.object(sync,'_http',return_value={'access_token':'new'}):sync.Nuvio._ensure_token()
        data=json.loads(self.path.read_text())
        self.assertEqual(data['profile_index'],2);self.assertEqual(data['profile_name'],'TV')
        self.assertTrue(data['uses_primary_addons']);self.assertEqual(data['access_token'],'new')

    def test_logout_cannot_restore_backup_login(self):
        sync.Nuvio.save_token({'access_token':'a'});sync.Nuvio.save_token({'access_token':'b'})
        self.assertTrue(Path(str(self.path)+'.bak').exists())
        sync.Nuvio.clear()
        self.assertFalse(sync.Nuvio.is_linked());self.assertFalse(Path(str(self.path)+'.bak').exists())

    def test_failed_profile_request_does_not_cache_profile_one(self):
        sync.Nuvio.save_token({'access_token':'a'})
        with mock.patch.object(sync.Nuvio,'_rpc',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):sync.Nuvio._profile_id()
        self.assertNotIn('profile_index',sync.Nuvio.token())

    def test_multiple_profiles_require_choice(self):
        sync.Nuvio.save_token({'access_token':'a'})
        with mock.patch.object(sync.Nuvio,'_rpc',return_value=[{'profile_index':1,'name':'Main'},{'profile_index':2,'name':'TV'}]):
            with self.assertRaises(ValueError):sync.Nuvio._profile_id()

    def test_shared_addons_use_primary_profile_but_collections_use_selected(self):
        sync.Nuvio.save_token({'access_token':'a','profile_index':2,'uses_primary_addons':True})
        with mock.patch.object(sync.Nuvio,'_rest_get',return_value=[]) as get, mock.patch.object(sync.Nuvio,'_rpc',return_value=[]) as rpc:
            sync.Nuvio.sync_addons([],direction='pull');sync.Nuvio.sync_collections([],direction='pull')
        self.assertIn('profile_id=eq.1',get.call_args.args[0]);self.assertEqual(rpc.call_args.args[1]['p_profile_id'],2)

    def test_refresh_cannot_resurrect_logged_out_session(self):
        sync.Nuvio.save_token({'access_token':'old','refresh_token':'r','created_at':1})
        def refresh(*a,**kw):sync.Nuvio.clear();return {'access_token':'late'}
        with mock.patch.object(sync,'_http',side_effect=refresh):sync.Nuvio._ensure_token()
        self.assertFalse(sync.Nuvio.is_linked())


class ImportPersistence(unittest.TestCase):
    def setUp(self):
        validator=importlib.import_module('resources.lib.collection_validation')
        patch=mock.patch.object(validator,'validate',return_value={'ok':True})
        patch.start();self.addCleanup(patch.stop)

    def test_settings_read_sees_saved_write_and_external_change(self):
        cache=importlib.import_module('resources.lib.settings_cache')
        disk={'nuvio_sync_enabled':'false'}
        class Snapshot:
            def __init__(self,*a):self.values=dict(disk)
            def getSetting(self,key):return self.values.get(key,'')
            def setSetting(self,key,value):self.values[key]=value;disk.update(self.values)
        with mock.patch.object(cache.xbmcaddon,'Addon',side_effect=Snapshot):
            proxy=cache.CachedAddon(Snapshot())
            self.assertEqual(proxy.getSetting('nuvio_sync_enabled'),'false')
            proxy.setSetting('nuvio_sync_enabled','true')
            self.assertEqual(proxy.getSetting('nuvio_sync_enabled'),'true')
            disk['nuvio_metadata_provider']='new-provider';proxy.invalidate()
            self.assertEqual(proxy.getSetting('nuvio_metadata_provider'),'new-provider')

    def test_fetch_once_no_mutations_and_manifest_failure_reported(self):
        with mock.patch.object(imp.sync.Nuvio,'sync_addons',return_value=[{'manifest_url':'https://example.invalid/manifest.json'}]),mock.patch.object(imp.sync.Nuvio,'sync_collections',return_value=[]) as collections,mock.patch.object(imp.sync.Nuvio,'sync_progress',return_value=[]),mock.patch.object(imp.store,'list_providers',return_value=[]),mock.patch.object(imp.client,'get_json',side_effect=TimeoutError),mock.patch.object(imp.store,'add_provider') as save:
            result=imp.fetch()
        collections.assert_not_called();save.assert_not_called()
        self.assertEqual(len(result['errors']),1);self.assertEqual(result['providers'],[])

    def test_actual_provider_and_collection_files_survive_cache_reload(self):
        manifest={'id':'aiometadata','version':'1','resources':['meta','catalog'],'types':['movie']}
        collections=[{'id':'c','title':'My collection','folders':[{'id':'f','title':'Films','sources':[{'addonId':'aiometadata','catalogId':'movie','type':'movie'}]}]}]
        with tempfile.TemporaryDirectory() as tmp:
            providers=Path(tmp)/'providers.json';path=Path(tmp)/'collections.json'
            with mock.patch.object(imp.store,'PROVIDERS_PATH',str(providers)),mock.patch.object(imp.store,'_PROVIDERS_CACHE',None),mock.patch.object(imp.store,'_PROVIDERS_MTIME',None),mock.patch.object(imp.collection_profile,'profile_file',return_value=path),mock.patch.object(imp.backend_api,'provider',return_value=None):
                result=imp.apply({'providers':[{'manifest_url':'https://example.invalid/manifest.json','manifest':manifest}],'collections':collections,'progress':[],'errors':[]})
                self.assertEqual(result['providers'],1);self.assertEqual(result['collections'],1)
                imp.store._PROVIDERS_CACHE=None
                self.assertEqual(imp.store.list_providers()[0]['manifest']['id'],'aiometadata')
                self.assertEqual(imp.collection_profile.load()[0]['folders'][0]['title'],'Films')
                again=imp.apply({'providers':[{'manifest_url':'https://example.invalid/manifest.json','manifest':manifest}],'collections':[],'progress':[],'errors':[]})
                self.assertEqual(len(imp.store.list_providers()),1)
                self.assertEqual(imp.collection_profile.load()[0]['folders'][0]['title'],'Films')
                self.assertTrue(again['errors'])

    def test_cancelled_import_does_not_commit(self):
        with mock.patch.object(settings,'choose_nuvio_profile',return_value=True),mock.patch.object(sync.Nuvio,'is_linked',return_value=True),mock.patch.object(sync.Nuvio,'token',return_value={'profile_index':1}),mock.patch.object(play,'job',return_value=None),mock.patch.object(imp,'apply') as apply:
            self.assertFalse(settings.sync_nuvio())
        apply.assert_not_called()


class EmptyHome(unittest.TestCase):
    def test_default_layout_is_fixed_without_implicit_cloud_collection_fallback(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(imp.collection_profile,'profile_file',return_value=Path(tmp)/'missing.json'):
            layout=imp.collection_profile.load()
        self.assertEqual(layout,[])
        self.assertTrue(imp.collection_profile.defaults())

    def test_card_edits_and_explicit_layout_import_survive_reload(self):
        profile=imp.collection_profile
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(profile,'profile_file',return_value=Path(tmp)/'layout.json'),mock.patch('resources.lib.collection_validation.validate',return_value={'ok':True}):
            layout=profile.defaults();folder=layout[0]['folders'][0]
            folder.update(title='Evening',hidden=True,cover='https://example.invalid/cover.jpg')
            profile.save(layout);saved=profile.load()[0]['folders'][0]
            self.assertEqual(saved['title'],'Evening');self.assertTrue(saved['hidden'])
            self.assertEqual(saved['cover'],'https://example.invalid/cover.jpg')
            source=saved['sources'][0]
            imported=[{'id':'mine','title':'Other Home','folders':[{'title':'New card','sources':[source]},
                {'title':'Sports','sources':[source]},{'title':'World','sources':[source]}]}]
            profile.save(imported)
            # 6.0.35: World is an ordinary collection; only Sports stays out.
            self.assertEqual([f['title'] for f in profile.load()[0]['folders']],['New card','World'])

    def window(self):
        win=home.HomeWindow();controls={}
        def control(cid):
            # Real Kodi 21 Window::GetControlById rejects XML grouplist controls.
            # A permissive Mock here previously concealed the blank-Home defect.
            if cid==6000:raise RuntimeError('Unknown control type for python')
            if cid not in controls:
                controls[cid]=mock.Mock();controls[cid].getSelectedPosition.return_value=0
            return controls[cid]
        win.getControl=control;win.getFocusId=lambda:7000;win.setProperty=mock.Mock();win.setFocusId=mock.Mock();win._touch=mock.Mock();win.close=mock.Mock()
        self.addCleanup(win._finish)
        return win

    def test_empty_shelves_and_empty_rows_always_leave_navigation(self):
        for shelves in ([],[{'title':'Empty','rows':[]}]):
            win=self.window()
            with mock.patch.object(home.xbmcgui,'ListItem',return_value=mock.Mock()):win._paint(shelves)
            win.setFocusId.assert_called_with(7000)
            self.assertTrue(win._shelves[0]['rows'])
            self.assertFalse(win._futures)

    def test_compact_layout_keeps_same_controls_with_xml_viewport(self):
        path=ROOT/'script.nuvio/resources/skins/Default/1080i'
        normal=ET.parse(path/'nuvio_home.xml').getroot()
        compact=ET.parse(path/'nuvio_home_compact.xml').getroot()
        view=compact.find(".//control[@id='6000']")
        self.assertEqual((view.findtext('top'),view.findtext('height')),('140','890'))
        source=normal.find(".//control[@id='6000']")
        view.find('top').text=source.findtext('top');view.find('height').text=source.findtext('height')
        self.assertEqual(ET.tostring(normal),ET.tostring(compact))
        with mock.patch.object(home.xbmc,'getCondVisibility',return_value=True):self.assertEqual(home.home_xml(),'nuvio_home_compact.xml')

    def test_initialization_error_leaves_visible_message_and_settings_focus(self):
        win=self.window();win._paint=mock.Mock(side_effect=RuntimeError('unsupported control'))
        win.onInit()
        win.setFocusId.assert_called_with(107)
        self.assertTrue(any(c.args[0]=='nuvio.home.error' and c.args[1] for c in win.setProperty.call_args_list))

    def test_close_supports_kodi_python38_executor(self):
        win=self.window();called=[]
        class Pool:
            def shutdown(self,wait=True):called.append(wait)
        win._pool=Pool();future=mock.Mock();win._futures=[future]
        win._finish()
        future.cancel.assert_called_once();self.assertEqual(called,[False])

    def test_invalid_remembered_focus_does_not_blank_rows(self):
        win=self.window();win._focus_memory={'home':['bad',None]}
        with mock.patch.object(home.xbmcgui,'ListItem',return_value=mock.Mock()):win._paint([{'title':'Row','rows':[{'title':'Card'}]}])
        win.setFocusId.assert_called_with(7000)

    def test_worker_never_touches_controls_and_stale_updates_are_discarded(self):
        win=self.window();win._shelves=[{'rows':[]}];win._set_rows=mock.Mock()
        with mock.patch.object(home.home_data,'load_catalog',return_value=[{'title':'Loaded'}]):
            worker=threading.Thread(target=win._load,args=(0,{},0));worker.start();worker.join(1)
        self.assertFalse(worker.is_alive());win._set_rows.assert_not_called()
        win._generation=1;win.drain_updates();win._set_rows.assert_not_called()

    def test_home_search_settings_navigation_has_no_my_list(self):
        root=ET.parse(ROOT/'script.nuvio/resources/skins/Default/1080i/nuvio_home.xml').getroot()
        buttons={int(c.get('id')):c for c in root.findall('./controls/control') if c.get('type')=='button'}
        self.assertEqual(set(buttons),{101,105,106,107,108})  # 6.0.35: Library (106)
        self.assertEqual(buttons[106].findtext('label'),'Library')
        self.assertEqual(buttons[107].findtext('onright'),'108')
        self.assertEqual(buttons[108].findtext('label'),'HUB')
        for c in buttons.values():
            for name in ('onleft','onright'):self.assertIn(int(c.findtext(name)),buttons)
        self.assertEqual(home.NAV,{101:''})


class SimklLibrary(unittest.TestCase):
    def test_movie_and_series_are_added_to_plan_to_watch(self):
        for mt,kind in (('movie','movies'),('series','shows')):
            with mock.patch.object(simkl,'authorized',return_value=True),mock.patch.object(simkl,'_request',return_value={'added':{kind:[{'ids':{'imdb':'tt123'}}]},'not_found':{kind:[]}}) as request:
                self.assertTrue(simkl.add_to_library({'media_type':mt,'imdb_id':'tt123','title':'Example'}))
            self.assertEqual(request.call_args.args[0],'/sync/add-to-list')
            self.assertEqual(request.call_args.kwargs['payload'][kind][0]['to'],'plantowatch')
            self.assertNotIn('seasons',request.call_args.kwargs['payload'][kind][0])

    def test_server_failure_is_not_reported_as_saved(self):
        for response in ({},{'not_found':{'movies':[{}]}},{'error':'denied'}):
            with mock.patch.object(simkl,'authorized',return_value=True),mock.patch.object(simkl,'_request',return_value=response):
                with self.assertRaises(ValueError):simkl.add_to_library({'imdb_id':'tt123'})


class Uninstall(unittest.TestCase):
    def test_owned_dependency_ledger_excludes_preexisting_and_unrelated_installs(self):
        def row(enabled=True,*deps):return {'enabled':enabled,'dependencies':[{'addonid':d} for d in deps]}
        before={'weather.openmeteo':row(False),'existing.module':row()}
        after={'weather.openmeteo':row(True,'existing.module','new.module'),
               'existing.module':row(),'new.module':row(),'unrelated.new':row()}
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(remove,'ledger_path',return_value=Path(tmp)/'ledger.json'):
            remove.record_install('weather.openmeteo',before,after)
            ledger=remove.read_ledger()
        self.assertEqual(ledger['owned'],['new.module'])
        self.assertEqual(ledger['enabled_existing'],['weather.openmeteo'])

    def test_failed_move_restores_already_moved_component(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'addons';stage=Path(tmp)/'staging';stage.mkdir();root.mkdir()
            for aid in ('script.nuvio','skin.nuvio'):
                (root/aid).mkdir();(root/aid/'addon.xml').write_text('<addon id="'+aid+'"/>')
            original=remove.os.replace
            def move(source,dest):
                if Path(source)==root/'skin.nuvio':raise OSError('test failure')
                return original(source,dest)
            with mock.patch.object(remove.os,'replace',side_effect=move):
                with self.assertRaises(OSError):remove.stage_removal(root,['script.nuvio','skin.nuvio'],stage)
            self.assertTrue((root/'script.nuvio').exists());self.assertTrue((root/'skin.nuvio').exists())

    def test_dependency_order_and_shared_addons_kept(self):
        def row(*deps):return {'dependencies':[{'addonid':d} for d in deps]}
        installed={'skin.nuvio':row('script.nuvio'),'screensaver.nuvio':row('script.nuvio'),
                   'script.nuvio':row('plugin.video.nuviohub'),'plugin.video.nuviohub':row(),
                   'weather.openmeteo':row('shared.module'),'shared.module':row(), 'other.addon':row('shared.module')}
        order=remove.removal_plan(installed,{'owned':['weather.openmeteo','shared.module']})
        self.assertNotIn('shared.module',order);self.assertNotIn('other.addon',order)
        self.assertLess(order.index('skin.nuvio'),order.index('script.nuvio'))
        self.assertLess(order.index('script.nuvio'),order.index('plugin.video.nuviohub'))

    def test_removal_moves_only_explicit_ids_preserving_userdata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'addons';stage=Path(tmp)/'staging';stage.mkdir();root.mkdir()
            for aid in ('script.nuvio','other.addon'):
                p=root/aid;p.mkdir();(p/'addon.xml').write_text('<addon id="'+aid+'"/>')
            profile=Path(tmp)/'userdata';profile.mkdir();(profile/'settings.xml').write_text('keep')
            self.assertEqual(remove.stage_removal(root,['script.nuvio'],stage),['script.nuvio'])
            self.assertTrue((root/'other.addon').exists());self.assertEqual((profile/'settings.xml').read_text(),'keep')

    def test_invalid_removal_target_stops_before_any_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'addons';stage=Path(tmp)/'staging';stage.mkdir();root.mkdir()
            (root/'script.nuvio').mkdir();(root/'script.nuvio/addon.xml').write_text('<addon id="script.nuvio"/>')
            with self.assertRaises(ValueError):remove.stage_removal(root,['script.nuvio','../userdata'],stage)
            self.assertTrue((root/'script.nuvio').exists())
