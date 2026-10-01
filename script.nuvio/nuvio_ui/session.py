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
from resources.lib.theme import folder as theme_folder


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


def has_video_layer(os_release='/etc/os-release'):
    """Boxes that show hardware video on a plane under Kodi's interface
    (CoreELEC/LibreELEC/OSMC and similar, Android). PCs draw video in the GUI."""
    if xbmc.getCondVisibility('System.Platform.Android'):
        return True
    try:
        with open(os_release, encoding='utf-8', errors='replace') as stream:
            text = stream.read().lower()
    except OSError:
        return False
    return any(name in text for name in ('coreelec', 'libreelec', 'osmc', 'alexelec'))


def open_session():
    # Skin XML adds a black frame over small videos only where Kodi's own
    # translucent shade over the video plane does not show.
    xbmcgui.Window(10000).setProperty('nuvio.videolayer', '1' if has_video_layer() else '')
    scene()
    win=SessionWindow('nuvio_session.xml', xbmcaddon.Addon('script.nuvio').getAddonInfo('path'), theme_folder(),'1080i')
    win.show()
    monitor=xbmc.Monitor()
    for _ in range(100):
        if win.ready.is_set() or monitor.waitForAbort(.01):
            break
    return win
