from resources.lib import art_cache
import xbmc
import xbmcgui
from resources.lib.trailer_support import trailer_url
import time
import threading
from resources.lib.theme import folder as theme_folder

_PLAYER=None

def wait_for_playback():
    """Close all dialogs before calling; don't reopen Home during AV/window startup."""
    monitor=xbmc.Monitor();seen=False;start=time.monotonic()
    home=xbmcgui.Window(10000);request=home.getProperty('nuvio.playback.started')
    xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')
    while not monitor.waitForAbort(.05):
        playing=xbmc.Player().isPlayingVideo()
        full=xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)')
        if full:seen=True
        if seen and not full:
            # Leaving the player is Stop, so the service commits resume before
            # the same title page returns. Closing an OSD keeps fullscreen active.
            if playing:xbmc.Player().stop()
            break
        if not playing and time.monotonic()-start>2:break
        if not seen and time.monotonic()-start>10:break
    if not xbmc.Player().isPlaying():
        home.clearProperty('nuvio.preview.active')
        # Let the service commit Stop before the details screen reads resume.
        # A missing service must not leave the UI waiting indefinitely.
        # The service saves progress and flags it within milliseconds; do not
        # keep the user staring at an empty screen longer than 0.8 s.
        for _ in range(40):
            if not request or home.getProperty('nuvio.playback.finished')==request:break
            if monitor.waitForAbort(.02):break

def play_trailer(meta):
    return show_trailer(meta)


class TrailerWindow(xbmcgui.WindowXMLDialog):
    def __init__(self,*args,**kwargs):
        super().__init__(*args);self.meta=kwargs['meta'];self.closed=False;self.opened=threading.Event()
    def onInit(self):
        self.setProperty('nuvio.title',str(self.meta.get('name') or self.meta.get('title') or 'Trailer'))
        self.setProperty('nuvio.art',art_cache.url(self.meta.get('background') or self.meta.get('poster') or ''))
        self.setFocusId(100);self.opened.set()
    def close(self):
        self.closed=True;super().close()
    def onClick(self,cid):
        if cid==100:self.close()
    def onAction(self,action):
        if action.getId() in (9,10,92,216,13):self.close()


def show_trailer(meta):
    """Resolve/cache first, then play a local clip above the existing details."""
    import xbmcaddon,uuid
    from .home_trailers import PreviewPlayer
    from .playback import job
    from resources.lib.trailer_cache import prepare
    if xbmc.Player().isPlayingVideo():
        xbmcgui.Dialog().ok('Trailer','Stop the current video before opening a trailer.');return False
    cancelled=threading.Event()
    def resolve():
        # Trailer source order from Settings > Trailers (YouTube and/or IMDb).
        from resources.lib.trailer_support import trailer_candidates,playable
        for candidate in trailer_candidates(trailer_url(meta),(meta,)):
            path=playable(candidate,prepare,cancelled)
            if path or cancelled.is_set():return path
        return ''
    try: url=job(resolve,meta,label='Preparing trailer')
    finally: cancelled.set()
    if not url:
        # A resolution failure never reaches Kodi's playback queue.
        return False
    player=PreviewPlayer();player.token=uuid.uuid4().hex
    win=TrailerWindow('nuvio_trailer.xml',xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),theme_folder(),'1080i',meta=meta)
    monitor=xbmc.Monitor();home=xbmcgui.Window(10000)
    item=xbmcgui.ListItem(label='Trailer: '+str(meta.get('name') or meta.get('title') or ''))
    item.setProperty('nuvio.preview',player.token);item.setProperty('IsPlayable','true')
    home.setProperty('nuvio.preview.active',player.token)
    started=False
    from resources.lib import refresh_guard
    try:
        refresh_guard.suspend()  # 6.0.35: no TV mode switch for a trailer (issue #4)
        win.show();player.path=url;player.play(url,item,windowed=True);begin=time.monotonic()
        while not win.closed and not monitor.abortRequested():
            if player.owns() and (player.ready or player.getTime()>.15):
                if not started:win.setProperty('nuvio.trailer.ready','1')
                started=True
            if player.failed or (started and not player.isPlayingVideo()):break
            if not started and time.monotonic()-begin>8:break
            monitor.waitForAbort(.1)
    finally:
        player.cancel();player.stop_owned();player._ended();win.close()
        refresh_guard.restore()
    return started
