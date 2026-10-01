"""Upgrade migration: restore Kodi controls changed by Nuvio 6.0.1–6.0.3."""
import json
import xbmc
from .nuviohub.common import profile_path

VALUES = {'videoplayer.seeksteps': [-10,-5,-3,-1,1,3,5,10], 'videoplayer.seekdelay': 250}

def rpc(method, **params):
    response=json.loads(xbmc.executeJSONRPC(json.dumps(dict(jsonrpc='2.0',id=1,method=method,params=params))))
    if 'error' in response:raise ValueError('Kodi seek setting unavailable')
    return response.get('result')

def apply():
    """Migrate builds 6.0.1–6.0.3 back to the user's original Kodi controls."""
    restore()

def restore():
    import xbmcvfs
    from pathlib import Path
    keys=Path(xbmcvfs.translatePath('special://profile/keymaps/nuvio-playback.xml'))
    if keys.exists() and 'Nuvio owned playback keys' in keys.read_text(encoding='utf-8'):
        keys.unlink();xbmc.executebuiltin('Action(ReloadKeymaps)')
    path=Path(profile_path())/'nuvio_seek_backup.json'
    if path.exists():
        previous=json.loads(path.read_text(encoding='utf-8'))
        for key,value in previous.items():
            if key in VALUES and rpc('Settings.GetSettingValue',setting=key)['value']==VALUES[key]:
                if rpc('Settings.SetSettingValue',setting=key,value=value) is not True:
                    raise ValueError('Kodi could not restore seek settings')
        path.unlink()
