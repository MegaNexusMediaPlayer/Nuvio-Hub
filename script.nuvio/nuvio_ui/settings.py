"""Nuvio-only account setup and independent presentation preferences."""
import json
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from resources.lib import backend_api, settings_cache, collection_profile
from resources.lib.nuviohub import store
from resources.lib.setup_wizard import add_manifest, resources
from .system_setup import rpc,ensure_addon
from . import settings_page as page
from resources.lib.theme import folder as theme_folder

ADDON=settings_cache.cached_addon()

def select_provider(role):
    # Compatibility entry point for the existing wizard and collection editor.
    return metadata_addons() if role == 'metadata' else stream_addons()


def metadata_addons():
    from resources.lib import metadata_providers, default_setup
    def cinemeta_missing():
        return default_setup.cinemeta_provider(store.list_providers()) is None
    def rows():
        entries = metadata_providers.entries()
        result = [page.item(p.get('name') or p['id'],
                            'Built-in · no setup' if (p.get('manifest') or {}).get('id') == default_setup.CINEMETA_ID
                            else 'Metadata and compatible catalogs', enabled=on)
                  for p, on in entries]
        if cinemeta_missing():
            result.append(page.item('Cinemeta · built-in, no setup', 'Add'))
        return result + [page.item('Add metadata manifest URL'), page.item('Back')]
    def choose(pick):
        entries = metadata_providers.entries()
        extra = 1 if cinemeta_missing() else 0
        if pick < len(entries):
            provider, on = entries[pick]
            metadata_providers.set_enabled(provider['id'], not on)
            if (provider.get('manifest') or {}).get('id') == default_setup.CINEMETA_ID:
                # A manual choice: never switched back automatically.
                ADDON.setSetting(default_setup.CINEMETA_AUTO, '' if not on else 'off')
        elif extra and pick == len(entries):
            from .playback import job
            try:job(default_setup.install_cinemeta, label='Adding Cinemeta')
            except Exception:xbmcgui.Dialog().ok('Cinemeta','Cinemeta could not be added now. Check the connection and retry.')
            ADDON.setSetting(default_setup.CINEMETA_AUTO, '')
        elif pick == len(entries) + extra:
            before = {p['id'] for p in metadata_providers.candidates()}
            if add_manifest(xbmcgui.Dialog()):
                for p in metadata_providers.candidates():
                    if p['id'] not in before:
                        metadata_providers.set_enabled(p['id'], True)
        else:
            return page.DONE
    return page.show('Metadata add-ons · enable each provider', rows, choose)


def stream_addons():
    from resources.lib import stream_providers
    def rows():
        providers=stream_providers.entries()
        return [page.item(p.get('name') or p['id'], 'Stream results', enabled=on)
                for p,on in providers]+[page.item('Add stream add-on manifest URL'),page.item('Back')]
    def choose(pick):
        providers=stream_providers.entries()
        if pick<len(providers):
            provider,on=providers[pick]
            stream_providers.set_enabled(provider['id'],not on)
        elif pick==len(providers):
            before={p['id'] for p in stream_providers.candidates()}
            if add_manifest(xbmcgui.Dialog()):
                for p in stream_providers.candidates():
                    if p['id'] not in before:stream_providers.set_enabled(p['id'],True)
        else:return page.DONE
    return page.show('Stream add-ons · enable each provider',rows,choose)


def addons():
    from resources.lib import stream_providers, metadata_providers
    dialog=xbmcgui.Dialog()
    previous=0
    while True:
        metadata = metadata_providers.entries()
        name = '%d / %d enabled' % (sum(1 for _, on in metadata if on), len(metadata))
        providers=stream_providers.entries()
        enabled=sum(1 for _,on in providers if on)
        pick=dialog.select('Add-ons',['Metadata add-ons: '+name,
            'Stream add-ons: %d / %d enabled'%(enabled,len(providers)),
            'Add configured manifest URL','Import add-ons from Nuvio','Remove a provider','Actor search fallback (optional TMDb key)','Back'],preselect=previous)
        if pick<0 or pick==6:return
        previous=pick
        if pick==0:select_provider('metadata')
        elif pick==1:stream_addons()
        elif pick==2:add_manifest(dialog)
        elif pick==3:sync_nuvio()
        elif pick==5:
            key=dialog.input('Optional TMDb API key',option=xbmcgui.ALPHANUM_HIDE_INPUT).strip()
            if key:ADDON.setSetting('tmdb_api_key',key);settings_cache.invalidate()
        elif pick==4:
            providers=store.list_providers()
            i=dialog.select('Remove provider',[p.get('name') or p['id'] for p in providers])
            if i>=0 and dialog.yesno('Remove provider','Remove this provider from Nuvio Hub?'):
                store.remove_provider(providers[i]['id'])
                for role in ('metadata','streams'):
                    if ADDON.getSetting('nuvio_'+role+'_provider')==providers[i]['id']:ADDON.setSetting('nuvio_'+role+'_provider','')
                settings_cache.invalidate()

