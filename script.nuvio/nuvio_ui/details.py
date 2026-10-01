from resources.lib import art_cache
from .dialog import Dialog
from . import browse_meta
"""Title details and a plain AIOStreams selection screen."""
import xbmc
import queue
import threading
import time
import xbmcaddon
import xbmcgui
from resources.lib import backend_api, simkl
from resources.lib import simkl_watched, title_details


class Details(Dialog):
    def __init__(self,*args,**kwargs):
        super().__init__(*args)
        self.meta=kwargs['meta']
        self.action=''
        self.closed=False
        self._metadata_pending=kwargs.get('metadata_pending',False);self._metadata_job=None;self._metadata_error=False;self._after_metadata=None
        self._extra_jobs=[];self._extras_started=False
        self.context=kwargs.get('context') or {}
        self.seasons=[];self.episodes=[];self.related=[];self._related_loaded=False;self._season=None;self._recommendations=queue.Queue();self._descriptions=queue.Queue();self._description_jobs=set()
        self.landscape=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_card_shape')=='landscape'

    def onInit(self):
        m=self.meta
        from .session import scene
        scene(art_cache.url(m.get('background') or m.get('poster') or ''), m.get('name') or m.get('title') or '')
        self._season=None
        self.setProperty('nuvio.title',m.get('name') or m.get('title') or m['id'])
        self.setProperty('nuvio.plot',m.get('description') or m.get('overview') or '')
        self.setProperty('nuvio.fanart',art_cache.url(m.get('background') or ''))
        self.setProperty('nuvio.poster',art_cache.url(m.get('poster') or ''))
        self.setProperty('nuvio.year',str(m.get('releaseInfo') or m.get('year') or ''))
        series=m.get('type')=='series'
        self.setProperty('nuvio.series','1' if series else '')
        self.getControl(100).setLabel('Play episode' if series else 'Play')
        for cid in (101,103,104,106):self.getControl(cid).setEnabled(not self._metadata_pending and not self._metadata_error)
        self.setProperty('nuvio.meta_line','  |  '.join(str(v) for v in (
            m.get('releaseInfo') or m.get('year'), m.get('runtime'),
            ' / '.join(str(g.get('name') or '') if isinstance(g,dict) else str(g) for g in m.get('genres') or []) if isinstance(m.get('genres'),list) else m.get('genres'),
            ('IMDb '+str(m['imdbRating'])) if m.get('imdbRating') else '') if v))
        self._people()
        if series:
            self.seasons=title_details.seasons(m)
            self.getControl(501).reset()
            self.getControl(501).addItems([xbmcgui.ListItem(label=title_details.season_label(n)) for n in self.seasons])
            if self.seasons:
                requested=title_details.number(self.context.get('season'),1)
                first=self.seasons.index(requested) if requested in self.seasons else 0
                self.getControl(501).selectItem(first);self._episodes(first);self.setFocusId(501)
            else:self.setProperty('nuvio.empty','Loading episodes…' if self._metadata_pending else 'No episodes supplied for this series.')
        else:
            self.setProperty('nuvio.empty','')
        if self._metadata_pending:
            self.setProperty('nuvio.related_status','Loading details…')
            if self._metadata_job is None:self._metadata_job=browse_meta.request(self.context)
        else:self._start_extras()
        self._favorite_label()
        self._watch_badges()
        self.restore_focus()

    def _start_extras(self):
        if self._related_loaded:self._recommendations.put(self.related);return
        if self._extras_started:return
        self._extras_started=True
        self.setProperty('nuvio.related_status','Loading recommendations…')
        def load_related():
            if self.closed:return
            try:rows=title_details.related(self.meta,limit=100)
            except Exception:rows=[]
            if not self.closed:self._recommendations.put(rows)
        from .playback import _BACKGROUND
        self._extra_jobs.append(_BACKGROUND.submit(load_related))

    def _people(self):
        items=[]
        for person in self.meta.get('nuvio_people',title_details.people(self.meta)):
            li=xbmcgui.ListItem(label=person['name'],label2=person['role'])
            li.setArt(art_cache.art({'thumb':person.get('photo') or 'special://home/addons/script.nuvio/resources/media/person.png'}))
            items.append(li)
        self.getControl(503).reset();self.getControl(503).addItems(items)
        self.setProperty('nuvio.has_people','1' if items else '')

    def _episodes(self,index):
        if not self.seasons:return
        index=max(0,min(index,len(self.seasons)-1))
        season=self.seasons[index]
        if season==self._season:return
        self._season=season
        self.episodes=title_details.episodes(self.meta,season)
        items=[]
        for e in self.episodes:
            from resources.lib.display_text import clean, episode_line
            li=xbmcgui.ListItem(label=clean(e.get('title') or e.get('name') or 'Episode %s'%e['episode']))
            li.setProperty('episode_meta', episode_line(e, season))
            art=(e.get('thumbnail') or e.get('background') or self.meta.get('background') or e.get('poster') or self.meta.get('poster')) if self.landscape else (e.get('poster') or self.meta.get('poster') or e.get('thumbnail'))
            li.setArt(art_cache.art({'thumb':art or ''}))
            li.setProperty('plot',title_details.episode_plot(e,self.meta))
            li.setProperty('episode_title',(self.meta.get('name') or self.meta.get('title') or '')+' - S%s E%s - %s'%(season,e['episode'],e.get('title') or e.get('name') or 'Episode'))
            items.append(li)
        self.getControl(502).reset();self.getControl(502).addItems(items)
        selected=next((i for i,e in enumerate(self.episodes) if e['id']==self.context.get('video_id')),0)
        if items:self.getControl(502).selectItem(selected)
        self.setProperty('nuvio.season',title_details.season_label(season))
        self._watch_badges()
        missing=any(not title_details.episode_description(e) for e in self.episodes)
        if missing and season not in self._description_jobs:
            self._description_jobs.add(season)
            def load():
                try:data=title_details.season_descriptions(self.meta,season)
                except Exception:data={}
                if not self.closed:self._descriptions.put((season,data))
            from .playback import _BACKGROUND
            self._extra_jobs.append(_BACKGROUND.submit(load))

    def onFocus(self,cid):
        if cid==502 and self.seasons:
            self._episodes(self.getControl(501).getSelectedPosition())

    def tick(self):
        if self.closed:return
        # Kodi moves horizontal list selection without another onFocus callback.
        if self.seasons and self.getFocusId()==501:
            self._episodes(self.getControl(501).getSelectedPosition())
        if self._metadata_job is not None and self._metadata_job.done():
            future,self._metadata_job=self._metadata_job,None
            try:
                meta=future.result()
                if not meta:raise ValueError('No details returned')
            except Exception:
                self._metadata_pending=False;self._metadata_error=True;self._after_metadata=None
                self.setProperty('nuvio.related_status','Details unavailable. Select Play to retry, or press Back.')
                self.getControl(100).setLabel('Retry details')
            else:
                self._metadata_pending=False;self._metadata_error=False
                try:self._restore_focus=self.getFocusId()
                except Exception:pass
                combined=dict(self.meta,**meta)
                for key in ('name','poster','background','description'):
                    if not combined.get(key):combined[key]=self.meta.get(key) or ''
                self.meta=combined;self.onInit()
                # First season becomes navigable as soon as its episodes arrive.
                if self.meta.get('type')=='series' and self.seasons and self.getFocusId()==100:self.setFocusId(501)
                if self._after_metadata is not None:
                    manual=self._after_metadata;self._after_metadata=None
                    self.defer(lambda:self._play(manual))
        while not self._descriptions.empty():
            season,data=self._descriptions.get_nowait()
            if data.get('season'):
                self.meta.setdefault('nuvio_season_overviews',{})[str(season)]=data['season']
            for e in title_details.episodes(self.meta,season):
                summary=data.get(title_details.number(e.get('episode')))
                if not title_details.episode_description(e) and summary:
                    e['description']=summary
            if season==self._season:
                for i,e in enumerate(self.episodes):self.getControl(502).getListItem(i).setProperty('plot',title_details.episode_plot(e,self.meta))
        try:rows=self._recommendations.get_nowait()
        except queue.Empty:return
        self.related=rows;self._related_loaded=True
        self.setProperty('nuvio.related_status','' if rows else 'No recommendations available for this title.')
        items=[];watched=simkl_watched.snapshot()
        for row in rows[:16]:
            li=xbmcgui.ListItem(label=row['title'])
            li.setArt(art_cache.art({'thumb':(row.get('fanart') or row.get('poster')) if self.landscape else row.get('poster') or ''}))
            li.setProperty('plot',row.get('plot') or '')
            target=row['target'];li.setProperty('watched','1' if simkl_watched.state(watched,target['media_type'],target['canonical_id']).get('watched') else '')
            items.append(li)
        self.getControl(504).reset();self.getControl(504).addItems(items)

    def child(self,fn,*args,**kwargs):
        if self.seasons:
            self.context['season']=self._season
            if self.episodes:
                pos=max(0,min(self.getControl(502).getSelectedPosition(),len(self.episodes)-1))
                self.context['video_id']=self.episodes[pos]['id']
        return super().child(fn,*args,**kwargs)

    def _more_like(self):
        from .catalog import open_catalog
        if not self._related_loaded:return
        self.child(open_catalog,{'label':'More like this · '+str(self.meta.get('name') or self.meta.get('title') or ''),'rows':self.related})

    def _person(self):
        from .playback import job
        from .catalog import open_catalog
        persons=self.meta.get('nuvio_people',title_details.people(self.meta))
        pos=self.getControl(503).getSelectedPosition()
        if not 0<=pos<len(persons):return
        person=persons[pos]
        self.child(open_person,person)

    def _info(self,episode=False):
        if self._metadata_pending or self._metadata_error:return
        entry=None
        if episode and self.episodes:
            entry=self.episodes[max(0,self.getControl(502).getSelectedPosition())]
        show_info(self.meta,entry)

    def _watch_badges(self):
        m=self.meta;mid=m.get('id') or self.context.get('canonical_id')
        entry=simkl_watched.state(simkl_watched.snapshot(),m.get('type') or 'movie',mid)
        self.setProperty('nuvio.watched','1' if entry.get('watched') else '')
        for i,season in enumerate(self.seasons):
            eps=title_details.episodes(m,season)
            watched=entry.get('watched') or str(season) in entry.get('seasons',[]) or (bool(eps) and all(simkl_watched.is_episode_watched(entry,season,e['episode']) for e in eps))
            self.getControl(501).getListItem(i).setProperty('watched','1' if watched else '')
        for i,e in enumerate(self.episodes):
            self.getControl(502).getListItem(i).setProperty('watched','1' if simkl_watched.is_episode_watched(entry,e.get('season',1),e['episode']) else '')

    def _mark_watched(self):
        from .playback import job
        from .simkl_account import link
        if not simkl.authorized() and not link():return
        m=self.meta;scope='title';season=episode=None
        if m.get('type')=='series':
            if self.seasons:self._episodes(self.getControl(501).getSelectedPosition())
            choices=['Entire series (all aired episodes)']
            if self.seasons:
                season=self.seasons[max(0,self.getControl(501).getSelectedPosition())]
                choices.append(title_details.season_label(season))
            if self.episodes:
                e=self.episodes[max(0,self.getControl(502).getSelectedPosition())]
                choices.append('Episode S%s E%s - %s'%(e.get('season',1),e['episode'],e.get('title') or e.get('name') or 'Episode'))
            pick=xbmcgui.Dialog().select('Mark watched on Simkl',choices)
            if pick<0:return
            scope=('title','season','episode')[pick]
            if scope=='episode':season=e.get('season',1);episode=e['episode']
        from resources.lib.plugin import extract_ids
        ctx=dict(extract_ids(m),media_type=m.get('type') or 'movie',canonical_id=m.get('id') or '',title=m.get('name') or m.get('title') or '')
        try:
            if job(lambda:simkl_watched.mark(ctx,scope,season,episode),label='Saving watched status to Simkl'):
                self._watch_badges()
        except Exception as exc:
            xbmcgui.Dialog().ok('Simkl',str(exc) if isinstance(exc,ValueError) else 'Could not save watched status. Please retry.')

    def _play(self,manual=False):
        if self._metadata_pending or self._metadata_error:
            self._after_metadata=manual;self.getControl(100).setLabel('Preparing video…')
            if self._metadata_error:
                self._metadata_error=False;self._metadata_pending=True;self._metadata_job=browse_meta.request(self.context)
            return
        context=dict(self.context)
        if manual:context['force_manual']=True
        if self.meta.get('type')=='series':
            if self.seasons:self._episodes(self.getControl(501).getSelectedPosition())
            if not self.episodes:
                xbmcgui.Dialog().ok('Episodes','The selected metadata provider has no episodes for this series.');return
            pos=max(0,self.getControl(502).getSelectedPosition())
            e=self.episodes[min(pos,len(self.episodes)-1)]
            if context.get('video_id')!=e['id']:
                context.pop('resume_seconds',None);context.pop('resume_percent',None)
            context.update(video_id=e['id'],season=e.get('season',1),episode=e['episode'])
        if context.pop('nuvio_refresh_local_resume',False):
            # Stop may be delivered after this window began opening. Read the
            # committed final position again at the actual playback click.
            from resources.lib import continue_local
            saved=next((r for r in continue_local.recent() if r.get('canonical_id')==self.meta['id'] and r.get('video_id')==(context.get('video_id') or self.meta['id'])),None)
            context.pop('resume_seconds',None);context.pop('resume_percent',None)
            if saved and saved.get('event_type')!='watched':
                context.update(resume_seconds=saved.get('position') or 0,resume_percent=saved.get('percent') or 0)
        self.context=context
        if choose_stream(self.meta,context):self.action='playing';self.close()

    def _favorite_label(self):
        self.getControl(101).setLabel('Add to Library')

    def _add_to_library(self):
        from .playback import job
        from .simkl_account import link
        if not simkl.authorized() and not link():return
        from resources.lib.plugin import extract_ids
        ids=extract_ids(self.meta)
        ctx=dict(ids,media_type=self.meta.get('type') or 'movie',title=self.meta.get('name') or self.meta.get('title') or '')
        try:
            if job(lambda:simkl.add_to_library(ctx),label='Saving to Simkl Library'):
                self.getControl(101).setLabel('Saved to Library')
                xbmcgui.Dialog().ok('Library','Saved to Simkl Plan to Watch.')
        except Exception as exc:
            xbmcgui.Dialog().ok('Library',str(exc) if isinstance(exc,ValueError) else 'Simkl could not confirm the save. Check your connection and retry.')

    def onClick(self,control_id):
        if control_id==100:
            self._play()
        elif control_id==501:
            self._episodes(self.getControl(501).getSelectedPosition());self.setFocusId(502)
        elif control_id==502:self._play()
        elif control_id==103:
            from .trailers import show_trailer
            if not show_trailer(self.meta):self.setProperty('nuvio.trailer_status','Trailer unavailable. Try another title, or change the trailer source in Settings > Trailers.')
        elif control_id==101:
            self._add_to_library()
        elif control_id==104:self._mark_watched()
        elif control_id==105:self._more_like()
        elif control_id==106:self._info()
        elif control_id==503:
            self._person()
        elif control_id==504 and self.related:
            row=self.related[self.getControl(504).getSelectedPosition()]
            outcome=self.child(open_context,row['target'],row=row)
            if outcome=='playing' or isinstance(outcome,dict):self.action=outcome;self.close()
        elif control_id==102:self.close()

    def close(self):
        if self._metadata_job:self._metadata_job.cancel()
        for future in self._extra_jobs:future.cancel()
        self.closed=True
        super().close()

    def onAction(self,action):
        aid=action.getId()
        if aid in (9,10,92,216):
            self.close()
        elif aid in (117,101,1009,11):
            focus=self.getFocusId()
            if focus==504 and self.related:
                outcome=self.child(context_menu,self.related[self.getControl(504).getSelectedPosition()]['target'],info=aid==11)
                if outcome=='playing' or isinstance(outcome,dict):self.action=outcome;self.close()
                return
            choice='info' if aid==11 else context_choice()
            if choice=='manual':
                if focus==501:self._episodes(self.getControl(501).getSelectedPosition())
                self._play(manual=True)
            elif choice=='related':self._more_like()
            elif choice=='info':self._info(episode=focus==502)


