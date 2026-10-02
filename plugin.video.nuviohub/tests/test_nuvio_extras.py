"""Behavioral regression checks for collections, onboarding and playback ownership."""
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
import importlib
from unittest import mock

import kodi_stub

c = kodi_stub.import_lib_module('collections_home')
h = kodi_stub.import_lib_module('home_data')
w = kodi_stub.import_lib_module('setup_wizard')
s = kodi_stub.import_lib_module('skip_service')
import frontend_test_support
frontend_test_support.install()
t = importlib.import_module('nuvio_ui.home_trailers')
i18n = kodi_stub.import_lib_module('i18n')
ROOT = Path(kodi_stub.ADDON_ROOT)


def aio():
    return {'id': 'installed-aio', 'manifest': {'id': 'aio-metadata', 'resources': ['catalog', {'name': 'meta'}],
            'catalogs': [{'id': 'tvdb.trending', 'type': mt} for mt in ('movie','series')]}}


class CollectionsTests(unittest.TestCase):
    def setUp(self):
        # These tests cover a deliberately imported preset, not first-run defaults.
        profile=importlib.import_module('resources.lib.collection_profile')
        patch=mock.patch.object(c,'groups',return_value=profile.defaults())
        patch.start();self.addCleanup(patch.stop)
        switches=mock.patch('resources.lib.metadata_providers.entries',return_value=[(aio(),True)])
        switches.start();self.addCleanup(switches.stop)

    def test_artwork_is_bundled_and_promotional_fields_removed(self):
        groups = c.groups()
        self.assertEqual(sum(len(g['folders']) for g in groups),69)
        for group in groups:
            for folder in group['folders']:
                self.assertEqual(set(folder) - {'id','title','sources','cover','backdrop','animation','hideTitle','hidden'}, set())
                for field in ('cover','backdrop'):
                    if folder.get(field): self.assertTrue((ROOT/folder[field]).is_file())

    def test_provider_name_cannot_spoof_manifest_identity(self):
        source = {'addonId':'aio-metadata','catalogId':'tvdb.trending','type':'series'}
        provider = aio()
        self.assertEqual(c.matching_catalog(source,[provider])[0]['id'],'installed-aio')
        provider['manifest']['id']='different'
        provider['name']='AIOMetadata'
        # 6.0.36: the catalog itself (not the name) connects another instance.
        self.assertEqual(c.matching_catalog(source,[provider])[0]['id'],'installed-aio')
        provider['manifest']['catalogs']=[x for x in provider['manifest']['catalogs'] if x.get('id')!='tvdb.trending']
        self.assertIsNone(c.matching_catalog(source,[provider]))

    def test_genre_filter_is_preserved(self):
        folder = c.find_collection('collections.discover.recommended')
        shelf = c.folder_shelf(folder,[aio()])
        self.assertEqual(len(shelf['collection_job']),2)
        self.assertEqual(shelf['collection_job'][0][2],{'genre':'Action'})

    def test_absent_provider_is_actionable_and_never_fabricates_titles(self):
        shelf = c.folder_shelf(c.find_collection('collections.discover.recommended'),[])
        self.assertNotIn('collection_job',shelf)
        self.assertIn('action=first_run_wizard',shelf['rows'][0]['path'])

    def test_home_order_includes_streaming_after_trending(self):
        api = SimpleNamespace(_home_row_visible=lambda key:key=='continue',
                              _setting=lambda *args:'false',
                              _home_payload=lambda **kw:{'continue':[]},build_url=lambda **kw:'plugin://plugin.video.nuviohub/?'+kw['action'])
        with mock.patch.object(h,'_api',return_value=api), mock.patch('nuviolib.backend_api.provider',return_value={'id':'meta'}):
            shelves=h.initial_shelves()
        self.assertEqual([r['title'] for r in shelves[:4]],['Continue Watching','Discover','Streaming Services','Genres'])
        self.assertEqual(shelves[2]['rows'][0]['title'],'Netflix')
        self.assertEqual(shelves[2]['shape'],'landscape')


