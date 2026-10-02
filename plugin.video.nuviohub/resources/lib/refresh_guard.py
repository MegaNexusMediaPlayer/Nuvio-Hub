"""No display mode switch for small preview videos (6.0.35, GitHub issue #4).

With Kodi's "Adjust display refresh rate" on, starting a trailer or a Sports
preview switched the TV's mode. On some CoreELEC builds (Dolby Vision
avdvplus) a video in a small window then stays black - audio only - and the
GUI hangs. While a preview plays the setting is turned off and afterwards put
back. When the setting is already off nothing is touched, so devices that
work today keep working exactly the same way. The original value is also
kept in the add-on settings, so the service restores it after a crash.
"""
import json
import xbmc

SETTING = 'videoplayer.adjustrefreshrate'
STORE = 'nuvio_refresh_restore'          # original value while suspended
PROPERTY = 'nuvio.refresh.suspended'     # Window(Home): previews holding it


def _rpc(method, params):
    try:
        reply = json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
    except (TypeError, ValueError):
        return None
    return reply.get('result') if isinstance(reply, dict) else None


def _addon():
    import xbmcaddon
    return xbmcaddon.Addon('plugin.video.nuviohub')


def _home():
    import xbmcgui
    return xbmcgui.Window(10000)


def suspend():
    """Before a preview starts. Returns True when the setting was switched off."""
    home = _home()
    if home.getProperty(PROPERTY):
        return True   # another preview already holds it
    result = _rpc('Settings.GetSettingValue', {'setting': SETTING}) or {}
    value = result.get('value')
    if not value:
        return False  # off (0) or unknown: nothing to do
    _addon().setSetting(STORE, str(value))
    if _rpc('Settings.SetSettingValue', {'setting': SETTING, 'value': 0}) is None:
        _addon().setSetting(STORE, '')
        return False
    home.setProperty(PROPERTY, '1')
    return True


def restore(force=False):
    """After the preview stopped (cheap when nothing was suspended). ``force``
    (service start) also restores a value left behind by a crash."""
    home = _home()
    if not force and not home.getProperty(PROPERTY):
        return False
    addon = _addon()
    stored = addon.getSetting(STORE)
    if not stored and not home.getProperty(PROPERTY):
        return False
    home.clearProperty(PROPERTY)
    addon.setSetting(STORE, '')
    if stored:
        try:
            _rpc('Settings.SetSettingValue', {'setting': SETTING, 'value': int(stored)})
        except ValueError:
            return False
    return True
