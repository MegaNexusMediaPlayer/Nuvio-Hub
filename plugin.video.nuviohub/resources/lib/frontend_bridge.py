"""Launch the independent UI. The backend never loads a legacy presentation window."""
import xbmc
import xbmcgui


def open_home(settings=False, repair=False):
    """Opening the video add-on (also by mistake, before "Install") does the
    whole first start: install the interface, skin and screensaver, switch to
    the MegaNexus skin, then open MegaNexus (its first start offers setup)."""
    from .bundle_installer import ensure_components, outdated, paths
    busy=None
    try:
        packages,addons_dir=paths()
        if repair or outdated(packages,addons_dir):
            busy=xbmcgui.DialogProgressBG()
            busy.create('MegaNexus','Installing the interface, skin and screensaver...')
        ensure_components(force=repair)
    except Exception as exc:
        if busy:busy.close();busy=None
        xbmcgui.Dialog().ok('MegaNexus installation',str(exc))
        return
    finally:
        if busy:busy.close()
    import xbmcaddon
    addon=xbmcaddon.Addon('plugin.video.nuviohub')
    from . import skin_activation
    # 6.0.33: checked at every entry, not only the first one - Kodi can lose the
    # skin (killed before saving, or an update it had not finished loading).
    # "No" in Kodi's keep-skin question is respected for this session.
    if skin_activation.wanted(addon):
        try:status=skin_activation.switch(addon)
        except Exception as exc:
            xbmc.log('[MegaNexus] Skin switch failed: %s'%exc,xbmc.LOGWARNING);status='failed'
        if status=='failed':skin_activation.report_failure()
        if xbmc.getCondVisibility('Window.IsVisible(yesnodialog)'):return
    xbmc.executebuiltin('RunScript(script.nuvio%s)'%(',settings' if settings else ''))


def open_context(context):
    from . import cache_store
    allowed=('media_type','canonical_id','title','video_id','season','episode','resume_seconds','resume_percent')
    context={key:context[key] for key in allowed if context.get(key) not in (None,'')}
    key=cache_store.put('nuvio_open',context)
    xbmc.executebuiltin('RunScript(script.nuvio,open,%s)'%key)


def legacy_streams(**context):
    return open_context(context)