def sync_nuvio():
    from resources.lib.nuviohub import nuvio_stremio_sync as sync
    from .playback import job
    if not sync.Nuvio.is_linked():xbmcgui.Dialog().ok('Nuvio account','Sign in to Nuvio in Account first.');return
    if not sync.Nuvio.token().get('profile_index') and not choose_nuvio_profile():return False
    from resources.lib import nuvio_import
    result=job(nuvio_import.fetch,label='Importing Nuvio - '+nuvio_status())
    if result is None:return False
    report=nuvio_import.apply(result)
    settings_cache.invalidate()
    message='%d add-ons saved. Home layout kept. Import and validate your collections in Settings > Collections before browsing.'%report['providers']
    if not report['providers']:message+=' No add-ons imported; check your selected profile.'
    if report['errors']:message+='\n'+'\n'.join(dict.fromkeys(report['errors']))
    xbmcgui.Dialog().ok('Nuvio import - '+nuvio_status(),message)
    return bool(report['providers'] or report['collections']) and not report['errors']


def nuvio_status():
    from resources.lib.nuviohub import nuvio_stremio_sync as sync
    token=sync.Nuvio.token()
    if not token.get('access_token'):return 'Not connected'
    return 'Connected / '+str(token.get('profile_name') or ('Profile '+str(token['profile_index']) if token.get('profile_index') else 'Choose profile'))


def choose_nuvio_profile():
    from resources.lib.nuviohub import nuvio_stremio_sync as sync
    from .playback import job
    profiles=job(sync.Nuvio.profiles,label='Loading Nuvio profiles')
    if not profiles:return False
    pick=0 if len(profiles)==1 else xbmcgui.Dialog().select('Choose the Nuvio profile with your collections',[p['profile_name'] for p in profiles])
    if pick<0:return False
    sync.Nuvio.select_profile(profiles[pick])
    return True

def sign_in_nuvio():
    from resources.lib.nuviohub import nuvio_stremio_sync as sync
    dialog=xbmcgui.Dialog()
    email=dialog.input('Nuvio email').strip()
    if not email:return False
    password=dialog.input('Nuvio password',option=xbmcgui.ALPHANUM_HIDE_INPUT)
    if not password:return False
    from .playback import job
    try:token=job(lambda:sync.Nuvio.authenticate(email,password),label='Signing in to Nuvio')
    except Exception:token=None
    if not token:
        dialog.ok('Nuvio account','Sign-in did not complete. Check your account and connection, or skip and connect later.')
        return False
    sync.Nuvio.save_token(token)
    ADDON.setSetting('nuvio_sync_enabled','true')
    settings_cache.invalidate()
    if not choose_nuvio_profile():return False
    import_from_nuvio()  # 6.0.25: connecting imports everything; no extra steps
    return True


def import_from_nuvio():
    """Connected account: add-ons, progress and the profile's collections, with
    the metadata add-ons those collections use switched ON, so Home loads at once.
    A Home layout the user made is replaced only after a yes."""
    from resources.lib import nuvio_import
    from .playback import job
    dialog=xbmcgui.Dialog()
    collections=True
    if nuvio_import.layout_is_users_own():
        collections=dialog.yesno('Nuvio account','Replace your current Home layout with the collections of your Nuvio profile?')
    result=job(lambda:nuvio_import.fetch(collections=collections),label='Importing your Nuvio add-ons and collections')
    if result is None:return False
    report=nuvio_import.apply(result)
    settings_cache.invalidate()
    try:
        from .browse_meta import clear
        clear()
    except Exception:pass
    lines=['%d add-ons imported.'%report['providers']]
    if report.get('collections'):lines.append('%d collections are on Home.'%report['collections'])
    if report.get('metadata_on'):lines.append('Metadata switched ON: '+', '.join(report['metadata_on'])+'.')
    if report['errors']:lines.append('\n'.join(dict.fromkeys(report['errors'])))
    dialog.ok('Nuvio account - '+nuvio_status(),'\n'.join(lines))
    return bool(report['providers'] or report.get('collections')) and not report['errors']


