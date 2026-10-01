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

ADDON=settings_cache.cached_addon()

def select_provider(role):
    # Compatibility entry point for the existing wizard and collection editor.
    return metadata_addons() if role == 'metadata' else stream_addons()


def metadata_addons():
    from resources.lib import metadata_providers
    def rows():
        entries = metadata_providers.entries()
        return [page.item(p.get('name') or p['id'], 'Metadata and compatible catalogs', enabled=on)
                for p, on in entries] + [page.item('Add metadata manifest URL'), page.item('Back')]
    def choose(pick):
        entries = metadata_providers.entries()
        if pick < len(entries):
            provider, on = entries[pick]
            metadata_providers.set_enabled(provider['id'], not on)
        elif pick == len(entries):
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
    dialog.ok('Nuvio account',nuvio_status()+'. Account saved. Next: import your add-ons and collections.')
    return True


def accounts():
    from resources.lib.nuviohub import nuvio_stremio_sync as sync
    def rows():return [page.item('Sign in',nuvio_status()),page.item('Sync add-ons and progress','Keep Home layout'),page.item('Sign out'),page.item('Choose Nuvio profile',sync.Nuvio.token().get('profile_name') or ''),page.item('Continue Watching sync', (ADDON.getSetting('nuvio_progress_interval') or '60')+' seconds'),page.item('Back')]
    def choose(pick):
        if pick==0:
            if sign_in_nuvio():sync_nuvio()
        elif pick==1:sync_nuvio()
        elif pick==2:sync.Nuvio.clear();ADDON.setSetting('nuvio_sync_enabled','false')
        elif pick==3:choose_nuvio_profile()
        elif pick==4:progress_settings()
        elif pick==5:return page.DONE
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


def commit_collections(data):
    """Network validation is cancellable; only the UI commits after success."""
    from resources.lib import collection_validation
    from .playback import job
    groups = collection_profile.normalize(data)
    proof = collection_validation.stored_proof(groups)
    if proof is None:
        import threading
        cancel = threading.Event()
        proof = job(lambda: collection_validation.validate(groups, stopped=cancel.is_set), label='Checking collection catalogs and metadata', cancel=cancel)
    if proof is None:
        return False
    if not proof.get('ok') or not collection_validation.accepts(groups, proof):
        xbmcgui.Dialog().ok('Collection check failed', collection_validation.message(proof))
        return False
    count = collection_profile.save(groups, validation=proof)
    xbmcgui.Dialog().notification('Collections', '%d validated collections saved' % count)
    return True


def toggle(key):ADDON.setSetting(key,'false' if ADDON.getSetting(key)=='true' else 'true')
def onoff(key):return 'On' if ADDON.getSetting(key)=='true' else 'Off'

def playback():
    dialog=xbmcgui.Dialog()
    def rows():return [page.item('Autoplay first provider result',enabled=ADDON.getSetting('nuvio_autoplay')=='true'),
        page.item('Intro / credits',ADDON.getSetting('nuvio_skip_mode') or 'Button'),
        page.item('TheIntroDB API key (optional)','Configured' if ADDON.getSetting('nuvio_introdb_key') else 'Not set'),page.item('Back')]
    def choose(pick):
        if pick==0:toggle('nuvio_autoplay')
        elif pick==1:
            values=('Button','Automatic','Off');current=ADDON.getSetting('nuvio_skip_mode') or 'Button'
            i=dialog.select('Intro / credits',['Show Skip button','Skip automatically','Off'],preselect=values.index(current) if current in values else 0)
            if i>=0:ADDON.setSetting('nuvio_skip_mode',values[i])
        elif pick==2:
            key=dialog.input('TheIntroDB API key',option=xbmcgui.ALPHANUM_HIDE_INPUT)
            if key:ADDON.setSetting('nuvio_introdb_key',key.strip())
        elif pick==3:return page.DONE
    return page.show('Playback · Kodi controls',rows,choose)


