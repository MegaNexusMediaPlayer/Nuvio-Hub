"""Image/GIF or owned video screensaver, independent of watch/progress playback.

Kodi deactivates a registered screensaver when video starts. The registered
entry therefore wakes it before handing off to a separate ordinary script.
That script owns its modal and only its own video; it never replaces paused
media, clears playlists, or changes application fullscreen/resolution.
"""
import json
import os
import time
import uuid
import threading
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from resources.lib import presentation_settings, saver_state
from .home_trailers import PreviewPlayer
from .system_setup import rpc

DEFAULT_ART='special://home/addons/script.nuvio/resources/media/nuvio_banner.png'
VIDEO_EXTENSIONS=('.mp4','.m4v','.mkv','.webm','.mov','.avi','.ts','.m2ts')


def video_file(addon):
    path=addon.getSetting('nuvio_screensaver_video').strip()
    # A chosen local/SMB file only. No arbitrary plugin routes, manifests or
    # streaming credentials are passed to the screensaver playback queue.
    return path if addon.getSetting('nuvio_screensaver_type')=='video' and path.lower().endswith(VIDEO_EXTENSIONS) and xbmcvfs.exists(path) else ''


class SaverWindow(xbmcgui.WindowXMLDialog):
    def __init__(self,*args):
        super().__init__(*args)
        self.closed=False;self.ready=threading.Event();self.opened=time.monotonic()
    def onInit(self):
        addon=xbmcaddon.Addon('plugin.video.nuviohub')
        self.setProperty('nuvio.background',addon.getSetting('nuvio_screensaver_art') or DEFAULT_ART)
        presentation_settings.sync()
        self.ready.set()
    def onAction(self,action):
        aid=action.getId()
        if aid==0 or (aid==107 and time.monotonic()-self.opened<.4):return
        self.close()
    def onClick(self,cid):self.close()
    def close(self):
        self.closed=True
        super().close()


class SaverMonitor(xbmc.Monitor):
    def __init__(self,window=None):
        super().__init__();self.window=window;self.deactivated=False
    def onScreensaverDeactivated(self):
        self.deactivated=True
        if self.window:self.window.close()
    def onAbortRequested(self):
        if self.window:self.window.close()


LOOP_RESTART_GRACE=3.0


class VideoPlayer(PreviewPlayer):
    def __init__(self):
        super().__init__();self.ended=False;self.ended_at=0.0
    def onPlayBackEnded(self):
        # The owner may start another loop, with a fresh playback token.
        self.ended=True;self.ended_at=time.monotonic()
    def onAVStarted(self):
        super().onAVStarted()
        if self.ready:
            try:self.showSubtitles(False)
            except Exception:pass


def window():
    return SaverWindow('nuvio_screensaver.xml',xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),'Default','1080i')


def run_image():
    home=xbmcgui.Window(10000);token=uuid.uuid4().hex
    home.setProperty('nuvio.saver.active',token)
    win=None
    try:
        win=window();monitor=SaverMonitor(win)
        win.show()
        while not win.closed and not monitor.abortRequested():monitor.waitForAbort(.1)
    finally:
        if win:win.close()
        if home.getProperty('nuvio.saver.active')==token:home.clearProperty('nuvio.saver.active')


def launch():
    addon=xbmcaddon.Addon('plugin.video.nuviohub');home=xbmcgui.Window(10000)
    if saver_state.active():return
    # isPlaying includes paused video/audio. Do not interrupt it to animate.
    if not video_file(addon) or xbmc.Player().isPlaying():
        run_image();return
    token=uuid.uuid4().hex;issued=time.time()
    home.setProperty('nuvio.saver.active',token)
    home.setProperty('nuvio.saver.pending',json.dumps({'token':token,'issued':issued}))
    launched=False
    try:
        monitor=SaverMonitor()
        if xbmc.getCondVisibility('System.ScreenSaverActive'):
            # Kodi consumes this wake action rather than navigating the page.
            rpc('Input.ContextMenu')
            for _ in range(30):
                if monitor.deactivated or not xbmc.getCondVisibility('System.ScreenSaverActive'):break
                if monitor.waitForAbort(.05):return
            if xbmc.getCondVisibility('System.ScreenSaverActive'):return
        if monitor.abortRequested() or xbmc.Player().isPlaying():return
        path=os.path.join(xbmcaddon.Addon('screensaver.nuvio').getAddonInfo('path'),'video.py')
        # Kodi's registered screensaver interpreter is now free to terminate.
        xbmc.executebuiltin('RunScript("%s",%s)'%(path.replace('"',''),token))
        launched=True
    finally:
        if not launched and home.getProperty('nuvio.saver.active')==token:
            home.clearProperty('nuvio.saver.active');home.clearProperty('nuvio.saver.pending')


