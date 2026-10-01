from resources.lib import art_cache
from .dialog import Dialog
"""Remote-friendly Nuvio-style shelves, with cancellable background catalog loading."""
import queue
import time
import json
import traceback
from concurrent.futures import ThreadPoolExecutor

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import home_data
from resources.lib import simkl_watched
import xbmcaddon

ADDON = xbmcaddon.Addon('script.nuvio')
BACK = {9, 10, 92, 216, 247, 257, 275, 61448, 61467}
ROW_BASE = 7000
NAV = {101: ''}


def home_xml():
    # Kodi's Python bridge cannot access XML grouplist controls. Keep their
    # viewport dimensions in XML, with a compact variant for a hidden hero.
    return 'nuvio_home_compact.xml' if xbmc.getCondVisibility('Skin.HasSetting(nuvio.hidehero)') else 'nuvio_home.xml'


def launch_command(row):
    """Only addon-owned routes are accepted from cards; provider text is never a builtin."""
    p = home_data._api()
    if row.get('target'):
        path, folder = p._content_click_path(**row['target'])
    else:
        path, folder = row.get('path') or '', bool(row.get('is_folder'))
    if not path.startswith('plugin://') or any(c in path for c in ('\n', '\r', '"')):
        return ''
    return 'ActivateWindow(Videos,"%s",return)' % path if folder else 'RunPlugin("%s")' % path


