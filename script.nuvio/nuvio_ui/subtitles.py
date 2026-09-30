import xbmc
import xbmcgui
from resources.lib import cache_store,nuvio_subtitles
from .system_setup import rpc
from .playback import job,plain_label

def pick(rows,playerid,context,request_id):
    groups=nuvio_subtitles.group_rows(rows)
    langs=sorted(groups,key=lambda x:(x!='hr',nuvio_subtitles.NAMES.get(x,x)))
    if not langs:xbmcgui.Dialog().ok('Subtitles','No subtitle files were returned. Try searching your Nuvio subtitle add-ons.');return
    dialog=xbmcgui.Dialog()
    index=dialog.select('Subtitle language',[nuvio_subtitles.NAMES.get(l,l)+' · '+str(len(groups[l]))+' versions' for l in langs])
    if index<0:return
    candidates=groups[langs[index]];labels=[]
    for i,row in enumerate(candidates):
        release=plain_label(row.get('displayName') or row.get('name') or row.get('release') or row.get('filename')) or 'Version '+str(i+1)
        source=plain_label(row.get('sourceName') or ('Embedded track' if row.get('embedded') else 'Subtitle provider'))
        labels.append('%d. %s — %s'%(i+1,release,source))
    index=dialog.select(nuvio_subtitles.NAMES.get(langs[index],langs[index]),labels)
    if index<0:return
    row=candidates[index]
    player=xbmc.Player()
    if not player.isPlayingVideo() or player.getPlayingItem().getProperty('nuvio.request')!=request_id:return
    if row.get('embedded'):
        rpc('Player.SetSubtitle',{'playerid':playerid,'subtitle':row['index'],'enable':True});return
    path=job(lambda:nuvio_subtitles.prepare_selected(row,context.get('video_id') or context.get('canonical_id') or 'selected'),label='Loading selected subtitle')
    if not path:return
    # Downloads can finish after a channel/title switch. Never apply to another video.
    if not player.isPlayingVideo() or player.getPlayingItem().getProperty('nuvio.request')!=request_id:return
    player.setSubtitles(path);player.showSubtitles(True)

def run():
    try:
        active=next((p for p in rpc('Player.GetActivePlayers') or [] if p['type']=='video'),None)
        if not active:return
        playerid=active['playerid'];player=xbmc.Player();request_id=player.getPlayingItem().getProperty('nuvio.request')
        xbmcgui.Window(10000).setProperty('nuvio.subtitle.manual',request_id)
        key=xbmcgui.Window(10000).getProperty('nuvio.subtitle.context')
        context=cache_store.get('nuvio_play',key) or {}
        if context.get('nuvio_request_id')!=request_id:context={}
        props=rpc('Player.GetProperties',{'playerid':playerid,'properties':['subtitles','subtitleenabled']}) or {}
        embedded=[dict(s,embedded=True,sourceName='Embedded track',lang=s.get('language')) for s in props.get('subtitles') or []]
        rows=embedded+nuvio_subtitles.external_rows(context)
        choice=xbmcgui.Dialog().select('Nuvio subtitles',['Choose language and version','Search all Nuvio subtitle add-ons','Disable subtitles' if props.get('subtitleenabled') else 'Enable subtitles','Kodi subtitle settings / timing'])
        if choice==0:pick(rows,playerid,context,request_id)
        elif choice==1:
            if not context:xbmcgui.Dialog().ok('Subtitles','Start this movie or episode through Nuvio Hub to search your providers.');return
            rows=job(lambda:nuvio_subtitles.external_rows(context,search=True),label='Searching subtitle add-ons')
            if rows is not None:pick(embedded+rows,playerid,context,request_id)
        elif choice==2:player.showSubtitles(not props.get('subtitleenabled'))
        elif choice==3:xbmc.executebuiltin('ActivateWindow(osdsubtitlesettings)')
    except Exception as exc:
        xbmcgui.Dialog().ok('Subtitles',str(exc) if isinstance(exc,ValueError) else 'Subtitle selection could not finish. Try another file or provider.')
