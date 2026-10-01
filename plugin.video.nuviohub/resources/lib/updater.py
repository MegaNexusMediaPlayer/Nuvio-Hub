"""Updates from the project's GitHub releases.

The latest release of MegaNexusMediaPlayer/Nuvio-Hub carries the installer
``Nuvio-Hub-Complete-<version>.zip`` (tag ``v<version>``), optionally with a
``.sha256`` file. A newer version is downloaded, verified and installed:

1. the backend folder is replaced atomically (old copy kept in the profile's
   installation-backups; restored if anything fails);
2. the bundled interface, skin and screensaver packages from the new backend are
   installed with the existing hash-checked bundle installer;
3. Kodi rescans add-ons; a restart finishes the update.

Nothing runs while a video plays or the Nuvio interface is open.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from urllib.request import Request, urlopen

REPO = 'MegaNexusMediaPlayer/Nuvio-Hub'
API = 'https://api.github.com/repos/%s/releases/latest' % REPO
RELEASES = 'https://github.com/%s/releases' % REPO
ASSET = re.compile(r'^Nuvio-Hub-Complete-(\d+(?:\.\d+){1,3})\.zip$')
BACKEND = 'plugin.video.nuviohub'
MAX_ZIP = 200 * 1024 * 1024
CHECK_EVERY = 12 * 3600
AUTO_SETTING = 'nuvio_auto_update'
CHECKED_SETTING = 'nuvio_update_checked'
PENDING_SETTING = 'nuvio_restart_pending'   # '<version>|<Kodi session token>' until Kodi restarts
BOOT_PROPERTY = 'nuvio.service.boot'        # Window(10000) property; gone after a Kodi restart
PROMPTED_PROPERTY = 'nuvio.restart.prompted'
USER_AGENT = 'NuvioHub-Updater (Kodi)'


def parse_version(text):
    try:
        return tuple(int(x) for x in str(text).strip().lstrip('vV').split('.'))
    except ValueError:
        return ()


def newer(candidate, current):
    return parse_version(candidate) > parse_version(current)


def _get(url, timeout, opener=urlopen, accept='application/json'):
    return opener(Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept}), timeout=timeout)


def latest(opener=urlopen, timeout=10):
    """{'version', 'url', 'sha256_url', 'page'} of the latest release, or None."""
    with _get(API, timeout, opener, 'application/vnd.github+json') as response:
        data = json.loads(response.read(2 * 1024 * 1024).decode('utf-8'))
    assets = {a.get('name'): a.get('browser_download_url') for a in data.get('assets') or [] if isinstance(a, dict)}
    for name, url in assets.items():
        match = ASSET.match(name or '')
        if match and str(url or '').startswith('https://'):
            return {'version': match.group(1), 'url': url, 'sha256_url': assets.get(name + '.sha256') or '',
                    'page': data.get('html_url') or RELEASES, 'tag': data.get('tag_name') or ''}
    return None


def download(info, folder, opener=urlopen, timeout=30, stopped=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / ('Nuvio-Hub-Complete-%s.zip' % info['version'])
    digest = hashlib.sha256()
    size = 0
    with _get(info['url'], timeout, opener, 'application/octet-stream') as response, open(target, 'wb') as out:
        while True:
            if stopped and stopped():
                raise RuntimeError('Update cancelled.')
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ZIP:
                raise ValueError('The update is larger than expected.')
            digest.update(chunk)
            out.write(chunk)
    if info.get('sha256_url'):
        with _get(info['sha256_url'], timeout, opener, 'text/plain') as response:
            expected = response.read(4096).decode('utf-8', 'replace').split()[0].strip().lower()
        if expected != digest.hexdigest():
            target.unlink()
            raise ValueError('The update does not match its published checksum.')
    return target


def validate(zip_path, version):
    """Only the backend folder, no unsafe paths, and the promised version."""
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            parts = info.filename.replace('\\', '/').split('/')
            if parts[0] != BACKEND or any(p in ('..', '.') for p in parts) or ':' in info.filename:
                raise ValueError('Unexpected file in the update.')
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Links are not allowed in the update.')
        root = ET.fromstring(archive.read(BACKEND + '/addon.xml'))
        if root.get('id') != BACKEND or root.get('version') != version:
            raise ValueError('The update is not Nuvio Hub %s.' % version)
        if BACKEND + '/resources/packages/bundle.json' not in archive.namelist():
            raise ValueError('The update has no bundled interface.')


def replace_backend(zip_path, addons_dir, backup_dir):
    """Swap the backend folder; the previous one is kept and restored on failure."""
    addons_dir, backup_dir = Path(addons_dir), Path(backup_dir)
    stage = Path(tempfile.mkdtemp(prefix='.nuvio-update-', dir=str(addons_dir)))
    backup = backup_dir / ('backend-%d' % time.time_ns())
    target = addons_dir / BACKEND
    moved = False
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(stage)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            os.replace(target, backup)
            moved = True
        os.replace(stage / BACKEND, target)
        return backup if moved else None
    except Exception:
        if moved and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def install(info, addons_dir, profile_dir, opener=urlopen, stopped=None):
    """Download, verify and install ``info``; returns the installed components."""
    from . import bundle_installer
    profile_dir = Path(profile_dir)
    zip_path = download(info, profile_dir / 'updates', opener, stopped=stopped)
    try:
        validate(zip_path, info['version'])
        backup = replace_backend(zip_path, addons_dir, profile_dir / 'installation-backups')
        packages = Path(addons_dir) / BACKEND / 'resources' / 'packages'
        try:
            changed = bundle_installer.install_components(packages, addons_dir,
                                                          profile_dir / 'installation-backups')
        except Exception:
            # Keep backend and interface in step: put the previous backend back.
            if backup is not None:
                broken = Path(addons_dir) / (BACKEND + '.failed-update')
                shutil.rmtree(broken, ignore_errors=True)
                os.replace(Path(addons_dir) / BACKEND, broken)
                os.replace(backup, Path(addons_dir) / BACKEND)
            raise
        prune_backups(profile_dir / 'installation-backups')
        return [BACKEND] + list(changed)
    finally:
        try:
            zip_path.unlink()
        except OSError:
            pass


def prune_backups(folder, keep=3):
    """Keep the newest ``keep`` backups of each kind (backend / interface)."""
    folder = Path(folder)
    if not folder.is_dir():
        return
    entries = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    for kind in (lambda p: p.name.startswith('backend-'), lambda p: not p.name.startswith('backend-')):
        for old in [p for p in entries if kind(p)][keep:]:
            shutil.rmtree(old, ignore_errors=True)


def due(addon, now=None):
    try:
        last = float(addon.getSetting(CHECKED_SETTING) or 0)
    except ValueError:
        last = 0
    return (now or time.time()) - last >= CHECK_EVERY


def check_and_update(addon, interactive=False, opener=urlopen):
    """Service/Settings entry. Returns (status, info): 'current', 'available',
    'installed', 'busy' or 'error'."""
    import xbmc
    import xbmcgui
    import xbmcvfs
    addon.setSetting(CHECKED_SETTING, str(int(time.time())))
    current = addon.getAddonInfo('version')
    try:
        info = latest(opener)
    except Exception:
        return 'error', None
    if not info or not newer(info['version'], current):
        return 'current', info
    if not interactive and addon.getSetting(AUTO_SETTING) == 'false':
        return 'available', info
    home = xbmcgui.Window(10000)
    if xbmc.Player().isPlayingVideo() or home.getProperty('nuvio.frontend.running'):
        return 'busy', info
    addons_dir = xbmcvfs.translatePath('special://home/addons')
    profile_dir = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    try:
        install(info, addons_dir, profile_dir, opener)
    except Exception as exc:
        xbmc.log('[NuvioHub] update to %s failed: %s' % (info['version'], exc), xbmc.LOGWARNING)
        return 'error', info
    xbmc.executebuiltin('UpdateLocalAddons')
    mark_pending(addon, info['version'])
    return 'installed', info


def interactive_check():
    """Kodi > Add-ons > Nuvio Hub > Configure > Check for updates now."""
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcvfs
    addon = xbmcaddon.Addon(BACKEND)
    dialog = xbmcgui.Dialog()
    current = addon.getAddonInfo('version')
    busy = xbmcgui.DialogProgressBG()
    busy.create('Nuvio Hub', 'Checking GitHub for updates')
    try:
        info = latest()
    except Exception:
        info = False
    finally:
        busy.close()
    if info is False:
        dialog.ok('Nuvio Hub updates', 'GitHub could not be reached. Check the connection and retry.\n' + RELEASES)
        return
    if not info or not newer(info['version'], current):
        dialog.ok('Nuvio Hub updates', 'Nuvio Hub %s is up to date.' % current)
        return
    if not dialog.yesno('Nuvio Hub updates', 'Nuvio Hub %s is available (installed %s). Install it now?' % (info['version'], current)):
        return
    if xbmc.Player().isPlayingVideo() or xbmcgui.Window(10000).getProperty('nuvio.frontend.running'):
        dialog.ok('Nuvio Hub updates', 'Stop playback and close the MegaNexus interface, then retry.')
        return
    busy = xbmcgui.DialogProgressBG()
    busy.create('Nuvio Hub', 'Installing %s' % info['version'])
    try:
        install(info, xbmcvfs.translatePath('special://home/addons'), xbmcvfs.translatePath(addon.getAddonInfo('profile')))
    except Exception as exc:
        busy.close()
        dialog.ok('Nuvio Hub updates', 'The update could not be installed; your current version was kept.\n' + (str(exc) if isinstance(exc, ValueError) else ''))
        return
    busy.close()
    xbmc.executebuiltin('UpdateLocalAddons')
    mark_pending(addon, info['version'])
    prompt_restart(addon, info['version'])


# ---- Restart prompt after an automatic update --------------------------------

def boot_token():
    """Token of the running Kodi session (set by the service at start-up)."""
    import uuid
    import xbmcgui
    home = xbmcgui.Window(10000)
    token = home.getProperty(BOOT_PROPERTY)
    if not token:
        token = uuid.uuid4().hex
        home.setProperty(BOOT_PROPERTY, token)
    return token


def mark_pending(addon, version):
    addon.setSetting(PENDING_SETTING, '%s|%s' % (version, boot_token()))


def pending_version(addon):
    """Installed version still waiting for a Kodi restart, or ''. A restart of
    Kodi by any route (new session token) clears it."""
    version, _, session = (addon.getSetting(PENDING_SETTING) or '').partition('|')
    if version and session and session != boot_token():
        addon.setSetting(PENDING_SETTING, '')
        return ''
    return version


def safe_to_prompt():
    """Never over a video or the open Nuvio interface."""
    import xbmc
    import xbmcgui
    return not xbmc.Player().isPlayingVideo() and not xbmcgui.Window(10000).getProperty('nuvio.frontend.running')


def prompt_restart(addon, version):
    """Yes restarts Kodi (or reboots / closes it, per platform) now; Later keeps
    the reminder for the next Nuvio entry."""
    import xbmc
    import xbmcgui
    from .kodi_restart import plan
    xbmcgui.Window(10000).setProperty(PROMPTED_PROPERTY, version)
    # 6.0.34: reboot on CoreELEC/LibreELEC (RestartApp froze Amlogic boxes),
    # close Kodi on Android/Apple (RestartApp cannot reopen it there).
    builtin, label, question = plan()
    if xbmcgui.Dialog().yesno('MegaNexus', question % version, nolabel='Later', yeslabel=label):
        addon.setSetting(PENDING_SETTING, '')
        xbmc.executebuiltin(builtin)
        return True
    return False


def prompt_when_safe(addon, monitor, poll=5):
    """Service: after an automatic install, ask once this session as soon as no
    video plays and Nuvio is closed. Returns True when Kodi is restarting."""
    import xbmcgui
    while not monitor.abortRequested():
        version = pending_version(addon)
        if not version or xbmcgui.Window(10000).getProperty(PROMPTED_PROPERTY) == version:
            return False  # Already asked this session: the reminder waits for the next Nuvio entry.
        if safe_to_prompt():
            return prompt_restart(addon, version)
        if monitor.waitForAbort(poll):
            return False
    return False


def prompt_at_entry(addon=None):
    """Nuvio entry: remind about a pending restart before the interface opens.
    Returns True when Kodi is restarting (the interface should not open)."""
    import xbmc
    import xbmcaddon
    addon = addon or xbmcaddon.Addon(BACKEND)
    version = pending_version(addon)
    if not version or xbmc.Player().isPlayingVideo():
        return False
    return prompt_restart(addon, version)
