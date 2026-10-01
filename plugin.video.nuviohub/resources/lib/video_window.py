"""Windowed video (Home trailer previews, IPTV guide preview, Details trailer).

On Windows/Linux PCs the video is drawn into Kodi's interface, so a small video
window always shows. Amlogic/CoreELEC boxes draw hardware-decoded video on a
separate plane under the interface; some CoreELEC configurations (notably Dolby
Vision processing of SDR video) leave that windowed plane black while the audio
plays, although fullscreen playback is fine. This module offers:

* a user switch - with windowed video OFF, trailers and IPTV open in Kodi's
  normal fullscreen player, which works on every device;
* a CoreELEC helper that finds the device's Dolby Vision settings (by ID text,
  no hard-coded build-specific IDs) and, on confirmation only, switches on a
  "skip Dolby Vision for windowed playback" option when the build has one.
"""
import json
import os

SETTING = 'nuvio_windowed_video'


def _addon(addon=None):
    if addon is not None:
        return addon
    import xbmcaddon
    return xbmcaddon.Addon('plugin.video.nuviohub')


def allowed(addon=None):
    """Windowed video is ON unless the user switched it off."""
    try:
        return _addon(addon).getSetting(SETTING) != 'off'
    except Exception:
        return True


def set_allowed(on, addon=None):
    _addon(addon).setSetting(SETTING, 'on' if on else 'off')


def is_coreelec(os_release='/etc/os-release'):
    try:
        with open(os_release, encoding='utf-8', errors='replace') as stream:
            return 'coreelec' in stream.read().lower()
    except OSError:
        return os.path.isdir('/storage/.kodi') and os.path.exists('/usr/lib/kernel-overlays')


def _rpc(method, params=None):
    import xbmc
    request = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        request['params'] = params
    reply = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    if reply.get('error'):
        raise RuntimeError(reply['error'].get('message') or 'JSON-RPC error')
    return reply.get('result') or {}


def dolby_vision_settings(rpc=_rpc):
    """Kodi settings whose ID mentions Dolby Vision (CoreELEC adds them)."""
    try:
        rows = rpc('Settings.GetSettings', {'level': 'expert'}).get('settings') or []
    except Exception:
        return []
    found = []
    for row in rows:
        sid = str(row.get('id') or '')
        text = (sid + ' ' + str(row.get('label') or '')).lower()
        if 'dolbyvision' in text.replace(' ', '') or '.dv' in sid.lower() or 'dolby vision' in text:
            found.append({'id': sid, 'label': str(row.get('label') or sid), 'type': row.get('type'),
                          'value': row.get('value')})
    return found


def windowed_skip_setting(settings):
    """The 'skip Dolby Vision for windowed playback' switch, if this build has one."""
    for row in settings:
        text = (row['id'] + ' ' + row['label']).lower()
        if row.get('type') == 'boolean' and 'window' in text:
            return row
    return None


def enable(setting_id, rpc=_rpc):
    rpc('Settings.SetSettingValue', {'setting': setting_id, 'value': True})


HINT_SETTING = 'nuvio_coreelec_window_hint'


def coreelec_hint(addon=None):
    """Once, on CoreELEC, point to the fix when the first small video starts."""
    try:
        addon = _addon(addon)
        if addon.getSetting(HINT_SETTING) == 'true' or not is_coreelec():
            return
        addon.setSetting(HINT_SETTING, 'true')
        import xbmcgui
        xbmcgui.Dialog().notification('Black video with sound?',
                                      'Settings > Trailers > CoreELEC: windowed video is black?', time=8000)
    except Exception:
        pass