class HomeWindow(Dialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self._shelves = kwargs.get('shelves') or []
        self._bucket = ''
        self._generation = 0
        self._closed = False
        self._pending = ''
        self._updates = queue.Queue()
        self._pool = None
        self._futures = []
        self._last_touch = 0
        self._focus_memory = {}
        self._previews = None
        self._suspended = False
        self._shelf_memory={}
        self._scheduled=set()
        self._watch_loaded=False
        self._progress_revision=xbmcgui.Window(10000).getProperty('nuvio.progress.revision')
        self._last_progress_check=0
        self._bucket = kwargs.get('bucket') or ''

    def onInit(self):
        self.setProperty('nuvio.home.error','')
        reset_continue=False
        try:
            saved = json.loads(xbmcgui.Window(10000).getProperty('nuvio.home.focus') or '{}')
            if isinstance(saved, dict):
                self._focus_memory = saved
        except (ValueError, TypeError):
            pass
        try:
            window=xbmcgui.Window(10000)
            revision=window.getProperty('nuvio.progress.revision')
            if not self._bucket and self._shelves and self._shelves[0].get('continue_job'):
                # Every Home entry starts this shelf at its newest title, even
                # after a restart/import or when another view consumed revision.
                reset_continue=True
                self._shelves[0]=home_data.continue_shelf()
                self._progress_revision=revision
                if self._focus_memory.get('home',[0,0])[0]==0:self._focus_memory['home']=[0,0]
                window.setProperty('nuvio.home.progress_seen',revision)
            self._paint(self._shelves)
            if reset_continue:self.getControl(ROW_BASE).selectItem(0)
        except Exception:
            xbmc.log('[Nuvio] Home initialization failed:\n'+traceback.format_exc(),xbmc.LOGERROR)
            self.setProperty('nuvio.home.error','Home could not display its collections. Open Settings or reinstall the complete Nuvio ZIP.')
            self.setFocusId(107)
            return
        try:
            from .home_trailers import Controller
            if self._previews:self._previews.finish()
            self._previews = Controller(self)
            self._previews.start()
        except Exception:
            # Optional trailers must never prevent local collection cards rendering.
            xbmc.log('[Nuvio] Preview controller unavailable: '+traceback.format_exc(),xbmc.LOGWARNING)

        self.restore_focus()

    def preview_selection(self):
        if self._closed or self._suspended: return None
        if xbmc.getCondVisibility('Skin.HasSetting(nuvio.hidehero)'):return None
        control_id = self.getFocusId()
        index = control_id - ROW_BASE
        if not 0 <= index < len(self._shelves): return None
        pos = self.getControl(control_id).getSelectedPosition()
        rows = self._shelves[index]['rows']
        if not 0 <= pos < len(rows) or not rows[pos].get('target') or rows[pos].get('person'): return None
        return (self._generation, index, pos), dict(rows[pos])

    @staticmethod
    def _shelf_key(shelf):
        jobs=shelf.get('collection_job') or ([(*shelf['job'],shelf.get('extra') or {})] if shelf.get('job') else [])
        return json.dumps([(p.get('id'),c.get('type'),c.get('id'),extra) for p,c,extra in jobs],sort_keys=True) if jobs else ''

    def _paint(self, shelves):
        for shelf in shelves:
            saved=self._shelf_memory.get(self._shelf_key(shelf))
            if saved and saved[0]>time.monotonic():shelf.update(rows=saved[1],_loaded=True)
        self._card_shape=xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_card_shape') or 'poster'
        shelves = [dict(s, rows=s.get('rows') or [home_data.placeholder(
            'No titles yet', 'Open Settings to connect your metadata provider.')]) for s in shelves[:home_data.MAX_ROWS]]
        if not shelves:
            shelves = [{'title':'Welcome to Nuvio', 'rows':[home_data.placeholder(
                'Open Settings', 'Connect your Nuvio account and metadata provider to load titles.',
                'plugin://plugin.video.nuviohub/?action=setup_center')]}]
        self._generation += 1
        generation = self._generation
        for future in self._futures:
            future.cancel()
        self._futures = []
        self._scheduled=set()
        self._shelves = shelves
        for i in range(home_data.MAX_ROWS):
            self.setProperty('nuvio.row.%d.visible' % i, '1' if i < len(shelves) else '')
            if i < len(shelves):
                landscape = shelves[i].get('shape',self._card_shape)=='landscape'
                self.setProperty('nuvio.row.%d.shape' % i, 'landscape' if landscape else 'poster')
                self.getControl(6500 + i).setHeight(256 if landscape else 372)
                self.getControl(ROW_BASE + i).setHeight(214 if landscape else 330)
                self.getControl(ROW_BASE+i).controlUp(self.getControl(ROW_BASE+i-1 if i else 101))
                self.getControl(ROW_BASE+i).controlDown(self.getControl(ROW_BASE+i+1 if i+1<len(shelves) else ROW_BASE+i))
                self.setProperty('nuvio.row.%d.title' % i, shelves[i]['title'])
                self._set_rows(i, shelves[i]['rows'])
        try:
            saved = self._focus_memory.get(self._bucket or 'home') or [0, 0]
            saved = [int(saved[0]), int(saved[1])]
        except (ValueError, TypeError, IndexError, KeyError):saved=[0,0]
        row = max(0, min(int(saved[0]), len(shelves) - 1))
        self.setProperty('nuvio.hero_row', str(row))
        self.setProperty('nuvio.tab', self._bucket or 'home')
        self.setFocusId(ROW_BASE+row)
        self.getControl(ROW_BASE + row).selectItem(min(max(0, int(saved[1])), len(shelves[row]['rows']) - 1))
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=2)
        self._queue_visible()
        if not getattr(self,'_watch_loaded',False):
            self._watch_loaded=True
            self._pool.submit(self._refresh_watched)
        self._touch()

    def _queue_visible(self):
        if not self._pool or self._closed or self._suspended:return
        row=max(0,min(self.getFocusId()-ROW_BASE,len(self._shelves)-1))
        # Load the focused shelf and its neighbours before off-screen catalogs.
        indices=list(dict.fromkeys([row,row+1,row+2,0]))
        for i in indices:
            if i>=len(self._shelves) or i in self._scheduled:continue
            shelf=self._shelves[i]
            if shelf.get('continue_job') or ((shelf.get('job') or shelf.get('collection_job') or shelf.get('people_job')) and not shelf.get('_loaded')):
                self._scheduled.add(i)
                shelf['progress_revision']=self._progress_revision
                self._futures.append(self._pool.submit(self._load, i, dict(shelf), self._generation))

    def _refresh_watched(self):
        try:simkl_watched.refresh()
        except Exception:return  # Keep offline status; never block Home on Simkl.
        if not self._closed:self._updates.put((self._generation,-1,[]))

    def _watched_badges(self):
        data=simkl_watched.snapshot()
        for i,shelf in enumerate(self._shelves):
            control=self.getControl(ROW_BASE+i)
            for pos,row in enumerate(shelf['rows']):
                target=row.get('target') or {}
                watched=simkl_watched.state(data,target.get('media_type'),target.get('canonical_id')).get('watched')
                control.getListItem(pos).setProperty('watched','1' if watched else '')

    def _load(self, index, shelf, generation):
        if self._closed or generation != self._generation:
            return
        try:
            if shelf.get('continue_job'):
                from resources.lib.continue_metadata import enrich
                def stopped():return self._closed or generation!=self._generation or shelf.get('progress_revision')!=self._progress_revision
                def update(rows):
                    if not stopped():
                        self._updates.put((generation, index, rows, shelf.get('progress_revision')))
                rows=enrich(shelf['rows'],update,stopped)
                from resources.lib.watch_nextup import augment
                rows=augment(rows,refresh=True,stopped=stopped)
                if stopped():return
            else:rows = home_data.load_catalog(shelf,stopped=lambda:self._closed or generation!=self._generation)
        except Exception:
            rows = [home_data.placeholder('Open catalog',
                'This catalog could not load right now. Select to retry in the full browser.', shelf.get('path',''))]
        if self._closed or generation != self._generation:
            return
        self._updates.put((generation, index, rows, shelf.get('progress_revision') if shelf.get('continue_job') else None))

    def drain_updates(self):
        self.drain_events()
        if self._closed:return
        self._queue_visible()
        now=time.monotonic()
        if now-self._last_progress_check>=.5:
            self._last_progress_check=now
            revision=xbmcgui.Window(10000).getProperty('nuvio.progress.revision')
            if revision!=self._progress_revision:
                self._progress_revision=revision
                if not self._bucket and self._shelves and self._shelves[0].get('continue_job'):
                    shelf=home_data.continue_shelf();shelf['progress_revision']=revision
                    self._shelves[0]=shelf;self._set_rows(0,shelf['rows'])
                    xbmcgui.Window(10000).setProperty('nuvio.home.progress_seen',revision)
                    if self._pool:self._futures.append(self._pool.submit(self._load,0,dict(shelf),self._generation))
        if self._previews:
            try:self._previews.tick()
            except Exception:
                self._previews.close()
                xbmc.log('[Nuvio] Preview stopped after a player error.',xbmc.LOGWARNING)
        # Workers only enqueue data. The window owner applies Kodi controls.
        for _ in range(32):
            try:
                update = self._updates.get_nowait()
                generation, index, rows = update[:3]
            except queue.Empty:return
            if self._closed or generation != self._generation:continue
            if len(update)>3 and update[3] is not None and update[3]!=self._progress_revision:continue
            if index==-1:self._watched_badges();continue
            rows = rows or [home_data.placeholder('No titles found', 'Try another collection or check Settings.')]
            self._shelves[index]['rows'] = rows
            self._shelves[index]['_loaded'] = True
            key=self._shelf_key(self._shelves[index])
            if key and any(row.get('target') for row in rows):
                self._shelf_memory[key]=(time.monotonic()+300,rows)
                if len(self._shelf_memory)>32:self._shelf_memory.pop(next(iter(self._shelf_memory)))
            self._set_rows(index, rows)

    def _set_rows(self, index, rows):
        control = self.getControl(ROW_BASE + index)
        try:
            position = control.getSelectedPosition()
        except Exception:
            position = 0
        try:old_identity=control.getSelectedItem().getProperty('nuvio.identity')
        except Exception:old_identity=''
        identities=[]
        items = []
        watched_data=simkl_watched.snapshot()
        for row in rows:
            li = xbmcgui.ListItem(label=str(row.get('title') or 'Untitled'), label2=str(row.get('subtitle') or ''))
            art={key: str(row.get(key) or '') for key in ('poster', 'fanart', 'clearlogo')}
            if getattr(self,'_card_shape','poster')=='landscape' and row.get('target'):
                art['poster']=row.get('landscape') or row.get('fanart') or row.get('poster') or ''
            li.setArt(art_cache.art(art))
            for key in ('title', 'plot', 'meta_line', 'subtitle', 'resume_label', 'airing_banner','tomorrow'):
                li.setProperty(key, str(row.get(key) or '').replace(' • ','[CR]') if key=='airing_banner' else str(row.get(key) or ''))
            li.setProperty('shape', row.get('shape') or 'poster')
            li.setProperty('animation', row.get('animation') or '')
            li.setProperty('hide_title', row.get('hide_title') or '')
            target=row.get('target') or {}
            identity=json.dumps([target.get('media_type'),target.get('canonical_id'),target.get('video_id'),row.get('collection_id'),None if target.get('canonical_id') or row.get('collection_id') else row.get('path')],ensure_ascii=False)
            li.setProperty('nuvio.identity',identity);identities.append(identity)
            li.setProperty('watched','1' if simkl_watched.state(watched_data,target.get('media_type'),target.get('canonical_id')).get('watched') else '')
            try:
                percent = min(100, max(0, int(float(row.get('percent_value') or 0))))
            except (ValueError, TypeError, OverflowError):
                percent = 0
            li.setProperty('progress', str(percent))
            li.setProperty('has_progress', '1' if percent else '')
            items.append(li)
        control.reset()
        control.addItems(items)
        if items:
            if old_identity and old_identity in identities:position=identities.index(old_identity)
            control.selectItem(min(max(0, position), len(items) - 1))

    def _touch(self):
        now = time.monotonic()
        if now - self._last_touch > 2:
            self._last_touch = now
            xbmcgui.Window(10000).setProperty('nuviohub.interactive_busy', str(time.time()))

    def onFocus(self, control_id):
        self._touch()
        if ROW_BASE <= control_id < ROW_BASE + len(self._shelves):
            self.setProperty('nuvio.hero_row', str(control_id - ROW_BASE))

    def onAction(self, action):
        self._touch()
        if action.getId() in (117,101,1009,11):
            cid=self.getFocusId()
            if ROW_BASE <= cid < ROW_BASE+len(self._shelves):
                rows=self._shelves[cid-ROW_BASE]['rows'];pos=self.getControl(cid).getSelectedPosition()
                if 0<=pos<len(rows) and rows[pos].get('target'):
                    from .details import context_menu,open_person
                    self._suspended=True
                    if self._previews:self._previews.pause()
                    try:outcome=self.child(open_person,rows[pos]['person']) if rows[pos].get('person') else self.child(context_menu,rows[pos]['target'],info=action.getId()==11,row=rows[pos])
                    finally:self._suspended=False;self._watched_badges()
                    if outcome=='playing' or isinstance(outcome,dict):
                        self._pending=outcome;self._finish()
            return
        if action.getId() in BACK:
            if self._bucket:
                if self._previews:self._previews.pause()
                self._bucket = ''
                self._paint(home_data.initial_shelves())
            else:
                self.setFocusId(101)

    def onClick(self, control_id):
        self._touch()
        if control_id in NAV:
            if self._previews:self._previews.pause()
            self._bucket = NAV[control_id]
            self._paint(home_data.initial_shelves(self._bucket))
            return
        if self._previews:self._previews.pause()
        if control_id == 105:
            self._suspended=True
            try: query=xbmcgui.Dialog().input('Search movies, series, actors & more').strip()
            finally:
                self._suspended=False
                self._watched_badges()
            if query:
                self._search_query=query
                self._bucket='search'
                self._paint(home_data.search_shelves(query))
            return
        elif control_id == 108:
            self._pending='hub'
            self._finish()
            return
        elif control_id == 107:
            self._settings()
            return
        elif ROW_BASE <= control_id < ROW_BASE + len(self._shelves):
            index = control_id - ROW_BASE
            pos = self.getControl(control_id).getSelectedPosition()
            rows = self._shelves[index]['rows']
            if not 0 <= pos < len(rows):
                return
            row = dict(rows[pos])
            self._focus_memory[self._bucket or 'home'] = [index, pos]
            xbmcgui.Window(10000).setProperty('nuvio.home.focus', json.dumps(self._focus_memory))
        else:
            return
        if row.get('collection_id'):
            from resources.lib.collections_home import collection_shelves
            self._bucket = 'collection:' + row['collection_id']
            self._focus_memory.pop(self._bucket,None)
            self._paint(collection_shelves(row['collection_id']))
            return
        if row.get('group_id'):
            self._bucket='group:'+row['group_id']
            self._paint(home_data.initial_shelves(self._bucket));return
        if row.get('target'):
            from .details import open_context,open_person
            self._suspended=True
            if self._previews: self._previews.pause()
            try:
                outcome=self.child(open_person,row['person']) if row.get('person') else self.child(open_context,row['target'],row=row)
                command=outcome if outcome=='playing' or isinstance(outcome,dict) else ''
            finally:
                self._suspended=False
                self._watched_badges()
        elif any(action in (row.get('path') or '') for action in ('action=first_run_wizard','action=setup_center')):
            self._settings();return
        elif any(action in (row.get('path') or '') for action in ('action=nuvio_collection','action=catalog_all')):
            from urllib.parse import urlsplit,parse_qs
            from .catalog import open_catalog
            self._suspended=True
            if self._previews:self._previews.pause()
            try:
                params={k:v[0] for k,v in parse_qs(urlsplit(row['path']).query).items()}
                params.setdefault('label',self._shelves[index]['title'])
                params['initial_rows']=[r for r in self._shelves[index]['rows'] if r.get('target')]
                outcome=self.child(open_catalog,params)
                command=outcome if outcome=='playing' or isinstance(outcome,dict) else ''
            finally:
                self._suspended=False
                self._watched_badges()
        else:
            command = launch_command(row)
        if command:
            self._pending = command
            self._finish()

    def _settings(self):
        from .settings import run
        previous_xml=home_xml()
        self._suspended=True
        if self._previews:self._previews.pause()
        try:command=self.child(run)
        finally:
            self._suspended=False
            from .browse_meta import clear
            clear()
            self._shelf_memory.clear()
        if command:self._pending=command;self._finish();return
        from .setup_gate import ready
        if not ready():self._pending='reload';self._finish();return
        if home_xml()!=previous_xml:
            self._pending='reload';self._finish();return
        self.setProperty('nuvio.home.error','')
        if self._bucket.startswith('collection:'):
            from resources.lib.collections_home import collection_shelves
            shelves=collection_shelves(self._bucket.split(':',1)[1])
        elif self._bucket=='search':
            shelves=home_data.search_shelves(getattr(self,'_search_query',''))
        else:shelves=home_data.initial_shelves(self._bucket)
        self._paint(shelves)

    def _finish(self):
        if self._previews:
            self._previews.close()
        self._closed = True
        self._generation += 1
        if self._pool:
            for future in self._futures:future.cancel()
            self._pool.shutdown(wait=False)  # Kodi Windows still embeds Python 3.8.
        self.close()


