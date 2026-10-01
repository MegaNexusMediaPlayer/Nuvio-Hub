#!/usr/bin/env python3
"""Static Kodi repository site for GitHub Pages (6.0.21).

Run after `review/build_bundle.py` (it builds the component ZIPs). Output:

  <out>/index.html                              File manager source; lists the repo ZIP
  <out>/repository.meganexus-<v>.zip            "Install from zip file"
  <out>/repo/addons.xml (+ .md5)                read by repository.meganexus
  <out>/repo/<id>/<id>-<version>.zip (+ icon/fanart)

The backend entry is the complete bundle (backend + packaged components), so a
fresh install from the repository gets everything; the three components are
also listed so Kodi updates them on its own. Publishing is manual (gh-pages).
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'plugin.video.nuviohub/resources/packages'
REPO = ROOT / 'repository.meganexus'
DEFAULT_BASE = 'https://meganexusmediaplayer.github.io/Nuvio-Hub/'
STAMP = (2026, 9, 29, 0, 0, 0)


def manifest(zip_path, addon_id):
    with zipfile.ZipFile(zip_path) as z:
        return z.read(addon_id + '/addon.xml').decode('utf-8')


def strip_decl(text):
    return text.split('?>', 1)[1].strip() if text.lstrip().startswith('<?xml') else text.strip()


def repository_zip(out_dir, base):
    text = (REPO / 'addon.xml').read_text(encoding='utf-8').replace(DEFAULT_BASE, base)
    root = ET.fromstring(text.encode('utf-8'))
    version = root.get('version')
    target = out_dir / ('repository.meganexus-%s.zip' % version)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in (('addon.xml', text.encode('utf-8')), ('icon.png', (REPO / 'icon.png').read_bytes()),
                           ('fanart.png', (REPO / 'fanart.png').read_bytes())):
            info = zipfile.ZipInfo('repository.meganexus/' + name, date_time=STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED;info.external_attr = 0o644 << 16
            z.writestr(info, data)
    return target, text, version


def copy_assets(zip_path, addon_id, xml_text, dest):
    root = ET.fromstring(xml_text.encode('utf-8'))
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for node in root.findall('./extension/assets/*'):
            rel = (node.text or '').strip()
            member = addon_id + '/' + rel
            if rel and member in names:
                path = dest / rel;path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(z.read(member))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', help='Nuvio-Hub-Complete-<version>.zip from build_bundle.py')
    parser.add_argument('--output', required=True)
    parser.add_argument('--base-url', default=DEFAULT_BASE)
    args = parser.parse_args()
    base = args.base_url.rstrip('/') + '/'
    out = Path(args.output)
    if out.exists():
        shutil.rmtree(out)
    (out / 'repo').mkdir(parents=True)
    entries = [('plugin.video.nuviohub', Path(args.bundle))]
    entries += [(aid, PACKAGES / (aid + '.zip')) for aid in ('script.nuvio', 'skin.nuvio', 'screensaver.nuvio')]
    xmls, versions = [], {}
    for aid, src in entries:
        text = manifest(src, aid)
        version = ET.fromstring(text.encode('utf-8')).get('version')
        versions[aid] = version
        dest = out / 'repo' / aid;dest.mkdir(parents=True)
        shutil.copyfile(src, dest / ('%s-%s.zip' % (aid, version)))
        copy_assets(src, aid, text, dest)
        xmls.append(strip_decl(text))
    if len(set(versions.values())) != 1:
        raise SystemExit('Component versions differ: %s' % versions)
    repo_zip, repo_xml, repo_version = repository_zip(out, base)
    dest = out / 'repo' / 'repository.meganexus';dest.mkdir()
    shutil.copyfile(repo_zip, dest / repo_zip.name)
    for asset in ('icon.png', 'fanart.png'):
        shutil.copyfile(REPO / asset, dest / asset)
    xmls.append(strip_decl(repo_xml))
    addons = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n' + '\n'.join(xmls) + '\n</addons>\n'
    ET.fromstring(addons.encode('utf-8'))
    (out / 'repo/addons.xml').write_text(addons, encoding='utf-8')
    (out / 'repo/addons.xml.md5').write_text(hashlib.md5(addons.encode('utf-8')).hexdigest(), encoding='ascii')
    # Kodi's HTTP directory reader lists every <a href>; keep only the repo ZIP here.
    name = html.escape(repo_zip.name)
    (out / 'index.html').write_text(
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8"><title>MegaNexus</title></head><body>\n'
        '<a href="%s">%s</a>\n</body></html>\n' % (name, name), encoding='utf-8')
    (out / '.nojekyll').write_text('', encoding='ascii')
    report = {'base_url': base, 'file_manager_source': base, 'repository': repo_zip.name,
              'repository_version': repo_version, 'addons': versions}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
