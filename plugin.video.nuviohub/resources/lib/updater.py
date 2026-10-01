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
    return 'installed', info
