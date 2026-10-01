from .dialog import Dialog
"""Channel browser with EPG and two-click preview/fullscreen playback."""
import json
import time
import queue
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from .system_setup import rpc,ensure_addon
from .playback import plain_label,job
from resources.lib.iptv_config import xtream_urls,write_instance

ADDON=xbmcaddon.Addon('plugin.video.nuviohub')
_CHANNEL_CACHE=OrderedDict()
_CHANNEL_LOCK=threading.Lock()

def configure():
    dialog=xbmcgui.Dialog()
    if xbmc.getCondVisibility('Pvr.IsPlayingTV'):
        dialog.ok('IPTV','Stop live TV before changing the playlist.');return False
    choice=dialog.select('IPTV setup',['Xtream account','M3U playlist + XMLTV EPG','Use an existing Kodi PVR setup'])
    if choice<0:return False
    if choice==2:return True
    if choice==0:
        server=dialog.input('Xtream server URL including port').strip()
        if not server:return False
        username=dialog.input('Xtream username').strip()
        password=dialog.input('Xtream password',option=xbmcgui.ALPHANUM_HIDE_INPUT)
        if not username or not password:return False
        m3u,epg=xtream_urls(server,username,password)
    else:
        m3u=dialog.input('M3U playlist URL').strip()
        if not m3u:return False
        epg=dialog.input('XMLTV EPG URL (optional if supplied in the playlist)').strip()
    if not ensure_addon('pvr.iptvsimple'):return False
    profile=xbmcvfs.translatePath(xbmcaddon.Addon('pvr.iptvsimple').getAddonInfo('profile'))
    rpc('Addons.SetAddonEnabled',{'addonid':'pvr.iptvsimple','enabled':False})
    try:
        iid=write_instance(profile,m3u,epg,ADDON.getSetting('nuvio_iptv_instance'))
        ADDON.setSetting('nuvio_iptv_instance',str(iid))
        ADDON.setSetting('nuvio_iptv_configured','true')
    finally:rpc('Addons.SetAddonEnabled',{'addonid':'pvr.iptvsimple','enabled':True})
    return True

def channels(group='alltv',refresh=False):
    with _CHANNEL_LOCK:
        cached=_CHANNEL_CACHE.get(group)
        if not refresh and cached and time.monotonic()-cached[0]<60:return list(cached[1])
    # Kodi 21 'icon' is the channel logo; 'thumbnail' can be current EPG art.
    # Programme details/artwork are not requested
    # for every channel; the selected channel's guide loads after focus settles.
    rows=(rpc('PVR.GetChannels',{'channelgroupid':group,'properties':['icon','channelnumber','subchannelnumber','uniqueid','clientid']}) or {}).get('channels') or []
    # The unsorted response may follow database IDs rather than channel order.
    rows=sorted(rows,key=lambda r:(int(r.get('channelnumber') or 0),int(r.get('subchannelnumber') or 0)))
    if rows:
        with _CHANNEL_LOCK:
            _CHANNEL_CACHE[group]=(time.monotonic(),rows);_CHANNEL_CACHE.move_to_end(group)
            while len(_CHANNEL_CACHE)>8:_CHANNEL_CACHE.popitem(last=False)
    return list(rows)


def groups():
    rows=(rpc('PVR.GetChannelGroups',{'channeltype':'tv'}) or {}).get('channelgroups') or []
    return [{'channelgroupid':'alltv','label':'All channels'}]+[r for r in rows if r.get('channelgroupid')!='alltv']


def epg_time(value):
    # PVR JSON-RPC serializes UTC without a suffix. Convert once to local time.
    try:
        date=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
        return date.astimezone()
    except (ValueError,TypeError):return None


def programme_time(row):
    start,end=epg_time(row.get('starttime')),epg_time(row.get('endtime'))
    if not start or not end:return 'Time unavailable'
    return start.strftime('%d %b  %H:%M')+' - '+end.strftime('%H:%M')


def broadcasts(channel):
    rows=(rpc('PVR.GetBroadcasts',{'channelid':channel,'properties':['title','plot','starttime','endtime','isactive','isplayable']}) or {}).get('broadcasts') or []
    return sorted(rows,key=lambda r:r.get('starttime') or '')

def channel_key(row):return '%s:%s'%(row.get('clientid',''),row.get('uniqueid',row['channelid']))

