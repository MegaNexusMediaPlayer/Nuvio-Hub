"""MegaNexus skin: checks, activation and persistence.

6.0.33 (Android tablet, Kodi 22): the skin was lost after an app restart and
never offered again.
* Kodi writes ``lookandfeel.skin`` to guisettings.xml only on a clean exit;
  Android often kills Kodi instead, so the next start fell back to the
  default skin. ``persist`` writes the value at once.
* Before switching, ``check`` makes sure Kodi has loaded the skin and the
  add-ons it requires in the needed versions and enabled (after a file-based
  update Kodi can still report the old interface), so the switch is not
  refused silently.
* ``nuvio_skin_applied`` now means "the user wants the MegaNexus skin": it is
  checked at every MegaNexus entry and at Kodi start (``restore_on_start``).
  "No" in Kodi's keep-skin dialog is respected for the rest of the session.
* A failed switch reports its reason instead of only returning to Home.
"""
import json
import os
import time
import xbmc

SKIN = 'skin.nuvio'
APPLIED = 'nuvio_skin_applied'          # the user wants the MegaNexus skin
DECLINED = 'nuvio.skin.declined'        # Window(Home) property: "No" this session
SETTING = 'lookandfeel.skin'
CHECK_SECONDS = 20
LAST_REASON = ['']


def _rpc(method, params):
    try:
        return json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})))
    except (TypeError, ValueError):
        return {'error': {'message': 'no reply'}}


def _details(addon_id):
    reply = _rpc('Addons.GetAddonDetails', {'addonid': addon_id, 'properties': ['enabled', 'version', 'dependencies']})
    result = reply.get('result')
    addon = result.get('addon') if isinstance(result, dict) else None
    return addon if isinstance(addon, dict) else None


def _version(value):
    parts = []
    for piece in str(value or '0').split('.'):
        digits = ''.join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def _problem():
    """'' when the skin can be used now, else what is wrong (enables what it can)."""
    skin = _details(SKIN)
    if not skin:
        return 'The MegaNexus skin is not installed. Open Nuvio Hub and choose Install or repair.'
    needed = [(SKIN, '')]
    for dep in skin.get('dependencies') or []:
        aid = dep.get('addonid') or ''
        if aid and not dep.get('optional') and not aid.startswith('xbmc.'):
            needed.append((aid, dep.get('version') or ''))
    for aid, version in needed:
        info = skin if aid == SKIN else _details(aid)
        if not info:
            return 'Kodi has not loaded %s, which the MegaNexus skin needs. Restart Kodi and try again.' % aid
        if version and _version(info.get('version')) < _version(version):
            return ('Kodi still uses %s %s; the MegaNexus skin needs %s. Restart Kodi (fully close it) '
                    'and open MegaNexus again.' % (aid, info.get('version'), version))
        if info.get('enabled') is False:
            if _rpc('Addons.SetAddonEnabled', {'addonid': aid, 'enabled': True}).get('error'):
                return 'Kodi could not enable %s. Enable it under Add-ons > My add-ons.' % aid
    return ''


def check(monitor=None):
    """Wait (up to CHECK_SECONDS) until Kodi can switch to the skin; returns the
    remaining problem or ''."""
    monitor = monitor or xbmc.Monitor()
    problem = _problem()
    if not problem:
        return ''
    xbmc.executebuiltin('UpdateLocalAddons')
    deadline = time.monotonic() + CHECK_SECONDS
    while time.monotonic() < deadline:
        if monitor.waitForAbort(.5):
            break
        problem = _problem()
        if not problem:
            return ''
    return problem