def accounts():
    from resources.lib.nuviohub import nuvio_stremio_sync as sync
    def rows():return [page.item('Sign in',nuvio_status()),page.item('Sign in with phone · QR code'),page.item('Sync add-ons and progress','Keep Home layout'),page.item('Sign out'),page.item('Choose Nuvio profile',sync.Nuvio.token().get('profile_name') or ''),page.item('Continue Watching sync', (ADDON.getSetting('nuvio_progress_interval') or '60')+' seconds'),page.item('Back')]
    def choose(pick):
        if pick==0:sign_in_nuvio()
        elif pick==1:phone_setup()
        elif pick==2:sync_nuvio()
        elif pick==3:sync.Nuvio.clear();ADDON.setSetting('nuvio_sync_enabled','false')
        elif pick==4:choose_nuvio_profile()
        elif pick==5:progress_settings()
        elif pick==6:return page.DONE
    return page.show('Nuvio account',rows,choose)

def progress_settings():
    from resources.lib.nuviohub import nuvio_stremio_sync as sync
    dialog=xbmcgui.Dialog()
    pick=dialog.select('Continue Watching', ['Refresh interval (Nuvio + Simkl)', 'Nuvio sync direction', 'Back'])
    if pick==0:
        values=['30','60','120','300']
        current=ADDON.getSetting('nuvio_progress_interval') or '60'
        selected=dialog.select('Refresh in seconds · retries respect server limits', values, preselect=values.index(current) if current in values else 1)
        if selected>=0:ADDON.setSetting('nuvio_progress_interval',values[selected])
    elif pick==1:
        values=['Two-way','Upload only','Download only']
        current=ADDON.getSetting('nuvio_sync_direction') or 'Two-way'
        selected=dialog.select('Nuvio progress direction',values,preselect=values.index(current) if current in values else 0)
        if selected>=0:ADDON.setSetting('nuvio_sync_direction',values[selected])
    settings_cache.invalidate()


def collections():
    from .collection_editor import run
    return run()


def import_nuvio_collections():
    from resources.lib.nuviohub import nuvio_stremio_sync as sync
    from .playback import job
    dialog=xbmcgui.Dialog()
    if not sync.Nuvio.is_linked():dialog.ok('Collections','Connect a Nuvio account first.');return False
    if not sync.Nuvio.token().get('profile_index') and not choose_nuvio_profile():return False
    if not dialog.yesno('Import collection layout','Replace Home collection titles, pictures and order with the selected Nuvio profile? Sports and World stay excluded.'):return False
    data=job(lambda:sync.Nuvio.sync_collections([],direction='pull'),label='Importing collection layout')
    if data is None:return False
    return commit_collections(data)


def _switch_on_collection_addons(groups, dialog):
    """Collections reference catalogs of metadata add-ons that are OFF: ask once."""
    from resources.lib import collection_validation, metadata_providers
    from resources.lib.collections_home import matching_catalog
    providers = store.list_providers()
    switches = {p['id']: on for p, on in metadata_providers.entries(providers)}
    off = {}
    for _, source in collection_validation.sources(groups):
        match = matching_catalog(source, providers)
        if match and switches.get(match[0]['id']) is False:
            off[match[0]['id']] = match[0].get('name') or match[0]['id']
    if not off:
        return False
    if not dialog.yesno('Collections', 'These collections use add-ons that are OFF under Metadata add-ons:\n'
                        + ', '.join(off.values()) + '\nTurn them ON?'):
        return False
    for provider_id in off:
        metadata_providers.set_enabled(provider_id, True)
    settings_cache.invalidate()
    return True


def commit_collections(data, force=False):
    """Save the Home layout at once - no network check, nothing blocks (6.0.15).

    ``force`` additionally runs the catalog check and shows its report; an
    unavailable catalog is only reported, never a reason to refuse the layout.
    """
    dialog = xbmcgui.Dialog()
    groups = collection_profile.normalize(data)
    _switch_on_collection_addons(groups, dialog)
    count = collection_profile.save(groups)
    if force:
        from resources.lib import collection_validation
        from .playback import job
        import threading
        cancel = threading.Event()
        proof = job(lambda: collection_validation.validate(groups, stopped=cancel.is_set),
                    label='Checking collection catalogs', cancel=cancel)
        if proof is not None:
            collection_profile.save(groups, validation=proof)
            dialog.ok('Collection check', collection_validation.message(proof))
    else:
        dialog.notification('Collections', '%d collections saved' % count)
    return True


