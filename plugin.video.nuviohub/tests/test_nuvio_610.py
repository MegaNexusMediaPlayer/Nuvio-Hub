"""6.0.10 behavior contracts. HTTP and Kodi GUI are fakes, SQLite is real.

No test in this file claims a Kodi device, real account or glyph rendering pass.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
import frontend_test_support
frontend_test_support.install()
from resources.lib import (backend_api as api, metadata_providers as providers,
    resource_support as support, collection_validation as validation,
    collection_profile as profiles, collections_home as collections,
    browse_cache as cache, display_text, progress_model as model,
    nuvio_progress as outbox, progress_sync)
from resources.lib.nuviohub import store, client
from nuviohub import playback_store as db
from nuviohub.nuvio_stremio_sync import Nuvio
from nuvio_ui import setup_gate, browse_meta, home_window, startup
import kodi_stub
ROOT=Path(kodi_stub.ADDON_ROOT).parent


def source(pid='p', mid='meta.fixture', catalog='popular'):
    return {'id':pid,'name':pid,'base_url':'https://example.invalid/private-token',
            'manifest_url':'https://example.invalid/private-token/manifest.json',
            'manifest':{'id':mid,'name':'Fixture','version':'1',
                        'resources':['meta','catalog','stream'],'types':['movie','series'],
                        'idPrefixes':['tt','tmdb:'],
                        'catalogs':[{'id':catalog,'type':'movie','extra':[{'name':'genre','options':['Action','Drama']}]}]}}


def layout(pid='p', mid='meta.fixture'):
    return profiles.normalize([{'id':'g','title':'Test','folders':[{'id':'f','title':'Films',
        'sources':[{'addonId':mid,'providerId':pid,'catalogId':'popular','type':'movie','genre':'Action'}]}]}])


class ProviderFixture(unittest.TestCase):
    def setUp(self):
        self.sources=[source()]
        self.values={providers.SETTING:json.dumps([{'id':'p','enabled':True}])}
        values=self.values
        class Addon(kodi_stub._Addon):
            def getSetting(self,key):return values.get(key,'')
            def setSetting(self,key,value):values[key]=value
        self.stack=[mock.patch.object(providers.xbmcaddon,'Addon',Addon),
                    mock.patch.object(store,'list_providers',side_effect=lambda:self.sources)]
        for patch in self.stack:patch.start();self.addCleanup(patch.stop)


class Capabilities(ProviderFixture):
    def test_object_filters_do_not_inherit_global_prefixes(self):
        p=source();p['manifest']['resources']=[{'name':'meta','types':['movie']}]
        self.assertTrue(support.supports(p,'meta','movie','custom:12'))
    def test_string_resource_inherits_global_filters(self):
        self.assertFalse(support.supports(source(),'meta','movie','custom:12'))
    def test_object_empty_prefixes_support_nothing(self):
        p=source();p['manifest']['resources']=[{'name':'meta','idPrefixes':[]}]
        self.assertFalse(support.supports(p,'meta','movie','tt1'))
    def test_wrong_resource_type_is_rejected(self):
        self.assertFalse(support.supports(source(),'meta','person','tt1'))
    def test_off_provider_never_resurrects_as_preferred(self):
        self.values[providers.SETTING]='[{"id":"p","enabled":false}]'
        self.assertEqual(providers.enabled('movie','tt1',preferred='p'),[])
    def test_new_provider_requires_opt_in(self):
        self.sources.append(source('second'))
        self.assertEqual([p['id'] for p in providers.enabled()],['p'])
    def test_malformed_switches_fail_closed(self):
        for raw in ('invalid','{}','null'):
            self.values[providers.SETTING]=raw
            self.assertEqual(providers.enabled(),[])
    def test_switches_persist_each_provider_independently(self):
        self.sources.append(source('second'));providers.set_enabled('second',True)
        self.assertEqual({p['id'] for p in providers.enabled()},{'p','second'})
        providers.set_enabled('p',False)
        self.assertEqual([p['id'] for p in providers.enabled()],['second'])
    def test_signature_changes_with_endpoint_configuration(self):
        first=providers.signature();self.sources[0]['base_url']+='changed'
        self.assertNotEqual(first,providers.signature())
    def test_explicit_external_id_alias_is_valid(self):
        self.assertTrue(support.same_identity({'id':'internal:1','ids':{'imdb':'tt1'},'type':'movie'},'movie','tt1'))
    def test_unrelated_id_is_not_relabelled(self):
        self.assertFalse(support.same_identity({'id':'tt2','name':'Same title'},'movie','tt1'))
    def test_matching_id_wrong_media_type_is_rejected(self):
        self.assertFalse(support.same_identity({'id':'tt1','type':'series'},'movie','tt1'))
    def test_metadata_falls_back_after_wrong_identity(self):
        self.sources.append(source('second'));providers.set_enabled('second',True)
        with mock.patch.object(client,'fetch_meta',side_effect=[{'meta':{'id':'other'}},{'meta':{'id':'tt1','name':'Verified'}}]) as get:
            result=api.metadata('movie','tt1')
        self.assertEqual(get.call_count,2);self.assertEqual(result['_nuvio_metadata_provider'],'second')
    def test_metadata_falls_back_after_timeout(self):
        self.sources.append(source('second'));providers.set_enabled('second',True)
        with mock.patch.object(client,'fetch_meta',side_effect=[TimeoutError(),{'meta':{'id':'tt1'}}]):
            self.assertEqual(api.metadata('movie','tt1')['id'],'tt1')
    def test_metadata_failure_does_not_expose_configured_tokens(self):
        with mock.patch.object(client,'fetch_meta',side_effect=ValueError('https://example.invalid/private-token')):
            with self.assertRaises(ValueError) as caught:api.metadata('movie','tt1')
        self.assertNotIn('private-token',str(caught.exception))


class Collections(ProviderFixture):
    def setUp(self):
        super().setUp();self.groups=layout()
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.path=Path(temp.name)/'collections.json'
        patches=[mock.patch.object(profiles,'profile_file',return_value=self.path),
            mock.patch.object(cache,'_CACHE',cache.Cache(Path(temp.name)/'browse.db')),
            mock.patch.object(client,'fetch_catalog',return_value={'metas':[{'id':'tt1','type':'movie'},{'id':'tt2','type':'movie'}]}),
            mock.patch.object(client,'fetch_meta',side_effect=lambda p,t,mid,**kw:{'meta':{'id':mid,'type':t}})]
        for patch in patches:patch.start();self.addCleanup(patch.stop)
    def test_new_install_has_no_implicit_presets(self):
        self.assertEqual(profiles.load(),[])
    def test_valid_collection_proof_survives_restart(self):
        proof=validation.validate(self.groups);self.assertTrue(proof['ok'])
        self.assertEqual(profiles.save(self.groups,validation=proof),1)
        self.assertEqual(profiles.load(),self.groups)
        self.assertIsNotNone(validation.stored_proof(profiles.load()))
    def test_unknown_catalog_is_saved_and_only_reported(self):
        # 6.0.15: collections never block; a missing catalog stays empty on Home.
        profiles.save(self.groups)
        changed=copy.deepcopy(self.groups);changed[0]['folders'][0]['sources'][0]['addonId']='unrelated'
        self.assertEqual(profiles.save(changed),1)
        self.assertEqual(profiles.load()[0]['folders'][0]['sources'][0]['addonId'],'unrelated')
        report=validation.validate(changed)
        self.assertFalse(report['ok']);self.assertTrue(report['skipped'])
    def test_wrong_metadata_sample_fails(self):
        with mock.patch.object(client,'fetch_meta',return_value={'meta':{'id':'tt999'}}):
            self.assertFalse(validation.validate(self.groups)['ok'])
    def test_empty_catalog_is_a_warning_not_a_block(self):
        # 6.0.11: a temporarily empty catalog no longer rejects the whole import.
        with mock.patch.object(client,'fetch_catalog',return_value={'metas':[]}):
            proof=validation.validate(self.groups)
        self.assertTrue(proof['ok']);self.assertTrue(any('empty' in w for w in proof['warnings']))
    def test_wrong_catalog_item_type_fails(self):
        with mock.patch.object(client,'fetch_catalog',return_value={'metas':[{'id':'tt1','type':'series'}]}):
            self.assertFalse(validation.validate(self.groups)['ok'])
    def test_missing_required_filter_fails_before_http(self):
        self.sources[0]['manifest']['catalogs'][0]['extra'].append({'name':'country','isRequired':True})
        with mock.patch.object(client,'fetch_catalog') as fetch:
            self.assertFalse(validation.validate(self.groups)['ok']);fetch.assert_not_called()
    def test_unlisted_filter_option_is_a_warning(self):
        # 6.0.11: Nuvio exports may use values the manifest does not list.
        self.groups[0]['folders'][0]['sources'][0]['genre']='MadeUp'
        proof=validation.validate(self.groups)
        self.assertTrue(proof['ok']);self.assertTrue(any('not offered' in w for w in proof['warnings']))
    def test_legacy_required_filters_supported(self):
        self.assertTrue(validation.filter_error({'extraRequired':['search'],'extraSupported':['search']},{}))
        self.assertEqual(validation.filter_error({'extraRequired':['search'],'extraSupported':['search']},{'search':'Actor'}),'')
    def test_duplicate_installs_prefer_binding_then_enabled_metadata(self):
        # 6.0.11: Nuvio exports carry no local provider ID; a duplicate install
        # resolves to the enabled metadata add-on instead of failing.
        self.sources.append(source('second'));ref=self.groups[0]['folders'][0]['sources'][0];ref['providerId']=''
        self.assertEqual(collections.matching_catalog(ref,self.sources)[0]['id'],'p')
        ref['providerId']='second';self.assertEqual(collections.matching_catalog(ref,self.sources)[0]['id'],'second')
        ref['providerId']='unknown-remote-id';self.assertEqual(collections.matching_catalog(ref,self.sources)[0]['id'],'p')
    def test_cancelled_check_is_only_a_report(self):
        # 6.0.15: the check is a report stored next to the layout, never a gate.
        proof=validation.validate(self.groups,stopped=lambda:True)
        self.assertFalse(proof['ok'])
        self.assertEqual(profiles.save(self.groups,validation=proof),1)
        self.assertEqual(profiles.load(),self.groups)
    def test_settings_change_invalidates_proof(self):
        proof=validation.validate(self.groups);providers.set_enabled('p',False)
        self.assertFalse(validation.accepts(self.groups,proof))
    def test_adding_only_streams_does_not_invalidate_collections(self):
        proof=validation.validate(self.groups);new=source('stream','stream.only');new['manifest']['resources']=['stream'];new['manifest']['catalogs']=[]
        self.sources.append(new);self.assertTrue(validation.accepts(self.groups,proof))
    def test_collection_title_and_picture_edits_do_not_require_network(self):
        proof=validation.validate(self.groups);self.groups[0]['folders'][0].update(title='晚上 🎬',cover='custom.jpg')
        self.assertTrue(validation.accepts(self.groups,proof))
    def test_catalog_only_provider_can_use_separate_metadata(self):
        self.sources[0]['manifest']['resources']=['catalog']
        self.sources.append(source('metadata','other.meta'));providers.set_enabled('metadata',True)
        self.assertTrue(validation.validate(self.groups)['ok'])
    def test_accountless_setup_is_ready_with_verified_addons(self):
        profiles.save(self.groups)
        with mock.patch.object(setup_gate.stream_providers,'enabled',return_value=[self.sources[0]]),mock.patch.object(Nuvio,'is_linked',return_value=False):
            self.assertTrue(setup_gate.ready())
    def test_missing_collection_is_not_ready_even_with_addons(self):
        with mock.patch.object(setup_gate.stream_providers,'enabled',return_value=self.sources):self.assertFalse(setup_gate.ready())
    def test_empty_export_does_not_erase_current_layout(self):
        profiles.save(self.groups);before=self.path.read_bytes()
        with self.assertRaises(ValueError):profiles.save([])
        self.assertEqual(self.path.read_bytes(),before)


class ByteCache(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.path=Path(temp.name)/'cache.db'
        self.clock=[100];self.cache=cache.Cache(self.path,ram_limit=100,disk_limit=220,clock=lambda:self.clock[0])
    def test_byte_eviction_not_item_count(self):
        for n in range(10):self.cache.put(str(n),{'text':'x'*35})
        self.assertLessEqual(self.cache.bytes,100)
        conn=sqlite3.connect(self.path)
        try:self.assertLessEqual(conn.execute('SELECT SUM(bytes) FROM cache').fetchone()[0],220)
        finally:conn.close()
    def test_ttl_expiry(self):
        self.cache.put('a',{'title':'一'},ttl=2);self.clock[0]=103
        self.assertIsNone(self.cache.get('a'))
    def test_restart_reads_disk_and_promotes_to_ram(self):
        self.cache.put('a',{'title':'東京'});second=cache.Cache(self.path,clock=lambda:100)
        self.assertIsNone(second.get('a',memory_only=True))
        self.assertEqual(second.get('a'),{'title':'東京'})
        self.assertIsNotNone(second.get('a',memory_only=True))
    def test_each_read_is_an_isolated_copy(self):
        self.cache.put('a',{'rows':[1]});self.cache.get('a')['rows'].append(2)
        self.assertEqual(self.cache.get('a')['rows'],[1])
    def test_memory_peek_never_opens_sqlite(self):
        with mock.patch.object(self.cache,'_connect',side_effect=AssertionError('GUI disk access')):
            self.assertIsNone(self.cache.get('missing',memory_only=True))
    def test_large_entry_is_rejected(self):
        self.assertFalse(self.cache.put('a',{'text':'x'*300}));self.assertEqual(self.cache.bytes,0)
    def test_explicit_clear_erases_disk_and_memory(self):
        self.cache.put('a',{'x':1});self.cache.clear();self.assertIsNone(self.cache.get('a'));self.assertEqual(self.cache.bytes,0)
    def test_keys_include_provider_configuration_and_filters(self):
        p=source();c=p['manifest']['catalogs'][0];a=cache.catalog_key(p,c,{'genre':'Action'})
        self.assertNotEqual(a,cache.catalog_key(p,c,{'genre':'Drama'}));p['base_url']+='new'
        self.assertNotEqual(a,cache.catalog_key(p,c,{'genre':'Action'}));self.assertNotIn('private-token',a)
    def test_duplicate_catalog_requests_share_one_network_call(self):
        p=source();c=p['manifest']['catalogs'][0];entered=threading.Event();release=threading.Event()
        def load(*args,**kwargs):entered.set();release.wait(2);return {'metas':[{'id':'tt1'}]}
        big=cache.Cache(self.path.with_name('big.db'))
        with mock.patch.object(cache,'instance',return_value=big),mock.patch.object(client,'fetch_catalog',side_effect=load) as get,ThreadPoolExecutor(2) as pool:
            first=pool.submit(cache.catalog,p,c);self.assertTrue(entered.wait(1));second=pool.submit(cache.catalog,p,c)
            time.sleep(.03);release.set();self.assertEqual(first.result(2),second.result(2));get.assert_called_once()
    def test_empty_transient_catalog_is_not_cached(self):
        p=source();c=p['manifest']['catalogs'][0]
        with mock.patch.object(cache,'instance',return_value=self.cache),mock.patch.object(client,'fetch_catalog',return_value={'metas':[]}) as get:
            cache.catalog(p,c);cache.catalog(p,c);self.assertEqual(get.call_count,2)
    def test_settings_clear_keeps_persistent_cache(self):
        with mock.patch.object(cache,'instance',return_value=self.cache):
            self.cache.put('a',{'x':1});browse_meta.clear();self.assertIsNotNone(self.cache.get('a'))
            browse_meta.clear(persistent=True);self.assertIsNone(self.cache.get('a'))


class ProgressWire(unittest.TestCase):
    def row(self,**kwargs):
        return dict(dict(media_type='series',canonical_id='tt123',video_id='tt123:2:3',season=2,episode=3,position=25.25,duration=100,updated_at=1700000000.25),**kwargs)
    def test_wire_uses_milliseconds_and_nuvio_episode_key(self):
        row=model.to_wire(self.row());self.assertEqual(row['position'],25250);self.assertEqual(row['duration'],100000)
        self.assertEqual(row['last_watched'],1700000000250);self.assertEqual(row['progress_key'],'tt123_s2e3')
    def test_wire_round_trip_retains_fractional_seconds(self):
        row=model.from_wire(model.to_wire(self.row()));self.assertEqual(row['position'],25.25);self.assertEqual(row['updated_at'],1700000000.25)
    def test_legacy_millisecond_db_timestamp_normalizes(self):
        self.assertEqual(model.timestamp(1700000000250),1700000000.25)
    def test_unknown_runtime_is_not_fabricated(self):
        self.assertIsNone(model.to_wire(self.row(duration=0,percent=55)))
    def test_invalid_episode_is_not_uploaded_as_movie(self):
        self.assertIsNone(model.to_wire(self.row(season=None,episode=None,video_id='tt123')))
    def test_special_season_zero_works(self):
        self.assertEqual(model.to_wire(self.row(season=0))['progress_key'],'tt123_s0e3')
    def test_completion_normalizes_to_end(self):
        self.assertEqual(model.to_wire(self.row(position=95))['position'],100000)
    def test_movie_key_is_not_prefixed_with_type(self):
        row=self.row(media_type='movie',season=None,episode=None,video_id='tt123')
        self.assertEqual(model.to_wire(row)['progress_key'],'tt123')
    def test_nonfinite_numbers_are_safe(self):
        self.assertIsNone(model.to_wire(self.row(duration=float('nan'))))
        self.assertEqual(model.number(float('inf')),0)
    def test_explicit_alias_joins_tmdb_and_imdb(self):
        self.assertEqual(model.identity(self.row(canonical_id='tmdb:12',imdb_id='tt123')),model.identity(self.row()))


class DurableOutbox(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.scope='account-A/profile-1'
        for patch in (mock.patch.object(db,'DB_PATH',str(Path(temp.name)/'playback.db')),mock.patch.object(db,'_DB_READY',False),mock.patch.object(outbox,'scope',side_effect=lambda:self.scope)):
            patch.start();self.addCleanup(patch.stop)
        db._ensure_db()
    def save(self,position=25,stamp=100):
        row=dict(media_type='movie',canonical_id='tt1',video_id='tt1',position=position,duration=100,percent=position,ext_updated_at=stamp,event_type='progress')
        db.upsert_entries([row]);return row
    def test_local_progress_is_durably_queued(self):
        self.save();self.assertEqual(len(outbox.pending()),1);self.assertEqual(outbox.pending()[0]['position'],25)
    def test_different_account_does_not_see_pending_history(self):
        self.save();self.scope='account-B/profile-1';self.assertEqual(outbox.pending(),[])
    def test_different_profile_does_not_see_pending_history(self):
        self.save();self.scope='account-A/profile-2';self.assertEqual(outbox.pending(),[])
    def test_new_heartbeat_survives_ack_for_old_request(self):
        self.save();old=outbox.pending();self.save(35,110);outbox.acknowledge(old,self.scope)
        self.assertEqual(outbox.pending()[0]['position'],35)
    def test_exact_ack_removes_only_sent_mutation(self):
        self.save();outbox.acknowledge(outbox.pending(),self.scope);self.assertEqual(outbox.pending(),[])
    def test_remote_import_does_not_echo_into_outbox(self):
        row=self.save();outbox.acknowledge(outbox.pending(),self.scope);row['ext_updated_at']=120
        db.upsert_entries([row],mark_dirty=False);self.assertEqual(outbox.pending(),[])
    def test_explicit_remove_queues_tombstone(self):
        self.save();db.delete_entry('movie','tt1','tt1');self.assertEqual(outbox.pending()[0]['_operation'],'delete')
        self.assertEqual(db.list_recent_items(),[])
    def test_explicit_watched_queues_completion(self):
        self.save();db.mark_watched('movie','tt1','tt1');self.assertEqual(outbox.pending()[0]['percent'],100)
        self.assertEqual(db.list_continue_items(),[])
    def test_remote_percentage_reuses_only_known_local_runtime(self):
        self.save();db.upsert_entries([dict(media_type='movie',canonical_id='tt1',video_id='tt1',position=0,duration=0,percent=60,ext_updated_at=200)],mark_dirty=False)
        row=db.list_recent_items()[0];self.assertEqual(row['duration'],100);self.assertEqual(row['position'],60)
    def test_old_progress_cannot_overwrite_newer_stop(self):
        self.save(40,200);self.save(25,100);self.assertEqual(db.list_recent_items()[0]['position'],40)
        self.assertEqual(outbox.pending()[0]['position'],40)
    def test_account_switch_prevents_ack(self):
        self.save();rows=outbox.pending();account=self.scope;self.scope='other'
        outbox.acknowledge(rows,account);self.scope=account;self.assertEqual(len(outbox.pending()),1)


class CloudConflict(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.remote=[];self.account='A'
        def rpc(method,body):
            self.calls.append((method,body));return self.remote if method=='sync_pull_watch_progress' else None
        for patch in (mock.patch.object(Nuvio,'_profile_id',return_value=1),mock.patch.object(Nuvio,'_rpc',side_effect=rpc),mock.patch.object(outbox,'scope',side_effect=lambda:self.account),mock.patch.object(outbox,'acknowledge')):
            patch.start();self.addCleanup(patch.stop)
        self.local=dict(media_type='movie',canonical_id='tt1',video_id='tt1',position=20,duration=100,updated_at=1700000100)
    def test_pull_happens_before_push(self):
        Nuvio.sync_progress([self.local]);self.assertEqual([x[0] for x in self.calls],['sync_pull_watch_progress','sync_push_watch_progress'])
    def test_newer_remote_progress_is_not_rolled_back(self):
        self.remote=[model.to_wire(dict(self.local,position=70,updated_at=1700000200))]
        rows=Nuvio.sync_progress([self.local]);self.assertEqual(rows[0]['position'],70)
        self.assertEqual(len(self.calls),1)
    def test_newer_local_progress_pushes_exact_units(self):
        self.remote=[model.to_wire(dict(self.local,position=10,updated_at=1700000050))]
        Nuvio.sync_progress([self.local]);self.assertEqual(self.calls[1][1]['p_entries'][0]['position'],20000)
    def test_pull_only_does_not_upload_pending_entries(self):
        Nuvio.sync_progress([self.local],direction='pull');self.assertEqual(len(self.calls),1)
    def test_unknown_runtime_does_not_push_invented_position(self):
        Nuvio.sync_progress([dict(self.local,duration=0,percent=60)]);self.assertEqual(len(self.calls),1)
    def test_failed_push_is_not_acknowledged(self):
        with mock.patch.object(Nuvio,'_rpc',side_effect=[[],TimeoutError()]),mock.patch.object(outbox,'acknowledge') as ack:
            with self.assertRaises(TimeoutError):Nuvio.sync_progress([self.local])
            ack.assert_not_called()
    def test_profile_switch_aborts_cross_profile_write(self):
        def switch(*args):self.account='B';return []
        with mock.patch.object(Nuvio,'_rpc',side_effect=switch):
            with self.assertRaisesRegex(ValueError,'profile changed'):Nuvio.sync_progress([self.local])
    def test_remove_uses_nuvio_delete_rpc(self):
        Nuvio.sync_progress([dict(self.local,_operation='delete')]);self.assertEqual(self.calls[1][0],'sync_delete_watch_progress')
        self.assertEqual(self.calls[1][1]['p_keys'],['tt1'])


class PresentationAndCadence(unittest.TestCase):
    def test_cjk_emoji_zwj_and_names_are_not_translated(self):
        text='梁朝偉 · 李安 👨\u200d👩\u200d👧\u200d👦 🎬'
        self.assertEqual(display_text.clean(text),text)
    def test_nfc_composition_without_changing_words(self):
        self.assertEqual(display_text.clean('Jose\u0301\x00'),'José')
    def test_episode_line_uses_selected_season_when_missing(self):
        self.assertIn('Season 2 · Episode 3',display_text.episode_line({'episode':3,'season':None},2))
    def test_episode_line_includes_real_date_only(self):
        self.assertIn('Released 2020-01-01',display_text.episode_line({'season':2,'episode':1,'released':'2020-01-01T00:00:00Z'}))
        self.assertNotIn('Released',display_text.episode_line({'season':2,'episode':1,'released':'not a date'}))
    def test_future_release_is_labelled_airs(self):
        self.assertIn('Airs 2999-01-01',display_text.episode_line({'season':2,'episode':1,'released':'2999-01-01'}))
    def test_actor_layout_has_round_mask_and_separate_rows(self):
        xml=ET.parse(ROOT/'script.nuvio/resources/skins/Default/1080i/nuvio_person.xml')
        self.assertIsNotNone(xml.find(".//control[@id='500']"));self.assertIsNotNone(xml.find(".//control[@id='501']"))
        self.assertTrue(any('person_circle.png' in n.get('diffuse','') for n in xml.iter('texture')))
    def test_native_kodi_unicode_font_reference_not_bundled_font(self):
        xml=ET.parse(ROOT/'skin.nuvio/xml/Font.xml')
        self.assertTrue(all(n.text=='special://xbmc/media/Fonts/arial.ttf' for n in xml.iter('filename')))
    def test_plot_textboxes_have_autoscroll(self):
        for name in ('nuvio_details.xml','nuvio_details_landscape.xml','nuvio_home.xml','nuvio_home_compact.xml'):
            xml=ET.parse(ROOT/'script.nuvio/resources/skins/Default/1080i'/name)
            found=[n for n in xml.iter('control') if n.get('type')=='textbox' and 'plot' in (n.findtext('label') or '')]
            self.assertTrue(found,name);self.assertTrue(all(n.find('autoscroll') is not None for n in found),name)
    def test_startup_pool_is_bounded(self):
        self.assertEqual(startup.MAX_WORKERS,4);self.assertLessEqual(startup.MAX_STARTUP_SECONDS,40)
    def test_cache_budget_is_160_plus_40_mib_not_process_rss(self):
        from resources.lib import art_cache
        self.assertEqual(cache.RAM_LIMIT,40*1024*1024)
        self.assertEqual(art_cache.LIMITS['ram200'],160*1024*1024)
    def test_retry_after_is_respected_and_bounded(self):
        self.assertEqual(progress_sync.retry_delay(SimpleNamespace(headers={'Retry-After':'180'}),0),180)
        self.assertEqual(progress_sync.retry_delay(SimpleNamespace(headers={'Retry-After':'999999'}),0),3600)
    def test_backoff_grows_after_failures(self):
        self.assertEqual(progress_sync.retry_delay(Exception(),0),30)
        self.assertGreater(progress_sync.retry_delay(Exception(),3),30)
    def test_home_last_row_does_not_wrap(self):
        text=(ROOT/'script.nuvio/nuvio_ui/home_window.py').read_text()
        self.assertIn('else ROW_BASE+i',text[text.find('controlDown'):text.find('controlDown')+160])
    def test_trailer_default_and_full_option_exist(self):
        text=(ROOT/'script.nuvio/nuvio_ui/settings.py').read_text()
        self.assertIn('Full trailer',text)
        self.assertIn('90',(ROOT/'script.nuvio/nuvio_ui/home_trailers.py').read_text())

class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.time=0;self.props={};self.account='A';self.settings={'nuvio_progress_interval':'60','cloud_sync_interval_min':'30'}
        self.window=SimpleNamespace(getProperty=lambda k:self.props.get(k,''),clearProperty=lambda k:self.props.pop(k,None))
        self.scheduler=progress_sync.Scheduler(self.window,clock=lambda:self.time)
        self.sync=SimpleNamespace(enabled_targets=lambda:['nuvio'],_sections_for=lambda t:{'progress':True},run_sync=mock.Mock(return_value={'ok':True}))
        self.simkl=SimpleNamespace(enabled=lambda:False,authorized=lambda:False)
        for patch in (mock.patch.object(outbox,'scope',side_effect=lambda:self.account),mock.patch.object(outbox,'pending',return_value=[])):
            patch.start();self.addCleanup(patch.stop)
    def step(self):self.scheduler.step(self.sync,self.simkl,SimpleNamespace(getSetting=lambda k:self.settings.get(k,'')),threading.Lock())
    def test_regular_pull_cadence_is_sixty_seconds(self):
        self.step();self.time=59;self.step();self.assertEqual(self.sync.run_sync.call_count,1)
        self.time=60;self.step();self.assertEqual(self.sync.run_sync.call_count,2)
    def test_dirty_local_progress_pushes_before_regular_pull(self):
        self.step();self.time=1;self.props['nuviohub.sync_dirty']='event';self.step()
        self.time=6;self.step();self.assertEqual(self.sync.run_sync.call_count,2)
        self.assertNotIn('nuviohub.sync_dirty',self.props)
    def test_master_off_prevents_nuvio_sync(self):
        self.settings['cloud_sync_interval_min']='0';self.step();self.sync.run_sync.assert_not_called()
    def test_failed_cycle_retains_dirty_event_and_backs_off(self):
        self.sync.run_sync.return_value={'ok':False};self.props['nuviohub.sync_dirty']='event';self.step()
        self.time=10;self.step();self.assertEqual(self.sync.run_sync.call_count,1)
        self.assertEqual(self.props['nuviohub.sync_dirty'],'event')
        self.time=31;self.step();self.assertEqual(self.sync.run_sync.call_count,2)
    def test_profile_switch_requests_a_fresh_pull(self):
        self.step();self.account='B';self.time=1;self.step();self.assertEqual(self.sync.run_sync.call_count,2)
    def test_new_event_during_sync_is_not_cleared(self):
        self.props['nuviohub.sync_dirty']='first'
        def sync(**kwargs):self.props['nuviohub.sync_dirty']='second';return {'ok':True}
        self.sync.run_sync.side_effect=sync;self.step();self.assertEqual(self.props['nuviohub.sync_dirty'],'second')

if __name__=='__main__':unittest.main()


class CachePresetUpgradeTests(unittest.TestCase):
    def test_upgrade_preserves_explicit_non_ram_preferences(self):
        from resources.lib.art_cache import selected_mode
        class Settings:
            def __init__(self, mode): self.mode = mode
            def getSetting(self, key): return self.mode
            def setSetting(self, key, value): self.mode = value
        for previous, expected in (('ram150','ram200'), ('ram200','ram200'),
                                   ('disk246','disk246'), ('disk512','disk512'), ('off','off'), ('','ram200')):
            with self.subTest(previous=previous):
                settings=Settings(previous)
                self.assertEqual(selected_mode(settings), expected)
