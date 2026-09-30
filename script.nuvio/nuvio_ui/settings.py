"""Nuvio-only account setup and independent presentation preferences."""
import json
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from resources.lib import backend_api, settings_cache, collection_profile
from resources.lib.dexhub import store
from resources.lib.setup_wizard import add_manifest, resources
from .system_setup import rpc,ensure_addon
from . import settings_page as page

ADDON=settings_cache.cached_addon()

def select_provider(role):
    resource='meta' if role=='metadata' else 'stream'
    candidates=[p for p in store.list_providers() if resource in resources(p)]
    if not candidates:xbmcgui.Dialog().ok('Add-ons','Add a configured provider manifest with the '+resource+' resource first.');return
    pick=xbmcgui.Dialog().select('Metadata for all collections' if role=='metadata' else 'Stream provider',[p.get('name') or p['id'] for p in candidates])
    if pick>=0:ADDON.setSetting('nuvio_'+role+'_provider',candidates[pick]['id']);settings_cache.invalidate()

def addons():
    dialog=xbmcgui.Dialog()
    previous=0
    while True:
        meta,streams=backend_api.provider('metadata'),backend_api.provider('streams')
        name=lambda p:(p.get('name') or p['id']) if p else 'Not connected'
        pick=dialog.select('Add-ons',['Metadata: '+name(meta),'Streams: '+name(streams),'Add configured manifest URL','Import add-ons from Nuvio','Remove a provider','Back'],preselect=previous)
        if pick<0 or pick==5:return
        previous=pick
        if pick in (0,1):select_provider('metadata' if pick==0 else 'streams')
        elif pick==2:add_manifest(dialog)
        elif pick==3:sync_nuvio()
        elif pick==4:
            rows=store.list_providers();i=dialog.select('Remove provider',[p.get('name') or p['id'] for p in rows])
            if i>=0 and dialog.yesno('Remove provider','Remove this provider from Nuvio Hub?'):
                store.remove_provider(rows[i]['id'])
                for role in ('metadata','streams'):
                    if ADDON.getSetting('nuvio_'+role+'_provider')==rows[i]['id']:ADDON.setSetting('nuvio_'+role+'_provider','')

def sync_nuvio():
    from resources.lib.dexhub import nuvio_stremio_sync as sync
    from .playback import job
    if not sync.Nuvio.is_linked():xbmcgui.Dialog().ok('Nuvio account','Sign in to Nuvio in Account first.');return
    if not sync.Nuvio.token().get('profile_index') and not choose_nuvio_profile():return False
    from resources.lib import nuvio_import
    result=job(nuvio_import.fetch,label='Importing Nuvio - '+nuvio_status())
    if result is None:return False
    report=nuvio_import.apply(result)
    settings_cache.invalidate()
    message='%d add-ons saved. Home layout kept. Collection import is optional in Skin configuration.'%report['providers']
    if not report['providers']:message+=' No add-ons imported; check your selected profile.'
    if report['errors']:message+='\n'+'\n'.join(dict.fromkeys(report['errors']))
    xbmcgui.Dialog().ok('Nuvio import - '+nuvio_status(),message)
    return bool(report['providers'] or report['collections']) and not report['errors']


def nuvio_status():
    from resources.lib.dexhub import nuvio_stremio_sync as sync
    token=sync.Nuvio.token()
    if not token.get('access_token'):return 'Not connected'
    return 'Connected / '+str(token.get('profile_name') or ('Profile '+str(token['profile_index']) if token.get('profile_index') else 'Choose profile'))


def choose_nuvio_profile():
    from resources.lib.dexhub import nuvio_stremio_sync as sync
    from .playback import job
    profiles=job(sync.Nuvio.profiles,label='Loading Nuvio profiles')
    if not profiles:return False
    pick=0 if len(profiles)==1 else xbmcgui.Dialog().select('Choose the Nuvio profile with your collections',[p['profile_name'] for p in profiles])
    if pick<0:return False
    sync.Nuvio.select_profile(profiles[pick])
    return True

def sign_in_nuvio():
    from resources.lib.dexhub import nuvio_stremio_sync as sync
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
    from resources.lib.dexhub import nuvio_stremio_sync as sync
    def rows():return [page.item('Sign in',nuvio_status()),page.item('Sync add-ons and progress','Keep Home layout'),page.item('Sign out'),page.item('Choose Nuvio profile',sync.Nuvio.token().get('profile_name') or ''),page.item('Back')]
    def choose(pick):
        if pick==0:
            if sign_in_nuvio():sync_nuvio()
        elif pick==1:sync_nuvio()
        elif pick==2:sync.Nuvio.clear();ADDON.setSetting('nuvio_sync_enabled','false')
        elif pick==3:choose_nuvio_profile()
        elif pick==4:return page.DONE
    return page.show('Nuvio account',rows,choose)

def collections():
    from .collection_editor import run
    return run()