def toggle(key):ADDON.setSetting(key,'false' if ADDON.getSetting(key)=='true' else 'true')
def onoff(key):return 'On' if ADDON.getSetting(key)=='true' else 'Off'

def playback():
    dialog=xbmcgui.Dialog()
    def rows():return [page.item('Autoplay first provider result',enabled=ADDON.getSetting('nuvio_autoplay')=='true'),
        page.item('Intro / credits',ADDON.getSetting('nuvio_skip_mode') or 'Button'),
        page.item('TheIntroDB API key (optional)','Configured' if ADDON.getSetting('nuvio_introdb_key') else 'Not set'),
        page.item('Sport · play the selected event in the small video',enabled=ADDON.getSetting('nuvio_sport_autoplay')!='false'),page.item('Back')]
    def choose(pick):
        if pick==0:toggle('nuvio_autoplay')
        elif pick==1:
            values=('Button','Automatic','Off');current=ADDON.getSetting('nuvio_skip_mode') or 'Button'
            i=dialog.select('Intro / credits',['Show Skip button','Skip automatically','Off'],preselect=values.index(current) if current in values else 0)
            if i>=0:ADDON.setSetting('nuvio_skip_mode',values[i])
        elif pick==2:
            key=dialog.input('TheIntroDB API key',option=xbmcgui.ALPHANUM_HIDE_INPUT)
            if key:ADDON.setSetting('nuvio_introdb_key',key.strip())
        elif pick==3:ADDON.setSetting('nuvio_sport_autoplay','false' if ADDON.getSetting('nuvio_sport_autoplay')!='false' else 'true')
        elif pick==4:return page.DONE
    return page.show('Playback · Kodi controls',rows,choose)


