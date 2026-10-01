"""One persistent weather/clock preference for every Nuvio surface."""
import xbmc
import xbmcaddon
import xbmcgui

KEY = 'nuvio_hide_weather_clock'
PROPERTY = 'nuvio.hide_weather_clock'


def hidden():
    addon = xbmcaddon.Addon('plugin.video.nuviohub')
    return addon.getSetting(KEY) == 'true' or xbmc.getCondVisibility('Skin.HasSetting(nuvio.hideweather)')


def sync():
    addon = xbmcaddon.Addon('plugin.video.nuviohub')
    # Preserve a user's old skin setting on upgrade. Do not migrate from an
    # unrelated skin before Nuvio has loaded its own saved preferences.
    if addon.getSetting('nuvio_weather_clock_migrated') != 'true' and xbmc.getSkinDir() == 'skin.nuvio':
        if xbmc.getCondVisibility('Skin.HasSetting(nuvio.hideweather)'):
            addon.setSetting(KEY, 'true')
        addon.setSetting('nuvio_weather_clock_migrated', 'true')
    value = hidden()
    xbmcgui.Window(10000).setProperty(PROPERTY, '1' if value else '')
    return value


def set_hidden(value):
    addon = xbmcaddon.Addon('plugin.video.nuviohub')
    addon.setSetting(KEY, 'true' if value else 'false')
    addon.setSetting('nuvio_weather_clock_migrated', 'true')
    xbmcgui.Window(10000).setProperty(PROPERTY, '1' if value else '')
    xbmc.executebuiltin(('Skin.SetBool' if value else 'Skin.Reset') + '(nuvio.hideweather)', True)
    from . import settings_cache
    settings_cache.invalidate()