class Info(Dialog):
    def __init__(self,*args,**kwargs):
        super().__init__(*args);self.meta=kwargs['meta'];self.episode=kwargs.get('episode')
    def onInit(self):
        m=self.meta;e=self.episode
        title=m.get('name') or m.get('title') or ''
        if e:title+=' - S%s E%s - %s'%(e.get('season',1),e.get('episode'),e.get('title') or e.get('name') or 'Episode')
        self.setProperty('nuvio.title',title)
        self.setProperty('nuvio.poster',art_cache.url(m.get('poster') or ''))
        plot=title_details.episode_plot(e,m) if e else (m.get('overview') or m.get('description') or 'No description supplied.')
        self.setProperty('nuvio.plot',plot)
        self.getControl(510).setText(plot)
        self.getControl(503).reset()
        items=[]
        for person in m.get('nuvio_people',title_details.people(m)):
            li=xbmcgui.ListItem(label=person['name'],label2=person['role'])
            li.setArt(art_cache.art({'thumb':person.get('photo') or 'special://home/addons/script.nuvio/resources/media/person.png'}));items.append(li)
        self.getControl(503).addItems(items)
        self.setProperty('nuvio.has_people','1' if items else '')
    def onClick(self,cid):
        if cid==102:self.close()
        elif cid==503:Details._person(self)
    def onAction(self,action):
        if action.getId() in (9,10,92,216):self.close()


