"""Account and extras are optional; Home separately requires validated catalog setup."""
import xbmcgui
from resources.lib import backend_api, settings_cache
from resources.lib.nuviohub import nuvio_stremio_sync as sync
from . import settings

ADDON=settings.ADDON


def _steps():
    from . import simkl_account, system_setup, iptv
    return [
        ('Nuvio account', [('Manage connected Nuvio account',settings.accounts) if sync.Nuvio.is_linked() else ('Connect Nuvio account',settings.sign_in_nuvio),
                           ('Choose saved account profile',settings.choose_nuvio_profile)]),
        ('Add-ons (Home layout is kept)', [('Import my Nuvio add-ons and progress',settings.sync_nuvio),
                                   ('Add a configured provider manifest',lambda:settings.add_manifest(xbmcgui.Dialog())),
                                   ('Import and validate Nuvio collections',settings.import_nuvio_collections),
                                   ('Collections / skin configuration',settings.collections)]),
        ('Metadata and streams', [('Enable metadata add-ons',lambda:settings.select_provider('metadata')),
                                 ('Enable stream add-ons',lambda:settings.select_provider('streams'))]),
        ('Playback preferences', [('Autoplay, intro / credits and trailer settings',settings.playback)]),
        ('Simkl watch tracking', [('Connect Simkl with a PIN',simkl_account.link),
                                 ('Tracking and import preferences',simkl_account.run)]),
        ('Optional extras', [('Set up IPTV / EPG',iptv.configure),('Weather location',system_setup.weather),
                            ('Skin and screensaver preferences',_appearance)]),
    ]


def _appearance():
    # Full Kodi settings leave this modal flow; the regular settings menu owns it.
    return settings.appearance()


def _summary():
    from resources.lib import simkl
    meta,streams=backend_api.provider('metadata'),backend_api.provider('streams')
    name=lambda p:(p.get('name') or p.get('id')) if p else 'Not connected'
    return '\n'.join(['Nuvio account: '+('Connected' if sync.Nuvio.is_linked() else 'Skipped'),
                      'Metadata: '+name(meta),'Streams: '+name(streams),
                      'Simkl: '+('Connected' if simkl.authorized() else 'Skipped'),
                      '', 'You can change every choice in HUB Settings.'])


def _finish():
    ADDON.setSetting('nuvio_setup_v110_done','true')
    ADDON.setSetting('nuvio_setup_v110_step','0')
    ADDON.setSetting('nuvio_wizard_applied','true')
    settings_cache.invalidate()


def _offered():
    ADDON.setSetting('nuvio_setup_offered','true')
    settings_cache.invalidate()


def _already_started():
    """Recognize partially configured profiles created before the offered flag."""
    if any(ADDON.getSetting(key)=='true' for key in ('nuvio_setup_offered','nuvio_setup_v110_done','nuvio_wizard_applied')):return True
    try:
        if int(ADDON.getSetting('nuvio_setup_v110_step') or 0)>0:return True
    except ValueError:pass
    if any(ADDON.getSetting('nuvio_'+role+'_provider') for role in ('metadata','streams')):return True
    if sync.Nuvio.is_linked():return True
    from resources.lib import simkl
    return simkl.authorized()


def run(force=False):
    if not force and _already_started():
        if ADDON.getSetting('nuvio_setup_offered')!='true':_offered()
        return
    # Offer once, including when Back/Cancel dismisses the very first step.
    # Completion is separate: every optional step remains available manually.
    _offered()
    dialog=xbmcgui.Dialog()
    if not force:
        # 6.0.22: the phone is the easy way; the remote steps stay available.
        way=dialog.select('Welcome to MegaNexus',['Set up on your phone · QR code','Set up with the remote','Skip · open MegaNexus'])
        if way<0 or way==2:return
        if way==0:
            from .phone_setup import run as phone
            if phone():_finish()
            return
    steps=_steps()
    try:index=0 if force else min(len(steps)-1,max(0,int(ADDON.getSetting('nuvio_setup_v110_step') or 0)))
    except ValueError:index=0
    while index<len(steps):
        title,actions=steps[index]
        labels=[name for name,_ in actions]+['Next','Skip this step','Finish optional steps and check collection setup']
        if index:labels.append('Previous step')
        status=(' - '+settings.nuvio_status()) if index<2 else ''
        pick=dialog.select('Welcome to MegaNexus - %d/%d: %s%s'%(index+1,len(steps),title,status),labels)
        if pick<0:return  # Open Nuvio goes to Home; setup stays available in Settings.
        if pick<len(actions):
            try:
                result=actions[pick][1]()
                if result=='nuvio:activate_skin':return 'nuvio:activate_skin:wizard'
                if isinstance(result,str) and result.startswith('ActivateWindow('):return result
                if result is True and index<2:
                    index+=1
                    ADDON.setSetting('nuvio_setup_v110_step',str(index))
            except Exception:
                dialog.ok('Nuvio setup','This step could not finish. Check your account or connection, retry, or skip it for now.')
            finally:settings_cache.invalidate()
            continue
        choice=pick-len(actions)
        if choice==2:_finish();return
        index=index-1 if choice==3 else index+1
        ADDON.setSetting('nuvio_setup_v110_step',str(index))
    dialog.ok('Nuvio setup',_summary())
    _finish()
