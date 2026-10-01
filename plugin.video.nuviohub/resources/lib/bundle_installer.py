"""Install our UI, skin and screensaver packages, with hashes and rollback."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

from .legacy_names import OLD_ADDON_ID

ALLOWED = {'script.nuvio', 'skin.nuvio', 'screensaver.nuvio'}
# The service's automatic install and the GitHub updater share one process.
_INSTALL_LOCK = threading.Lock()


def validate_archive(path, addon_id, version, sha256):
    if addon_id not in ALLOWED: raise ValueError('Unknown bundle component')
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != sha256:
        raise ValueError('Bundle checksum mismatch')
    with zipfile.ZipFile(path) as archive:
        total=0
        for info in archive.infolist():
            parts=info.filename.replace('\\','/').split('/')
            if parts[0]!=addon_id or any(p in ('..','.') for p in parts) or any(p=='' for p in parts[:-1]) or ':' in info.filename:
                raise ValueError('Unsafe bundle path')
            if (info.external_attr>>16)&0o170000==0o120000:raise ValueError('Bundle links are not allowed')
            total+=info.file_size
            if total>150_000_000:raise ValueError('Bundle is too large')
        root=ET.fromstring(archive.read(addon_id+'/addon.xml'))
        if root.get('id')!=addon_id or root.get('version')!=version:
            raise ValueError('Bundle identity mismatch')


def installed_version(directory):
    try:return ET.parse(Path(directory)/'addon.xml').getroot().get('version','')
    except (OSError,ET.ParseError):return ''


def installed_matches(directory,row):
    try:
        return installed_version(directory)==row['version'] and (Path(directory)/'.nuvio-bundle-sha256').read_text(encoding='ascii').strip()==row['sha256']
    except OSError:return False


def install_components(packages, addons_dir, backup_dir, force=False):
    """Filesystem-only seam. Existing user profiles are never touched."""
    with _INSTALL_LOCK:
        return _install_components(packages, addons_dir, backup_dir, force)


def outdated(packages, addons_dir):
    """Bundled components whose installed copy differs from this backend's packages."""
    try:desired=json.loads((Path(packages)/'bundle.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return []
    return [r['id'] for r in desired if isinstance(r,dict) and r.get('id') in ALLOWED
            and not installed_matches(Path(addons_dir)/r['id'],r)]


def _install_components(packages, addons_dir, backup_dir, force=False):
    packages,addons_dir,backup_dir=Path(packages),Path(addons_dir),Path(backup_dir)
    manifest=json.loads((packages/'bundle.json').read_text(encoding='utf-8'))
    if not isinstance(manifest,list) or {r.get('id') for r in manifest}!=ALLOWED or len(manifest)!=len(ALLOWED):
        raise ValueError('Incomplete bundle')
    pending=[]
    for row in manifest:
        if row.get('file')!=row['id']+'.zip':raise ValueError('Invalid package filename')
        validate_archive(packages/row['file'],row['id'],row['version'],row['sha256'])
        if force or not installed_matches(addons_dir/row['id'],row):pending.append(row)
    if not pending:return []
    addons_dir.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.nuvio-stage-',dir=str(addons_dir)))
    backup=backup_dir/str(time.time_ns())
    changed=[];backed_up=[]
    try:
        for row in pending:
            with zipfile.ZipFile(packages/row['file']) as archive:archive.extractall(stage)
            (stage/row['id']/'.nuvio-bundle-sha256').write_text(row['sha256'],encoding='ascii')
        backup.mkdir(parents=True,exist_ok=True)
        for row in pending:
            aid=row['id'];target=addons_dir/aid
            if target.is_symlink():raise ValueError('An installed component is a link')
            if target.exists():
                os.replace(target,backup/aid);backed_up.append(aid)
            os.replace(stage/aid,target);changed.append(aid)
        return changed
    except Exception:
        for aid in reversed(changed):
            # These are exact allowlisted folders created in this transaction.
            target=addons_dir/aid
            if target.exists():os.replace(target,stage/(aid+'.failed'))
        for aid in reversed(backed_up):os.replace(backup/aid,addons_dir/aid)
        raise
    finally:
        if stage.parent.resolve()==addons_dir.resolve() and stage.name.startswith('.nuvio-stage-'):
            shutil.rmtree(stage)


def paths():
    import xbmcaddon
    import xbmcvfs
    addon=xbmcaddon.Addon('plugin.video.nuviohub')
    return (Path(addon.getAddonInfo('path'))/'resources/packages', Path(xbmcvfs.translatePath('special://home/addons')))


VERSION_SETTING='nuvio_components_for'  # backend version whose components were installed


def backend_version(packages):
    try:return ET.parse(Path(packages).parents[1]/'addon.xml').getroot().get('version','')
    except (OSError,ET.ParseError):return ''


def auto_install(monitor, busy=lambda: False, wait=10, retry=30, attempts=120):
    """Service: after the backend was installed or updated (Kodi repository,
    ZIP or GitHub), install the bundled interface, skin and screensaver without
    "Install or repair". Once a backend version has installed them, a component
    the user uninstalled is NOT put back (only the next update reinstalls).
    Waits while video plays, the interface is open or a removal runs."""
    import xbmc
    import xbmcaddon
    import xbmcgui
    if monitor.waitForAbort(wait):return []
    addon=xbmcaddon.Addon('plugin.video.nuviohub')
    for _ in range(attempts):
        packages,addons_dir=paths()
        version=backend_version(packages)
        home=xbmcgui.Window(10000)
        if home.getProperty('nuvio.uninstalling'):return []
        if version and addon.getSetting(VERSION_SETTING)==version:return []
        if not outdated(packages,addons_dir):
            addon.setSetting(VERSION_SETTING,version);return []
        if not xbmc.Player().isPlayingVideo() and not home.getProperty('nuvio.frontend.running') and not busy():
            changed=ensure_components()
            addon.setSetting(VERSION_SETTING,version)
            if changed:
                xbmcgui.Dialog().notification('MegaNexus','Interface, skin and screensaver updated',xbmcgui.NOTIFICATION_INFO,5000)
            return changed
        if monitor.waitForAbort(retry):return []
    return []


def ensure_components(force=False):
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcvfs
    addon=xbmcaddon.Addon('plugin.video.nuviohub')
    packages=Path(addon.getAddonInfo('path'))/'resources/packages'
    addons_dir=Path(xbmcvfs.translatePath('special://home/addons'))
    desired=json.loads((packages/'bundle.json').read_text(encoding='utf-8'))
    needs_change=force or any(not installed_matches(addons_dir/r['id'],r) for r in desired)
    if needs_change and xbmc.Player().isPlayingVideo():
        raise RuntimeError('Stop playback before installing or updating the MegaNexus interface.')
    if needs_change and xbmcgui.Window(10000).getProperty('nuvio.frontend.running'):
        raise RuntimeError('Close the MegaNexus interface and restart Kodi before updating the bundled components.')
    changed=install_components(packages,addons_dir,Path(xbmcvfs.translatePath(addon.getAddonInfo('profile')))/'installation-backups',force)
    xbmc.executebuiltin('UpdateLocalAddons')
    monitor=xbmc.Monitor()
    for aid in ('script.nuvio','skin.nuvio','screensaver.nuvio'):
        for attempt in range(60):  # slow boxes need up to ~30 s to discover new add-ons
            result=json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc':'2.0','id':1,'method':'Addons.GetAddonDetails','params':{'addonid':aid,'properties':['enabled']}})))
            if result.get('result',{}).get('addon'):
                enabled=json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc':'2.0','id':1,'method':'Addons.SetAddonEnabled','params':{'addonid':aid,'enabled':True}})))
                if enabled.get('error'):raise RuntimeError('Kodi could not enable '+aid+'. Restart Kodi and retry.')
                break
            if monitor.waitForAbort(0.5):return changed
        else:raise RuntimeError('Kodi has not discovered '+aid+'. Restart Kodi and reopen Nuvio Hub.')
    # The original service uses some of the same legacy playback property names.
    # The profile has already been copied read-only by default.py; preserve its data.
    if not xbmc.Player().isPlayingVideo():
        old=json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc':'2.0','id':1,'method':'Addons.GetAddonDetails',
            'params':{'addonid':OLD_ADDON_ID,'properties':['enabled']}})))
        if old.get('result',{}).get('addon',{}).get('enabled'):
            xbmc.executeJSONRPC(json.dumps({'jsonrpc':'2.0','id':1,'method':'Addons.SetAddonEnabled',
                'params':{'addonid':OLD_ADDON_ID,'enabled':False}}))
    if addon.getSetting('nuvio_screensaver_applied')!='true':
        result=json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc':'2.0','id':1,'method':'Settings.SetSettingValue','params':{'setting':'screensaver.mode','value':'screensaver.nuvio'}})))
        if not result.get('error'):addon.setSetting('nuvio_screensaver_applied','true')
    if 'skin.nuvio' in changed and xbmc.getSkinDir()=='skin.nuvio':
        xbmc.executebuiltin('ReloadSkin')
    return changed