def show_info(meta,episode=None):
    win=Info('nuvio_info.xml',xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),'Default','1080i',meta=meta,episode=episode)
    try:win.doModal()
    finally:win.close()


class ContextMenu(xbmcgui.WindowXMLDialog):
    def __init__(self,*args,**kwargs):
        super().__init__(*args);self.choice=''
    def onInit(self):
        self.setFocusId(100)
    def onClick(self,cid):
        if cid in (100,101,102):
            self.choice=('manual','related','info')[cid-100]
            self.close()
    def onAction(self,action):
        if action.getId() in (9,10,92,216):self.close()


def context_choice():
    win=ContextMenu('nuvio_context.xml',xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),'Default','1080i')
    try:win.doModal();return win.choice
    finally:win.close()


def context_menu(context,info=False,row=None):
    choice='info' if info else context_choice()
    if not choice:return ''
    ctx=dict(context,details_view=choice)
    if choice=='manual':ctx['force_manual']=True
    return open_context(ctx,row=row)


def choose_stream(meta,context):
    from .playback import play
    try:return play(meta,context)
    except Exception as exc:
        xbmcgui.Dialog().ok('Playback',str(exc) if isinstance(exc,ValueError) else 'Could not load this source. Check your provider configuration and connection.')
        return False


def open_context(context,row=None):
    mid=context.get('canonical_id') or context.get('id') or ''
    if not mid:return ''
    mt=context.get('media_type') or context.get('type') or 'movie'
    if mt in ('tv','show','tvshow','episode','anime'):mt='series'
    context=dict(context,canonical_id=mid,media_type=mt)
    meta=browse_meta.cached(context)
    metadata_pending=meta is None
    if meta is None:meta=browse_meta.seed(context,row)
    view=context.get('details_view')
    direct=(view=='manual' and (mt=='movie' or context.get('video_id'))) or (not view and (context.get('resume_seconds') or context.get('video_id')))
    if metadata_pending and (direct or view=='info'):
        from .playback import job
        try:meta=job(lambda:backend_api.metadata(mt,mid),meta,label='Loading details')
        except Exception:meta=None
        if not meta:return ''
        metadata_pending=False
    if view=='info':
        episode=next((e for e in title_details.episodes(meta) if e['id']==context.get('video_id')),None) if mt=='series' else None
        show_info(meta,episode);return ''
    playing=bool(direct and choose_stream(meta,context))
    addon=xbmcaddon.Addon('script.nuvio')
    filename='nuvio_details_landscape.xml' if xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_card_shape')=='landscape' else 'nuvio_details.xml'
    while True:
        if playing:
            from .trailers import wait_for_playback
            wait_for_playback()
            import json
            home=xbmcgui.Window(10000);raw=home.getProperty('nuvio.next_episode')
            home.clearProperty('nuvio.next_episode')
            if raw:
                try:next_context=json.loads(raw)
                except ValueError:next_context={}
                if next_context.get('canonical_id')==mid:
                    context=next_context
                    playing=choose_stream(meta,context)
                    if playing:continue
            from resources.lib import continue_local
            saved=next((r for r in continue_local.recent() if r.get('canonical_id')==mid and r.get('video_id')==context.get('video_id')),None)
            context.pop('resume_seconds',None);context.pop('resume_percent',None)
            if saved and saved.get('event_type')!='watched':
                context.update(resume_seconds=saved.get('position') or 0,resume_percent=saved.get('percent') or 0)
            context['nuvio_refresh_local_resume']=True
            playing=False
        window=Details(filename,addon.getAddonInfo('path'),'Default','1080i',meta=meta,context=context,metadata_pending=metadata_pending)
        try:
            window.doModal();action=window.action;context=dict(window.context)
            meta=window.meta;metadata_pending=window._metadata_pending
        finally:window.close()
        if action=='playing':playing=True;continue
        return action


def open_person(person):
    from .playback import job
    from .person import open_page
    try:
        page = job(lambda: title_details.person_page(person), label='Loading actor · Movies and Series')
    except Exception as exc:
        xbmcgui.Dialog().ok('Actor filmography', str(exc) if isinstance(exc, ValueError) else 'Filmography could not load. Check the metadata add-ons and retry.')
        return ''
    if page is None:
        return ''
    return open_page(page)
