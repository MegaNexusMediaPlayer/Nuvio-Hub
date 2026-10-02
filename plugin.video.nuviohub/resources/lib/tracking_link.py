"""Connect Trakt / Simkl from the phone setup page (6.0.35).

``start`` asks the service for a device code and returns the page to open
plus the code; a background thread on the TV waits for the approval and saves
the token. ``status`` is what the phone page shows. No dialogs on the TV.
"""
import threading
import time
from urllib.parse import quote, urlsplit

SERVICES = ('trakt', 'simkl', 'plex')   # plex: 6.0.39 beta, a media server linked the same way
_LOCK = threading.Lock()
_PENDING = {}   # service -> {'code', 'url', 'expires', 'error'}


def connected(service):
    try:
        if service == 'plex':
            from . import plex_client
            return plex_client.is_signed_in()
        if service == 'trakt':
            from . import trakt
            return trakt.authorized()
        from . import simkl
        return bool(simkl.enabled() and simkl.authorized())
    except Exception:
        return False


def status():
    now = time.monotonic()
    result = {}
    with _LOCK:
        for service in SERVICES:
            pending = _PENDING.get(service)
            if pending and pending['expires'] < now:
                pending = None
                _PENDING.pop(service, None)
            result[service] = {'connected': connected(service),
                               'code': pending['code'] if pending else '',
                               'url': pending['url'] if pending else '',
                               'error': pending.get('error', '') if pending else ''}
    return result


def _trakt_code():
    from . import trakt
    trakt.ensure_enabled()
    code = trakt._request('/oauth/device/code', payload={'client_id': trakt.client_id()}, method='POST', auth=False, timeout=10)
    user_code = str((code or {}).get('user_code') or '').strip()
    device_code = str((code or {}).get('device_code') or '').strip()
    if not user_code or not device_code:
        raise ValueError('Trakt did not return a code. Try again.')
    url = str(code.get('verification_url') or 'https://trakt.tv/activate')
    if urlsplit(url).hostname not in ('trakt.tv', 'www.trakt.tv'):
        url = 'https://trakt.tv/activate'

    def poll():
        try:
            token = trakt._request('/oauth/device/token', payload={'code': device_code, 'client_id': trakt.client_id(),
                                                                   'client_secret': trakt.client_secret()},
                                   method='POST', auth=False, timeout=10)
        except Exception:
            return None   # 400 = not approved yet
        if isinstance(token, dict) and token.get('access_token'):
            token['created_at'] = int(time.time())
            trakt.save_token(token)
            return True
        return None
    return user_code, url, int(code.get('interval') or 5), int(code.get('expires_in') or 600), poll


def _simkl_code():
    from . import simkl
    from .settings_cache import cached_addon
    code = simkl._request('/oauth/pin?client_id=' + quote(simkl.client_id(), safe=''), timeout=10)
    user_code = str((code or {}).get('user_code') or '').strip()
    if not user_code:
        raise ValueError('Simkl did not return a code. Try again.')
    url = str(code.get('verification_url') or simkl.PIN_URL_FALLBACK)
    if urlsplit(url).hostname not in ('simkl.com', 'www.simkl.com'):
        url = simkl.PIN_URL_FALLBACK
    path = '/oauth/pin/%s?client_id=%s' % (quote(user_code, safe=''), quote(simkl.client_id(), safe=''))

    def poll():
        try:
            data = simkl._request(path, timeout=10)
        except Exception:
            return None
        if isinstance(data, dict) and data.get('access_token'):
            simkl.save_token({'access_token': data['access_token'], 'created_at': int(time.time())})
            addon = cached_addon()
            addon.setSetting('enable_simkl', 'true')
            addon.setSetting('simkl_mark_watched', 'true')
            simkl.invalidate_cache()
            return True
        return None
    return user_code, url, int(code.get('interval') or 5), int(code.get('expires_in') or 900), poll


def _plex_code():
    """plex.tv/link with the short PIN (the page asks the user to sign in)."""
    from . import plex_client
    from .settings_cache import cached_addon
    pin = plex_client.request_pin()
    code = str(pin.get('code') or '').strip()
    if not code or not pin.get('id'):
        raise ValueError('Plex did not return a code. Try again.')

    def poll():
        try:
            linked = plex_client.poll_pin(pin['id'], code, flavor=pin.get('flavor') or 'v2')
        except Exception:
            return None
        if linked:
            cached_addon().setSetting('nuvio_plex_enabled', 'true')
            return True
        return None
    return code, 'https://plex.tv/link', 3, 900, poll


def start(service, sleep=time.sleep):
    """Begin linking; returns {'url', 'code'} for the phone."""
    if service not in SERVICES:
        raise ValueError('Unknown tracking service.')
    try:
        code, url, interval, expires, poll = {'trakt': _trakt_code, 'simkl': _simkl_code, 'plex': _plex_code}[service]()
    except ValueError:
        raise
    except Exception:
        raise ValueError('%s could not be reached. Check the connection and retry.' % service.title())
    interval = max(3 if service == 'plex' else 5, min(60, interval))
    expires = max(60, min(1800, expires))
    entry = {'code': code, 'url': url, 'expires': time.monotonic() + expires}
    with _LOCK:
        _PENDING[service] = entry

    def wait():
        while time.monotonic() < entry['expires']:
            sleep(interval)
            with _LOCK:
                if _PENDING.get(service) is not entry:
                    return  # a newer attempt replaced this one
            if poll():
                from . import settings_cache
                settings_cache.invalidate()
                with _LOCK:
                    if _PENDING.get(service) is entry:
                        _PENDING.pop(service, None)
                return
    threading.Thread(target=wait, name='MegaNexusLink-' + service, daemon=True).start()
    return {'url': url, 'code': code}


def disconnect(service):
    if service == 'trakt':
        from . import trakt
        trakt.logout()
    elif service == 'simkl':
        from . import simkl
        simkl.logout()
    elif service == 'plex':
        from . import plex_client
        from .settings_cache import cached_addon
        plex_client.sign_out()
        cached_addon().setSetting('nuvio_plex_enabled', 'false')
    else:
        raise ValueError('Unknown tracking service.')
    with _LOCK:
        _PENDING.pop(service, None)
    return {}