def import_nuvio_collections():
    from resources.lib.dexhub import nuvio_stremio_sync as sync
    from .playback import job
    dialog=xbmcgui.Dialog()
    if not sync.Nuvio.is_linked():dialog.ok('Collections','Connect a Nuvio account first.');return False
    if not sync.Nuvio.token().get('profile_index') and not choose_nuvio_profile():return False
    if not dialog.yesno('Import collection layout','Replace Home collection titles, pictures and order with the selected Nuvio profile? Sports and World stay excluded.'):return False
    data=job(lambda:sync.Nuvio.sync_collections([],direction='pull'),label='Importing collection layout')
    if data is None:return False
    count=collection_profile.save(data)
    dialog.ok('Collections','%d collections saved. Choose metadata in Skin configuration.'%count)
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
        page.item('Trailer duration',(ADDON.getSetting('nuvio_trailer_duration') or '30')+' seconds'),
        page.item('YouTube add-on','Configure' if xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)') else 'Install'),page.item('Back')]
    def choose(pick):
        if pick==0:toggle('nuvio_auto_trailers')
        elif pick in (1,2):
            values=[3,5,6,8,10,15,20,30] if pick==1 else [15,20,30,45,60]
            key='nuvio_trailer_delay' if pick==1 else 'nuvio_trailer_duration'
            current=ADDON.getSetting(key) or ('6' if pick==1 else '30');labels=[str(v) for v in values]
            i=dialog.select('Seconds',labels,preselect=labels.index(current) if current in labels else 0)
            if i>=0:ADDON.setSetting(key,labels[i])
        elif pick==3:
            if ensure_addon('plugin.video.youtube'):xbmcaddon.Addon('plugin.video.youtube').openSettings()
        elif pick==4:return page.DONE
    return page.show('Trailers',rows,choose)


def performance():
    keys=['disk246','disk512','ram150','off']
    labels=['Internal disk · 246 MB','Internal disk · 512 MB','RAM · 150 MB','Off · Kodi texture cache only']
    def rows():
        mode=ADDON.getSetting('nuvio_art_cache') or 'disk246'
        label=labels[keys.index(mode)] if mode in keys else labels[-1]
        return [page.item('Metadata image cache',label),
            page.item('Cache usage',xbmcgui.Window(10000).getProperty('nuvio.art_cache.usage') or 'Starting'),
            page.item('Clear Nuvio image cache'),page.item('Back')]
    def choose(pick):
        if pick==0:
            mode=ADDON.getSetting('nuvio_art_cache') or 'disk246'
            index=xbmcgui.Dialog().select('Cache limit · downloaded images',labels,preselect=keys.index(mode) if mode in keys else 0)
            if index>=0:
                ADDON.setSetting('nuvio_art_cache',keys[index]);xbmc.executebuiltin('NotifyAll(nuvio,artcache.configure)')
        elif pick==1:
            xbmcgui.Dialog().ok('Image cache','Limits apply to downloaded image files. RAM fills as you browse and resets with Kodi. Disk images survive restart. Kodi manages decoded textures separately. Up to four images download at once.')
        elif pick==2:xbmc.executebuiltin('NotifyAll(nuvio,artcache.clear)')
        elif pick==3:return page.DONE
    return page.show('Performance & image cache',rows,choose)


def appearance():
    from . import system_setup
    dialog=xbmcgui.Dialog()
    def rows():
        saver=(rpc('Settings.GetSettingValue',{'setting':'screensaver.mode'}) or {}).get('value','')
        return [page.item('Use Nuvio skin','Active' if xbmc.getSkinDir()=='skin.nuvio' else 'Activate'),
            page.item('Home hero and description',enabled=not xbmc.getCondVisibility('Skin.HasSetting(nuvio.hidehero)')),
            page.item('Card titles',enabled=not xbmc.getCondVisibility('Skin.HasSetting(nuvio.hidetitles)')),
            page.item('Weather and clock',enabled=not xbmc.getCondVisibility('Skin.HasSetting(nuvio.hideweather)')),
            page.item('Animated collection art (focused card only)',enabled=ADDON.getSetting('nuvio_animated_art')=='true'),
            page.item('Automatic trailer settings',onoff('nuvio_auto_trailers')),
            page.item('Weather location / provider',xbmc.getInfoLabel('Weather.Location') or 'Not configured'),
            page.item('Nuvio screensaver',enabled=saver=='screensaver.nuvio'),
            page.item('Screensaver image / GIF','Custom' if ADDON.getSetting('nuvio_screensaver_art') else 'Default Nuvio art'),
            page.item('Kodi interface settings'),page.item('Collections layout and metadata'),
            page.item('Movie and series cards','Landscape' if ADDON.getSetting('nuvio_card_shape')=='landscape' else 'Portrait posters'),page.item('Back')]
    def choose(pick):
        if pick==12:return page.DONE
        if pick==0:return 'nuvio:activate_skin'
        elif pick in (1,2,3):xbmc.executebuiltin('Skin.ToggleSetting(%s)'%{1:'nuvio.hidehero',2:'nuvio.hidetitles',3:'nuvio.hideweather'}[pick],True)
        elif pick==4:toggle('nuvio_animated_art')
        elif pick==5:trailers()
        elif pick==6:system_setup.weather()
        elif pick==7:
            current=(rpc('Settings.GetSettingValue',{'setting':'screensaver.mode'}) or {}).get('value','')
            rpc('Settings.SetSettingValue',{'setting':'screensaver.mode','value':'screensaver.xbmc.builtin.dim' if current=='screensaver.nuvio' else 'screensaver.nuvio'})
        elif pick==8:
            path=dialog.browseSingle(1,'Screensaver image or animated GIF','files','.png|.jpg|.jpeg|.webp|.gif')
            if path:ADDON.setSetting('nuvio_screensaver_art',path)
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
