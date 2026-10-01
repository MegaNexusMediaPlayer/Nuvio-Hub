"""Standalone removal helper; copied outside the bundle before it is launched."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import time
import xml.etree.ElementTree as ET

BUNDLE = {'plugin.video.nuviohub','script.nuvio','skin.nuvio','screensaver.nuvio'}


def rpc(method, params=None):
    import xbmc
    reply=json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})))
    if reply.get('error'):raise ValueError('Kodi could not complete '+method+(' for '+params['addonid'] if params and params.get('addonid') else '')+'. Restart Kodi and retry removal.')
    return reply.get('result')


def inventory():
    return {a['addonid']:a for a in rpc('Addons.GetAddons',{'properties':['enabled','dependencies','path']}).get('addons',[])}


def ledger_path():
    import xbmcaddon, xbmcvfs
    return Path(xbmcvfs.translatePath(xbmcaddon.Addon('plugin.video.nuviohub').getAddonInfo('profile')))/'installed-components.json'


def read_ledger():
    try:return json.loads(ledger_path().read_text(encoding='utf-8'))
    except (OSError,ValueError):return {'owned':[], 'enabled_existing':[]}


def record_install(aid, before, after):
    """Claim only newly installed nodes in the requested add-on's dependency graph."""
    visited=set()
    def visit(key):
        if key in visited or key not in after:return
        visited.add(key)
        for dep in after[key].get('dependencies',[]):visit(dep['addonid'])
    visit(aid)
    ledger=read_ledger()
    ledger['owned']=sorted(set(ledger.get('owned',[])) | (visited-set(before)))
    enabled={key for key in visited & set(before) if before[key].get('enabled') is False and after[key].get('enabled') is True}
    ledger['enabled_existing']=sorted(set(ledger.get('enabled_existing',[])) | enabled)
    path=ledger_path();path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:temp.write_text(json.dumps(ledger),encoding='utf-8');os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()


def removal_plan(installed, ledger):
    wanted=(BUNDLE | set(ledger.get('owned',[]))) & set(installed)
    wanted={aid for aid in wanted if not aid.startswith(('xbmc.','kodi.'))}
    # Retain transitive dependencies needed by ANY outside add-on, even disabled.
    while True:
        needed={d['addonid'] for aid,row in installed.items() if aid not in wanted for d in row.get('dependencies',[])}
        smaller=wanted-needed
        if smaller==wanted:break
        wanted=smaller
    order=[]
    while wanted:
        dependencies={d['addonid'] for aid in wanted for d in installed[aid].get('dependencies',[])}
        leaves=sorted(wanted-dependencies)
        if not leaves:raise ValueError('Circular add-on dependencies; remove these through Kodi settings.')
        order.extend(leaves);wanted.difference_update(leaves)
    return order


def stage_removal(addons_dir, order, stage):
    """Validate ALL targets before moving any; restore on partial failure."""
    root=Path(addons_dir).resolve();stage=Path(stage).resolve();targets=[]
    if stage==root or root in stage.parents:raise ValueError('Removal staging must be outside addons.')
    for aid in order:
        if not re.fullmatch(r'[a-zA-Z0-9._-]+',aid):raise ValueError('Invalid component ID')
        target=root/aid
        if target.is_symlink() or target.resolve().parent!=root:raise ValueError('Component path is outside addons.')
        if not target.exists():continue
        if ET.parse(target/'addon.xml').getroot().get('id')!=aid:raise ValueError('Component identity mismatch')
        targets.append((aid,target))
    moved=[]
    try:
        for aid,target in targets:
            os.replace(target,stage/aid);moved.append(aid)
    except Exception:
        for aid in reversed(moved):os.replace(stage/aid,root/aid)
        raise
    return moved


def prepare():
    import xbmcvfs
    # Run without an add-on invocation context so disabling the Hub service cannot
    # stop this helper halfway through the removal.
    path=Path(xbmcvfs.translatePath('special://temp'))/('nuvio-uninstall-'+uuid.uuid4().hex+'.py')
    shutil.copyfile(__file__,path)
    return 'RunScript("%s")'%str(path).replace('\\','/')


def seek_restore(addons_root):
    """The seek-settings restore function, loaded BEFORE the files are moved.

    This helper runs as a standalone copy in special://temp (no package), so a
    relative import is impossible; it used to fail here after the components
    were already disabled, and every removal was rolled back."""
    if __package__:
        from .seek_profile import restore
        return restore
    import sys
    backend = str(Path(addons_root) / 'plugin.video.nuviohub')
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from resources.lib.seek_profile import restore
    return restore


def switch_to_estuary(monitor):
    import xbmc
    if xbmc.getSkinDir()!='skin.nuvio':return True
    rpc('Settings.SetSettingValue',{'setting':'lookandfeel.skin','value':'skin.estuary'})
    start=time.monotonic();seen=False
    while time.monotonic()-start<30:
        visible=xbmc.getCondVisibility('Window.IsVisible(yesnodialog)')
        if visible:seen=True
        elif seen or time.monotonic()-start>=5:
            return xbmc.getSkinDir()=='skin.estuary'
        if monitor.waitForAbort(.1):return False
    return False