def consume_handoff(token):
    home=xbmcgui.Window(10000)
    try:data=json.loads(home.getProperty('nuvio.saver.pending') or '{}')
    except ValueError:return False
    if not isinstance(data,dict):return False
    try:age=time.time()-float(data.get('issued',0))
    except (ValueError,TypeError):return False
    if data.get('token')!=token or not 0<=age<=10 or home.getProperty('nuvio.saver.active')!=token:return False
    home.clearProperty('nuvio.saver.pending');return True


def run_video(token):
    home=xbmcgui.Window(10000)
    if not consume_handoff(token):
        if home.getProperty('nuvio.saver.active')==token:home.clearProperty('nuvio.saver.active')
        return
    win=None;player=None;muted_by_us=False
    try:
        addon=xbmcaddon.Addon('plugin.video.nuviohub');path=video_file(addon)
        if not path or xbmc.Player().isPlaying():return
        win=window();monitor=xbmc.Monitor();win.show()
        for _ in range(100):
            if win.ready.is_set() or win.closed or monitor.waitForAbort(.01):break
        if win.closed or not win.ready.is_set() or xbmc.Player().isPlaying():return
        original=(rpc('Application.GetProperties',{'properties':['muted']}) or {}).get('muted')
        if original is False:
            if rpc('Application.SetMute',{'mute':True}) is True:muted_by_us=True
            else:path=''  # Silent video is required; do not play unexpected audio.
        elif original is not True:
            # Unknown sound state: display artwork rather than play audio.
            path=''
        begin=0;started=False
        while not win.closed and not monitor.abortRequested():
            if path and (player is None or player.ended):
                if xbmc.Player().isPlaying():
                    # Kodi still reports "playing" for a moment after EOF, with no
                    # video left to own. Short clips looped once and then the
                    # screensaver closed; wait for the teardown instead.
                    if player and player.ended and time.monotonic()-player.ended_at<LOOP_RESTART_GRACE:
                        monitor.waitForAbort(.05);continue
                    break  # Another caller owns playback.
                if player:player.cancel();player._ended()
                player=VideoPlayer();player.token=uuid.uuid4().hex;player.path=path
                item=xbmcgui.ListItem(label='Nuvio screensaver')
                item.setProperty('nuvio.preview',player.token);item.setProperty('IsPlayable','true')
                home.setProperty('nuvio.preview.active',player.token)
                home.setProperty('nuvio.preview.silent',player.token)
                begin=time.monotonic();started=False
                player.play(path,item,windowed=True)
            if player and path:
                if player.failed or (not started and time.monotonic()-begin>8):
                    player.cancel();player.stop_owned();path='';win.setProperty('nuvio.saver.video','')
                elif player.owns() and player.ready:
                    started=True;win.setProperty('nuvio.saver.video','1')
                elif started and not player.ended and not player.isPlayingVideo():break
                elif started and player.isPlayingVideo() and not player.owns():break
            monitor.waitForAbort(.05)
    finally:
        if player:
            saver_state.cancel_play(player.token)
            player.cancel();player.stop_owned();player._ended()
            # The backend service rejects this exact item token if a queued
            # playback starts after this interpreter has already exited.
        if win:win.close()
        if muted_by_us:
            try:
                current=(rpc('Application.GetProperties',{'properties':['muted']}) or {}).get('muted')
                if current is True:rpc('Application.SetMute',{'mute':False})
            except Exception:xbmc.log('[Nuvio] Could not restore screensaver mute state.',xbmc.LOGWARNING)
        if home.getProperty('nuvio.saver.active')==token:
            home.clearProperty('nuvio.saver.active');home.clearProperty('nuvio.saver.pending')
