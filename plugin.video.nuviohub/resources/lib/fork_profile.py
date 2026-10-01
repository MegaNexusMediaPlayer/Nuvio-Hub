"""One-time, read-only import of the upstream profile into this independent addon.

Only durable user data is copied. SQLite backup includes committed WAL rows.
Destination files are never overwritten; a lock serializes plugin/service startup.
"""
import json
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .legacy_names import OLD_ADDON_ID as OLD_ID
NEW_ID = 'plugin.video.nuviohub'


def rewrite_local_refs(value):
    if isinstance(value, dict):
        return {k: rewrite_local_refs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rewrite_local_refs(v) for v in value]
    if isinstance(value, str):
        # Provider URLs and authentication payloads must stay byte-for-byte intact.
        if value.startswith(('plugin://' + OLD_ID, 'special://home/addons/' + OLD_ID,
                             'special://profile/addon_data/' + OLD_ID)):
            return value.replace(OLD_ID, NEW_ID)
    return value


def import_profile(source, target):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    marker = target / 'nuvio_import.json'
    if marker.exists():
        return
    lock = target / '.nuvio-import.lock'
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # Other startup owns the migration. Never import half a profile.
        for _ in range(100):
            if marker.exists():
                return
            if not lock.exists():
                return import_profile(source, target)
            time.sleep(0.05)
        raise RuntimeError('Profile import is still running; reopen Nuvio Hub shortly.')
    os.close(fd)
    copied = []
    try:
        if source.is_dir():
            for path in source.iterdir():
                name = path.name
                if not path.is_file() or path.is_symlink() or name.startswith('.'):
                    continue
                if path.suffix not in ('.json', '.db', '.xml'):
                    continue
                if any(word in name.lower() for word in ('cache', 'session', 'lock', 'health', 'task', 'queue')):
                    continue
                dest = target / name
                if dest.exists():
                    continue
                temp = target / (name + '.importing')
                if path.suffix == '.db':
                    src = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
                    try:
                        dst = sqlite3.connect(str(temp))
                        try:
                            src.backup(dst)
                        finally:
                            dst.close()
                    finally:
                        src.close()
                elif path.suffix == '.json':
                    data = json.loads(path.read_text(encoding='utf-8-sig'))
                    temp.write_text(json.dumps(rewrite_local_refs(data), ensure_ascii=False), encoding='utf-8')
                elif name == 'settings.xml':
                    tree = ET.parse(path)
                    root = tree.getroot()
                    settings = {n.get('id'): n for n in root.iter('setting')}
                    for key, value in {'ui_language': 'English', 'ui_lang_autodetected': 'true', 'home_style': '1'}.items():
                        node = settings.get(key)
                        if node is None:
                            node = ET.SubElement(root, 'setting', {'id': key})
                        if 'value' in node.attrib:
                            node.set('value', value)
                        node.set('default', 'false')
                        node.text = value
                    for node in root.iter('setting'):
                        if node.text:
                            node.text = rewrite_local_refs(node.text)
                        if 'value' in node.attrib:
                            node.set('value', rewrite_local_refs(node.get('value')))
                    tree.write(temp, encoding='utf-8', xml_declaration=True)
                else:
                    # Only the Kodi settings document is imported as XML.
                    continue
                os.replace(temp, dest)
                copied.append(name)
        marker.write_text(json.dumps({'version': 1, 'copied': copied, 'source_modified': False}), encoding='utf-8')
    finally:
        lock.unlink(missing_ok=True)


def ensure_profile():
    import xbmcaddon
    import xbmcvfs
    addon = xbmcaddon.Addon(NEW_ID)
    if addon.getSetting('nuvio_profile_applied') == 'true':
        return
    target = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    source = xbmcvfs.translatePath('special://profile/addon_data/' + OLD_ID)
    import_profile(source, target)
    # Kodi may have cached settings before the imported file appeared.
    # These presentation values also fix legacy Arabic selections in the English build.
    settings_path = Path(target) / 'settings.xml'
    if settings_path.exists():
        # Snapshot every value before setSetting can flush Kodi's cached document.
        settings = {n.get('id'): n.get('value', n.text or '')
                    for n in ET.parse(settings_path).getroot().iter('setting') if n.get('id')}
        for key, value in settings.items():
            addon.setSetting(key, value)
    addon.setSetting('ui_language', 'English')
    addon.setSetting('ui_lang_autodetected', 'true')
    addon.setSetting('nuvio_profile_applied', 'true')