def purge_bundle_profiles(profile_root):
    """Only explicit Nuvio IDs; never purge shared dependency accounts/settings."""
    root=Path(profile_root).resolve();targets=[]
    for aid in sorted(BUNDLE):
        target=root/aid
        if target.is_symlink() or target.resolve().parent!=root:raise ValueError('Unsafe settings path; settings were retained.')
        if target.exists():targets.append(target)
    for target in targets:shutil.rmtree(target)


def run():
    import xbmc, xbmcgui, xbmcvfs
    dialog=xbmcgui.Dialog();monitor=xbmc.Monitor();home=xbmcgui.Window(10000)
    for _ in range(40):
        if not home.getProperty('nuvio.frontend.running'):break
        if monitor.waitForAbort(.1):return
    if home.getProperty('nuvio.frontend.running'):raise ValueError('Close Nuvio and retry removal.')
    if xbmc.Player().isPlaying():raise ValueError('Stop playback before removing Nuvio.')
    installed=inventory();ledger=read_ledger();order=removal_plan(installed,ledger)
    if not BUNDLE.intersection(installed).issubset(order):
        raise ValueError('Another installed add-on requires Nuvio. Remove that dependency in Kodi first.')
    if not order:dialog.ok('Nuvio removal','No Nuvio components remain.');return
    choice=dialog.select('Remove Nuvio build',[
        'Keep accounts, settings and history (recommended)',
        'Remove Nuvio accounts, settings and history too','Cancel'],preselect=0)
    if choice not in (0,1):return
    keep=choice==0
    message='Accounts, settings and playback history will be kept.' if keep else 'Nuvio accounts, settings and history will be deleted. This cannot be undone.'
    if not dialog.yesno('Remove Nuvio build','Remove these components?\n'+', '.join(order)+'\n'+message+' Shared and pre-existing add-ons are kept.'):return
    home.setProperty('nuvio.uninstalling','1')
    moved=[]
    root=Path(xbmcvfs.translatePath('special://home/addons')).resolve()
    try:restore=seek_restore(root)
    except Exception:restore=None  # Optional: Kodi seek steps simply stay as they are.
    try:
        if rpc('Settings.GetSettingValue',{'setting':'screensaver.mode'}).get('value')=='screensaver.nuvio':
            rpc('Settings.SetSettingValue',{'setting':'screensaver.mode','value':'screensaver.xbmc.builtin.dim'})
        if not switch_to_estuary(monitor):raise ValueError('Removal cancelled: keep the Estuary skin when Kodi asks, then retry.')
        if 'weather.openmeteo' in order:
            current=rpc('Settings.GetSettingValue',{'setting':'weather.addon'}).get('value')
            if current=='weather.openmeteo':rpc('Settings.SetSettingValue',{'setting':'weather.addon','value':''})
        for aid in order:
            # Skin/services can remain in use briefly after the confirmed switch.
            for attempt in range(20):
                try:rpc('Addons.SetAddonEnabled',{'addonid':aid,'enabled':False});break
                except ValueError:
                    if attempt==19:raise
                    if monitor.waitForAbort(.25):return
            details=rpc('Addons.GetAddonDetails',{'addonid':aid,'properties':['enabled']})
            if details.get('addon',{}).get('enabled') is not False:raise ValueError('Kodi could not disable '+aid)
        for aid in ledger.get('enabled_existing',[]):
            if aid in installed and aid not in order:
                outside=[key for key,row in installed.items() if key not in order and key!=aid and any(d['addonid']==aid for d in row.get('dependencies',[]))]
                if not outside:rpc('Addons.SetAddonEnabled',{'addonid':aid,'enabled':False})
        # Same filesystem as addons: atomic rename works on CoreELEC mount layouts too.
        stage=Path(tempfile.mkdtemp(prefix='nuvio-removed-',dir=str(root.parent))).resolve()
        moved=stage_removal(root,order,stage)
        try:
            if restore:restore()
        except Exception:xbmc.log('[Nuvio] Could not restore previous seek settings.',xbmc.LOGWARNING)
        if not keep:
            monitor.waitForAbort(1)
            purge_bundle_profiles(xbmcvfs.translatePath('special://profile/addon_data'))
        xbmc.executebuiltin('UpdateLocalAddons')
        for _ in range(30):
            if not set(moved).intersection(inventory()):break
            if monitor.waitForAbort(.2):break
        if set(moved).intersection(inventory()):
            dialog.ok('Nuvio removal','Components were removed. Restart Kodi to refresh its component list. '+('Accounts and settings are kept.' if keep else 'Nuvio account data was removed.'))
            return
        if stage.parent==root.parent and stage.name.startswith('nuvio-removed-'):
            shutil.rmtree(stage)
        dialog.ok('Nuvio removed','Removed %d components. Restart Kodi to finish unloading services. '%len(moved)+('Your accounts, settings and history are kept.' if keep else 'Nuvio account data was removed.'))
        xbmc.executebuiltin('ActivateWindow(home)')
    except Exception:
        if not moved:
            for aid in reversed(order):
                if installed[aid].get('enabled'):
                    try:rpc('Addons.SetAddonEnabled',{'addonid':aid,'enabled':True})
                    except Exception:pass
        raise
    finally:home.clearProperty('nuvio.uninstalling')


if __name__=='__main__':
    import xbmcgui
    try:run()
    except Exception as exc:xbmcgui.Dialog().ok('Nuvio removal',str(exc) if isinstance(exc,ValueError) else 'Removal could not finish. Restart Kodi, then retry from Nuvio Settings.')
