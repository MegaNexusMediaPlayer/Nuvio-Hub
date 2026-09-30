"""Preserve every release within its language, loading one selected file at a time."""
from . import subtitle_broker as broker
import json
import xbmc
import xbmcaddon
import xbmcgui

NAMES={'hr':'Croatian','sr':'Serbian','bs':'Bosnian','sl':'Slovenian','en':'English','de':'German','it':'Italian','fr':'French','es':'Spanish','pt':'Portuguese','und':'Unknown language'}

def language(value):
    if isinstance(value,(list,tuple)):
        return next((language(v) for v in value if language(v)!='und'),'und')
    if isinstance(value,dict):
        value=next((value[k] for k in ('lang','language','languageCode','code','name') if value.get(k)),'und')
    raw=str(value or 'und').strip().lower()
    aliases={'cro':'hr','hrv':'hr','croatian':'hr','hrvatski':'hr','ser':'sr','srp':'sr','serbian':'sr','bos':'bs','bosnian':'bs','slv':'sl','slovenian':'sl'}
    if raw in aliases:return aliases[raw]
    # Kodi owns the language registry, including names outside our common labels.
    try:
        code=xbmc.convertLanguage(raw,xbmc.ISO_639_1)
        if code:return code.lower()
        code=xbmc.convertLanguage(raw,xbmc.ISO_639_2)
        if code:return code.lower()
    except Exception:pass
    return broker._normalize_lang(raw)

def languages():
    data=json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc':'2.0','id':1,
        'method':'Settings.GetSettings','params':{'level':'expert'}})))
    setting=next((s for s in data.get('result',{}).get('settings',[])
                  if s.get('id')=='locale.subtitlelanguage'),{})
    excluded={'none','forced_only','original','default','mediadefault',''}
    rows=[{'label':r['label'],'value':r['value']} for r in setting.get('options',[])
          if r.get('value') not in excluded]
    if not rows:raise ValueError('Kodi could not return its subtitle languages. Reopen Settings and try again.')
    return rows

def preferred():
    addon=xbmcaddon.Addon('plugin.video.nuviohub')
    return addon.getSetting('nuvio_subtitle_language') or (addon.getSetting('preferred_subtitle_langs') or 'en').split(',')[0]

def language_name(value):
    try:
        name=xbmc.convertLanguage(str(value),xbmc.ENGLISH_NAME)
        if name:return name
    except Exception:pass
    return NAMES.get(language(value),str(value))

def group_rows(rows):
    groups={}
    for row in rows:
        clean=dict(row);lang=language(row.get('lang') or row.get('language'))
        clean['lang']=lang;groups.setdefault(lang,[]).append(clean)
    return groups

def external_rows(context,search=False):
    # Searching with an empty seed avoids the old broker's early exit when the
    # stream already supplied a sidecar. Include both sets AFTER provider search.
    initial=[]
    for raw in context.get('subtitles') or []:
        row=broker._coerce_subtitle(raw)
        if row:
            row['sourceName']=row.get('sourceName') or context.get('provider_name') or 'Stream provider'
            initial.append(row)
    if search:
        found=broker.search_subtitles(context,initial_subtitles=[],max_results=1000)
        initial=broker._dedupe(initial+found)
    for row in initial:row['lang']=language(row.get('lang'))
    return initial

def prepare_selected(row,key):
    from .playback.subtitle_files import _prepare_subtitle_files
    result=_prepare_subtitle_files([row],key,prefer_local_copy=True,defer_download=False)
    if not result or str(result[0]['path']).startswith(('http://','https://')):
        raise ValueError('The selected subtitle could not be downloaded. Try another release.')
    return result[0]['path']

def auto_apply(context,player=None):
    """Search off the playback path; one matching file, never a different video."""
    from .session_store import load_session
    player=player or xbmc.Player()
    uid=context.get('playback_uid');request=context.get('nuvio_request_id')
    wanted=language(context.get('nuvio_subtitle_language') or preferred())
    home=xbmcgui.Window(10000)
    def current():
        try:
            return bool(uid and request and player.isPlayingVideo() and
                (load_session() or {}).get('playback_uid')==uid and
                home.getProperty('nuvio.playback.started')==request and
                home.getProperty('nuvio.subtitle.manual')!=request)
        except Exception:return False
    if not current():return False
    # Source-native releases already match this video. Search other installed
    # addons only if the source did not supply the selected language.
    rows=external_rows(context,search=False)
    selected=next((r for r in rows if language(r.get('lang'))==wanted),None)
    if selected is None:
        rows=external_rows(context,search=True)
        selected=next((r for r in rows if language(r.get('lang'))==wanted),None)
    if not current():return False
    # Preserve the provider's order, including numbered Croatian releases.
    if selected:
        path=prepare_selected(selected,context.get('video_id') or context.get('canonical_id') or uid)
        if not current():return False
        player.setSubtitles(path);player.showSubtitles(True)
        return True
    return False
