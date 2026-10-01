"""Independent Nuvio presentation entry point."""
import os
import sys
import uuid
import xbmc
import xbmcaddon
import xbmcgui

backend = xbmcaddon.Addon('plugin.video.nuviohub').getAddonInfo('path')
for path in (backend, os.path.join(backend, 'resources', 'lib')):
    if path not in sys.path: sys.path.insert(0, path)

home = xbmcgui.Window(10000)
def finish_jobs():
    module=sys.modules.get('nuvio_ui.playback')
    if module:module._JOBS.shutdown();module._BACKGROUND.shutdown();module._CATALOG.shutdown()

def launch():
    token=uuid.uuid4().hex
    home.setProperty('nuvio.frontend.running', token)
    session=None
    try:
        from resources.lib import settings_cache
        from nuvio_ui.system_setup import execute_command
        settings_cache.invalidate()
        from resources.lib.presentation_settings import sync as sync_appearance
        sync_appearance()
        if mode not in ('settings','skinsettings'):
            from nuvio_ui.session import open_session
            session=open_session()
        try:
            from resources.lib.seek_profile import apply
            apply()
        except Exception:xbmc.log("[Nuvio] Could not restore original Kodi seek controls.",xbmc.LOGWARNING)
        if mode == 'iptv':
            from nuvio_ui.iptv import open_iptv
            open_iptv()
        elif mode == 'wizard':
            from nuvio_ui.onboarding import run as setup
            command=setup(force=True)
            if command:execute_command(command)
            from nuvio_ui.home_window import open_home
            if not xbmc.getCondVisibility('Window.IsVisible(yesnodialog)'):open_home()
        elif mode == 'phone':
            # HUB / backend entry: after Save on the phone MegaNexus starts.
            from nuvio_ui.phone_setup import run as phone
            if phone():
                from nuvio_ui.onboarding import _finish
                _finish()
                from nuvio_ui.home_window import open_home
                open_home()
            else:xbmc.executebuiltin('ActivateWindow(Home)')
        elif mode == 'skinsettings':
            from nuvio_ui.settings import appearance
            command=appearance()
            if command:execute_command(command)
        elif mode == 'settings':
            from nuvio_ui.settings import run
            command=run()
            if command:execute_command(command)
            else:xbmc.executebuiltin('ActivateWindow(Home)')
        elif mode == 'open' and len(sys.argv) > 2:
            from resources.lib import cache_store
            from nuvio_ui.details import open_context
            command = open_context(cache_store.get('nuvio_open', sys.argv[2]) or {})
            if isinstance(command,dict) and 'trailer' in command:
                from nuvio_ui.trailers import play_trailer,wait_for_playback
                if play_trailer(command['trailer']):wait_for_playback()
                command=''
            if command=='playing':
                xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')
            elif command: xbmc.executebuiltin(command)
        else:
            from nuvio_ui.onboarding import run as setup
            command=setup()
            if command:execute_command(command)
            from nuvio_ui.home_window import open_home
            if not xbmc.getCondVisibility('Window.IsVisible(yesnodialog)'):open_home()
    except Exception:
        xbmc.log('[Nuvio] Interface failed. See component installation and provider configuration.', xbmc.LOGERROR)
        xbmcgui.Dialog().ok('Nuvio', 'Could not open the interface. Open Nuvio Hub settings to repair the bundled components or check your provider configuration.')
    finally:
        if session:session.close()
        finish_jobs()
        if home.getProperty('nuvio.frontend.running')==token:
            home.clearProperty('nuvio.frontend.running')


mode = sys.argv[1] if len(sys.argv) > 1 else 'home'
if mode=='subtitles':
    from nuvio_ui.subtitles import run
    try:run()
    finally:finish_jobs()
elif home.getProperty('nuvio.frontend.running'):
    # One modal interface at a time, including on skin reload/activation.
    pass
else:
    restarting=False
    try:
        # An installed update waiting for a Kodi restart: ask before the
        # interface opens ("Later" asks again at the next entry).
        from resources.lib import updater
        restarting=updater.prompt_at_entry()
    except Exception:
        xbmc.log('[Nuvio] Restart reminder skipped.',xbmc.LOGDEBUG)
    if not restarting:
        launch()