def trailers():
    dialog=xbmcgui.Dialog()
    def rows():return [page.item('Automatic trailers',enabled=ADDON.getSetting('nuvio_auto_trailers')=='true'),
        page.item('Trailer focus delay',(ADDON.getSetting('nuvio_trailer_delay') or '6')+' seconds'),
        page.item('Trailer duration',('Full trailer' if ADDON.getSetting('nuvio_trailer_duration')=='0' else (ADDON.getSetting('nuvio_trailer_duration') or '90')+' seconds')),
        page.item('YouTube add-on','Configure' if xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)') else 'Install'),page.item('Back')]
    def choose(pick):
        if pick==0:toggle('nuvio_auto_trailers')
        elif pick in (1,2):
            values=[3,5,6,8,10,15,20,30] if pick==1 else [15,20,30,45,60,90,120,0]
            key='nuvio_trailer_delay' if pick==1 else 'nuvio_trailer_duration'
            current=ADDON.getSetting(key) or ('6' if pick==1 else '90');labels=[str(v) for v in values]
            i=dialog.select('Trailer length' if pick==2 else 'Seconds', ['Full trailer' if v=='0' else v+' seconds' for v in labels],preselect=labels.index(current) if current in labels else 0)
            if i>=0:ADDON.setSetting(key,labels[i])
        elif pick==3:
            if ensure_addon('plugin.video.youtube'):xbmcaddon.Addon('plugin.video.youtube').openSettings()
        elif pick==4:return page.DONE
    return page.show('Trailers',rows,choose)


def performance():
    from resources.lib.art_cache import selected_mode
    keys=['ram200','disk246','disk512','off']
    labels=['RAM · 200 MiB (160 images + 40 metadata)','Internal disk images · 246 MiB','Internal disk images · 512 MiB','Images off · Kodi texture cache only']
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
        elif pick==1:
            xbmcgui.Dialog().ok('Image cache','RAM 200: 160 MiB of image bytes plus 40 MiB of serialized metadata. Metadata also has a 128 MiB disk budget. Kodi decoded textures and Python overhead are separate. Startup warms first catalog pages, not every title in an unlimited catalog. Missing pages load on demand.')
        elif pick==2:
            from . import browse_meta
            browse_meta.clear(persistent=True)
            xbmc.executebuiltin('NotifyAll(nuvio,artcache.clear)')
        elif pick==3:return page.DONE
    return page.show('Performance & image cache',rows,choose)


def screensaver_media():
    def rows():
        kind=ADDON.getSetting('nuvio_screensaver_type') or 'image'
        return [page.item('Image / animated GIF','Selected' if kind!='video' else ''),
                page.item('Animated video · MP4, MKV, WebM, MOV','Selected' if kind=='video' else ''),
                page.item('Restore default Nuvio artwork'),page.item('Back')]
    def choose(pick):
        if pick==3:return page.DONE
        if pick==2:
            ADDON.setSetting('nuvio_screensaver_type','image')
            ADDON.setSetting('nuvio_screensaver_art','');ADDON.setSetting('nuvio_screensaver_video','')
        else:
            video=pick==1
            mask='.mp4|.m4v|.mkv|.webm|.mov|.avi|.ts|.m2ts' if video else '.png|.jpg|.jpeg|.webp|.gif'
            path=xbmcgui.Dialog().browseSingle(1,'Choose screensaver video' if video else 'Choose image / animated GIF','files',mask)
            if path:
                ADDON.setSetting('nuvio_screensaver_video' if video else 'nuvio_screensaver_art',path)
                ADDON.setSetting('nuvio_screensaver_type','video' if video else 'image')
        settings_cache.invalidate()
    return page.show('Screensaver media · videos loop silently; paused media keeps artwork',rows,choose)


def appearance():
    from . import system_setup
    dialog=xbmcgui.Dialog()
    from resources.lib import presentation_settings
    presentation_settings.sync()
    def rows():
        saver=(rpc('Settings.GetSettingValue',{'setting':'screensaver.mode'}) or {}).get('value','')
        return [page.item('Use Nuvio skin','Active' if xbmc.getSkinDir()=='skin.nuvio' else 'Activate'),
            page.item('Home hero and description',enabled=not xbmc.getCondVisibility('Skin.HasSetting(nuvio.hidehero)')),
            page.item('Card titles',enabled=not xbmc.getCondVisibility('Skin.HasSetting(nuvio.hidetitles)')),
            page.item('Weather and clock · all Nuvio screens',enabled=not presentation_settings.hidden()),
            page.item('Animated collection art (focused card only)',enabled=ADDON.getSetting('nuvio_animated_art')=='true'),
            page.item('Automatic trailer settings',onoff('nuvio_auto_trailers')),
            page.item('Weather location / provider',xbmc.getInfoLabel('Weather.Location') or 'Not configured'),
            page.item('Nuvio screensaver',enabled=saver=='screensaver.nuvio'),
            page.item('Screensaver media', 'Animated video' if ADDON.getSetting('nuvio_screensaver_type')=='video' else 'Image / GIF'),
            page.item('Kodi interface settings'),page.item('Collections layout and metadata'),
            page.item('Movie and series cards','Landscape' if ADDON.getSetting('nuvio_card_shape')=='landscape' else 'Portrait posters'),page.item('Back')]
    def choose(pick):
        if pick==12:return page.DONE
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

def tracking_accounts():
    def rows():return [page.item('Nuvio account',nuvio_status()),page.item('Simkl account & tracking'),page.item('Back')]
    def choose(pick):
        if pick==0:return accounts()
        elif pick==1:
            from .simkl_account import run as simkl_settings
            return simkl_settings()
        elif pick==2:return page.DONE
    return page.show('Accounts & tracking',rows,choose)


def maintenance():
    def rows():return [page.item('About & updates',xbmcaddon.Addon('script.nuvio').getAddonInfo('version')),page.item('Run setup wizard'),page.item('Remove Nuvio build'),page.item('Back')]
    def choose(pick):
        if pick==0:xbmcgui.Dialog().ok('Nuvio '+xbmcaddon.Addon('script.nuvio').getAddonInfo('version'),'Nuvio account and collections, your metadata provider and ordered stream results. Manual ZIP updates. Weather, IPTV Simple and YouTube are optional official Kodi components.')
        elif pick==1:
            from .onboarding import run as wizard
            return wizard(force=True)
        elif pick==2:
            from resources.lib.nuvio_uninstall import prepare
            return prepare()
        elif pick==3:return page.DONE
    return page.show('Maintenance',rows,choose)


def run(back_command=''):
    def iptv_settings():
        from .iptv import configure
        configure()
    actions=[('Accounts & tracking',tracking_accounts),('Add-ons',addons),('Collections',collections),
        ('IPTV',iptv_settings),('Playback',playback),('Subtitles',subtitle_settings),('Trailers',trailers),
        ('Home & appearance',appearance),('Performance & image cache',performance),('Maintenance',maintenance)]
    def rows():return [page.item(label) for label,_ in actions]+[page.item('Done')]
    def choose(pick):
        try:
            if pick==len(actions):return page.DONE
            result=actions[pick][1]()
            return result if isinstance(result,str) else None
        except Exception as exc:xbmcgui.Dialog().ok('Nuvio',str(exc) if isinstance(exc,ValueError) else 'This operation could not finish. Check the configuration and connection, then retry.')
        finally:settings_cache.invalidate()
    return page.show('Nuvio Settings',rows,choose,back_result=back_command)


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