def open_home():
    from .setup_gate import ensure_ready
    if not ensure_ready():return
    from .startup import prepare
    prepare()
    xbmcgui.Window(10000).setProperty('nuvio.progress.pull_requested', str(time.time()))
    monitor=xbmc.Monitor()
    bucket='';search_query=''
    while not monitor.abortRequested():
        if bucket.startswith('collection:'):
            from resources.lib.collections_home import collection_shelves
            shelves=collection_shelves(bucket.split(':',1)[1])
        elif bucket=='search':shelves=home_data.search_shelves(search_query)
        else:shelves=home_data.initial_shelves(bucket)
        window=HomeWindow(home_xml(),ADDON.getAddonInfo('path'),'Default','1080i',shelves=shelves,bucket=bucket)
        window._search_query=search_query
        try:
            window.show_ready()
            while not window._closed and not monitor.abortRequested():
                window.drain_updates()
                monitor.waitForAbort(.1)
            pending=window._pending;bucket=window._bucket;search_query=getattr(window,'_search_query','')
        finally:
            window._finish()
            if window._previews:window._previews.finish()
        if pending=='hub':return
        if pending=='reload':continue
        if isinstance(pending,dict) and 'trailer' in pending:
            from .trailers import play_trailer
            if not play_trailer(pending['trailer']):continue
            pending='playing'
        if pending=='playing':
            from .trailers import wait_for_playback
            wait_for_playback()
            continue
        if pending:
            xbmcgui.Window(10000).clearProperty('nuvio.frontend.running')
            from .system_setup import execute_command
            execute_command(pending)
        else:
            xbmc.executebuiltin('ActivateWindow(Home)')
        return
