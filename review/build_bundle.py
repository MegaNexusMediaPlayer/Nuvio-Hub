"""Deterministic Kodi ZIP containing the backend, UI, skin and screensaver."""
from pathlib import Path
import hashlib
import argparse
import json
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BACK=ROOT/'plugin.video.nuviohub'
PACKAGES=BACK/'resources/packages'
PACKAGES.mkdir(parents=True,exist_ok=True)
OMIT_UI={'home_window.py','home_trailers.py','source_browser.py','sources_loading.py','skin_theme.py','search_window.py'}
BACK_MEDIA={'icon.png','nuvio_mark.png','nuvio_banner.png','meganexus_icon.png','meganexus_fanart.png'}
UI_MEDIA={'nuvio_video_vignette.png','kofi_qr.png','nuvio_poster_mask_v2.png','nuvio_poster_focus_v2.png','nuvio_tile_mask_v2.png','nuvio_tile_focus_v2.png','person.png','person_circle.png','person_ring.png','black.png','white.png','nuvio_mark.png','nuvio_wordmark.png','nuvio_banner.png','nuvio_hero_shade.png','nuvio_hero_fade.png',
          'nuvio_pill.png','nuvio_poster_mask.png','nuvio_poster_focus.png','nuvio_poster_blank.png','nuvio_tile_mask.png','nuvio_tile_focus.png','meganexus_saver_bg.png','meganexus_saver_logo.png','meganexus_saver_glow.png','meganexus_saver_spark.png','meganexus_icon.png','meganexus_fanart.png',
          'nuvio_banner_dark.png','nuvio_banner_dim.png','meganexus_saver_bg_dark.png','meganexus_saver_bg_dim.png','nuvio_bottom_fade.png',
          'nuvio_tile_glass.png','nuvio_poster_glass.png',
          'nuvio_tile_focus_glass.png','nuvio_poster_focus_glass.png'}
CRISP_PILL=re.compile(r'nuvio_(?:pill_\d+x\d+_r\d+|wordmark_\d+x\d+|(?:tile|poster)_(?:mask|glass|focus|focus_glass)_\d+x\d+)\.png$')  # per-size pills, logos and card shapes (review/make_crisp_shapes.py)
COLLECTION_MEDIA={value for group in json.loads((BACK/'resources/collections.json').read_text(encoding='utf-8'))
                  for folder in group['folders'] for key,value in folder.items()
                  if key in ('cover','backdrop','animation') and isinstance(value,str) and value.startswith('resources/media/collections/')}
COLLECTION_MEDIA.update(json.loads((BACK/'resources/collection_animations.json').read_text(encoding='utf-8')).values())
NAMES={'plugin.video.nuviohub':'Nuvio Hub','script.nuvio':'MegaNexus',
       'skin.nuvio':'MegaNexus','screensaver.nuvio':'MegaNexus'}


def release_version(root=ROOT):
    """Reject mixed releases before writing any installable packages."""
    manifests={aid:ET.parse(root/aid/'addon.xml').getroot() for aid in NAMES}
    versions={node.get('version') for node in manifests.values()}
    if len(versions)!=1 or not next(iter(versions)):
        raise ValueError('All Nuvio components must have the same release version')
    version=next(iter(versions))
    for aid,node in manifests.items():
        if node.get('id')!=aid or node.get('name')!=NAMES[aid]:
            raise ValueError('Invalid Nuvio component identity: '+aid)
        for dependency in node.findall('./requires/import'):
            if dependency.get('addon') in NAMES and dependency.get('version')!=version:
                raise ValueError('Nuvio dependency version mismatch: '+aid)
    return version


def files_for(source):
    for path in source.rglob('*'):
        if not path.is_file():continue
        if path.suffix.lower() in ('.ttf','.otf','.ttc','.woff','.woff2'):continue
        rel=path.relative_to(source)
        if any(p.startswith('.') or p in ('tests','__pycache__') for p in rel.parts) or path.suffix in ('.pyc','.pyo'):continue
        if 'language' in rel.parts and any(p.startswith('resource.language.') and p!='resource.language.en_gb' for p in rel.parts):continue
        if source.name=='plugin.video.nuviohub':
            if rel.parts[0] not in ('resources','addon.xml','default.py','service.py','LICENSE.txt','README.md'):continue
            if 'skins' in rel.parts or path.name in OMIT_UI:continue
            if rel.as_posix().startswith('resources/media/') and path.name not in BACK_MEDIA:continue
        elif source.name=='script.nuvio':
            if rel.as_posix().startswith('resources/media/') and 'collections' not in rel.parts and path.name not in UI_MEDIA and not CRISP_PILL.match(path.name):continue
            if 'collections' in rel.parts and rel.as_posix() not in COLLECTION_MEDIA:continue
        elif source.name=='skin.nuvio':
            if rel.parts[0]=='colors' and path.name not in ('defaults.xml','dark.xml','dim.xml'):continue  # light/dark/dim themes
        yield path


def build(source,out):
    files=list(files_for(source))
    for path in files:
        if path.suffix=='.py':compile(path.read_text(encoding='utf-8-sig'),str(path),'exec')
        elif path.suffix=='.xml':ET.parse(path)
        elif path.suffix=='.json':json.loads(path.read_text(encoding='utf-8-sig'))
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in sorted(files):
            info=zipfile.ZipInfo(source.name+'/'+path.relative_to(source).as_posix(),date_time=(2026,9,29,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o644<<16
            z.writestr(info,path.read_bytes())
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert all(n.startswith(source.name+'/') for n in z.namelist())
    return {'id':source.name,'file':out.name,'version':ET.parse(source/'addon.xml').getroot().get('version'),
            'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'files':len(files),'bytes':out.stat().st_size}


if __name__=='__main__':
    version=release_version()
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='Nuvio-Hub-Complete-'+version+'.zip')
    args=parser.parse_args()
    components=[]
    for name in ('script.nuvio','skin.nuvio','screensaver.nuvio'):
        components.append(build(ROOT/name,PACKAGES/(name+'.zip')))
    (PACKAGES/'bundle.json').write_text(json.dumps(components,indent=2),encoding='utf-8')
    out=ROOT/args.output
    result=build(BACK,out)
    with zipfile.ZipFile(out) as z:
        names=z.namelist()
        assert not any('/skins/' in n or '/resource.language.ar_' in n or Path(n).name in OMIT_UI for n in names)
        assert not any('/tests/' in n or '/.test-profile/' in n for n in names)
    (ROOT/(out.name+'.sha256')).write_text(result['sha256']+'  '+out.name+'\n',encoding='ascii')
    (ROOT/'review/bundle-report.json').write_text(json.dumps({'bundle':result,'components':components},indent=2),encoding='utf-8')
    print(json.dumps({'bundle':result,'components':components},indent=2))
