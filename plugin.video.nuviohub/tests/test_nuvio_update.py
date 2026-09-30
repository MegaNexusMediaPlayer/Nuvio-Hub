import importlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import kodi_stub
import frontend_test_support
frontend_test_support.install()
profile=kodi_stub.import_lib_module('collection_profile')
api=kodi_stub.import_lib_module('backend_api')
pages=kodi_stub.import_lib_module('catalog_pages')
subs=kodi_stub.import_lib_module('nuvio_subtitles')
iptv=kodi_stub.import_lib_module('iptv_config')
cw=kodi_stub.import_lib_module('continue_metadata')
preview=importlib.import_module('nuvio_ui.home_trailers')
playback=importlib.import_module('nuvio_ui.playback')
support=kodi_stub.import_lib_module('trailer_support')
ROOT=Path(kodi_stub.ADDON_ROOT).parent

class UpdateTests(unittest.TestCase):
    def test_personal_collection_order_filters_and_ids_are_preserved(self):
        source={'addonId':'personal','catalogId':'my-list','type':'movie','genre':'Drama'}
        data=[{'id':'mine','title':'My picks','folders':[{'id':'f','title':'Evening','catalogSources':[source],'focusGifUrl':'https://example.test/a.gif'}]},
              {'id':'collections.world','title':'World','folders':[{'sources':[source]}]},
              {'id':'sports','title':'Sports','folders':[{'sources':[source]}]}]
        result=profile.normalize(data)
        self.assertEqual([g['id'] for g in result],['mine'])
        self.assertEqual(result[0]['folders'][0]['sources'][0]['genre'],'Drama')
        self.assertEqual(result[0]['folders'][0]['animation'],'https://example.test/a.gif')

    def test_corrupt_collection_import_does_not_replace_working_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'collections.json';path.write_text('existing')
            with mock.patch.object(profile,'profile_file',return_value=path):
                with self.assertRaises(ValueError):profile.save({'bad':'input'})
            self.assertEqual(path.read_text(),'existing')

    def test_continue_metadata_changes_art_but_not_resume_identity_or_position(self):
        row={'title':'Unknown','percent_value':'45','target':{'canonical_id':'tt123','video_id':'tt123:1:2','media_type':'tv','season':'1','episode':'2','resume_seconds':'987'}}
        with mock.patch.object(cw.backend_api,'metadata',return_value={'name':'Actual show','poster':'poster'}):out=cw.enrich([row])[0]
        self.assertEqual(out['title'],'Actual show');self.assertEqual(out['poster'],'poster')
        self.assertEqual(out['target']['resume_seconds'],'987');self.assertEqual(out['target']['video_id'],'tt123:1:2')
        self.assertEqual(row['title'],'Unknown')

    def test_metadata_failure_has_a_stable_saved_title_not_unknown(self):
        with mock.patch.object(cw.backend_api,'metadata',side_effect=TimeoutError):out=cw.enrich([{'title':'Loading title…','target':{'canonical_id':'tt1'}}])[0]
        self.assertEqual(out['title'],'Saved movie · tt1')

    def test_numeric_progress_id_is_normalized_even_when_art_is_already_cached(self):
        row={'title':'Saved title','poster':'poster','target':{'canonical_id':'123','video_id':'123:1:2','media_type':'tvshow','resume_seconds':321}}
        with mock.patch.object(cw.backend_api,'metadata') as fetch:out=cw.enrich([row])[0]
        fetch.assert_not_called();self.assertEqual(out['target']['canonical_id'],'tmdb:123')
        self.assertEqual(out['target']['video_id'],'123:1:2');self.assertEqual(out['target']['resume_seconds'],321)

    def test_continue_uses_known_imdb_and_strips_episode_suffix_for_metadata_only(self):
        row={'title':' UNKNOWN ','target':{'canonical_id':'opaque','imdb_id':'tt123:2:3','video_id':'provider-episode','media_type':'tv'}}
        with mock.patch.object(cw.backend_api,'metadata',return_value={'name':'Show','poster':'cover'}) as fetch:out=cw.enrich([row])[0]
        fetch.assert_called_once_with('series','tt123')
        self.assertEqual(out['target']['video_id'],'provider-episode');self.assertEqual(out['title'],'Show')

    def test_cloud_progress_without_display_fields_keeps_saved_title_and_poster(self):
        db=importlib.import_module(cw.__package__+'.dexhub.playback_store')
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(db,'DB_PATH',str(Path(tmp)/'progress.db')),mock.patch.object(db,'_DB_READY',False):
            row={'media_type':'movie','canonical_id':'tt1','video_id':'tt1','title':'Real title','poster':'cover','background':'backdrop','position':100,'duration':1000,'percent':10,'ext_updated_at':100}
            db.upsert_entries([row],mark_dirty=False)
            db.upsert_entries([dict(row,title='',poster='',background='',position=400,percent=40,ext_updated_at=200)],mark_dirty=False)
            saved=db.list_continue_items()[0]
            self.assertEqual(saved['title'],'Real title');self.assertEqual(saved['poster'],'cover');self.assertEqual(saved['background'],'backdrop')
            self.assertEqual(saved['position'],400);self.assertEqual(saved['updated_at'],200)

    def test_metadata_repair_is_persisted_without_changing_resume_or_timestamp(self):
        db=importlib.import_module(cw.__package__+'.dexhub.playback_store')
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(db,'DB_PATH',str(Path(tmp)/'progress.db')),mock.patch.object(db,'_DB_READY',False):
            db.upsert_entries([{'media_type':'tv','canonical_id':'tt1','video_id':'tt1:1:2','position':321,'duration':1000,'percent':32,'ext_updated_at':123}],mark_dirty=False)
            row={'title':'Unknown','progress_key':['tv','tt1','tt1:1:2'],'target':{'canonical_id':'tt1','media_type':'tv','video_id':'tt1:1:2'}}
            with mock.patch.object(cw.backend_api,'metadata',return_value={'name':'Actual title','poster':'cover','background':'backdrop'}):cw.enrich([row])
            saved=db.list_continue_items()[0]
            self.assertEqual(saved['title'],'Actual title');self.assertEqual(saved['poster'],'cover')
            self.assertEqual(saved['position'],321);self.assertEqual(saved['updated_at'],123);self.assertEqual(saved['percent'],32)

    def test_continue_resume_uses_start_offset_without_native_resume_prompt(self):
        p=kodi_stub.import_lib_module('plugin');item=mock.Mock();info={'title':'Title','resumetime':987.25,'duration':3600}
        p._apply_nuvio_resume_item(item,info,{'nuvio_request_id':'request','resume_seconds':987.25})
        self.assertNotIn('resumetime',info)
        item.setProperty.assert_called_once_with('StartOffset','987.25')

    def test_exact_resume_does_not_ignore_first_30_seconds_or_clamp_last_90(self):
        companion=kodi_stub.import_lib_module('companion')
        for target in (20.25,110.5):
            player=companion.CompanionPlayer.__new__(companion.CompanionPlayer)
            player.ctx={'resume_seconds':target,'nuvio_resume_exact':True};player._resume_applied=False;player._resume_in_progress=False;player._resume_generation=0
            player._player_looks_active=lambda **kw:True;player.getTotalTime=lambda:120;position=[0]
            player.getTime=lambda:position[0]
            player.seekTime=mock.Mock(side_effect=lambda value:position.__setitem__(0,value))
            with mock.patch.object(companion.threading,'Thread',side_effect=lambda target,**kw:SimpleNamespace(start=target)):
                player._apply_resume_async()
            player.seekTime.assert_called_once_with(target)
            self.assertTrue(player._resume_applied)

    def test_resume_flags_and_seconds_survive_session_handoff(self):
        p=kodi_stub.import_lib_module('plugin');target={}
        ctx={'nuvio_request_id':'request','nuvio_resume_exact':True,'resume_seconds':20.25}
        with mock.patch.object(p,'_compute_next_episode_hint',return_value=None),mock.patch.object(p,'_source_picker_url_from_ctx',return_value=''):
            p._augment_session_ctx(target,ctx,[])
        self.assertTrue(target['nuvio_resume_exact']);self.assertEqual(target['resume_seconds'],20.25)

    def test_continue_opens_saved_episode_directly_without_details_choice(self):
        details=importlib.import_module('nuvio_ui.details')
        ctx={'canonical_id':'tt1','media_type':'tv','video_id':'tt1:2:3','season':2,'episode':3,'resume_seconds':987.25}
        meta={'id':'tt1','type':'series'}
        trailers=importlib.import_module('nuvio_ui.trailers')
        local=importlib.import_module('resources.lib.continue_local')
        with mock.patch.object(playback,'job',return_value=meta),mock.patch.object(details,'choose_stream',return_value=True) as choose,mock.patch.object(details,'Details') as window,mock.patch.object(trailers,'wait_for_playback') as wait,mock.patch.object(local,'recent',return_value=[]):
            window.return_value.action='';window.return_value.context=ctx
            self.assertEqual(details.open_context(ctx),'')
        wait.assert_called_once();window.assert_called_once()
        self.assertEqual(choose.call_args.args[1]['video_id'],'tt1:2:3')

    def test_catalog_page_uses_raw_offset_and_retains_genre(self):
        client=kodi_stub.import_lib_module('dexhub.client')
        h=kodi_stub.import_lib_module('home_data')
        jobs=[{'provider':{'id':'p'},'catalog':{'id':'list','type':'movie','extra':[{'name':'skip'}]},'extra':{'genre':'Drama'},'offset':7,'done':False}]
        with mock.patch.object(client,'fetch_catalog',return_value={'metas':[{'id':'tt1'},{}]}) as fetch,mock.patch.object(h,'media_card',side_effect=lambda m,*a:m):rows,state=pages.fetch_page(jobs)
        self.assertEqual(fetch.call_args.kwargs['extra'],{'genre':'Drama','skip':7})
        self.assertEqual(state[0]['offset'],9);self.assertEqual(jobs[0]['offset'],7);self.assertEqual(rows,[{'id':'tt1'}])

    def test_focus_outlines_only_exist_on_active_row(self):
        root=ET.parse(ROOT/'script.nuvio/resources/skins/Default/1080i/nuvio_home.xml')
        ids=[x.get('id') for x in root.findall('.//control') if x.get('id')]
        self.assertEqual(len(ids),len(set(ids)))
        for row in root.findall('.//control[@type="list"]'):
            for c in row.findall('focusedlayout/control'):
                if '_focus.png' in c.findtext('texture',''):self.assertIn('Control.HasFocus('+row.get('id')+')',c.findtext('visible',''))

    def test_screensaver_has_no_actions_or_buttons(self):
        root=ET.parse(ROOT/'script.nuvio/resources/skins/Default/1080i/nuvio_screensaver.xml')
        self.assertFalse(root.findall('.//onclick'));self.assertFalse(root.findall('.//control[@type="button"]'))

    def test_stream_glyph_cleanup_keeps_release_details(self):
        cleaned=playback.plain_label('🔥 [B]4K HEVC[/B] ⚡ 12.5 GB\nHrvatski čćžšđ · HDR')
        self.assertIn('4K HEVC',cleaned);self.assertIn('12.5 GB',cleaned);self.assertIn('čćžšđ',cleaned)
        self.assertNotIn('🔥',cleaned)

    def test_automatic_preview_never_resolves_youtube(self):
        meta={'trailerStreams':[{'ytId':'abcdefghijk'},{'url':'https://example.test/clip.mp4'}]}
        self.assertEqual(support.trailer_url(meta,allow_youtube=False),'https://example.test/clip.mp4')
        self.assertEqual(support.trailer_url({'trailers':[{'source':'abcdefghijk'}]},allow_youtube=False),'')

    def test_preview_close_does_not_wait_for_player_play(self):
        entered=threading.Event();release=threading.Event();props={}
        row={'title':'Title','target':{'canonical_id':'preview-lock-test','media_type':'movie'}}
        window=SimpleNamespace(setProperty=lambda k,v:props.__setitem__(k,v),preview_selection=lambda:('key',row))
        controller=preview.Controller(window);controller.player.token='unit-preview';controller.player.isPlaying=lambda:False
        controller.player.play=mock.Mock(side_effect=AssertionError('Network worker must not touch Player'))
        def resolve(*args):entered.set();release.wait(2);return 'https://example.test/clip.mp4'
        with mock.patch.object(controller,'_resolve',side_effect=resolve):
            worker=threading.Thread(target=controller._work,args=('key',row,True,'unit-preview',threading.Event()));worker.start()
            self.assertTrue(entered.wait(1));before=time.monotonic();controller.close()
            self.assertLess(time.monotonic()-before,.1)
            release.set();worker.join(1)
        self.assertTrue(controller.player.cancelled)
        controller.player.play.assert_not_called()

    def test_xtream_credentials_are_url_encoded_not_concatenated(self):
        m3u,epg=iptv.xtream_urls('https://tv.example:8443','name&x','pass?&!')
        self.assertIn('username=name%26x',m3u);self.assertIn('password=pass%3F%26%21',epg)
        self.assertNotIn('name&x',m3u)

    def test_iptv_instance_does_not_overwrite_another_playlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            original=Path(tmp)/'instance-settings-90100.xml';original.write_text('<settings><setting id="kodi_addon_instance_name">Other</setting></settings>')
            before=original.read_bytes();iid=iptv.write_instance(tmp,'https://example.test/tv.m3u','https://example.test/epg.xml')
            self.assertEqual(iid,90101);self.assertEqual(original.read_bytes(),before)
            values={s.get('id'):s.text for s in ET.parse(Path(tmp)/f'instance-settings-{iid}.xml').getroot()}
            self.assertEqual(values['m3uUrl'],'https://example.test/tv.m3u');self.assertEqual(values['epgUrl'],'https://example.test/epg.xml')

    def test_all_croatian_releases_remain_individually_selectable(self):
        rows=[{'lang':('hr','hrv','cro','Croatian')[i%4],'url':f'https://example.test/{i}.srt','displayName':f'release{i}'} for i in range(14)]
        groups=subs.group_rows(rows)
        self.assertEqual(list(groups),['hr']);self.assertEqual(len(groups['hr']),14)
        self.assertEqual(groups['hr'][13]['displayName'],'release13')

    def test_subtitle_search_includes_nuvio_providers_even_when_aio_has_rows(self):
        context={'subtitles':[{'lang':'hr','url':'https://example.test/a.srt','sourceType':'stream'}]}
        with mock.patch.object(subs.broker,'search_subtitles',return_value=[{'lang':'hrv','url':'https://example.test/b.srt','sourceName':'Nuvio provider'}]) as search:
            rows=subs.external_rows(context,search=True)
        self.assertEqual(len(rows),2);self.assertEqual(search.call_args.kwargs['initial_subtitles'],[])
        self.assertEqual([r['lang'] for r in rows],['hr','hr'])

    def test_only_the_chosen_subtitle_is_downloaded(self):
        files=kodi_stub.import_lib_module('playback.subtitle_files');chosen={'lang':'hr','url':'https://example.test/14.srt'}
        with mock.patch.object(files,'_prepare_subtitle_files',return_value=[{'path':'/local/chosen.hr.srt'}]) as prepare:
            self.assertEqual(subs.prepare_selected(chosen,'video'),'/local/chosen.hr.srt')
        self.assertEqual(prepare.call_args.args[0],[chosen])

if __name__=='__main__':unittest.main()
