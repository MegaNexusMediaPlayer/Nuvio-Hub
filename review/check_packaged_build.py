"""Check real ZIPs and import their code with isolated Kodi API stubs."""
from pathlib import Path
import hashlib
import importlib
import io
import json
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(tempfile.mkdtemp(prefix='nuvio-package-smoke-'))
with zipfile.ZipFile(ROOT/(sys.argv[1] if len(sys.argv)>1 else 'Nuvio-Hub-Complete-6.0.2.zip')) as outer:
    outer.extractall(OUT)
BACK=OUT/'plugin.video.nuviohub'
packages=BACK/'resources/packages'
manifest=json.loads((packages/'bundle.json').read_text())
for row in manifest:
    raw=(packages/row['file']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==row['sha256']
    with zipfile.ZipFile(io.BytesIO(raw)) as component:
        assert component.testzip() is None
        component.extractall(OUT)

from build_bundle import release_version
version=release_version(OUT)
assert all(row['version']==version for row in manifest)
for aid in ('plugin.video.nuviohub','script.nuvio','skin.nuvio','screensaver.nuvio'):
    addon=ET.parse(OUT/aid/'addon.xml').getroot()
    for asset in addon.findall('./extension/assets/*'):
        assert (OUT/aid/asset.text).is_file(), (aid, asset.text)

# Validate all literal addon asset references in the actual packaged XML.
checked=0
for path in OUT.rglob('*.xml'):
    tree=ET.parse(path)
    for node in tree.iter():
        values=[node.text or '']+list(node.attrib.values())
        for value in values:
            if value.startswith('special://home/addons/') and '$' not in value:
                target=OUT/value.removeprefix('special://home/addons/')
                assert target.is_file(), (path, value)
                checked+=1
    if path.name=='addon.xml':
        assert not tree.findall("extension[@point='xbmc.addon.repository']")
assert not (BACK/'resources/skins').exists()
assert not list(OUT.rglob('resource.language.ar_*'))
assert not list(OUT.rglob('default_movie_poster.png'))
for group in json.loads((BACK/'resources/collections.json').read_text(encoding='utf-8')):
    assert group['id'] not in ('collections.world','collections.sports')
    for folder in group['folders']:
        for key in ('cover','backdrop','animation'):
            value=folder.get(key,'')
            if value.startswith('resources/media/'):
                assert (OUT/'script.nuvio'/value).is_file(),value
for value in json.loads((BACK/'resources/collection_animations.json').read_text(encoding='utf-8')).values():
    assert (OUT/'script.nuvio'/value).is_file(),value
for name in ('home_window','home_trailers','source_browser','sources_loading','skin_theme','search_window'):
    assert not (BACK/'resources/lib'/f'{name}.py').exists()
for name in ('Home','Settings','DialogSelect','DialogKeyboard','VideoOSD','Font'):
    assert (OUT/'skin.nuvio/xml'/f'{name}.xml').is_file()

sys.path.insert(0,str(ROOT/'plugin.video.nuviohub/tests'))
import kodi_stub
kodi_stub.ADDON_ROOT=str(BACK)
kodi_stub.LIB=str(BACK/'resources/lib')
kodi_stub.install()
import xbmcaddon
class Addon(kodi_stub._Addon):
    def __init__(self, aid='plugin.video.nuviohub'): self.aid=aid
    def getAddonInfo(self,key):
        return {'id':self.aid,'path':str(OUT/self.aid),'profile':str(OUT/'profiles'/self.aid),'version':'1.0.0'}.get(key,'')
xbmcaddon.Addon=Addon
sys.path[:0]=[str(BACK),str(OUT/'script.nuvio')]
modules=('resources.lib.plugin','resources.lib.backend_api','resources.lib.backend_listing',
         'resources.lib.bundle_installer','resources.lib.skip_service',
         'resources.lib.continue_local','resources.lib.trailer_cache','resources.lib.seek_profile','resources.lib.art_cache','nuvio_ui.dialog',
         'resources.lib.nuvio_import','resources.lib.nuvio_uninstall','nuvio_ui.collection_editor',
         'resources.lib.collection_profile','resources.lib.catalog_pages','resources.lib.continue_metadata',
         'resources.lib.nuvio_subtitles','resources.lib.iptv_config','resources.lib.simkl',
         'nuvio_ui.home_window','nuvio_ui.home_trailers','nuvio_ui.details','nuvio_ui.settings',
         'nuvio_ui.browse_meta','nuvio_ui.source_text','nuvio_ui.catalog','nuvio_ui.playback','nuvio_ui.iptv','nuvio_ui.subtitles',
         'nuvio_ui.trailers','nuvio_ui.system_setup','nuvio_ui.onboarding','nuvio_ui.simkl_account')
for name in modules:
    mod=importlib.import_module(name)
    assert Path(mod.__file__).is_relative_to(OUT),mod.__file__
print(json.dumps({'extracted_to':str(OUT),'imported_packaged_modules':len(modules),'validated_xml_asset_refs':checked,
                  'unified_version':version,
                  'components':[row['id'] for row in manifest],'result':'PASS'},indent=2))