def current_id():
    try:
        for p in rpc('Player.GetActivePlayers') or []:
            if p['type']=='video':return (rpc('Player.GetItem',{'playerid':p['playerid']}) or {}).get('item',{}).get('id')
    except Exception:pass
    return None


def open_preview(channel_id):
    """Kodi Player.Open(channelid) obeys the PVR fullscreen preference.

    JSON-RPC has no windowed option for a channel. Temporarily override the
    documented native preference while its synchronous PlayMedia call decides
    the playback mode, then restore it even on errors. Never change app-window
    fullscreen, video zoom, resolution, or the user's saved channel setup.
    """
    setting='pvrplayback.switchtofullscreenchanneltypes'
    previous=(rpc('Settings.GetSettingValue',{'setting':setting}) or {}).get('value')
    if type(previous) is not int or previous not in (0,1,2,3):
        raise ValueError('Kodi could not enable the IPTV preview. Check PVR playback settings.')
    changed=previous!=0
    if changed and rpc('Settings.SetSettingValue',{'setting':setting,'value':0}) is not True:
        raise ValueError('Kodi did not allow windowed IPTV playback.')
    try:
        return rpc('Player.Open',{'item':{'channelid':channel_id}})
    finally:
        if changed:
            # Do not overwrite a preference the user changed in another window.
            current=(rpc('Settings.GetSettingValue',{'setting':setting}) or {}).get('value')
            if current==0:rpc('Settings.SetSettingValue',{'setting':setting,'value':previous})

