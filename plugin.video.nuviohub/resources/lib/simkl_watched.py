"""Account-scoped watched snapshot: no network request while painting a poster."""
import hashlib
import os
import time
import copy
from . import simkl
_MEM={}

def _invalidate_view():
    # An open Home must remove progress that was marked watched on Simkl too.
    try:
        import xbmcgui
        xbmcgui.Window(10000).setProperty('nuvio.progress.revision',str(time.time_ns()))
    except Exception:pass

def _account():
    token=simkl.token_data().get('access_token') or ''
    return hashlib.sha256(token.encode()).hexdigest() if token else ''

def _path():return os.path.join(os.path.dirname(simkl.TOKEN_PATH),'simkl_watched.json')

def _remote_snapshot():
    account=_account()
    if not account:return {'items':{}}
    path=_path()
    try:stamp=os.stat(path).st_mtime_ns
    except OSError:stamp=0
    memo=(account,path,stamp)
    if _MEM.get('key')==memo:return _MEM['data']
    data=simkl._read_json(path,{})
    _MEM.update(key=memo,data=data if data.get('account')==account else {'account':account,'items':{}})
    return _MEM['data']

def snapshot():
    local=copy.deepcopy(_remote_snapshot())
    try:
        from . import playback_store
        for identity,entry in playback_store.watched_snapshot().items():
            target=local.setdefault('items',{}).setdefault(identity,{'watched':False,'seasons':[],'episodes':[]})
            target['watched']=bool(target.get('watched') or entry.get('watched'))
            target['episodes']=sorted(set(target.get('episodes',[]))|set(entry.get('episodes',[])))
    except Exception:pass
    return local


def aliases(ids):
    out=[]
    for key in ('imdb','tmdb','tvdb','simkl'):
        value=str(ids.get(key) or '').strip()
        if value:out.append(('tt'+value if not value.startswith('tt') else value) if key=='imdb' else key+':'+value)
    return out

def key(media,mid):return ('movie' if media=='movie' else 'series')+'|'+str(mid)

def state(data,media,mid):return data.get('items',{}).get(key(media,mid),{})

def parse(data,kind):
    import re
    from .trakt import _parse_trakt_ts
    result={};media='movie' if kind=='movies' else 'series'
    for row in data.get(kind) or []:
        node=row.get('movie') or row.get('show') or {};episodes=[];times={}
        for season in row.get('seasons') or []:
            for episode in season.get('episodes') or []:
                episode_key='%s:%s'%(season.get('number'),episode.get('number'))
                episodes.append(episode_key)
                stamp=_parse_trakt_ts(episode.get('watched_at'))
                if stamp:times[episode_key]=stamp
        total=int(row.get('total_episodes_count') or 0)
        watched=row.get('status')=='completed' or (total>0 and int(row.get('watched_episodes_count') or 0)>=total)
        entry={'watched':watched,'episodes':episodes,'seasons':[]}
        stamp=_parse_trakt_ts(row.get('last_watched_at'))
        if stamp:
            if media=='movie':entry['watched_at']=stamp
            else:
                last=re.fullmatch(r'S(\d+)E(\d+)',str(row.get('last_watched') or ''),re.I)
                if last:times['%s:%s'%(int(last[1]),int(last[2]))]=stamp
        if times:entry['episode_watched_at']=times
        for mid in aliases(node.get('ids') or {}):result[key(media,mid)]=entry
    return result

def refresh(force=False):
    old=snapshot();account=old.get('account')
    if not account:return old
    start=time.time()
    if not force and start-float(old.get('updated') or 0)<900:return old
    items={}
    for kind in ('movies','shows','anime'):
        data=simkl._request('/sync/all-items/%s/?extended=full'%kind,auth=True,timeout=8)
        if not isinstance(data,dict) or kind not in data:raise ValueError('Simkl did not return a complete watched list.')
        items.update(parse(data,kind))
    # A manual mark or account change during the fetch takes precedence.
    latest=snapshot()
    if _account()!=account or float(latest.get('updated') or 0)>start:return latest
    result={'account':account,'updated':time.time(),'items':items}
    simkl._write_json(_path(),result)
    _invalidate_view()
    return result

def mark(ctx,scope='title',season=None,episode=None):
    if not simkl.authorized():raise ValueError('Connect Simkl in Nuvio Settings first.')
    ids=simkl._ids_from_ctx(ctx)
    if not ids:raise ValueError('This title has no IMDb, TMDb or TVDb ID for Simkl.')
    account=_account();media='movie' if ctx.get('media_type')=='movie' else 'series'
    item={'ids':ids,'title':ctx.get('title') or ''}
    if media=='series' and scope in ('season','episode'):
        if season is None or int(season)<0:raise ValueError('Select a season first.')
        part={'number':int(season)}
        if scope=='episode':
            if episode is None or int(episode)<0:raise ValueError('Select an episode first.')
            part['episodes']=[{'number':int(episode)}]
        item['seasons']=[part]
    kind='movies' if media=='movie' else 'shows'
    response=simkl._request('/sync/history',payload={kind:[item]},method='POST',auth=True,timeout=8)
    if not isinstance(response,dict) or response.get('error') or any((response.get('not_found') or {}).values()):
        raise ValueError('Simkl could not confirm this watched change.')
    added=response.get('added') or {}
    if not (added.get('statuses') or any(isinstance(added.get(k),(int,float)) and added[k]>0 for k in ('movies','shows','episodes'))):
        raise ValueError('Simkl did not confirm the change. Refresh your watched status and retry.')
    if _account()!=account:raise ValueError('The Simkl account changed. Reopen the title to refresh its status.')
    record(ctx,scope,season,episode)
    from . import continue_local
    continue_local.complete_matching(aliases(ids)+[ctx.get('canonical_id')],media,scope,season,episode)
    simkl.invalidate_cache('/sync/all-items')
    return True

def record(ctx,scope='title',season=None,episode=None):
    """Record only after a successful Simkl history write."""
    ids=simkl._ids_from_ctx(ctx);media='movie' if ctx.get('media_type')=='movie' else 'series'
    local=copy.deepcopy(snapshot());items=local.setdefault('items',{})
    mids=aliases(ids)
    if ctx.get('canonical_id'):mids.append(ctx['canonical_id'])
    for mid in set(mids):
        entry=dict(items.get(key(media,mid)) or {'watched':False,'seasons':[],'episodes':[]})
        if media=='movie' or scope=='title':entry['watched']=True
        elif scope=='season':entry['seasons']=sorted(set(entry.get('seasons',[]))|{str(season)})
        else:entry['episodes']=sorted(set(entry.get('episodes',[]))|{'%s:%s'%(season,episode)})
        items[key(media,mid)]=entry
    local['updated']=time.time()
    if not simkl._write_json(_path(),local):raise ValueError('Saved on Simkl, but the local watched cache could not be written. Check Kodi profile storage.')
    _invalidate_view()

def is_episode_watched(entry,season,episode):
    return bool(entry.get('watched') or str(season) in entry.get('seasons',[]) or '%s:%s'%(season,episode) in entry.get('episodes',[]))
