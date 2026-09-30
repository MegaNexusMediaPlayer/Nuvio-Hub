"""Acceptance checks for the separate UI/skin and direct AIO provider boundary."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import zipfile

import kodi_stub
ROOT=Path(kodi_stub.ADDON_ROOT)
sys.path.insert(0,str(ROOT.parent/'script.nuvio'))
api=kodi_stub.import_lib_module('backend_api')
client=kodi_stub.import_lib_module('dexhub.client')
installer=kodi_stub.import_lib_module('bundle_installer')
bridge=kodi_stub.import_lib_module('frontend_bridge')
plugin=kodi_stub.import_lib_module('plugin')
import frontend_test_support
frontend_test_support.install()
details=importlib.import_module('nuvio_ui.details')


class DirectAIOTests(unittest.TestCase):
    def test_source_order_duplicates_and_formatter_text_are_untouched(self):
        source={'id':'aio','manifest_url':'https://example.test/manifest.json'}
        rows=[{'name':'720p first','url':'https://example.test/1'},
              {'name':'4K second','url':'https://example.test/2','behaviorHints':{'notWebReady':False}},
              {'name':'720p duplicate','url':'https://example.test/1'}]
        original=json.dumps(rows)
        with mock.patch.object(api,'provider',return_value=source),mock.patch.object(client,'get_json',return_value={'streams':rows}) as get:
            found,result=api.streams('movie','tt123')
        self.assertIs(result,rows)
        self.assertEqual(json.dumps(result),original)
        self.assertEqual(found,source)
        self.assertEqual(get.call_args.kwargs['ttl_seconds'],0)
        self.assertEqual(get.call_args.kwargs['retry'],False)

    def test_no_other_provider_is_used_when_aiostreams_is_missing(self):
        with mock.patch.object(api,'provider',return_value=None),mock.patch.object(client,'get_json') as get:
            with self.assertRaisesRegex(ValueError,'Connect AIOStreams'):api.streams('movie','tt123')
        get.assert_not_called()

    def test_metadata_keeps_the_requested_playback_identity(self):
        with mock.patch.object(api,'provider',return_value={'id':'meta'}),mock.patch.object(client,'fetch_meta',return_value={'meta':{'id':'other','name':'Title'}}):
            self.assertEqual(api.metadata('movie','tt123')['id'],'tt123')

    def test_legacy_routes_only_bridge_to_the_new_interface(self):
        with mock.patch.object(bridge,'legacy_streams') as call:
            plugin.streams('movie','tt123')
            self.assertEqual(call.call_args.kwargs['canonical_id'],'tt123')
            plugin.episode_streams('tt123','tt123:1:2',1,2)
            self.assertEqual(call.call_args.kwargs['episode'],2)
            plugin.play_item(media_type='movie',canonical_id='tt123')
            plugin.series_meta('series','tt123')
            self.assertEqual(call.call_count,4)

    def test_playback_keeps_aio_headers_and_subtitles(self):
        row={'url':'https://example.test/movie.mp4','behaviorHints':{'proxyHeaders':{'request':{'Referer':'https://example.test/'}}},
             'subtitles':[{'url':'https://example.test/en.srt','lang':'en'}]}
        ctx=api.playback_context({'id':'tt123','type':'movie','name':'Title'},row,{'id':'aio'})
        self.assertIn('Referer=',ctx['stream_url'])
        self.assertEqual(ctx['subtitles'],row['subtitles'])
        self.assertEqual(ctx['behaviorHints'],row['behaviorHints'])

    def test_plain_picker_uses_the_selected_raw_row(self):
        playback=importlib.import_module('nuvio_ui.playback')
        rows=[{'name':'First','url':'a'},{'name':'Second','url':'b'}]
        loading=SimpleNamespace(show=lambda:None,close=lambda:None,cancelled=False)
        with mock.patch.object(playback,'job',return_value=({'id':'aio'},rows)),mock.patch.object(playback,'select_source',return_value=1),\
             mock.patch.object(playback,'Loading',return_value=loading),mock.patch.object(playback,'StartListener',return_value=SimpleNamespace(started=True,failed=False)),mock.patch.object(api,'playback_context',return_value={'stream_url':'b'}) as ctx,\
             mock.patch.object(api,'queue_playback',return_value='plugin://plugin.video.nuviohub/?action=nuvio_play&key=test'):
            started=playback.play({'id':'tt123','type':'movie'}, {})
        self.assertIs(ctx.call_args.args[1],rows[1])
        self.assertTrue(started)


class BundleInstallerTests(unittest.TestCase):
    def make_packages(self,path,revision='new',unsafe=False):
        path.mkdir(exist_ok=True)
        rows=[]
        for aid in ('script.nuvio','skin.nuvio','screensaver.nuvio'):
            target=path/(aid+'.zip')
            with zipfile.ZipFile(target,'w') as z:
                z.writestr(aid+'/addon.xml','<addon id="%s" version="1.0.0"/>'%aid)
                z.writestr(aid+'/revision.txt',revision)
                if unsafe:z.writestr(aid+'/../../escape.txt','bad')
            rows.append({'id':aid,'file':target.name,'version':'1.0.0','sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        (path/'bundle.json').write_text(json.dumps(rows),encoding='utf-8')
        return rows

    def test_install_same_version_update_and_profile_preservation(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);packages=base/'packages';addons=base/'addons';backups=base/'backups'
            profile=base/'userdata';profile.mkdir();(profile/'credentials.json').write_text('preserved')
            self.make_packages(packages,'first')
            self.assertEqual(installer.install_components(packages,addons,backups),['script.nuvio','skin.nuvio','screensaver.nuvio'])
            self.assertEqual(installer.install_components(packages,addons,backups),[])
            self.make_packages(packages,'second')
            self.assertEqual(len(installer.install_components(packages,addons,backups)),3)
            self.assertEqual((addons/'script.nuvio/revision.txt').read_text(),'second')
            self.assertEqual((profile/'credentials.json').read_text(),'preserved')
            self.assertEqual(next(backups.glob('*/script.nuvio/revision.txt')).read_text(),'first')

    def test_corrupt_zip_fails_before_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);packages=base/'packages';self.make_packages(packages)
            with (packages/'script.nuvio.zip').open('ab') as f:f.write(b'tamper')
            with self.assertRaisesRegex(ValueError,'checksum'):installer.install_components(packages,base/'addons',base/'backups')
            self.assertFalse((base/'addons/script.nuvio').exists())

    def test_zip_cannot_escape_target(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);packages=base/'packages';self.make_packages(packages,unsafe=True)
            with self.assertRaisesRegex(ValueError,'Unsafe'):installer.install_components(packages,base/'addons',base/'backups')
            self.assertFalse((base/'escape.txt').exists())

    def test_partial_install_rolls_back_both_components(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);packages=base/'packages';addons=base/'addons';backups=base/'backups'
            self.make_packages(packages,'first');installer.install_components(packages,addons,backups)
            self.make_packages(packages,'second')
            real=os.replace
            def replace(source,target):
                if Path(source).parent.name.startswith('.nuvio-stage-') and Path(source).name=='skin.nuvio':raise OSError('simulated disk failure')
                return real(source,target)
            with mock.patch.object(installer.os,'replace',side_effect=replace):
                with self.assertRaises(OSError):installer.install_components(packages,addons,backups)
            for aid in ('script.nuvio','skin.nuvio'):self.assertEqual((addons/aid/'revision.txt').read_text(),'first')


if __name__=='__main__':unittest.main()