class IPTV(Dialog):
    def __init__(self,*args,**kwargs):
        super().__init__(*args)
        self.rows=kwargs['rows'];self.group=kwargs.get('group','alltv')
        self.groups=kwargs.get('groups') or [{'channelgroupid':'alltv','label':'All channels'}]
        self.playing=current_id();self.fullscreen=False;self.closed=False
        self._pool=ThreadPoolExecutor(max_workers=2);self._jobs={};self._updates=queue.Queue()
        self._cache=OrderedDict();self._generation=0;self._selection=None;self._selected_at=0
        self._epg_channel=None;self._epg=[];self._epg_refresh=0;self._ready=False
        self._requested_group=self.group;self._pending_group=None
        self._initialized=False;self._selected=0;self._back_block_until=0
    def onInit(self):
        if self._initialized:
            self.getControl(501).reset()
            self.getControl(501).addItems([xbmcgui.ListItem(label=plain_label(g['label'])) for g in self.groups])
            selected=next((i for i,g in enumerate(self.groups) if g['channelgroupid']==self.group),0)
            self.getControl(501).selectItem(selected)
            self.setProperty('nuvio.group',plain_label(self.groups[selected]['label']))
            current=next((r for r in self.rows if r['channelid']==self.playing),None)
            self.setProperty('nuvio.playing',plain_label(current.get('label')) if current else '')
            self._paint()
            if self.rows:self.getControl(500).selectItem(min(self._selected,len(self.rows)-1))
            if self._epg:self._paint_epg(self._epg)
            self._ready=True;self.restore_focus()
            return
        self._initialized=True
        self.getControl(501).reset()
        self.getControl(501).addItems([xbmcgui.ListItem(label=plain_label(g['label'])) for g in self.groups])
        selected=next((i for i,g in enumerate(self.groups) if g['channelgroupid']==self.group),0)
        self.getControl(501).selectItem(selected)
        self.setProperty('nuvio.group',plain_label(self.groups[selected]['label']));self._paint()
        self._ready=True;self.setFocusId(500)
        last=ADDON.getSetting('nuvio_iptv_last_unique')
        row=next((r for r in self.rows if channel_key(r)==last),None)
        if row:
            self.getControl(500).selectItem(self.rows.index(row))
            if current_id()!=row['channelid']:self._play(row)
            else:self.setProperty('nuvio.playing',plain_label(row.get('label')))
        self._select_channel()
    def _paint(self):
        items=[]
        for number,r in enumerate(self.rows,1):
            now=r.get('broadcastnow') or {}
            # A group has a contiguous 1..N list; provider numbers remain in the
            # PVR database and the stable playback ID is never renumbered.
            li=xbmcgui.ListItem(label='%d  %s'%(number,plain_label(r.get('label'))),label2=plain_label(now.get('title') or ''))
            li.setArt({'icon':r.get('icon') or '', 'thumb':'', 'fanart':''});items.append(li)
        self.getControl(500).reset();self.getControl(500).addItems(items)
        self.setProperty('nuvio.iptv.status','' if items else 'No channels in this category.')

    def _submit(self,kind,key,call):
        previous=self._jobs.get(kind)
        if previous and not previous.done():return False
        generation=self._generation
        def load():
            try:result=call()
            except Exception:result=None
            if not self.closed:self._updates.put((kind,generation,key,result))
        self._jobs[kind]=self._pool.submit(load)
        return True

    def _request_group(self,key,refresh=False):
        self._requested_group=key
        self._pending_group=(key,refresh)
        self.setProperty('nuvio.iptv.status','Loading category...')

    def _load_pending_group(self):
        if self._pending_group:
            key,refresh=self._pending_group
            if self._submit('group',key,lambda:channels(key,refresh=refresh)):
                self._pending_group=None

    def _select_channel(self):
        pos=self.getControl(500).getSelectedPosition()
        if not 0<=pos<len(self.rows):return
        row=self.rows[pos];cid=row['channelid']
        if cid!=self._selection:
            self._selection=cid;self._selected_at=time.monotonic();self._epg_channel=None
            self.setProperty('nuvio.epg.channel',plain_label(row.get('label')))
            # Immediate now/next, then the full guide after the focus settles.
            self._paint_epg([r for r in (row.get('broadcastnow'),row.get('broadcastnext')) if r])

    def _paint_epg(self,rows):
        self._epg=rows
        items=[]
        for row in rows:
            li=xbmcgui.ListItem(label=programme_time(row),label2=plain_label(row.get('title') or row.get('label') or 'Programme'))
            li.setProperty('live','1' if row.get('isactive') else '')
            items.append(li)
        self.getControl(504).reset();self.getControl(504).addItems(items)
        now=datetime.now(timezone.utc)
        index=next((i for i,r in enumerate(rows) if (epg_time(r.get('endtime')) or now)>now),0)
        if items:self.getControl(504).selectItem(index)
        self.setProperty('nuvio.epg.empty','' if items else 'No EPG available for this channel.')

    def tick(self):
        self.drain_events()
        if self.closed or not self._ready:return
        self._load_pending_group()
        self._select_channel()
        now=time.monotonic()
        if self._selection is not None and now-self._selected_at>=.3 and (self._epg_channel!=self._selection or now>=self._epg_refresh):
            cid=self._selection;cached=self._cache.get(cid)
            if cached and now-cached[0]<60:
                self._paint_epg(cached[1]);self._epg_channel=cid;self._epg_refresh=cached[0]+60
            elif self._submit('epg',cid,lambda:broadcasts(cid)):
                self._epg_channel=cid;self._epg_refresh=now+60
        for _ in range(8):
            try:kind,generation,key,result=self._updates.get_nowait()
            except queue.Empty:break
            if generation!=self._generation:continue
            if kind=='group':
                if key!=self._requested_group:continue
                if result is not None:
                    self.group=key;self.rows=result;self._selection=None;self._paint()
                    self.setProperty('nuvio.group',plain_label(next(g['label'] for g in self.groups if g['channelgroupid']==key)))
                    ADDON.setSetting('nuvio_iptv_last_group',str(key));self.setFocusId(500)
                else:self.setProperty('nuvio.iptv.status','Could not load this category. Select it to retry.')
            elif kind=='epg':
                if result is not None:
                    self._cache[key]=(now,result);self._cache.move_to_end(key)
                    while len(self._cache)>24:self._cache.popitem(last=False)
                if key==self._selection:
                    if result:self._paint_epg(result)
                    elif not self._epg:self.setProperty('nuvio.epg.empty','EPG is not available yet. Check the XMLTV source in IPTV setup.')

    def _play(self,row):
        # Opening a channel via JSON-RPC uses Kodi PVR's EPG, buffering and tuner.
        try:open_preview(row['channelid'])
        except (RuntimeError,ValueError):
            self.setProperty('nuvio.iptv.status','This channel could not start in preview. Check the playlist or try another channel.')
            return
        self.playing=row['channelid']
        ADDON.setSetting('nuvio_iptv_last_unique',channel_key(row))
        self.setProperty('nuvio.playing',plain_label(row.get('label')))
        # Keep this modal visible: playback is rendered by its videowindow.
    def onClick(self,cid):
        if cid==500 and self.rows:
            row=self.rows[self.getControl(500).getSelectedPosition()]
            if self.playing==row['channelid'] and current_id()==row['channelid']:
                self._selected=self.getControl(500).getSelectedPosition()
                self.child(self._fullscreen)
                self._back_block_until=time.monotonic()+.3
            else:self._play(row)
        elif cid==506:
            if xbmc.getCondVisibility('Pvr.IsPlayingTV'):xbmc.Player().stop()
            self.finish()
        elif cid==501:
            pick=self.getControl(501).getSelectedPosition()
            if not 0<=pick<len(self.groups):return
            key=self.groups[pick]['channelgroupid']
            self._request_group(key)
        elif cid==502:
            self._cache.clear();self._epg_channel=None
            self._request_group(self.group,refresh=True)
        elif cid==503:
            if configure():
                with _CHANNEL_LOCK:_CHANNEL_CACHE.clear()
                self._request_group(self.group,refresh=True)
        elif cid==504 and self._epg:
            pos=self.getControl(504).getSelectedPosition()
            if 0<=pos<len(self._epg):
                row=self._epg[pos]
                xbmcgui.Dialog().textviewer(plain_label(row.get('title') or 'Programme'),programme_time(row)+'\n\n'+plain_label(row.get('plot') or 'No description available.'))
    def _fullscreen(self):
        """The SAME IPTV page survives native fullscreen, Stop and stream EOF."""
        self.fullscreen=True
        monitor=xbmc.Monitor()
        try:
            xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')
            seen=False;start=time.monotonic()
            while not monitor.waitForAbort(.05):
                full=xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)')
                if full:seen=True
                if seen and not full:break
                if not xbmc.Player().isPlayingVideo():break
                if not seen and time.monotonic()-start>5:break
        finally:
            self.fullscreen=False
            # Stop/EOF must return to the guide without auto-restarting a channel.
            if not xbmc.Player().isPlayingVideo():
                self.playing=None
                self.setProperty('nuvio.playing','')

    def onAction(self,action):
        aid=action.getId()
        if aid not in (9,10,92,216,247,257,275,61448,61467,13):return
        if time.monotonic()<self._back_block_until:return
        if xbmc.getCondVisibility('Pvr.IsPlayingTV'):
            xbmc.Player().stop()
            self.playing=None
            self.setProperty('nuvio.playing','')
            self.setProperty('nuvio.iptv.status','Preview stopped. Select a channel to play.')
            self.setFocusId(500)
        else:
            # HUB is deliberate, not a side effect of Escape or Stop.
            self.setFocusId(506 if aid!=13 else 500)

    def finish(self):
        if self.closed:return
        self.closed=True;self._generation+=1
        for future in self._jobs.values():future.cancel()
        self._pool.shutdown(wait=False);self.close()

