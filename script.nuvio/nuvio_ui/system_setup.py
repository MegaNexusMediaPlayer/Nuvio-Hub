import json
import time
import xbmc
import xbmcaddon
import xbmcgui


def execute_command(command):
    """Called only after the owning Nuvio modal window has closed."""
    while command:
        if command.startswith('nuvio:activate_skin'):
            from resources.lib.skin_activation import activate
            activate()
            if xbmc.getCondVisibility('Window.IsVisible(yesnodialog)'):return
            if command.endswith(':wizard'):
                from .onboarding import run
                command=run()
                continue
            xbmc.executebuiltin('ActivateWindow(Home)')
        else:xbmc.executebuiltin(command)
        return

def rpc(method,params=None):
    result=json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})))
    if result.get('error'):raise RuntimeError('Kodi could not complete '+method)
    return result.get('result')

def ensure_addon(aid):
    from resources.lib import nuvio_uninstall
    before=nuvio_uninstall.inventory()
    if not xbmc.getCondVisibility('System.HasAddon(%s)'%aid):
        # Kodi's InstallAddon is already a cancellable modal operation. Waiting
        # for that operation distinguishes Cancel from an ongoing installation;
        # polling HasAddon afterwards used to lock Nuvio for another 60 seconds.
        xbmc.executebuiltin('InstallAddon(%s)'%aid,True)
        if not xbmc.getCondVisibility('System.HasAddon(%s)'%aid):return False
    rpc('Addons.SetAddonEnabled',{'addonid':aid,'enabled':True})
    nuvio_uninstall.record_install(aid,before,nuvio_uninstall.inventory())
    return True

def weather():
    if ensure_addon('weather.openmeteo'):
        rpc('Settings.SetSettingValue',{'setting':'weather.addon','value':'weather.openmeteo'})
        xbmcaddon.Addon('weather.openmeteo').openSettings()
        xbmc.executebuiltin('Weather.Refresh')

def screensaver():
    rpc('Settings.SetSettingValue',{'setting':'screensaver.mode','value':'screensaver.nuvio'})
    xbmcgui.Dialog().ok('Nuvio screensaver','Enabled. Set the idle delay in Kodi Settings > Interface > Screensaver.')
