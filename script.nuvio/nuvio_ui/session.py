"""Retained native base window for a frontend session.

Dialogs may close while the native fullscreen player owns input. Kodi returns
first to this ordinary WindowXML, NOT to the launcher's HUB window. The caller
then restores its existing Details/Catalog/Home objects and selection. This
base has no routing/timers and never starts another frontend instance.
"""
import threading
import xbmc
import xbmcaddon
import xbmcgui


class SessionWindow(xbmcgui.WindowXML):
    def __init__(self, *args):
        super().__init__(*args)
        self.ready = threading.Event()

    def onInit(self):
        self.ready.set()

    def onAction(self, action):
        # A Back received between dialogs must not pop the base back to HUB.
        pass


def scene(art='', title=''):
    window=xbmcgui.Window(10000)
    window.setProperty('nuvio.scene.art', str(art or ''))
    window.setProperty('nuvio.scene.title', str(title or ''))


def open_session():
    scene()
    win=SessionWindow('nuvio_session.xml', xbmcaddon.Addon('script.nuvio').getAddonInfo('path'), 'Default', '1080i')
    win.show()
    monitor=xbmc.Monitor()
    for _ in range(100):
        if win.ready.is_set() or monitor.waitForAbort(.01):
            break
    return win
