"""TV side of "Set up on phone": QR window that owns the local setup service.

The service (resources.lib.phone_setup) starts when this window opens and is
stopped when it closes: Save on the phone, Back/Cancel on the TV, or 15 idle
minutes. Nothing keeps listening afterwards.
"""
import os
import xbmc
import xbmcaddon
import xbmcgui
from resources.lib import settings_cache
from resources.lib.theme import folder as theme_folder

POLL = .25
HINT_AFTER = 30   # seconds without the phone -> say what usually blocks it


class PhoneWindow(xbmcgui.WindowXMLDialog):
    # Callbacks only set flags; the owning loop in run() does the work.
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.qr = kwargs.get('qr') or ''
        self.url = kwargs.get('url') or ''
        self.cancelled = False

    def onInit(self):
        self.setProperty('nuvio.phone.qr', self.qr)
        self.setProperty('nuvio.phone.url', self.url)
        self.setProperty('nuvio.phone.status', 'Waiting for the phone…')
        self.setFocusId(100)

    def onClick(self, cid):
        if cid == 100:
            self.cancelled = True
            self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 92, 216, 247, 257, 275, 61448, 61467):
            self.cancelled = True
            self.close()


def run():
    """Returns True when the phone saved the setup."""
    from resources.lib.phone_setup import SetupService
    from resources.lib.plex_qr import qr_png
    from resources.lib.phone_setup import lan_ip
    host = lan_ip()
    if host.startswith('127.'):
        xbmcgui.Dialog().ok('Set up on phone', 'This device is not connected to a network. Connect it to the same Wi-Fi '
                            'as your phone and try again.')
        return False
    try:
        service = SetupService(host=host).start()
    except OSError:
        xbmcgui.Dialog().ok('Set up on phone', 'The setup service could not start on this device. '
                            'Check the network connection and try again.')
        return False
    qr = ''
    window = None
    saved = False
    try:
        qr = qr_png(service.url, box_size=10, border=2) or ''
        window = PhoneWindow('nuvio_phone_setup.xml', xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),
                             theme_folder(),'1080i', qr=qr, url=service.url)
        window.show()
        monitor = xbmc.Monitor()
        connected = False
        waited = 0.0
        while not window.cancelled and not monitor.abortRequested():
            waited += POLL
            if not connected and abs(waited - HINT_AFTER) < POLL / 2:
                window.setProperty('nuvio.phone.status', 'No phone yet? Use the same Wi-Fi. A firewall here must allow TCP port %d.' % service.port)
            if service.saved:
                saved = True
                break
            if service.connected and not connected:
                connected = True
                window.setProperty('nuvio.phone.status', 'Phone connected · waiting for Save')
            if service.idle():
                break
            if monitor.waitForAbort(POLL):
                break
    finally:
        if window:
            window.close()
        service.stop()
        if qr:
            try:
                os.remove(qr)  # the QR carries this session's key
            except OSError:
                pass
    if saved:
        settings_cache.invalidate()
        try:
            from .browse_meta import clear
            clear()  # card shape, ratings or catalogs may have changed
        except Exception:
            pass
        xbmcgui.Dialog().notification('MegaNexus', 'Setup saved from the phone', xbmcgui.NOTIFICATION_INFO, 3000)
    return saved
