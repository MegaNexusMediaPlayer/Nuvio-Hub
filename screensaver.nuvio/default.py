import xbmc
import xbmcaddon
import xbmcgui

class Saver(xbmcgui.WindowXMLDialog):
    def onInit(self):
        art=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_screensaver_art') or 'special://home/addons/script.nuvio/resources/media/nuvio_banner.png'
        self.setProperty('nuvio.background',art)
    def onAction(self,action):self.close()

class Monitor(xbmc.Monitor):
    def onScreensaverDeactivated(self):window.close()
    def onAbortRequested(self):window.close()

window=Saver('nuvio_screensaver.xml',xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),'Default','1080i')
monitor=Monitor()
try:window.doModal()
finally:window.close()