def persist(setting=SETTING, value=SKIN):
    """Write one Kodi setting into guisettings.xml immediately."""
    try:
        import xbmcvfs
        import xml.etree.ElementTree as ET
        path = xbmcvfs.translatePath('special://profile/guisettings.xml')
        tree = ET.parse(path)
        root = tree.getroot()
        if root.tag != 'settings' or root.get('version') != '2':
            return False
        node = next((n for n in root.iter('setting') if n.get('id') == setting), None)
        if node is None:
            node = ET.SubElement(root, 'setting', {'id': setting})
        if node.text == value and 'default' not in node.attrib:
            return True
        node.text = value
        node.attrib.pop('default', None)
        temp = path + '.meganexus-tmp'
        tree.write(temp, encoding='utf-8', xml_declaration=True)
        os.replace(temp, path)
        return True
    except Exception as exc:
        xbmc.log('[MegaNexus] Could not save the skin choice: %s' % exc, xbmc.LOGWARNING)
        return False


def _addon(addon):
    if addon is not None:
        return addon
    import xbmcaddon
    return xbmcaddon.Addon('plugin.video.nuviohub')


def _home():
    import xbmcgui
    return xbmcgui.Window(10000)


def switch(addon=None):
    """'ok', 'declined' (No in Kodi's keep dialog) or 'failed' (reason in LAST_REASON)."""
    LAST_REASON[0] = ''
    addon = _addon(addon)
    if xbmc.getSkinDir() == SKIN:
        persist()
        addon.setSetting(APPLIED, 'true')
        return 'ok'
    monitor = xbmc.Monitor()
    problem = check(monitor)
    if problem:
        LAST_REASON[0] = problem
        xbmc.log('[MegaNexus] Skin not switched: %s' % problem, xbmc.LOGWARNING)
        return 'failed'
    reply = _rpc('Settings.SetSettingValue', {'setting': SETTING, 'value': SKIN})
    if reply.get('error'):
        LAST_REASON[0] = 'Kodi refused the MegaNexus skin (%s).' % (reply['error'].get('message') or 'error')
        xbmc.log('[MegaNexus] %s' % LAST_REASON[0], xbmc.LOGWARNING)
        return 'failed'
    start = time.monotonic();seen = False;status = ''
    while time.monotonic() - start < 30:
        visible = xbmc.getCondVisibility('Window.IsVisible(yesnodialog)')
        if visible:
            seen = True
        elif seen:
            status = 'ok' if xbmc.getSkinDir() == SKIN else 'declined'
            break
        elif time.monotonic() - start >= 5 and xbmc.getSkinDir() == SKIN:
            status = 'ok'
            break
        if monitor.waitForAbort(.1):
            break
    if status == 'ok':
        persist()
        addon.setSetting(APPLIED, 'true')
        _home().clearProperty(DECLINED)
    elif status == 'declined':
        _home().setProperty(DECLINED, '1')
    else:
        # A slow or unresolved confirmation must never be covered by our UI.
        LAST_REASON[0] = 'Kodi did not confirm the skin change. Try again from HUB Settings.'
        status = 'failed'
    return status


def activate(addon=None):
    return switch(addon) == 'ok'


def wanted(addon=None):
    """The MegaNexus skin should be active but is not (and was not declined now)."""
    return xbmc.getSkinDir() != SKIN and not _home().getProperty(DECLINED)


def report_failure():
    import xbmcgui
    xbmcgui.Dialog().ok('MegaNexus skin', LAST_REASON[0] or 'Kodi could not switch to the MegaNexus skin.')


def restore_on_start(monitor, addon=None, busy=lambda: False, wait=15):
    """Kodi started without the MegaNexus skin although the user chose it (Kodi
    was killed before saving, or could not load the skin): switch back once
    Home is shown, through Kodi's keep-skin question."""
    addon = _addon(addon)
    if addon.getSetting(APPLIED) != 'true' or not wanted(addon):
        return ''
    if monitor.waitForAbort(wait):
        return ''
    for _ in range(120):
        if not wanted(addon):
            return ''
        if (xbmc.getCondVisibility('Window.IsActive(home)') and not xbmc.getCondVisibility('System.HasModalDialog')
                and not xbmc.Player().isPlayingVideo() and not busy()):
            xbmc.log('[MegaNexus] Kodi started without the MegaNexus skin; restoring it.', xbmc.LOGINFO)
            status = switch(addon)
            if status == 'failed':
                report_failure()
            return status
        if monitor.waitForAbort(5):
            return ''
    return ''
