"""Cross-interpreter safeguards for screensaver startup and cancelled playback."""
import json
import time
import xbmc
import xbmcgui


def _read(key):
    try:
        value=json.loads(xbmcgui.Window(10000).getProperty(key) or '{}')
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):return {}


def active():
    home=xbmcgui.Window(10000);token=home.getProperty('nuvio.saver.active')
    pending=_read('nuvio.saver.pending')
    if token and pending.get('token')==token:
        try:expired=not 0<=time.time()-float(pending.get('issued',0))<=10
        except (ValueError,TypeError):expired=True
        if expired:
            home.clearProperty('nuvio.saver.pending');home.clearProperty('nuvio.saver.active');return False
    return bool(token)


def cancel_play(token):
    if token:
        xbmcgui.Window(10000).setProperty('nuvio.saver.cancelled',json.dumps({'token':token,'issued':time.time()}))


def stop_cancelled_preview(player):
    """Service guard: a late queued AV start must not survive its saver owner.

    Item-token identity, not a file path or global flag, authorizes Stop. A
    concurrent user-selected movie is never stopped by this cleanup.
    """
    home=xbmcgui.Window(10000);value=_read('nuvio.saver.cancelled')
    if not value.get('token'):return False
    try:recent=0<=time.time()-float(value.get('issued',0))<=30
    except (ValueError,TypeError):recent=False
    if not recent:home.clearProperty('nuvio.saver.cancelled');return False
    try:owned=player.getPlayingItem().getProperty('nuvio.preview')==value['token']
    except Exception:return False
    if not owned:return False
    xbmc.executebuiltin('PlayerControl(Stop)')
    return True
