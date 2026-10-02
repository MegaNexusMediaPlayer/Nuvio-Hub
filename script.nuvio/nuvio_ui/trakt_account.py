"""Trakt in HUB Settings > Accounts & tracking (6.0.35). The backend already
scrobbles, imports progress and mirrors the watchlist; this page connects it."""
import xbmcgui
from resources.lib import trakt, settings_cache
from .settings import ADDON
from . import settings_page as page


def _toggle(key):
    ADDON.setSetting(key, 'false' if (ADDON.getSetting(key) or 'true') == 'true' else 'true')


def run():
    def rows():
        linked = trakt.authorized()
        return [page.item('Disconnect' if linked else 'Connect with code', 'Connected' if linked else 'Not connected'),
                page.item('Send what you watch (scrobble)', enabled=trakt.scrobble_enabled()),
                page.item('Import Continue Watching from Trakt', enabled=trakt.sync_enabled()),
                page.item('Watchlist in Library', enabled=(ADDON.getSetting('trakt_sync_watchlist') or 'true') == 'true'),
                page.item('Back')]

    def choose(pick):
        try:
            if pick == 0:
                if trakt.authorized():
                    if xbmcgui.Dialog().yesno('Trakt', 'Disconnect Trakt from MegaNexus?'):
                        trakt.logout()
                else:
                    trakt.device_auth()
            elif pick == 1:
                _toggle('trakt_scrobble')
            elif pick == 2:
                _toggle('trakt_sync_progress')
            elif pick == 3:
                _toggle('trakt_sync_watchlist')
            elif pick == 4:
                return page.DONE
        except Exception as exc:
            xbmcgui.Dialog().ok('Trakt', str(exc) or 'Trakt could not be reached. Check the connection and retry.')
        finally:
            settings_cache.invalidate()
        return None
    return page.show('Trakt', rows, choose)