class WizardTests(unittest.TestCase):
    def test_catalog_is_not_mistaken_for_stream_provider(self):
        self.assertEqual(w.status([aio()]),{'aio':True,'catalog':True,'stream':False})

    def test_metadata_preserves_deliberate_custom_mapping(self):
        settings={'provider_meta_map':json.dumps({'other':'tmdb_helper'})}
        addon=SimpleNamespace(getSetting=lambda k:settings.get(k,''),setSetting=lambda k,v:settings.__setitem__(k,v))
        self.assertTrue(w.configure_metadata(addon,[aio(),{'id':'other'},{'id':'new'}]))
        self.assertEqual(json.loads(settings['provider_meta_map']),{'other':'tmdb_helper','new':'installed-aio','installed-aio':'native'})

    def test_cancel_does_not_mark_setup_complete(self):
        settings={}
        addon=SimpleNamespace(getSetting=lambda k:settings.get(k,''),setSetting=lambda k,v:settings.__setitem__(k,v))
        dialog=SimpleNamespace(select=lambda *args:-1)
        with mock.patch.object(w.xbmcaddon,'Addon',return_value=addon),mock.patch.object(w.xbmcgui,'Dialog',return_value=dialog):
            self.assertFalse(w.run())
        self.assertNotIn('nuvio_wizard_applied',settings)

    def test_legacy_arabic_selection_always_uses_english(self):
        with mock.patch.object(i18n.ADDON,'getSetting',return_value='Arabic'):
            self.assertEqual(i18n._read_language_setting(),'en')


class SkipTests(unittest.TestCase):
    def test_movie_and_episode_identity(self):
        self.assertEqual(s.query_params({'media_type':'movie','imdb_id':'tt123'},100)['imdb_id'],'tt123')
        self.assertIsNone(s.query_params({'media_type':'series','imdb_id':'tt123'},100))
        self.assertEqual(s.query_params({'media_type':'series','tmdb_id':'99','season':1,'episode':2},120)['duration_ms'],120000)
        self.assertIsNone(s.query_params({'media_type':'movie','imdb_id':'tt123&bad=1'},100))

    def test_invalid_api_timestamps_never_seek(self):
        payload={'intro':[{'end_ms':float('nan')},{'end_ms':-1},{'end_ms':200000},{'end_ms':'bad'}]}
        self.assertEqual(s.normalize_segments(payload,100),[])

    def test_null_credits_end_is_bounded_to_media(self):
        self.assertEqual(s.normalize_segments({'credits':[{'start_ms':95000,'end_ms':None}]},100),
                         [{'type':'credits','start':95,'end':99.25}])

    def test_pick_best_timing_candidate(self):
        payload={'intro':[{'start_ms':0,'end_ms':10000,'confidence':0.2},{'start_ms':5000,'end_ms':15000,'confidence':0.9}]}
        self.assertEqual(s.normalize_segments(payload,100),[{'type':'intro','start':5,'end':15}])

    def test_other_playback_and_stale_uids_are_never_owned(self):
        player=SimpleNamespace(_foreign_active=False,_active_playback_uid='new',ctx={'playback_uid':'new'},
                               _last_started_file='our-stream',isPlayingVideo=lambda:True,getPlayingFile=lambda:'our-stream')
        self.assertTrue(s.owns_playback(player,'new'))
        self.assertFalse(s.owns_playback(player,'old'))
        player.getPlayingFile=lambda:'foreign-stream'
        self.assertFalse(s.owns_playback(player,'new'))
        player._foreign_active=True
        self.assertFalse(s.owns_playback(player,'new'))

    def test_lookup_no_ids_makes_no_network_request(self):
        with mock.patch.object(s,'urlopen') as network:
            self.assertEqual(s.lookup({},100),[])
            network.assert_not_called()


class TrailerTests(unittest.TestCase):
    def test_youtube_and_direct_clips(self):
        self.assertEqual(t.trailer_url({'trailers':[{'source':'abcdefghijk'}]}),'plugin://plugin.video.youtube/play/?video_id=abcdefghijk')
        self.assertEqual(t.trailer_url({'trailer':'https://youtu.be/abcdefghijk'}),'plugin://plugin.video.youtube/play/?video_id=abcdefghijk')
        self.assertEqual(t.trailer_url({'trailer':'https://example.com/trailer.mp4'}),'https://example.com/trailer.mp4')

    def test_arbitrary_plugin_or_builtin_is_not_a_trailer(self):
        for value in ('RunScript(bad)','plugin://plugin.bad/?action=run','https://example.com/page','https://example.com/a.mp4|x=y'):
            self.assertEqual(t.trailer_url({'trailer':value}),'')

    def test_preview_cancel_never_stops_foreign_playback(self):
        player=t.PreviewPlayer()
        player.token='ours'
        player.isPlayingVideo=lambda:True
        player.path='preview.mp4';player.getPlayingFile=lambda:'foreign.mp4'
        player.stop=mock.Mock()
        player.cancel()
        player.stop.assert_not_called()
        player.getPlayingFile=lambda:'preview.mp4'
        player.cancel()
        with mock.patch.object(t.xbmcgui,'Window',return_value=SimpleNamespace(getProperty=lambda key:'ours')),mock.patch.object(t.xbmc,'executebuiltin') as stop:
            player.stop_owned();player.stop_owned()
            stop.assert_called_once_with('PlayerControl(Stop)')
        player.stop.assert_not_called()


if __name__=='__main__': unittest.main()
