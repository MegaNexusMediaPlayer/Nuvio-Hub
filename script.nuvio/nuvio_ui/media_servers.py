"""HUB Settings > Accounts > Plex (beta) / Jellyfin / Emby (beta), 6.0.39.

Nothing runs before the user connects a server; connecting switches "Use in
MegaNexus" on, Home rows stay off until the user turns them on."""
import xbmc
import xbmcgui
from resources.lib import media_servers as servers, settings_cache
from . import settings_page as page

ADDON = settings_cache.cached_addon()
QUICK_CONNECT_SECONDS = 300


def _on(key, default='false'):
    return (ADDON.getSetting(key) or default) == 'true'


def _toggle(key, default='false'):
    ADDON.setSetting(key, 'false' if _on(key, default) else 'true')
    servers.forget()
    settings_cache.invalidate()


def _set(key, value):
    ADDON.setSetting(key, 'true' if value else 'false')
    servers.forget()
    settings_cache.invalidate()


def _rows(kind):
    return [page.item('%s account' % servers.label(kind), servers.status(kind)),
            page.item('Use %s in MegaNexus' % servers.label(kind), enabled=_on(servers.ENABLED[kind])),
            page.item('Your server first when playing', enabled=_on(servers.SOURCES[kind], 'true')),
            page.item('Home rows · Continue watching and Recently added', enabled=_on(servers.HOME[kind]))]


def _choose_common(kind, pick):
    if pick == 1:
        _toggle(servers.ENABLED[kind])
    elif pick == 2:
        _toggle(servers.SOURCES[kind], 'true')
    elif pick == 3:
        _toggle(servers.HOME[kind])


# ---------------------------------------------------------------------- Plex --

def _plex_connect():
    from resources.lib import plugin
    plugin.plex_login()   # QR + plex.tv/link code (the proven sign-in)
    if servers.signed_in(servers.PLEX):
        _set(servers.ENABLED[servers.PLEX], True)


def _plex_servers():
    from resources.lib import plex_client
    try:
        found = plex_client.servers(force=True)
    except Exception as exc:
        xbmcgui.Dialog().ok('Plex', 'Plex did not answer: %s' % exc)
        return
    lines = ['%s · %s' % (s.get('name') or 'Server', 'home network' if any(c.get('local') for c in s.get('connections') or [])
                          else 'remote: needs Plex Pass or Remote Watch Pass') for s in found]
    xbmcgui.Dialog().textviewer('Plex servers', '\n'.join(lines) or 'No servers on this Plex account.')


def plex():
    kind = servers.PLEX

    def rows():
        return _rows(kind) + [page.item('Servers · refresh and show'), page.item('Back')]

    def choose(pick):
        if pick == 0:
            if servers.signed_in(kind):
                if xbmcgui.Dialog().yesno('Plex', 'Disconnect the Plex account from MegaNexus?'):
                    from resources.lib import plex_client
                    plex_client.sign_out()
                    _set(servers.ENABLED[kind], False)
            else:
                _plex_connect()
        elif pick in (1, 2, 3):
            _choose_common(kind, pick)
        elif pick == 4:
            _plex_servers()
        elif pick == 5:
            return page.DONE
        return None
    return page.show('Plex (beta)', rows, choose)


# ------------------------------------------------------------ Jellyfin / Emby --

def _quick_connect(url):
    from resources.lib import emby_client
    state = emby_client.quick_connect_start(url)
    progress = xbmcgui.DialogProgress()
    progress.create('Jellyfin Quick Connect',
                    'In another Jellyfin app signed in to this server, open Settings > Quick Connect and enter:[CR][CR]'
                    '[B]%s[/B]' % state['code'])
    monitor = xbmc.Monitor()
    try:
        for tick in range(QUICK_CONNECT_SECONDS // 3):
            if progress.iscanceled():
                return None
            progress.update(int(tick * 300 / QUICK_CONNECT_SECONDS))
            auth = emby_client.quick_connect_poll(state)
            if auth:
                return auth
            if monitor.waitForAbort(3):
                return None
    finally:
        progress.close()
    xbmcgui.Dialog().ok('Jellyfin', 'The code expired. Start Quick Connect again.')
    return None


def _jellyfin_connect():
    from resources.lib import emby_client
    dialog = xbmcgui.Dialog()
    url = dialog.input('Server address (example: http://192.168.1.10:8096)').strip()
    if not url:
        return
    try:
        found = emby_client.detect(url)
        auth = None
        if found['flavor'] == emby_client.JELLYFIN:
            pick = dialog.select('Sign in to %s' % found['name'],
                                 ['Quick Connect · approve a code in another Jellyfin app', 'Username and password'])
            if pick < 0:
                return
            if pick == 0:
                auth = _quick_connect(found['url'])
                if auth is None:
                    return
        if auth is None:
            user = dialog.input('Username').strip()
            if not user:
                return
            password = dialog.input('Password', option=xbmcgui.ALPHANUM_HIDE_INPUT)
            auth = emby_client.sign_in(found['url'], user, password or '')
    except Exception as exc:
        dialog.ok('Jellyfin / Emby', str(exc) or 'Sign-in failed.')
        return
    _set(servers.ENABLED[servers.JELLYFIN], True)
    dialog.notification('MegaNexus', 'Connected to %s' % (auth.get('server_name') or 'the server'), time=3000)


def jellyfin():
    kind = servers.JELLYFIN

    def rows():
        return _rows(kind) + [page.item('Back')]

    def choose(pick):
        if pick == 0:
            if servers.signed_in(kind):
                if xbmcgui.Dialog().yesno(servers.label(kind), 'Disconnect this server from MegaNexus?'):
                    from resources.lib import emby_client
                    emby_client.sign_out()
                    _set(servers.ENABLED[kind], False)
            else:
                _jellyfin_connect()
        elif pick in (1, 2, 3):
            _choose_common(kind, pick)
        elif pick == 4:
            return page.DONE
        return None
    return page.show('Jellyfin / Emby (beta)', rows, choose)
