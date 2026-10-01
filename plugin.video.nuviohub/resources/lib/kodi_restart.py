"""How to restart Kodi after an update, per platform (6.0.34).

Kodi's ``RestartApp`` is only implemented for Windows and Linux
(ApplicationMessageHandling.cpp, Kodi 22):
* CoreELEC / LibreELEC: Kodi exits and the system restarts it; on Amlogic
  boxes the video/HDMI re-initialisation can freeze the box. A full reboot
  is reliable, so these systems reboot.
* Android: ``RestartApp`` only closes Kodi (the app cannot reopen itself).
  macOS / iOS / tvOS: it does nothing. These close Kodi cleanly (settings are
  saved) and the user opens it again.
* Windows and other Linux: a real restart.
"""
import xbmc

ELEC_IDS = {'coreelec', 'libreelec'}
ELEC_ADDONS = ('service.coreelec.settings', 'service.libreelec.settings')

PLANS = {
    'reboot': ('Reboot', 'Reboot', 'MegaNexus %s is installed. Reboot the box now to finish the update?'),
    'close': ('Quit', 'Close Kodi', 'MegaNexus %s is installed. Close Kodi now, then open Kodi again to finish the update?'),
    'restart': ('RestartApp', 'Restart', 'MegaNexus %s is installed. Restart Kodi now?'),
}


def _os_release(path='/etc/os-release'):
    values = {}
    try:
        with open(path, encoding='utf-8') as handle:
            for line in handle:
                key, sep, value = line.strip().partition('=')
                if sep:
                    values[key] = value.strip().strip('"').lower()
    except OSError:
        pass
    return values


def platform_kind(os_release='/etc/os-release'):
    cond = xbmc.getCondVisibility
    # Android also reports System.Platform.Linux: check it first.
    if cond('System.Platform.Android'):
        return 'android'
    if cond('System.Platform.Darwin') or cond('System.Platform.OSX'):
        return 'apple'
    if cond('System.Platform.Windows'):
        return 'windows'
    if cond('System.Platform.Linux'):
        info = _os_release(os_release)
        ids = {info.get('ID', '')} | set(info.get('ID_LIKE', '').split())
        if ids & ELEC_IDS or any(cond('System.HasAddon(%s)' % aid) for aid in ELEC_ADDONS):
            return 'elec'
        return 'linux'
    return 'other'


def plan(kind=None):
    """(builtin, yes label, question with %s for the version)."""
    kind = kind or platform_kind()
    if kind == 'elec':
        return PLANS['reboot']
    if kind in ('android', 'apple'):
        return PLANS['close']
    return PLANS['restart']
