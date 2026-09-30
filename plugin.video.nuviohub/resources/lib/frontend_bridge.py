"""Launch the independent UI. The backend never loads a legacy presentation window."""
import xbmc
import xbmcgui


def open_home(settings=False, repair=False):
    from .bundle_installer import ensure_components
    try:
        ensure_components(force=repair)
    except Exception as exc:
        xbmcgui.Dialog().ok('Nuvio installation',str(exc))
        return
    import xbmcaddon
    addon=xbmcaddon.Addon('plugin.video.nuviohub')
    if addon.getSetting('nuvio_skin_applied')!='true':
        from .skin_activation import activate
        activate()
        addon.setSetting('nuvio_skin_applied','true')
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
