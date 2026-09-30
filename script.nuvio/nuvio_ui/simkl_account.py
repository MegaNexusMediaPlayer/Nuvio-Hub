"""Simkl PIN linking and tracking preferences, without leaving Nuvio."""
import queue
import threading
import time
from urllib.parse import quote, urlsplit
import xbmc
import xbmcgui
from resources.lib import simkl, settings_cache
from .settings import ADDON
from .playback import job


def link(replace=False):
    if simkl.authorized() and not replace:
        xbmcgui.Dialog().ok('Simkl','Already connected. Use Simkl settings to sync or disconnect.')
        return True
    code=job(lambda:simkl._request('/oauth/pin?client_id='+quote(simkl.client_id(),safe=''),timeout=8),label='Connecting to Simkl')
    if code is None:return False
    user_code=str(code.get('user_code') or '')
    if not user_code:raise ValueError('Simkl did not return a pairing code. Check the connection or your Simkl client ID.')
    verify=str(code.get('verification_url') or simkl.PIN_URL_FALLBACK)
    if urlsplit(verify).hostname not in ('simkl.com','www.simkl.com'):verify=simkl.PIN_URL_FALLBACK
    interval=max(5,min(60,int(code.get('interval') or 5)))
    expires=max(30,min(1800,int(code.get('expires_in') or 900)))
    deadline=time.monotonic()+expires;next_poll=0;pending=False;results=queue.Queue()
    path='/oauth/pin/%s?client_id=%s'%(quote(user_code,safe=''),quote(simkl.client_id(),safe=''))
    def poll():
        try:results.put(('ok',simkl._request(path,timeout=8)))
        except Exception as exc:results.put(('error',getattr(exc,'code',0)))
    dialog=xbmcgui.DialogProgress();dialog.create('Simkl PIN: '+user_code,simkl._build_pin_message(verify,user_code,expires))
    last_remaining=expires
    monitor=xbmc.Monitor()
    try:
        while not dialog.iscanceled() and not monitor.abortRequested() and time.monotonic()<deadline:
            now=time.monotonic()
            remaining=max(0,int(deadline-now))
            if remaining!=last_remaining:
                dialog.update(int(100*(expires-remaining)/expires),simkl._build_pin_message(verify,user_code,remaining))
                last_remaining=remaining
            if not pending and now>=next_poll:
                pending=True;threading.Thread(target=poll,daemon=True).start()
            try:status,data=results.get_nowait()
            except queue.Empty:pass
            else:
                pending=False;next_poll=now+interval
                if status=='ok' and isinstance(data,dict) and data.get('access_token'):
                    # Only the active dialog may commit a token; a cancelled worker cannot.
                    if dialog.iscanceled() or monitor.abortRequested():return False
                    if not simkl.save_token({'access_token':data['access_token'],'created_at':int(time.time())}):
                        raise ValueError('Could not save the Simkl connection. Check Kodi profile storage.')
                    ADDON.setSetting('enable_simkl','true')
                    ADDON.setSetting('simkl_mark_watched','true')
                    settings_cache.invalidate();simkl.invalidate_cache()
                    dialog.close();xbmcgui.Dialog().ok('Simkl connected','Watched films and episodes will be sent to Simkl when playback ends or passes your watched threshold. You can import your existing history in Simkl settings.')
                    return True
                if status=='error' and data==429:interval=min(60,interval*2);next_poll=now+interval
                elif status=='error' and data in (401,403,412):raise ValueError('Simkl rejected the application credentials. Check the client ID in Simkl settings.')
            monitor.waitForAbort(.15)
    finally:dialog.close()
    return False


def sync_now():
    if not simkl.authorized():return link()
    def work():
        simkl.invalidate_cache()
        from resources.lib import simkl_watched
        simkl_watched.refresh(force=True)
        continuing=simkl.sync_continue_watching()
        movies,episodes=simkl.import_watched()
        from resources.lib.favorites_store import refresh_external_mirror
        refresh_external_mirror()
        return continuing,movies,episodes
    result=job(work,label='Syncing Simkl')
    if result:xbmcgui.Dialog().ok('Simkl','Imported %d continue-watching entries, %d watched films and %d watched episodes.'%tuple(int(n or 0) for n in result))


def run():
    from . import settings_page as page
    dialog=xbmcgui.Dialog()
    def rows():
        settings_cache.invalidate()
        linked=simkl.authorized()
        result=[page.item('Disconnect' if linked else 'Connect with PIN','Connected' if linked else 'Not connected'),
            page.item('Sync history, watching and watchlist now'),
            page.item('Send watched status',enabled=simkl.mark_watched_enabled()),
            page.item('Watched threshold','%d%%'%simkl.watched_threshold_percent()),
            page.item('Background history import',enabled=ADDON.getSetting('simkl_service_sync')!='false'),
            page.item('Local copy of Simkl Plan to Watch',enabled=ADDON.getSetting('watchlist_merge_simkl')!='false'),
            page.item('Custom Simkl client ID','Nuvio Hub' if simkl.client_id()==simkl.DEFAULT_CLIENT_ID else 'Custom'),
            page.item('About Simkl')]
        if simkl.needs_app_relink():result.append(page.item('Reconnect as Nuvio Hub','Keep current connection until new PIN is approved'))
        return result+[page.item('Back')]
    def choose(pick):
        if pick==(9 if simkl.needs_app_relink() else 8):return page.DONE
        linked=simkl.authorized()
        try:
            if pick==0:
                if linked:
                    if dialog.yesno('Simkl','Disconnect this device? Your Simkl history is kept.'):simkl.logout()
                else:link()
            elif pick==1:sync_now()
            elif pick in (2,4,5):
                key={2:'simkl_mark_watched',4:'simkl_service_sync',5:'watchlist_merge_simkl'}[pick]
                ADDON.setSetting(key,'true' if ADDON.getSetting(key)=='false' else 'false')
            elif pick==3:
                values=[70,75,80,85,90,95,99];i=dialog.select('Mark watched after',[str(n)+'%' for n in values])
                if i>=0:ADDON.setSetting('simkl_watched_threshold',str(values[i]))
            elif pick==6:
                if linked:dialog.ok('Simkl client ID','Disconnect before changing the application client ID.');return
                value=dialog.input('Simkl V1 client ID (blank uses Nuvio Hub)',ADDON.getSetting('simkl_client_id') or '')
                ADDON.setSetting('simkl_client_id',value.strip())
            elif pick==7:dialog.ok('Simkl','https://simkl.com\nTracks watched films and episodes. Local resume positions stay in Nuvio. New PIN connections use the registered Nuvio Hub application. A custom AUTH V1 client ID is optional.')
            elif pick==8 and simkl.needs_app_relink():link(replace=True)
        except Exception as exc:
            dialog.ok('Simkl',str(exc) if isinstance(exc,ValueError) else 'Could not complete the Simkl request. Check your connection and account, then retry.')
        finally:settings_cache.invalidate()
    return page.show('Simkl account & tracking',rows,choose)
