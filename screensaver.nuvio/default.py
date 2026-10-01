"""Nuvio screensaver entry point."""
import os
import sys
import xbmcaddon

backend=xbmcaddon.Addon('plugin.video.nuviohub').getAddonInfo('path')
frontend=xbmcaddon.Addon('script.nuvio').getAddonInfo('path')
for path in (backend,os.path.join(backend,'resources','lib'),frontend):
    if path not in sys.path:sys.path.insert(0,path)

if __name__=='__main__':
    from nuvio_ui.saver import launch
    launch()