def open_iptv():
    try:
        try:category_rows=groups()
        except RuntimeError:category_rows=[{'channelgroupid':'alltv','label':'All channels'}]
        saved=ADDON.getSetting('nuvio_iptv_last_group')
        group=next((g['channelgroupid'] for g in category_rows if str(g['channelgroupid'])==saved),'alltv')
        try:rows=channels(group)
        except RuntimeError:rows=[]
        if not rows and group!='alltv':
            group='alltv';rows=channels()
        if not rows:
            if not configure():return
            def wait_channels():
                for _ in range(60):
                    try:loaded=channels(refresh=True)
                    except RuntimeError:loaded=[]
                    if loaded:return loaded
                    if xbmc.Monitor().waitForAbort(.5):break
                return []
            rows=job(wait_channels,label='Loading channels and EPG') or []
        if not rows:
            xbmcgui.Dialog().ok('IPTV','No channels are available yet. Check the playlist in IPTV Simple settings, or restart Kodi after installing the PVR client.');return
        if group=='alltv':category_rows=groups()
        win=IPTV('nuvio_iptv.xml',xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),'Default','1080i',rows=rows,groups=category_rows,group=group)
        monitor=xbmc.Monitor()
        try:
            win.show_ready()
            while not win.closed and not monitor.abortRequested():
                win.tick();monitor.waitForAbort(.1)
        finally:win.finish()

    except Exception as exc:
        xbmcgui.Dialog().ok('IPTV',str(exc) if isinstance(exc,ValueError) else 'IPTV could not open. Check IPTV Simple and your playlist in Kodi PVR settings.')