def trailers():
    from resources.lib import imdb_trailers
    dialog=xbmcgui.Dialog()
    def rows():return [page.item('Automatic trailers',enabled=ADDON.getSetting('nuvio_auto_trailers')=='true'),
        page.item('Trailer focus delay',(ADDON.getSetting('nuvio_trailer_delay') or '6')+' seconds'),
        page.item('Trailer duration',('Full trailer' if ADDON.getSetting('nuvio_trailer_duration')=='0' else (ADDON.getSetting('nuvio_trailer_duration') or '90')+' seconds')),
        page.item('Trailer source',imdb_trailers.LABELS[imdb_trailers.source_setting(ADDON)]),
        page.item('IMDb trailer quality · no add-on needed',imdb_trailers.QUALITY_LABELS[imdb_trailers.quality_setting(ADDON)]),
        page.item('YouTube add-on','Configure' if xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)') else 'Install (only for YouTube trailers)'),page.item('Back')]
    def choose(pick):
        if pick==0:toggle('nuvio_auto_trailers')
        elif pick in (1,2):
            values=[3,5,6,8,10,15,20,30] if pick==1 else [15,20,30,45,60,90,120,0]
            key='nuvio_trailer_delay' if pick==1 else 'nuvio_trailer_duration'
            current=ADDON.getSetting(key) or ('6' if pick==1 else '90');labels=[str(v) for v in values]
            i=dialog.select('Trailer length' if pick==2 else 'Seconds', ['Full trailer' if v=='0' else v+' seconds' for v in labels],preselect=labels.index(current) if current in labels else 0)
            if i>=0:ADDON.setSetting(key,labels[i])
        elif pick==3:
            keys=list(imdb_trailers.SOURCES);current=imdb_trailers.source_setting(ADDON)
            i=dialog.select('Trailer source',[imdb_trailers.LABELS[k]+(' · default' if k==imdb_trailers.DEFAULT_SOURCE else '') for k in keys],
                            preselect=keys.index(current))
            if i>=0:ADDON.setSetting(imdb_trailers.SETTING,keys[i])
        elif pick==4:
            keys=['480','720','1080'];current=imdb_trailers.quality_setting(ADDON)
            i=dialog.select('IMDb trailer quality',[imdb_trailers.QUALITY_LABELS[k] for k in keys],preselect=keys.index(current))
            if i>=0:ADDON.setSetting(imdb_trailers.QUALITY_SETTING,keys[i])
        elif pick==5:
            if ensure_addon('plugin.video.youtube'):xbmcaddon.Addon('plugin.video.youtube').openSettings()
        elif pick==6:return page.DONE
    return page.show('Trailers',rows,choose)


def performance():
    from resources.lib.art_cache import selected_mode
    keys=['ram256','disk246','disk512','off']
    labels=['RAM · 256 MiB','Internal disk images · 246 MiB','Internal disk images · 512 MiB','Images off · Kodi texture cache only']
    def rows():
        mode=selected_mode(ADDON)
        label=labels[keys.index(mode)] if mode in keys else labels[-1]
        return [page.item('Metadata image cache',label),
            page.item('Cache usage',xbmcgui.Window(10000).getProperty('nuvio.art_cache.usage') or 'Starting'),
            page.item('Clear Nuvio images and metadata cache'),page.item('Back')]
    def choose(pick):
        if pick==0:
            mode=selected_mode(ADDON)
            index=xbmcgui.Dialog().select('Cache limit · downloaded images',labels,preselect=keys.index(mode) if mode in keys else 0)
            if index>=0:
                ADDON.setSetting('nuvio_art_cache',keys[index]);xbmc.executebuiltin('NotifyAll(nuvio,artcache.configure)')
        elif pick==2:
            from . import browse_meta
            browse_meta.clear(persistent=True)
            xbmc.executebuiltin('NotifyAll(nuvio,artcache.clear)')
        elif pick==3:return page.DONE
    return page.show('Performance & image cache',rows,choose)


def screensaver_label():
    from .saver import ANIMATED,saver_mode
    kind=saver_mode(ADDON)
    if kind==ANIMATED:return 'MegaNexus animated'
    if kind=='video':return 'Custom video'
    return 'Custom image / GIF' if ADDON.getSetting('nuvio_screensaver_art') else 'MegaNexus image'


def screensaver_media():
    from .saver import ANIMATED,saver_mode
    def current():
        kind=saver_mode(ADDON)
        if kind==ANIMATED:return 1
        if kind=='video':return 3
        return 2 if ADDON.getSetting('nuvio_screensaver_art') else 0
    def rows():
        selected=current()
        return [page.item(label,'Selected' if selected==i else '') for i,label in enumerate((
                    'MegaNexus · standard image','MegaNexus · animated',
                    'Custom image / animated GIF','Custom video · MP4, MKV, WebM, MOV'))]+[page.item('Back')]
    def choose(pick):
        if pick==4:return page.DONE
        if pick==0:
            ADDON.setSetting('nuvio_screensaver_type','image')
            ADDON.setSetting('nuvio_screensaver_art','');ADDON.setSetting('nuvio_screensaver_video','')
        elif pick==1:
            ADDON.setSetting('nuvio_screensaver_art','');ADDON.setSetting('nuvio_screensaver_video','')
            ADDON.setSetting('nuvio_screensaver_type',ANIMATED)
        else:
            video=pick==3
            mask='.mp4|.m4v|.mkv|.webm|.mov|.avi|.ts|.m2ts' if video else '.png|.jpg|.jpeg|.webp|.gif'
            path=xbmcgui.Dialog().browseSingle(1,'Choose screensaver video' if video else 'Choose image / animated GIF','files',mask)
            if path:
                ADDON.setSetting('nuvio_screensaver_video' if video else 'nuvio_screensaver_art',path)
                ADDON.setSetting('nuvio_screensaver_type','video' if video else 'image')
                if video:prepare_saver_loop(path)
        settings_cache.invalidate()
    return page.show('Screensaver media · videos loop silently; paused media keeps artwork',rows,choose)


def prepare_saver_loop(path):
    """Write the seamless silent loop copy now, so the screensaver starts with it."""
    from .saver import prepare_loop,LOOP_EXTENSIONS
    if not path.lower().endswith(LOOP_EXTENSIONS):return
    dialog=xbmcgui.DialogProgress()
    dialog.create('Screensaver video','Preparing a seamless, silent loop…')
    try:
        ready=prepare_loop(path,progress=lambda done:dialog.update(int(done*100)),stopped=dialog.iscanceled)
    finally:
        dialog.close()
    if not ready and not dialog.iscanceled():
        xbmcgui.Dialog().notification('Screensaver video','This clip loops with a short pause (format not supported for seamless looping).',xbmcgui.NOTIFICATION_INFO,5000)


def appearance():
    from . import system_setup
    dialog=xbmcgui.Dialog()
    from resources.lib import presentation_settings
    presentation_settings.sync()
    def rows():
        saver=(rpc('Settings.GetSettingValue',{'setting':'screensaver.mode'}) or {}).get('value','')
        from resources.lib import theme
        return [page.item('Use MegaNexus skin','Active' if xbmc.getSkinDir()=='skin.nuvio' else 'Activate'),
            page.item('Theme',theme.LABELS[theme.current(ADDON)]),
            page.item('Poster and catalog transparency',theme.OPACITY_LABELS[theme.card_opacity(ADDON)]),
            page.item('Home layout',home_layout_label()),
            page.item('Home hero and description',enabled=not xbmc.getCondVisibility('Skin.HasSetting(nuvio.hidehero)')),
            page.item('Card titles',enabled=not xbmc.getCondVisibility('Skin.HasSetting(nuvio.hidetitles)')),
            page.item('Weather and clock · all Nuvio screens',enabled=not presentation_settings.hidden()),
            page.item('Animated collection art (focused card only)',enabled=ADDON.getSetting('nuvio_animated_art')=='true'),
            page.item('Automatic trailer settings',onoff('nuvio_auto_trailers')),
            page.item('Weather location / provider',xbmc.getInfoLabel('Weather.Location') or 'Not configured'),
            page.item('MegaNexus screensaver',enabled=saver=='screensaver.nuvio'),
            page.item('Screensaver media', screensaver_label()),
            page.item('Kodi interface settings'),page.item('Collections layout and metadata'),
            page.item('Movie and series cards','Landscape' if ADDON.getSetting('nuvio_card_shape')=='landscape' else 'Portrait posters'),
            page.item('Ratings under the title (when the metadata add-on supplies them)',enabled=ADDON.getSetting('nuvio_show_ratings')!='false'),
            page.item('Back')]
    def choose(pick):
        if pick==1:return choose_theme()
        if pick==2:return choose_card_opacity()
        if pick==3:return choose_home_layout()
        if pick>3:pick-=3  # rows after Theme, transparency and layout keep their earlier numbers
        if pick==13:return page.DONE
        if pick==12:
            ADDON.setSetting('nuvio_show_ratings','false' if ADDON.getSetting('nuvio_show_ratings')!='false' else 'true')
            from .browse_meta import clear
            clear()
            return None
        if pick==0:return 'nuvio:activate_skin'
        elif pick in (1,2):xbmc.executebuiltin('Skin.ToggleSetting(%s)'%{1:'nuvio.hidehero',2:'nuvio.hidetitles'}[pick],True)
        elif pick==3:presentation_settings.set_hidden(not presentation_settings.hidden())
        elif pick==4:toggle('nuvio_animated_art')
        elif pick==5:trailers()
        elif pick==6:system_setup.weather()
        elif pick==7:
            current=(rpc('Settings.GetSettingValue',{'setting':'screensaver.mode'}) or {}).get('value','')
            rpc('Settings.SetSettingValue',{'setting':'screensaver.mode','value':'screensaver.xbmc.builtin.dim' if current=='screensaver.nuvio' else 'screensaver.nuvio'})
        elif pick==8:screensaver_media()
        elif pick==9:return 'ActivateWindow(settings)'
        elif pick==10:collections()
        elif pick==11:
            pick=dialog.select('Movie and series cards',['Portrait posters','Landscape'],preselect=1 if ADDON.getSetting('nuvio_card_shape')=='landscape' else 0)
            if pick>=0:ADDON.setSetting('nuvio_card_shape',('poster','landscape')[pick])
    return page.show('Skin configuration',rows,choose)

def home_layout_label():
    from resources.lib import collections_home as ch
    return 'Catalog rows' if ch.layout(ADDON)=='rows' else 'MegaNexus collections'


def choose_home_layout():
    """MegaNexus collections (default) or Nuvio-style catalog rows (6.0.35, issue #9)."""
    from resources.lib import collections_home as ch
    keys=list(ch.LAYOUTS);current=ch.layout(ADDON)
    pick=xbmcgui.Dialog().select('Home layout',[ch.LAYOUT_LABELS[k] for k in keys],preselect=keys.index(current))
    if pick>=0 and keys[pick]!=current:
        ADDON.setSetting(ch.LAYOUT_SETTING,keys[pick]);settings_cache.invalidate()
    return None  # Home repaints with the new layout when Settings closes


def choose_theme():
    """Light (MegaNexus blue), Dark (OLED) or Semi-dark: interface, HUB skin and screensaver."""
    from resources.lib import theme
    keys=list(theme.THEMES);current=theme.current(ADDON)
    pick=xbmcgui.Dialog().select('Theme',[theme.LABELS[k] for k in keys],preselect=keys.index(current))
    if pick>=0 and keys[pick]!=current:
        theme.apply(keys[pick],ADDON)
        xbmcgui.Dialog().notification('MegaNexus','Theme: '+theme.LABELS[keys[pick]].split(' · ')[0],xbmcgui.NOTIFICATION_INFO,2500)
    return None


def choose_card_opacity():
    """Posters and catalog art slightly see-through over the glass boxes (Off/10/20/30 %)."""
    from resources.lib import theme
    keys=list(theme.OPACITY_LEVELS);current=theme.card_opacity(ADDON)
    pick=xbmcgui.Dialog().select('Poster and catalog transparency',[theme.OPACITY_LABELS[k] for k in keys],preselect=keys.index(current))
    if pick>=0:theme.set_card_opacity(keys[pick],ADDON)
    return None


def tracking_accounts():
    from resources.lib import trakt,simkl
    def rows():return [page.item('Nuvio account',nuvio_status()),
        page.item('Simkl · tracking service','Connected' if simkl.authorized() else 'Not connected'),
        page.item('Trakt · tracking service','Connected' if trakt.authorized() else 'Not connected'),page.item('Back')]
    def choose(pick):
        if pick==0:return accounts()
        elif pick==1:
            from .simkl_account import run as simkl_settings
            return simkl_settings()
        elif pick==2:
            from .trakt_account import run as trakt_settings
            return trakt_settings()
        elif pick==3:return page.DONE
    return page.show('Accounts & tracking services',rows,choose)


def continue_watching():
    """Continue Watching like the Nuvio apps (6.0.35, GitHub issue #7)."""
    from resources.lib import continue_rules as rules
    def rows():return [page.item('Show titles watched in the last',rules.PERIOD_LABELS[str(rules.period_days(ADDON))]),
        page.item('Show unaired next episodes (airs tomorrow)',enabled=rules.show_unaired(ADDON)),
        page.item('Refresh interval and Nuvio sync direction',(ADDON.getSetting('nuvio_progress_interval') or '60')+' seconds'),
        page.item('Back')]
    def choose(pick):
        if pick==0:
            values=list(rules.PERIODS);current=str(rules.period_days(ADDON))
            selected=xbmcgui.Dialog().select('Continue Watching period',[rules.PERIOD_LABELS[v] for v in values],
                                             preselect=values.index(current) if current in values else 1)
            if selected>=0:ADDON.setSetting(rules.PERIOD_SETTING,values[selected])
        elif pick==1:ADDON.setSetting(rules.UNAIRED_SETTING,'false' if rules.show_unaired(ADDON) else 'true')
        elif pick==2:progress_settings()
        elif pick==3:return page.DONE
        settings_cache.invalidate()
        xbmcgui.Window(10000).setProperty('nuvio.progress.revision','settings-%s'%id(rows))
    return page.show('Continue Watching',rows,choose)


KOFI_URL='https://ko-fi.com/master100janovic'


class SupportWindow(xbmcgui.WindowXMLDialog):
    def onInit(self):self.setFocusId(100)
    def onClick(self,cid):self.close()
    def onAction(self,action):
        if action.getId() in (9,10,92,216,247,257,275,61448,61467):self.close()


def support():
    """Ko-fi QR code: scan with a phone to donate."""
    win=SupportWindow('nuvio_support.xml',xbmcaddon.Addon('script.nuvio').getAddonInfo('path'),theme_folder(),'1080i')
    try:win.doModal()
    finally:del win


def check_updates():
    """Compare with the latest GitHub release and install it on confirmation."""
    from resources.lib import updater
    from .playback import job
    backend=xbmcaddon.Addon('plugin.video.nuviohub');dialog=xbmcgui.Dialog()
    current=backend.getAddonInfo('version')
    try:info=job(updater.latest,label='Checking GitHub for updates')
    except Exception:
        dialog.ok('Updates','GitHub could not be reached. Check the connection and retry.\n'+updater.RELEASES);return
    if info is None:
        dialog.ok('Updates','No Nuvio Hub release was found.\n'+updater.RELEASES);return
    if not updater.newer(info['version'],current):
        dialog.ok('Updates','Nuvio Hub %s is up to date (latest release %s).'%(current,info['version']));return
    if not dialog.yesno('Update available','Nuvio Hub %s is available (installed %s).\nInstall it now? Kodi restarts the interface afterwards.'%(info['version'],current)):return
    if xbmc.Player().isPlayingVideo():
        dialog.ok('Updates','Stop playback first, then check again.');return
    try:
        job(lambda:updater.install(info,xbmcvfs.translatePath('special://home/addons'),
                                   xbmcvfs.translatePath(backend.getAddonInfo('profile'))),label='Installing Nuvio Hub %s'%info['version'])
    except Exception as exc:
        dialog.ok('Updates','The update could not be installed; your current version was kept.\n'+(str(exc) if isinstance(exc,ValueError) else ''));return
    xbmc.executebuiltin('UpdateLocalAddons')
    updater.mark_pending(backend,info['version'])
    # Settings are part of the open Nuvio interface: the restart question waits
    # until Nuvio is closed, then shows at the next Nuvio entry if postponed.
    dialog.ok('Updates','Nuvio Hub %s is installed. Kodi asks to restart when you leave Nuvio.'%info['version'])
    return page.DONE


def maintenance():
    def rows():return [page.item('Check for updates',xbmcaddon.Addon('script.nuvio').getAddonInfo('version')),
        page.item('Automatic updates from GitHub',enabled=ADDON.getSetting('nuvio_auto_update')!='false'),
        page.item('Support MegaNexus · Ko-fi','QR code'),
        page.item('Run setup wizard'),page.item('Remove MegaNexus build'),page.item('Back')]
    def choose(pick):
        if pick==0:
            result=check_updates()
            if result:return result
        elif pick==1:ADDON.setSetting('nuvio_auto_update','false' if ADDON.getSetting('nuvio_auto_update')!='false' else 'true')
        elif pick==2:support()
        elif pick==3:
            from .onboarding import run as wizard
            return wizard(force=True)
        elif pick==4:
            from resources.lib.nuvio_uninstall import prepare
            return prepare()
        elif pick==5:return page.DONE
    return page.show('Maintenance',rows,choose)


def phone_setup():
    from .phone_setup import run as phone
    phone()


def run(back_command=''):
    def iptv_settings():
        from .iptv import configure
        configure()
    actions=[('Set up on phone · QR code',phone_setup),('Accounts & tracking services',tracking_accounts),('Continue Watching',continue_watching),('Add-ons',addons),('Collections',collections),
        ('IPTV',iptv_settings),('Playback',playback),('Subtitles',subtitle_settings),('Trailers',trailers),
        ('Home & appearance',appearance),('Performance & image cache',performance),('Maintenance & updates',maintenance),
        ('Support MegaNexus · Ko-fi',support)]
    def rows():return [page.item(label) for label,_ in actions]+[page.item('Done')]
    def choose(pick):
        try:
            if pick==len(actions):return page.DONE
            result=actions[pick][1]()
            return result if isinstance(result,str) else None
        except Exception as exc:xbmcgui.Dialog().ok('Nuvio',str(exc) if isinstance(exc,ValueError) else 'This operation could not finish. Check the configuration and connection, then retry.')
        finally:settings_cache.invalidate()
    return page.show('HUB Settings',rows,choose,back_result=back_command)


def subtitle_settings():
    from resources.lib import nuvio_subtitles as subs
    def rows():return [page.item('Subtitle language',subs.language_name(subs.preferred())),
        page.item('Set subtitles on video start',enabled=ADDON.getSetting('nuvio_subtitles_on_start')=='true'),page.item('Back')]
    def choose(pick):
        if pick==0:
            choices=subs.languages();current=subs.language(subs.preferred())
            selected=next((i for i,r in enumerate(choices) if subs.language(r['value'])==current),0)
            index=xbmcgui.Dialog().select('Subtitle language',[r['label'] for r in choices],preselect=selected)
            if index>=0:
                value=choices[index]['value']
                ADDON.setSetting('nuvio_subtitle_language',value)
                ADDON.setSetting('preferred_subtitle_langs',subs.language(value))
        elif pick==1:toggle('nuvio_subtitles_on_start')
        elif pick==2:return page.DONE
    return page.show('Subtitles',rows,choose)
