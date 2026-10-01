"""Let Kodi's Keep skin dialog finish before opening any Nuvio window."""
import json
import time
import xbmc


def activate():
    if xbmc.getSkinDir()=='skin.nuvio':return True
    response=json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc':'2.0','id':1,
        'method':'Settings.SetSettingValue','params':{'setting':'lookandfeel.skin','value':'skin.nuvio'}})))
    if response.get('error'):raise RuntimeError('Kodi could not activate the MegaNexus skin.')
    monitor=xbmc.Monitor();start=time.monotonic();seen=False
    while time.monotonic()-start<30:
        visible=xbmc.getCondVisibility('Window.IsVisible(yesnodialog)')
        if visible:seen=True
        elif seen:return xbmc.getSkinDir()=='skin.nuvio'
        elif time.monotonic()-start>=5 and xbmc.getSkinDir()=='skin.nuvio':return True
        if monitor.waitForAbort(.1):return False
    # A slow or unresolved confirmation must never be covered by our UI.
    return False
