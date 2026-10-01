"""Local airing calendar for series the user has actually started."""
from datetime import date,datetime,timedelta,timezone
import json
import os
import threading
import time
from .nuviohub.common import profile_path
from . import playback_store,simkl_watched

_LOCK=threading.RLock()
_MEM={}

def _path():return os.path.join(profile_path(),'nuvio_airing.json')
def _read():
    try:
        path=_path();stamp=os.stat(path).st_mtime_ns
        with _LOCK:
            if _MEM.get('key')==(path,stamp):return dict(_MEM['data'])
            with open(path,encoding='utf-8') as stream:data=json.load(stream)
            if not isinstance(data,dict):return {}
            _MEM.update(key=(path,stamp),data=data)
            return dict(data)
    except (OSError,ValueError):return {}

def remember(meta,provider_id=''):
    if meta.get('type') not in ('series','tv','show','anime') or not meta.get('id'):return
    meta={k:v for k,v in meta.items() if k in ('id','type','name','title','poster','background','logo','description','videos')}
    meta['videos']=[{k:v for k,v in e.items() if k in ('id','season','episode','released','releaseDate','air_date','firstAired','overview')} for e in meta.get('videos',[]) if isinstance(e,dict)]
    with _LOCK:
        data=_read();data[str(meta['id'])]={'provider':provider_id,'saved':time.time(),'meta':meta}
        data=dict(sorted(data.items(),key=lambda pair:pair[1].get('saved',0),reverse=True)[:100])
        path=_path();os.makedirs(os.path.dirname(path),exist_ok=True)
        from .nuviohub.safe_io import write_json
        write_json(path,data)

def release_day(episode):
    value=episode.get('released') or episode.get('releaseDate') or episode.get('air_date') or episode.get('firstAired')
    if not value:return None
    try:
        if len(str(value))==10:return date.fromisoformat(value)
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone().date()
    except (ValueError,TypeError):return None

def number(value):
    try:return int(value)
    except (ValueError,TypeError):return 0

def next_card(meta,history,entry,today=None):
    today=today or date.today();base=(number(history.get('season')),number(history.get('episode')))
    try:last_watched=datetime.fromtimestamp(float(history['updated_at'])).date()
    except (KeyError,ValueError,TypeError,OverflowError,OSError):last_watched=today
    def watched_scope(episode):
        if '%s:%s'%(episode.get('season'),episode.get('episode')) in entry.get('episodes',[]):return True
        scope=entry.get('watched') or str(episode.get('season')) in entry.get('seasons',[])
        released=release_day(episode)
        # "All aired episodes watched" must not swallow a later season release.
        return bool(scope and (not released or released<=last_watched))
    episodes=sorted((e for e in meta.get('videos',[]) if isinstance(e,dict) and e.get('id') and number(e.get('season'))>0),
                    key=lambda e:(number(e.get('season')),number(e.get('episode'))))
    eligible=[e for e in episodes if (number(e.get('season')),number(e.get('episode')))>base and not watched_scope(e)]
    tomorrow=next((e for e in eligible if release_day(e)==today+timedelta(days=1)),None)
    selected=tomorrow
    if not selected and (float(history.get('percent') or 0)>=95 or history.get('event_type')=='watched'):
        selected=next((e for e in eligible if release_day(e) and release_day(e)<=today),None)
    if not selected:return None
    target={'media_type':'series','canonical_id':history['canonical_id'],'video_id':selected['id'],
            'season':selected['season'],'episode':selected['episode'],'resume_seconds':0}
    if tomorrow:target['details_view']=True
    return {'title':meta.get('name') or history.get('title') or '',
            'poster':meta.get('poster') or history.get('poster') or '',
            'fanart':meta.get('background') or history.get('background') or '',
            'clearlogo':meta.get('logo') or '', 'plot':selected.get('overview') or meta.get('description') or '',
            'subtitle':'S%s • E%s'%(selected['season'],selected['episode']),
            'meta_line':'Series','target':target,'percent_value':0,
            'airing_banner':'Tomorrow • New episode' if tomorrow else 'Next episode',
            'tomorrow':'1' if tomorrow else '', 'shape':'poster'}

def augment(rows,refresh=False,stopped=lambda:False):
    from . import backend_api
    source=backend_api.provider('metadata') or {};cache=_read();seen=set();history=[]
    for row in playback_store.list_recent_items(limit=500,media_types=('series','tv','show','anime')):
        mid=row['canonical_id']
        if mid not in seen and row.get('episode'):
            seen.add(mid);history.append(row)
        if len(history)>=50:break
    states=simkl_watched.snapshot();cards=[];requests=0
    for row in history:
        if stopped():return rows
        mid=row['canonical_id'];saved=cache.get(mid) or {};meta=saved.get('meta') or {}
        if saved.get('provider')!=source.get('id',''):meta={}
        if refresh and source and requests<4 and (not meta or time.time()-saved.get('saved',0)>3600):
            requests+=1
            try:
                meta=backend_api.metadata('series',mid,timeout=3)
            except Exception:pass
        if meta:
            card=next_card(meta,row,simkl_watched.state(states,'series',mid))
            if card:cards.append(card)
    output=[dict(row) for row in rows if row.get('target')]
    upcoming=[];next_episodes=[]
    for card in cards:
        mid=card['target']['canonical_id']
        existing=next((r for r in output if r.get('target',{}).get('canonical_id')==mid),None)
        if existing:
            if card.get('tomorrow'):
                existing.update(airing_banner=card['airing_banner'],tomorrow='1')
        elif card.get('tomorrow'):upcoming.append(card)
        else:next_episodes.append(card)
    # Resume cards retain last-played order. Airing banners must not displace
    # the film/episode just stopped; untouched upcoming titles follow resumes.
    output.extend(upcoming+next_episodes)
    return output or rows
