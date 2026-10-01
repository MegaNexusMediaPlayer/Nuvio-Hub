# -*- coding: utf-8 -*-
"""Small, self-contained Plex client used by Nuvio Hub's native Plex pages.

This module deliberately contains no UI and no Kodi directory code.  It uses
the public Plex PIN/resource/library endpoints and returns plain dictionaries,
which keeps it easy to test and makes the plugin routes short.  Credentials
are stored only in Kodi's addon settings and are never put in log messages.
"""
from __future__ import absolute_import

import json
import re
import platform as _platform_mod
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import ssl
import os

try:
    import xbmcvfs
except Exception:
    xbmcvfs = None

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui

from . import plex_state
# --- nuviohub-403-patch ---
try:
    from .i18n import tr as tr
except Exception:
    from resources.lib.i18n import tr as tr



def _addon():
    """A FRESH Addon handle per access.

    v3.9.186: the module-level singleton was built once per warm Python
    interpreter (reuselanguageinvoker=true), so the interpreter rendering the
    home page could hold a settings snapshot from BEFORE sign-in and keep
    reading an empty token — linking "worked" yet no section, no search results
    and no sources ever appeared.
    """
    return xbmcaddon.Addon('plugin.video.nuviohub')

PLEX_BASE = 'https://plex.tv'
WINDOW_ID = 10000
SERVER_CACHE_SECONDS = 24 * 60 * 60
LIBRARY_CACHE_SECONDS = 6 * 60 * 60
PAGE_SIZE = 80
_LIBRARIES_MEM = {}
_PIN_SHAPE = {}          # pin_id -> the endpoint shape that actually answers
_PIN_TIMEOUT = 8.0       # plex.tv PIN calls must never block the UI for 20s


_PERSIST_NAMES = {
    'plex_auth_json': 'plex_account.json',
    'plex_servers_cache_json': 'plex_servers.json',
    'plex_client_identifier': 'plex_client_id.txt',
}


def _profile_dir():
    """A durable addon-data directory shared by every Kodi interpreter."""
    try:
        raw = 'special://profile/addon_data/plugin.video.nuviohub/'
        path = xbmcvfs.translatePath(raw) if xbmcvfs is not None else raw
        if path and not path.startswith('special://'):
            os.makedirs(path, exist_ok=True)
            return path
    except Exception:
        pass
    return ''


def _persistent_path(setting_name):
    name = _PERSIST_NAMES.get(setting_name)
    base = _profile_dir()
    return os.path.join(base, name) if base and name else ''


def _read_persistent(setting_name):
    path = _persistent_path(setting_name)
    if not path:
        return ''
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read().strip()
    except Exception:
        return ''


def _write_persistent(setting_name, value):
    path = _persistent_path(setting_name)
    if not path:
        return False
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as handle:
            handle.write(str(value or ''))
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
        return True
    except Exception as exc:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        xbmc.log('[NuvioHub] Plex persistent write failed: %s' % exc, xbmc.LOGWARNING)
        return False


def _remove_persistent(setting_name):
    path = _persistent_path(setting_name)
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


class PlexError(Exception):
    """Expected Plex/network error safe to show as a short notification."""


def _setting(name, value=None):
    if value is None:
        try:
            return _addon().getSetting(name) or ''
        except Exception:
            return ''
    try:
        _addon().setSetting(name, str(value))
    except Exception:
        pass
    return str(value)


def client_identifier():
    """Return a stable, per-install Plex device id (required for PIN auth).

    Kodi settings can briefly look empty in another warm interpreter. Keep an
    atomic addon-data backup so a transient settings read never creates a new
    Plex device and makes the user link again.
    """
    value = (_setting('plex_client_identifier') or '').strip()
    if not value:
        value = _read_persistent('plex_client_identifier').strip()
        if value:
            _setting('plex_client_identifier', value)
    if not value:
        value = uuid.uuid4().hex
        _setting('plex_client_identifier', value)
        _write_persistent('plex_client_identifier', value)
    elif not _read_persistent('plex_client_identifier'):
        _write_persistent('plex_client_identifier', value)
    return value


def _platform_version():
    try:
        return _platform_mod.uname()[2] or '0'
    except Exception:
        return '0'


def _headers(token='', accept='application/xml'):
    try:
        addon_version = _addon().getAddonInfo('version') or '3.9.212'
    except Exception:
        addon_version = '3.9.212'
    headers = {
        'Accept': accept,
        'X-Plex-Product': 'Nuvio Hub',
        'X-Plex-Version': addon_version,
        'X-Plex-Client-Identifier': client_identifier(),
        'X-Plex-Platform': 'Kodi',
        'X-Plex-Client-Platform': 'Kodi',
        'X-Plex-Platform-Version': _platform_version(),
        'X-Plex-Language': 'en',
        'X-Plex-Device': 'Kodi',
        'X-Plex-Device-Name': 'Kodi',
        'X-Plex-Provides': 'player,controller',
    }
    if token:
        headers['X-Plex-Token'] = str(token)
    return headers


def _timeout():
    try:
        return max(5, int(_addon().getSetting('timeout') or '20'))
    except Exception:
        return 20


def _request(url, method='GET', token='', data=None, headers=None, timeout=None):
    merged = _headers(token)
    merged.update(headers or {})
    if isinstance(data, str):
        data = data.encode('utf-8')
    req = Request(url, data=data, headers=merged, method=method)
    try:
        with urlopen(req, timeout=(timeout or _timeout())) as response:
            return response.read()
    except HTTPError as exc:
        # Status only — never the URL: it can carry the Plex token.
        raise PlexError('Plex HTTP %s' % exc.code)
    except Exception as exc:
        # urllib wraps certificate errors in URLError(reason=...) on real
        # Kodi/Python builds.  The old code only caught ssl.SSLError directly,
        # which made the unit test pass while every *.plex.direct request in
        # Kodi still failed before library discovery.  Unwrap the exception
        # chain and retry ONLY certificate-validation failures.
        if not _is_certificate_error(exc):
            raise PlexError(tr('Could not reach the Plex server (%s)') % exc)
        # v3.9.210 — THE reason Plex returned nothing while Emby worked.
        #
        # Plex serves its LAN address over HTTPS on a *.plex.direct hostname
        # whose certificate chains to Let's Encrypt. Kodi/CoreELEC ships a CA
        # store that frequently cannot validate that chain, so EVERY request to
        # the server died here — no libraries, no search results, no sources —
        # while Emby kept working because it is reached over plain HTTP.
        # Plex for Kodi (PlexMod) solves this by bundling its own CA certs.
        #
        # We already authenticate the server with a token we obtained from
        # plex.tv, and the address came from plex.tv's own resource list, so
        # retrying that exact URL without chain validation adds no practical
        # exposure — and it is the difference between Plex working and not.
        xbmc.log('[NuvioHub] Plex TLS validation failed (%s) — retrying '
                 'without chain validation' % exc, xbmc.LOGWARNING)
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urlopen(req, timeout=(timeout or _timeout()), context=ctx) as response:
                return response.read()
        except Exception as retry_exc:
            raise PlexError(tr('Could not reach the Plex server (%s)') % retry_exc)


def _is_certificate_error(exc):
    """True for direct or urllib-wrapped certificate validation failures."""
    current = exc
    visited = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, (ssl.SSLCertVerificationError, ssl.CertificateError)):
            return True
        message = str(current or '').upper()
        if ('CERTIFICATE_VERIFY_FAILED' in message or
                'CERTIFICATE VERIFY FAILED' in message or
                'CERTIFICATE VALIDATION FAILED' in message):
            return True
        # urllib.error.URLError stores the actual TLS exception in .reason.
        next_error = getattr(current, 'reason', None)
        if next_error is current:
            break
        current = next_error
    return False


def _xml(data):
    try:
        return ET.fromstring(data or b'')
    except Exception as exc:
        raise PlexError(tr('Invalid Plex response (%s)') % exc)


def _json(data):
    try:
        value = json.loads((data or b'').decode('utf-8', 'ignore'))
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        raise PlexError(tr('Invalid Plex response (%s)') % exc)


def _node_value(node, name, default=''):
    if node is None:
        return default
    return node.attrib.get(name, node.findtext(name, default)) or default


def _auth_prop(name):
    return 'nuviohub.plex.auth' if name.endswith('auth_json') else ''


def _parse_json_setting(name, default):
    raw = ''
    try:
        raw = _setting(name) or ''
    except Exception:
        raw = ''
    if not raw and _auth_prop(name):
        # Shared by every warm interpreter: a cached Addon handle can miss a
        # sign-in written by another invocation, the window property cannot.
        try:
            raw = xbmcgui.Window(WINDOW_ID).getProperty(_auth_prop(name)) or ''
        except Exception:
            raw = ''
    if not raw:
        # Durable fallback: settings.xml can be stale/temporarily unreadable
        # across reuselanguageinvoker processes. Never interpret that as logout.
        raw = _read_persistent(name)
        if raw:
            try:
                _setting(name, raw)
            except Exception:
                pass
    try:
        value = json.loads(raw or '')
        return value if isinstance(value, type(default)) else default
    except Exception:
        return default


def _save_json_setting(name, value):
    try:
        blob = json.dumps(value, separators=(',', ':'), ensure_ascii=False)
        _setting(name, blob)
        _write_persistent(name, blob)
        if _auth_prop(name):
            xbmcgui.Window(WINDOW_ID).setProperty(_auth_prop(name), blob)
    except Exception:
        pass


def account():
    value = _parse_json_setting('plex_auth_json', {})
    if not value.get('token'):
        value = plex_state.load_account()
        if value.get('token'):
            _save_json_setting('plex_auth_json', value)
    elif not plex_state.load_account().get('token'):
        plex_state.save_account(value)
    return value if value.get('token') else {}


def is_signed_in():
    # Native search can continue from the durable server cache even if a warm
    # Kodi interpreter temporarily reads an empty account setting.
    return bool(account().get('token') or plex_state.has_usable_cached_servers())


def sign_out():
    _LIBRARIES_MEM.clear()
    _setting('plex_auth_json', '')
    _remove_persistent('plex_auth_json')
    try:
        xbmcgui.Window(WINDOW_ID).clearProperty('nuviohub.plex.auth')
    except Exception:
        pass
    _setting('plex_servers_cache_json', '')
    _remove_persistent('plex_servers_cache_json')
    plex_state.clear_account()


def request_pin(strong=False):
    """Create a plex.tv/link PIN.

    v3.9.183: the CURRENT v2 JSON endpoint is primary again. plex.tv has
    retired the legacy /pins.xml route on many deployments — it answers 404,
    which is exactly what the device reported. Legacy stays as a fallback.

    v4.6.8: `strong=True` requests a STRONG pin (plexapi MyPlexPinLogin
    _getCode: params={'strong': True}) — the ONLY flavor app.plex.tv/auth
    accepts for the QR deep link. The default weak 4-char pin remains the
    typed plex.tv/link flow, exactly as in the early versions. Strong pins
    are v2-only: no legacy fallback, the caller degrades to weak-only.
    """
    strong_flag = 'true' if strong else 'false'
    try:
        value = _json(_request(PLEX_BASE + '/api/v2/pins', method='POST',
                               data=urlencode({'strong': strong_flag}),
                               timeout=_PIN_TIMEOUT, headers={
                                   'Accept': 'application/json',
                                   'Content-Type': 'application/x-www-form-urlencoded',
                               }))
        pin_id, code = value.get('id'), value.get('code')
        if pin_id and code:
            return {'id': str(pin_id), 'code': str(code).upper() if not strong else str(code),
                    'flavor': 'v2', 'strong': bool(strong),
                    'link_url': 'https://plex.tv/link/?' + urlencode({'pin': str(code).upper()})}
    except PlexError as exc:
        xbmc.log('[NuvioHub] Plex v2 PIN failed (%s)%s' % (
            exc, '' if strong else ' - trying legacy'), xbmc.LOGWARNING)
    if strong:
        raise PlexError('strong PIN unavailable')

    root = _xml(_request(PLEX_BASE + '/pins.xml', method='POST', timeout=_PIN_TIMEOUT))
    code = (root.findtext('code') or '').strip()
    pin_id = (root.findtext('id') or '').strip()
    if not (code and pin_id):
        raise PlexError('Plex did not send a link code')
    return {'id': pin_id, 'code': code.upper(), 'flavor': 'legacy', 'strong': False,
            'link_url': 'https://plex.tv/link/?' + urlencode({'pin': code.upper()})}

def auth_link_url(code):
    """v4.6.7: the DIRECT auth deep link the QR should encode.

    Contract verified against python-plexapi (pkkid/python-plexapi,
    plexapi/myplex.py → MyPlexPinLogin.oauthUrl): app.plex.tv/auth/#!? with
    clientID + code + the context[device][*] set, all taken from the SAME
    header values used to create the PIN — the clientID must match or the
    authorised token never lands on our pin. The old QR encoded
    plex.tv/link/?pin=…, and that page ignores the query string entirely,
    so scanning only ever opened the generic type-a-code page.
    """
    headers = _headers()
    params = [
        ('clientID', headers['X-Plex-Client-Identifier']),
        ('context[device][product]', headers['X-Plex-Product']),
        ('context[device][version]', headers['X-Plex-Version']),
        ('context[device][platform]', headers['X-Plex-Platform']),
        ('context[device][platformVersion]', headers['X-Plex-Platform-Version']),
        ('context[device][device]', headers['X-Plex-Device']),
        ('context[device][deviceName]', headers['X-Plex-Device-Name']),
        ('code', str(code or '').strip()),
    ]
    return 'https://app.plex.tv/auth/#!?' + urlencode(params)


def _account_for_token(token):
    """Resolve the account, exchanging the PIN's temp token for the durable
    ``authentication-token`` exactly the way DPlex does via /users/account."""
    try:
        root = _xml(_request(PLEX_BASE + '/users/account', token=token))
        user = root if root.tag.lower() == 'user' else (root.find('.//user') or root)
        durable = (root.findtext('.//authentication-token') or
                   user.attrib.get('authenticationToken') or '').strip()
        username = (user.attrib.get('username') or user.attrib.get('title') or
                    _node_value(user, 'username') or _node_value(user, 'title'))
        if durable or username:
            return {
                'token': str(durable or token),
                'username': username or '',
                'user_id': user.attrib.get('id') or _node_value(user, 'id'),
                'signed_in_at': int(time.time()),
            }
    except PlexError:
        pass
    user = _json(_request(PLEX_BASE + '/api/v2/user', token=token,
                          headers={'Accept': 'application/json'}))
    return {
        'token': str(token),
        'username': user.get('username') or user.get('title') or user.get('email') or '',
        'user_id': str(user.get('id') or ''),
        'signed_in_at': int(time.time()),
    }


def poll_pin(pin_id, code='', flavor='v2'):
    """Return the authenticated account, or None while waiting.

    v3.9.183: BOTH pin shapes are tried. A 404 from one route (plex.tv has
    retired the legacy pins endpoint in places) now falls through to the other
    instead of aborting the sign-in.
    """
    def _v2():
        url = '%s/api/v2/pins/%s' % (PLEX_BASE, pin_id)
        if code:
            url += '?' + urlencode({'code': str(code)})
        value = _json(_request(url, method='GET', timeout=_PIN_TIMEOUT,
                               headers={'Accept': 'application/json'}))
        return value.get('authToken') or value.get('auth_token') or ''

    def _legacy():
        root = _xml(_request('%s/pins/%s.xml' % (PLEX_BASE, pin_id), method='GET',
                             timeout=_PIN_TIMEOUT))
        return (root.findtext('auth_token') or
                _node_value(root, 'auth_token') or
                _node_value(root, 'authToken') or '').strip()

    shapes = {'v2': _v2, 'legacy': _legacy}
    preferred = _PIN_SHAPE.get(str(pin_id)) or (
        'legacy' if str(flavor or 'v2') == 'legacy' else 'v2')
    order = [preferred] + [k for k in ('v2', 'legacy') if k != preferred]
    token, last = '', None
    for name in order:
        try:
            token = shapes[name]()
            # v3.9.185: pin the shape that answered. Polling every 2s used to
            # re-try the DEAD route on every cycle (two blocking round-trips
            # per tick) — that is the lag felt while the QR screen was open.
            _PIN_SHAPE[str(pin_id)] = name
            last = None
            break
        except PlexError as exc:
            last = exc
    if not token:
        if last is not None:
            raise last
        return None
    _PIN_SHAPE.pop(str(pin_id), None)
    value = _account_for_token(token)
    _save_json_setting('plex_auth_json', value)
    plex_state.save_account(value)
    _setting('plex_servers_cache_json', '')
    _remove_persistent('plex_servers_cache_json')
    return value

def _normalise_uri(value):
    value = str(value or '').strip().rstrip('/')
    if not value.startswith(('http://', 'https://')):
        return ''
    return value


def _cache_servers(servers):
    # A resource refresh can change server ownership/connections/libraries.
    _LIBRARIES_MEM.clear()
    payload = {'fetched_at': int(time.time()), 'servers': servers or []}
    _save_json_setting('plex_servers_cache_json', payload)
    plex_state.save_server_cache(servers or [], payload['fetched_at'])


def servers(force=False):
    """Discover every server accessible to the authenticated Plex account."""
    auth = account()
    token = auth.get('token')
    cached = _parse_json_setting('plex_servers_cache_json', {})
    if not (cached.get('servers') or []):
        cached = plex_state.load_server_cache()
        if cached.get('servers'):
            _save_json_setting('plex_servers_cache_json', cached)
    stale_servers = cached.get('servers') or []
    if not token:
        # Server access tokens are sufficient for library search/playback. Do
        # not hide all Plex sources just because the account blob was briefly
        # unreadable in another reuselanguageinvoker process.
        if stale_servers:
            xbmc.log('[NuvioHub] Plex account token unavailable; using %d cached server(s)'
                     % len(stale_servers), xbmc.LOGWARNING)
            return stale_servers
        return []
    if (not force and stale_servers and
            int(cached.get('fetched_at') or 0) + SERVER_CACHE_SECONDS > time.time()):
        return stale_servers

    try:
        root = _xml(_request(PLEX_BASE + '/api/resources?includeHttps=1&includeRelay=1',
                             token=token, timeout=min(8, _timeout())))
    except PlexError as exc:
        # A temporary plex.tv outage must never look like account deletion.
        # Use the last known resources and let the user refresh later.
        if stale_servers:
            xbmc.log('[NuvioHub] Plex resource refresh failed; using stale cache (%s)' % exc,
                     xbmc.LOGWARNING)
            return stale_servers
        raise
    found = []
    for device in root.findall('.//Device'):
        provides = (device.attrib.get('provides') or '').lower()
        if 'server' not in provides:
            continue
        server_token = device.attrib.get('accessToken') or token
        https_required = str(device.attrib.get('httpsRequired') or '') == '1'
        connections = []
        connection_uris = set()
        for connection in device.findall('./Connection'):
            uri = _normalise_uri(connection.attrib.get('uri'))
            if not uri:
                continue
            local = str(connection.attrib.get('local') or '') == '1'
            relay = str(connection.attrib.get('relay') or '') == '1'
            address = str(connection.attrib.get('address') or '').strip()
            port = str(connection.attrib.get('port') or '').strip()
            protocol = str(connection.attrib.get('protocol') or urlsplit(uri).scheme or '').lower()
            connections.append({
                'uri': uri,
                'local': local,
                'relay': relay,
                'protocol': protocol,
                'address': address,
                'port': port,
            })
            connection_uris.add(uri)
            # PlexMod's important LAN fallback: DNS-rebinding protection can
            # make the generated *.plex.direct host unresolvable even though
            # the server IP is reachable.  When the server does not require
            # HTTPS, retain a direct HTTP candidate after the official secure
            # URI.  It is a fallback only; the normal secure URI stays first.
            if (local and not relay and not https_required and address and port and
                    protocol == 'https'):
                if ':' in address and not address.startswith('['):
                    host = '[%s]' % address
                else:
                    host = address
                lan_uri = _normalise_uri('http://%s:%s' % (host, port))
                if lan_uri and lan_uri not in connection_uris:
                    connections.append({
                        'uri': lan_uri, 'local': True, 'relay': False,
                        'protocol': 'http', 'address': address, 'port': port,
                        'fallback': True,
                    })
                    connection_uris.add(lan_uri)
        # A deterministic preference keeps a local server fast while retaining
        # remote/relay fallbacks for users outside their home network.
        connections.sort(key=lambda c: (not c['local'], c['relay'], not c['uri'].startswith('https://')))
        if not connections:
            continue
        identity = device.attrib.get('clientIdentifier') or device.attrib.get('machineIdentifier') or device.attrib.get('name')
        if not identity:
            continue
        found.append({
            'id': str(identity),
            'name': device.attrib.get('name') or 'Plex Server',
            'product': device.attrib.get('product') or 'Plex Media Server',
            'platform': device.attrib.get('platform') or '',
            'owned': str(device.attrib.get('owned') or '') == '1',
            'https_required': https_required,
            'token': str(server_token),
            'connections': connections,
        })
    if found:
        _cache_servers(found)
        return found
    if stale_servers:
        xbmc.log('[NuvioHub] Plex returned zero resources; keeping stale server cache',
                 xbmc.LOGWARNING)
        return stale_servers
    _cache_servers([])
    return []


def server_by_id(server_id, force=False):
    for server in servers(force=force):
        if str(server.get('id')) == str(server_id):
            return server
    return None


_VERIFIED_URI_MEM = {}
_URI_TTL = 10 * 60


def _probe_server_uri(uri, token='', timeout=3):
    """True when the tiny /identity endpoint answers for this account."""
    try:
        _request(uri + '/identity', token=token, timeout=timeout)
        return True
    except PlexError:
        return False


def _verified_uri(server, force=False):
    """The first REACHABLE connection, verified once and remembered.

    v3.9.171 speed fix: browsing used to try every connection serially with
    the global 20s timeout — a dead LAN address meant every section open hung
    for 20 seconds.  DPlex/PM4K verify the address once and reuse it; we do
    the same: all candidates probed IN PARALLEL (3s each), winner picked by
    the existing local-first preference, cached in memory and mirrored in a
    Window property so every warm interpreter shares one probe per 10 min.
    """
    sid = str(server.get('id') or '')
    now = time.time()
    if not force and sid:
        hit = _VERIFIED_URI_MEM.get(sid)
        if hit and now < hit[1]:
            return hit[0]
        try:
            raw = xbmcgui.Window(10000).getProperty('nuviohub.plex.uri.%s' % sid) or ''
            if raw:
                uri, exp = raw.rsplit('|', 1)
                if now < float(exp):
                    _VERIFIED_URI_MEM[sid] = (uri, float(exp))
                    return uri
        except Exception:
            pass
    conns = []
    for c in server.get('connections') or []:
        uri = _normalise_uri(c.get('uri'))
        if uri:
            conns.append(uri)
    if not conns:
        return ''
    if len(conns) == 1:
        best = conns[0]
    else:
        reachable = {}
        with ThreadPoolExecutor(max_workers=min(4, len(conns))) as pool:
            token = server.get('token') or account().get('token') or ''
            futures = {pool.submit(_probe_server_uri, uri, token): uri for uri in conns}
            for future in as_completed(futures):
                try:
                    reachable[futures[future]] = bool(future.result())
                except Exception:
                    reachable[futures[future]] = False
        best = ''
        for uri in conns:  # connections arrive preference-sorted (local first)
            if reachable.get(uri):
                best = uri
                break
        if not best:
            best = conns[0]
    expires = now + _URI_TTL
    if sid:
        _VERIFIED_URI_MEM[sid] = (best, expires)
        try:
            xbmcgui.Window(10000).setProperty('nuviohub.plex.uri.%s' % sid,
                                              '%s|%s' % (best, expires))
        except Exception:
            pass
    return best


def _urls_for_server(server, path, params=None):
    path = '/' + str(path or '').lstrip('/')
    pairs = [(str(k), str(v)) for k, v in (params or {}).items() if v not in (None, '')]
    token = server.get('token') or account().get('token')
    if token:
        pairs.append(('X-Plex-Token', str(token)))
    query = urlencode(pairs)
    for connection in server.get('connections') or []:
        base = _normalise_uri(connection.get('uri'))
        if base:
            yield base + path + (('?' + query) if query else ''), base


def _server_xml(server, path, params=None):
    def _make_url(base):
        clean = '/' + str(path or '').lstrip('/')
        pairs = [(str(k), str(v)) for k, v in (params or {}).items() if v not in (None, '')]
        token = server.get('token') or account().get('token')
        if token:
            # The token is on the URL because direct requests can pass through
            # a relay. It is not logged by _request.
            pairs.append(('X-Plex-Token', str(token)))
        query = urlencode(pairs)
        return base + clean + (('?' + query) if query else '')

    browse_timeout = min(8, _timeout())
    base = _verified_uri(server)
    if base:
        try:
            return _xml(_request(_make_url(base), timeout=browse_timeout)), base
        except PlexError:
            # Network changed (left home Wi-Fi, VPN…): re-verify once, retry.
            fresh = _verified_uri(server, force=True)
            if fresh and fresh != base:
                try:
                    return _xml(_request(_make_url(fresh), timeout=browse_timeout)), fresh
                except PlexError:
                    pass
    last_error = None
    for url, fallback_base in _urls_for_server(server, path, params):
        try:
            return _xml(_request(url, timeout=browse_timeout)), fallback_base
        except PlexError as exc:
            last_error = exc
    raise last_error or PlexError('No valid connection to the Plex server')


def _guid_ids(node):
    values = {'imdb_id': '', 'tmdb_id': '', 'tvdb_id': ''}
    guid_values = [node.attrib.get('guid') or '']
    guid_values.extend(x.attrib.get('id') or '' for x in node.findall('./Guid'))
    for guid in guid_values:
        value = str(guid or '')
        lower = value.lower()
        for provider, key in (
                ('com.plexapp.agents.themoviedb://', 'tmdb_id'),
                ('com.plexapp.agents.thetvdb://', 'tvdb_id'),
                ('com.plexapp.agents.imdb://', 'imdb_id'),
                ('themoviedb://', 'tmdb_id'), ('thetvdb://', 'tvdb_id'),
                ('imdb://', 'imdb_id'), ('tmdb://', 'tmdb_id'), ('tvdb://', 'tvdb_id')):
            pos = lower.find(provider)
            if pos >= 0:
                ident = value[pos + len(provider):].split('?')[0].split('/')[0]
                if key == 'tmdb_id' and ident.lower().startswith('tv-'):
                    ident = ident[3:]
                if ident:
                    values[key] = ident
                break
    return values


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        return int(float(value or 0))
    except Exception:
        return default


def _first_media_part(node):
    media = node.find('./Media')
    part = media.find('./Part') if media is not None else None
    return part.attrib.get('key') if part is not None else ''


_VCODEC_MAP = {'hevc': 'HEVC', 'h264': 'H.264', 'h265': 'H.265', 'av1': 'AV1',
               'mpeg4': 'MPEG4', 'vc1': 'VC-1', 'mpeg2video': 'MPEG2'}
_ACODEC_MAP = {'truehd': 'TrueHD', 'dca': 'DTS', 'dts': 'DTS', 'dtshd': 'DTS-HD',
               'eac3': 'EAC3', 'ac3': 'AC3', 'aac': 'AAC', 'mp3': 'MP3',
               'flac': 'FLAC', 'opus': 'Opus', 'pcm': 'PCM'}
_CH_MAP = {1: '1.0', 2: '2.0', 6: '5.1', 8: '7.1'}


def _resolution_label(res):
    res = str(res or '').strip()
    if not res:
        return ''
    try:
        r = int(res)
        return '4K' if r > 1088 else ('1080p' if r >= 1080 else ('720p' if r >= 720 else 'SD'))
    except ValueError:
        return res.upper()


def _size_label(nbytes):
    try:
        n = int(nbytes or 0)
    except (TypeError, ValueError):
        return ''
    if n <= 0:
        return ''
    gb = n / (1024.0 ** 3)
    if gb >= 1:
        return '%.1f GB' % gb
    return '%.0f MB' % (n / (1024.0 ** 2))


def _hdr_from_part(part):
    """DPlex-style HDR detection from the video Stream displayTitle."""
    if part is None:
        return ''
    for stream in part.findall('.//Stream'):
        if stream.attrib.get('streamType') != '1':
            continue
        dt = (stream.attrib.get('displayTitle') or '').upper()
        if 'DOLBY VISION' in dt or 'DOVI' in dt or ' DV' in dt or dt.startswith('DV '):
            return 'Dolby Vision'
        if 'HDR' in dt:
            return 'HDR'
    return ''


def _audio_label(media):
    codec = (media.attrib.get('audioCodec') or '').lower()
    if not codec:
        return ''
    label = _ACODEC_MAP.get(codec, codec.upper())
    ch = media.attrib.get('audioChannels') or ''
    if ch:
        try:
            label += ' %s' % _CH_MAP.get(int(ch), '%sch' % ch)
        except (TypeError, ValueError):
            pass
    return label


_BITMAP_SUBTITLE_CODECS = {
    'pgs', 'hdmv_pgs_subtitle', 'hdmv-pgs-subtitle', 'vobsub',
    'dvd_subtitle', 'dvd-subtitle', 'dvdsub', 'dvb_subtitle',
    'dvb-subtitle', 'dvbsub', 'xsub',
}


def _subtitle_ext(codec, fmt=''):
    value = str(codec or fmt or '').lower()
    return {
        'subrip': 'srt', 'srt': 'srt', 'ass': 'ass', 'ssa': 'ssa',
        'webvtt': 'vtt', 'vtt': 'vtt', 'mov_text': 'srt',
    }.get(value, value or 'srt')


def _tokenized_plex_url(base_url, key, token=''):
    value = str(key or '').strip()
    if not value:
        return ''
    if value.startswith(('http://', 'https://')):
        url = value
    else:
        url = str(base_url or '').rstrip('/') + '/' + value.lstrip('/')
    if not token:
        return url
    try:
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        if not any(k.lower() == 'x-plex-token' for k, _v in pairs):
            pairs.append(('X-Plex-Token', str(token)))
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           urlencode(pairs), parts.fragment))
    except Exception:
        joiner = '&' if '?' in url else '?'
        return url + joiner + urlencode({'X-Plex-Token': str(token)})


def _external_subtitles_from_part(part, base_url='', token=''):
    rows = []
    if part is None:
        return rows
    for stream in part.findall('.//Stream'):
        if str(stream.attrib.get('streamType') or '') != '3':
            continue
        key = stream.attrib.get('key') or ''
        if not key:
            # Embedded tracks stay inside Plex/Kodi; only sidecar/external
            # streams can be attached with ListItem.setSubtitles().
            continue
        codec = str(stream.attrib.get('codec') or '').lower()
        fmt = str(stream.attrib.get('format') or '').lower()
        if codec in _BITMAP_SUBTITLE_CODECS or fmt in _BITMAP_SUBTITLE_CODECS:
            continue
        url = _tokenized_plex_url(base_url, key, token)
        if not url:
            continue
        lang = (stream.attrib.get('languageCode') or
                stream.attrib.get('languageTag') or
                stream.attrib.get('language') or 'und')
        rows.append({
            'id': str(stream.attrib.get('id') or len(rows) + 1),
            'url': url,
            'key': url,
            'lang': str(lang),
            'language': str(stream.attrib.get('language') or lang),
            'languageCode': str(stream.attrib.get('languageCode') or lang),
            'codec': codec or fmt or 'subrip',
            'format': _subtitle_ext(codec, fmt),
            'sourceType': 'stream',
            'sourceName': 'Plex',
            'title': str(stream.attrib.get('title') or stream.attrib.get('displayTitle') or ''),
            'forced': str(stream.attrib.get('forced') or '') == '1',
            'selected': str(stream.attrib.get('selected') or '') == '1',
        })
    return rows


def _media_versions(node, base_url="", token=""):
    """All playable versions of a Plex item (DPlex-style, one per Part).

    Each version carries the technical facts the user asked for: resolution,
    HDR, codecs, audio layout, container and the FILE SIZE, plus two
    ready-made strings: info_line for row/plot display and version_label for
    the "choose version" dialog.
    """
    versions = []
    for media in node.findall('./Media'):
        res = _resolution_label(media.attrib.get('videoResolution'))
        vcodec = _VCODEC_MAP.get((media.attrib.get('videoCodec') or '').lower(),
                                 (media.attrib.get('videoCodec') or '').upper())
        audio = _audio_label(media)
        container = (media.attrib.get('container') or '').upper()
        try:
            bitrate = round(float(media.attrib.get('bitrate') or 0) / 1000.0, 1)
        except (TypeError, ValueError):
            bitrate = 0.0
        bit_depth = media.attrib.get('bitDepth') or ''
        for part in media.findall('./Part'):
            hdr = _hdr_from_part(part)
            size_bytes = _int(part.attrib.get('size'))
            size = _size_label(size_bytes)
            blocks = []
            for val in (res, hdr, vcodec, audio, size):
                if val:
                    blocks.append('[ %s ]' % val)
            short = [b for b in (res, hdr, size, container) if b]
            versions.append({
                'part_key': part.attrib.get('key') or '',
                'file': part.attrib.get('file') or '',
                'resolution': res,
                'hdr': hdr,
                'video_codec': vcodec,
                'audio': audio,
                'container': container,
                'bitrate_mbps': bitrate,
                'bit_depth': bit_depth,
                'size_bytes': size_bytes,
                'size_label': size,
                'info_line': ' • '.join(blocks),
                'version_label': ' · '.join(short) or 'Version %d' % (len(versions) + 1),
                'subtitles': _external_subtitles_from_part(part, base_url, token),
            })
    return versions


def item_from_node(node, server, base_url=''):
    """Convert one Plex XML item into a transport-free UI/playback dict."""
    kind = (node.attrib.get('type') or '').lower()
    if kind == 'show':
        media_type = 'show'
    elif kind == 'season':
        media_type = 'season'
    elif kind in ('episode', 'clip'):
        media_type = 'episode'
    elif kind in ('artist', 'album', 'track'):
        media_type = 'audio'
    else:
        media_type = 'movie'
    ids = _guid_ids(node)
    title = node.attrib.get('title') or node.attrib.get('grandparentTitle') or 'Plex'
    show_title = node.attrib.get('grandparentTitle') or ''
    if media_type == 'episode' and show_title:
        title = '%s — %s' % (show_title, title)
    out = {
        'server_id': str(server.get('id') or ''),
        'server_name': server.get('name') or 'Plex',
        'server_url': base_url or ((server.get('connections') or [{}])[0].get('uri') or ''),
        'token': server.get('token') or '',
        'rating_key': str(node.attrib.get('ratingKey') or ''),
        'key': node.attrib.get('key') or '',
        'part_key': _first_media_part(node),
        'versions': _media_versions(node, base_url, server.get('token') or ''),
        'media_type': media_type,
        'title': title,
        'raw_title': node.attrib.get('title') or title,
        'show_title': show_title,
        'year': _int(node.attrib.get('year')),
        'duration_ms': _int(node.attrib.get('duration')),
        'view_offset_ms': _int(node.attrib.get('viewOffset')),
        'index': _int(node.attrib.get('index')),
        'season': _int(node.attrib.get('parentIndex')),
        'summary': node.attrib.get('summary') or '',
        'thumb': node.attrib.get('thumb') or node.attrib.get('parentThumb') or '',
        'art': node.attrib.get('art') or node.attrib.get('grandparentArt') or '',
        'parent_thumb': node.attrib.get('parentThumb') or '',
        'leaf_count': _int(node.attrib.get('leafCount')),
        'view_count': _int(node.attrib.get('viewCount')),
        'rating': _float(node.attrib.get('rating') or node.attrib.get('audienceRating')),
        'content_rating': node.attrib.get('contentRating') or '',
        'studio': node.attrib.get('studio') or '',
        'tagline': node.attrib.get('tagline') or '',
        'premiered': node.attrib.get('originallyAvailableAt') or '',
        'genres': [g.attrib.get('tag') for g in node.findall('./Genre') if g.attrib.get('tag')][:6],
        'directors': [d.attrib.get('tag') for d in node.findall('./Director') if d.attrib.get('tag')][:4],
        'writers': [w.attrib.get('tag') for w in node.findall('./Writer') if w.attrib.get('tag')][:4],
        'cast': [r.attrib.get('tag') for r in node.findall('./Role') if r.attrib.get('tag')][:10],
        'ids': ids,
        'info_line': '',
        'size_label': '',
    }
    if out['versions']:
        out['info_line'] = out['versions'][0].get('info_line') or ''
        out['size_label'] = out['versions'][0].get('size_label') or ''
    return out


def libraries(server, force=False):
    """Video libraries with a short process-memory cache.

    A Plex global search touches every library.  Keeping this tiny cache means
    a second search does not first serially re-request every server's section
    list, while still refreshing naturally after a resource refresh/sign-out.
    """
    cache_key = str(server.get('id') or '')
    cached = _LIBRARIES_MEM.get(cache_key) or {}
    if (not force and cached.get('rows') is not None and
            cached.get('at', 0) + LIBRARY_CACHE_SECONDS > time.time()):
        return list(cached.get('rows') or [])
    if not force and cache_key:
        # v3.9.171: sections shared across warm interpreters (one fetch per
        # TTL for the whole device instead of per interpreter).
        try:
            raw = xbmcgui.Window(10000).getProperty('nuviohub.plex.libs.%s' % cache_key) or ''
            if raw:
                data = json.loads(raw)
                if data.get('at', 0) + LIBRARY_CACHE_SECONDS > time.time():
                    _LIBRARIES_MEM[cache_key] = data
                    return list(data.get('rows') or [])
        except Exception:
            pass
    try:
        root, _base = _server_xml(server, '/library/sections')
    except PlexError as exc:
        # This is the line that tells the user WHY Plex is silent.
        xbmc.log('[NuvioHub] Plex UNREACHABLE: server=%s error=%s'
                 % (server.get('name') or '?', exc), xbmc.LOGERROR)
        return []
    rows = []
    for node in root.findall('./Directory'):
        kind = (node.attrib.get('type') or '').lower()
        if kind not in ('movie', 'show', 'artist', 'photo'):
            continue
        rows.append({
            'key': str(node.attrib.get('key') or ''),
            'title': node.attrib.get('title') or 'Library',
            'type': kind,
            'thumb': node.attrib.get('thumb') or '',
            'art': node.attrib.get('art') or '',
        })
    if not rows:
        # v3.9.214 — the bug that made Plex look permanently broken.
        #
        # One failed fetch (a TLS error, a timeout, a server that was asleep)
        # produced rows=[] — and that EMPTY list was then cached for 15 minutes
        # in memory AND mirrored into a window property shared by every warm
        # interpreter. From that moment on, search_server() saw "no sections",
        # returned [] instantly, and every lookup reported "no match" without
        # touching the network again. The server could come back and Nuvio Hub
        # would never notice. A failure must never be cached.
        xbmc.log('[NuvioHub] Plex libraries EMPTY for server=%s — not caching, '
                 'will retry on the next call' % (server.get('name') or '?'),
                 xbmc.LOGWARNING)
        try:
            xbmcgui.Window(WINDOW_ID).clearProperty('nuviohub.plex.libs.%s' % cache_key)
        except Exception:
            pass
        _LIBRARIES_MEM.pop(cache_key, None)
        return []

    xbmc.log('[NuvioHub] Plex libraries: server=%s sections=%d'
             % (server.get('name') or '?', len(rows)), xbmc.LOGINFO)
    payload = {'at': time.time(), 'rows': rows}
    _LIBRARIES_MEM[cache_key] = payload
    if cache_key:
        try:
            xbmcgui.Window(10000).setProperty('nuviohub.plex.libs.%s' % cache_key,
                                              json.dumps(payload))
        except Exception:
            pass
    return list(rows)


def children(server, key, start=0, size=PAGE_SIZE, sort=''):
    root, base = _server_xml(server, key, {
        'X-Plex-Container-Start': int(start or 0),
        'X-Plex-Container-Size': int(size or PAGE_SIZE),
        'sort': sort,
    })
    rows = []
    for node in list(root):
        if node.tag.rsplit('}', 1)[-1] not in ('Video', 'Directory'):
            continue
        rows.append(item_from_node(node, server, base))
    total = _int(root.attrib.get('totalSize'), len(rows))
    return rows, total


def episode_leaves(server, show_rating_key, season, episode):
    """Return every exact SxxEyy below a Plex show using DPlex's fast path.

    Some libraries expose episodes through allLeaves but not through the
    show -> seasons -> children walk (or use a flattened/no-season layout).
    Query both known endpoint shapes and keep each distinct episode RatingKey.
    """
    try:
        season_i, episode_i = int(season), int(episode)
    except Exception:
        return []
    found = []
    seen = set()
    for typed in (False, True):
        path = '/library/metadata/%s/allLeaves' % show_rating_key
        params = {'includeGuids': 1}
        if typed:
            params['type'] = 4
        try:
            root, base = _server_xml(server, path, params)
        except PlexError:
            continue
        for node in list(root.findall('.//Video')) + list(root.findall('./Video')):
            if str(node.attrib.get('type') or '').lower() != 'episode':
                continue
            if (_int(node.attrib.get('parentIndex'), -1) != season_i or
                    _int(node.attrib.get('index'), -1) != episode_i):
                continue
            row = item_from_node(node, server, base)
            key = str(row.get('rating_key') or '')
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            found.append(row)
    return found


def on_deck(server, start=0, size=PAGE_SIZE):
    root, base = _server_xml(server, '/library/onDeck', {
        'X-Plex-Container-Start': int(start or 0),
        'X-Plex-Container-Size': int(size or PAGE_SIZE),
    })
    return [item_from_node(node, server, base) for node in root.findall('./Video')]


def metadata(server, rating_key):
    # v3.9.221 — the real answer to "why does Plex have no ids?".
    #
    # It HAS them. Plex only ships the <Guid> children when they are asked for,
    # and this call never asked. So every item Nuvio Hub looked at arrived with an
    # empty id set, every id comparison failed, and the whole lookup collapsed
    # onto title matching — which is what made an Arabic query hopeless.
    root, base = _server_xml(server, '/library/metadata/%s' % rating_key,
                             {'includeGuids': 1})
    for node in list(root):
        if node.tag.rsplit('}', 1)[-1] in ('Video', 'Directory'):
            return item_from_node(node, server, base)
    raise PlexError('Plex item not found')


def search_server(server, query, media_type='', limit=40):
    """Search every video library on one server — libraries IN PARALLEL.

    v3.9.181: the per-library requests used to run one after another, so a
    server with 6 libraries paid 6 round-trips back-to-back and NuvioHub's
    unified search waited on the slowest chain. DPlex fans the same
    /library/sections/<key>/search requests out across a small pool; this does
    the same, so a whole server now costs roughly ONE round-trip.
    """
    wanted = {'movie': '1', 'show': '2', 'series': '2', 'episode': '4'}.get((media_type or '').lower(), '')
    sections = [lib for lib in libraries(server) if lib.get('type') in ('movie', 'show')]
    # v3.9.238: only fan out to sections that can actually CONTAIN the wanted
    # type. The unified search runs one 'movie' job and one 'series' job per
    # server, and this used to query EVERY video section for both — so a
    # movie library was also searched with type=2 (guaranteed empty) and a
    # show library with type=1. For a server with M movie + S show libraries
    # that wasted M+S authenticated round-trips per search, ~40% of the
    # server-search cost, for results that were empty by construction.
    if wanted == '1':
        sections = [lib for lib in sections if lib.get('type') == 'movie']
    elif wanted in ('2', '4'):
        sections = [lib for lib in sections if lib.get('type') == 'show']
    if not sections:
        # A sign-in/resource refresh can leave a previously cached empty
        # section list in the shared Window property.  Refresh it once before
        # concluding that the server has no searchable video libraries — but
        # only when there are NO video sections at all; an empty list because
        # the server simply has no libraries of the WANTED type is legitimate
        # and must not trigger a network refresh (nor re-admit cross-type
        # sections, which would undo the v3.9.238 filter).
        try:
            _all_video = [lib for lib in libraries(server)
                          if lib.get('type') in ('movie', 'show')]
        except Exception:
            _all_video = []
        if not _all_video:
            try:
                _all_video = [lib for lib in libraries(server, force=True)
                              if lib.get('type') in ('movie', 'show')]
            except Exception:
                _all_video = []
        if wanted == '1':
            sections = [lib for lib in _all_video if lib.get('type') == 'movie']
        elif wanted in ('2', '4'):
            sections = [lib for lib in _all_video if lib.get('type') == 'show']
        else:
            sections = _all_video
    if not sections:
        return []

    def _rows(root, base):
        found = []
        for node in list(root):
            if node.tag.rsplit('}', 1)[-1] not in ('Video', 'Directory'):
                continue
            item = item_from_node(node, server, base)
            if item['media_type'] in ('movie', 'show', 'episode'):
                found.append(item)
        return found

    # Fast server-wide search first.  Newer Plex agents reliably expose this
    # endpoint even when a library's legacy /search endpoint returns no rows.
    global_params = {
        'query': query,
        'includeGuids': 1,
        'X-Plex-Container-Start': 0,
        'X-Plex-Container-Size': int(limit),
    }
    if wanted:
        global_params['type'] = wanted
    global_rows = []
    try:
        root, base = _server_xml(server, '/library/all', global_params)
        global_rows = _rows(root, base)
    except PlexError:
        pass

    def _one(library):
        params = {'query': query, 'limit': int(limit), 'includeGuids': 1}
        if wanted:
            params['type'] = wanted
        try:
            root, base = _server_xml(server, '/library/sections/%s/search' % library['key'], params)
        except PlexError:
            root = None
            base = ''
        rows = _rows(root, base) if root is not None else []
        if rows:
            return rows

        # DPlex compatibility fallback.  Some Plex Media Server versions and
        # custom agents implement title filtering on /all but return an empty
        # container from /search.  Trying both is still one parallel request
        # per library and preserves every resolution/media version.
        all_params = {
            'title': query,
            'includeGuids': 1,
            'X-Plex-Container-Start': 0,
            'X-Plex-Container-Size': int(limit),
        }
        if wanted:
            all_params['type'] = wanted
        try:
            root, base = _server_xml(
                server, '/library/sections/%s/all' % library['key'], all_params)
            return _rows(root, base)
        except PlexError:
            # One inaccessible library must not hide the rest of the server.
            return []

    matches = list(global_rows)
    with ThreadPoolExecutor(max_workers=min(6, len(sections))) as pool:
        futures = [pool.submit(_one, lib) for lib in sections]
        for future in as_completed(futures):
            try:
                matches.extend(future.result() or [])
            except Exception:
                continue
            if len(matches) >= int(limit):
                break
    # The same metadata object can be returned by global query, /search and
    # /all?title. Collapse only these repeated API sightings by RatingKey;
    # playable Media/Part versions are expanded later and are never removed.
    unique = []
    seen_keys = set()
    for row in matches:
        key = str(row.get('rating_key') or '')
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        unique.append(row)
    return unique[:int(limit)]


def search_all(query, media_type='', limit_per_server=40):
    """Search every accessible server concurrently; offline servers skip.

    Results are assembled in the server-list order after the parallel work so
    the interface remains stable while a remote/shared server is slow.
    """
    server_rows = servers()
    if not server_rows:
        return []
    if len(server_rows) == 1:
        try:
            return search_server(server_rows[0], query, media_type, limit_per_server)
        except PlexError:
            return []
    found = {}
    workers = min(4, len(server_rows))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(search_server, server, query, media_type, limit_per_server): index
            for index, server in enumerate(server_rows)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                found[index] = future.result()
            except PlexError:
                found[index] = []
            except Exception:
                found[index] = []
    rows = []
    for index in range(len(server_rows)):
        rows.extend(found.get(index) or [])
    return rows



_TITLE_NOISE_RE = re.compile(r'[\[\](){}:.,!?\'"`~*_/\\|+-]+')
_TITLE_YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')
_AR_DIACRITICS_RE = re.compile("[\u064b-\u0652\u0640]")


def _norm_title(value):
    """Compare titles the way a human would, not byte-for-byte.

    v3.9.220 — the match was EXACT, so a library that stores
    "Cheat Sheet (2026)" was rejected when Nuvio Hub asked for "Cheat Sheet",
    and an Arabic title with a stray tatweel or a hamza variant never matched
    at all. Worse: a library whose items were never matched by Plex carries NO
    guids, so the id check can never pass and the title is the ONLY thing that
    can identify it — it has to be forgiving.
    """
    text = str(value or '').strip().lower()
    if not text:
        return ''
    text = _AR_DIACRITICS_RE.sub('', text)
    text = (text.replace("\u0623", "\u0627").replace("\u0625", "\u0627")
                .replace("\u0622", "\u0627").replace("\u0649", "\u064a")
                .replace("\u0629", "\u0647"))
    text = _TITLE_YEAR_RE.sub(' ', text)
    text = _TITLE_NOISE_RE.sub(' ', text)
    return ' '.join(text.split())


def _titles_match(a, b):
    a, b = _norm_title(a), _norm_title(b)
    if not a or not b:
        return False
    if a == b:
        return True
    # One being contained in the other covers "Cheat Sheet" vs
    # "Cheat Sheet 2026 4K", but only when the shorter side is substantial.
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 6 and short in long_


_PLEX_GUID_CACHE = {}
MATCH_BASE = 'https://metadata.provider.plex.tv'


def plex_guid_for_ids(ids, media_type='movie'):
    """imdb/tmdb  ->  the canonical plex:// guid, via Plex's own matcher.

    v3.9.221 — the missing step, taken straight from Plexio (the Stremio addon
    that does this successfully today).

    A library item's PRIMARY guid is `plex://movie/5d776…`. That is the only
    value `/library/all?guid=` can filter on. Nuvio Hub was passing
    `imdb://tt…` — which is stored as a <Guid> CHILD, is not the primary guid,
    and therefore never matched anything. Plex publishes a matcher that turns
    an external id into the canonical guid:

        metadata.provider.plex.tv/library/metadata/matches
            ?guid=com.plexapp.agents.imdb://tt…?lang=en&type=1

    Resolve once, cache, then ask the user's own server with the guid it
    actually understands.
    """
    imdb = str((ids or {}).get('imdb_id') or '').strip()
    tmdb = str((ids or {}).get('tmdb_id') or '').strip()
    if not (imdb or tmdb):
        return ''
    series = str(media_type).lower() in ('series', 'show', 'episode')
    want_type = 2 if series else 1
    cache_key = (imdb or tmdb, want_type)
    if cache_key in _PLEX_GUID_CACHE:
        return _PLEX_GUID_CACHE[cache_key]

    token = account().get('token') or ''
    candidates = []
    if imdb:
        candidates.append(('imdb-%s' % imdb,
                           'com.plexapp.agents.imdb://%s?lang=en' % imdb))
    if tmdb:
        candidates.append(('tmdb-%s' % tmdb,
                           'com.plexapp.agents.themoviedb://%s?lang=en' % tmdb))

    guid = ''
    for title, agent_guid in candidates:
        params = urlencode({'X-Plex-Token': token, 'type': want_type,
                            'title': title, 'guid': agent_guid})
        try:
            root = _xml(_request('%s/library/metadata/matches?%s'
                                 % (MATCH_BASE, params), timeout=8))
        except PlexError as exc:
            xbmc.log('[NuvioHub] Plex matcher failed (%s)' % exc, xbmc.LOGWARNING)
            continue
        for node in list(root):
            value = str(node.attrib.get('guid') or '').strip()
            if value.startswith('plex://'):
                guid = value
                break
        if guid:
            break

    _PLEX_GUID_CACHE[cache_key] = guid
    xbmc.log('[NuvioHub] Plex guid resolved: %s -> %s'
             % (imdb or tmdb, guid or 'NOT FOUND'), xbmc.LOGINFO)
    return guid


def find_by_guid(server, ids, media_type='movie', limit=12):
    """Look an item up by its EXTERNAL id — the correct Plex way.

    v3.9.217 — this is what Plex for Kodi (PlexMod) does:

        server.query("/library/all", guid=<guid>, type=<1|2>)

    `/library/all` is a GLOBAL lookup: one request resolves the guid across
    every library on the server. The earlier attempt walked
    /library/sections/<key>/all for each of the user's 17-25 sections and for
    each candidate guid — ~70 requests per server, which is exactly why each
    server took 14 seconds and then gave up.

    Every hit is still verified against the ids, so a server that ignores the
    filter can never leak the wrong film.
    """
    guids = []
    # The canonical plex:// guid — the ONLY value /library/all?guid= matches.
    canonical = plex_guid_for_ids(ids, media_type=media_type)
    if canonical:
        guids.append(canonical)
    imdb = str((ids or {}).get('imdb_id') or '').strip()
    tmdb = str((ids or {}).get('tmdb_id') or '').strip()
    tvdb = str((ids or {}).get('tvdb_id') or '').strip()
    if imdb:
        guids.append('imdb://%s' % imdb)
        # Libraries scanned with the legacy agents store this longer form.
        guids.append('com.plexapp.agents.imdb://%s?lang=en' % imdb)
    if tmdb:
        guids.append('tmdb://%s' % tmdb)
        guids.append('com.plexapp.agents.themoviedb://%s?lang=en' % tmdb)
    if tvdb:
        guids.append('tvdb://%s' % tvdb)
        guids.append('com.plexapp.agents.thetvdb://%s?lang=en' % tvdb)
    if not guids:
        return []

    series = str(media_type).lower() in ('series', 'show', 'episode')
    want_type = '2' if series else '1'

    out, seen = [], set()
    for guid in guids:
        try:
            root, base = _server_xml(server, '/library/all',
                                     {'guid': guid, 'type': want_type,
                                      'includeGuids': 1})
        except PlexError:
            continue
        for node in list(root):
            if node.tag.rsplit('}', 1)[-1] not in ('Video', 'Directory'):
                continue
            item = item_from_node(node, server, base)
            key = str(item.get('rating_key') or '')
            if not key or key in seen:
                continue
            row_ids = item.get('ids') or {}
            if not any(str(row_ids.get(k) or '').lower() == str((ids or {}).get(k) or '').lower()
                       for k in ('imdb_id', 'tmdb_id', 'tvdb_id') if (ids or {}).get(k)):
                continue          # verified — never the wrong item
            seen.add(key)
            out.append(item)
        if out:
            xbmc.log('[NuvioHub] Plex matched by GUID: server=%s guid=%s hits=%d'
                     % (server.get('name') or '?', guid, len(out)), xbmc.LOGINFO)
            return out[:int(limit)]
    return out[:int(limit)]

def episode_item(server, show_item, season, episode):
    """Walk show -> season -> episode, returning the episode with its Parts.

    v3.9.222 — the log said it plainly:

        plex lookup: ... -> 1 item(s)
        Plex Native source result: streams=0

    The SHOW was found (the Plexio guid match works), but plex_client had no
    episode_item() at all — the unified lookup called it, the call failed, and
    every series silently produced zero sources. Movies worked; series never
    could.
    """
    try:
        want_season = int(str(season).strip())
        want_episode = int(str(episode).strip())
    except (TypeError, ValueError):
        return None

    show_key = (show_item.get('key')
                or '/library/metadata/%s/children' % show_item.get('rating_key'))
    try:
        seasons, _total = children(server, show_key, size=60)
    except Exception:
        return None

    for season_row in seasons or []:
        try:
            if int(season_row.get('index') or -1) != want_season:
                continue
        except (TypeError, ValueError):
            continue
        season_key = (season_row.get('key')
                      or '/library/metadata/%s/children' % season_row.get('rating_key'))
        try:
            episodes, _t = children(server, season_key, size=200)
        except Exception:
            return None
        for row in episodes or []:
            try:
                if int(row.get('index') or -1) == want_episode:
                    # The listing carries no Parts — fetch the full record.
                    try:
                        return metadata(server, row.get('rating_key'))
                    except Exception:
                        return row
            except (TypeError, ValueError):
                continue
    return None


def find_all_by_ids(server, ids, media_type='movie', title='', limit=10):
    """EVERY matching library item on this server — see emby_client for why."""
    found, seen = [], set()

    # ID-exact first — this is what Emby was already doing, and it is why Emby
    # found the film while Plex did not.
    for item in find_by_guid(server, ids, media_type=media_type, limit=limit):
        key = str(item.get('rating_key') or '')
        if key and key not in seen:
            seen.add(key)
            found.append(item)

    if found:
        # v3.9.224 — the 43 seconds the log was showing.
        #
        # The canonical guid match is EXACT: Plex itself resolved the id and
        # handed back the item. Yet the code carried on regardless, because the
        # only gate was `len(found) >= limit` (24) and a film has two or three
        # copies, never twenty-four. So after a perfect match it still ran the
        # id-as-query searches AND the title search — each of which scans all
        # 17-25 sections of the library. Roughly a hundred pointless requests
        # per server, which is why one server took 43 seconds and the others
        # were cut off by the scan deadline before they could report anything.
        #
        # An exact match is the answer. Stop.
        xbmc.log('[NuvioHub] Plex exact guid match — skipping the title fallbacks '
                 '(server=%s, %d copies)' % (server.get('name') or '?', len(found)),
                 xbmc.LOGINFO)
        return _resolve_details(server, found, limit)

    rejected = []
    want = {k: str((ids or {}).get(k) or '').lower() for k in ('imdb_id', 'tmdb_id', 'tvdb_id')}
    kind = 'show' if str(media_type).lower() in ('series', 'show', 'episode') else 'movie'

    # v3.9.216 — ask Plex by ID, the way Emby is asked.
    #
    # Emby offers AnyProviderIdEquals=tmdb.<id>, so it finds an item no matter
    # what the library calls it. Plex has no equivalent on modern agents: its
    # ?guid= filter matches the PRIMARY guid, which is plex://movie/… — the
    # imdb/tmdb ids live in <Guid> CHILD elements and are not filterable.
    #
    # What Plex DOES do is index those ids in its search engine. So the ids
    # themselves are used as queries, alongside the titles. Every hit is then
    # verified against the ids below, so a stray match can never leak through.
    id_queries = []
    if want.get('imdb_id'):
        id_queries.append(want['imdb_id'])                      # tt39370732
    if want.get('tmdb_id'):
        id_queries.extend([want['tmdb_id'],                     # 1124796
                           'tmdb://%s' % want['tmdb_id']])
    if want.get('tvdb_id'):
        id_queries.append('tvdb://%s' % want['tvdb_id'])

    for query in id_queries:
        if len(found) >= int(limit):
            break
        try:
            rows_by_id = search_server(server, query, media_type=kind,
                                       limit=max(10, int(limit)))
        except Exception:
            continue
        for row in rows_by_id or []:
            row_ids = row.get('ids') or {}
            if not any(want[k] and str(row_ids.get(k) or '').lower() == want[k]
                       for k in want):
                continue                     # verified: never the wrong film
            key = str(row.get('rating_key') or '')
            if key and key not in seen:
                seen.add(key)
                found.append(row)
    if found:
        xbmc.log('[NuvioHub] Plex matched by ID: server=%s hits=%d'
                 % (server.get('name') or '?', len(found)), xbmc.LOGINFO)
    # Exact GUID scan first. Unlike find_by_ids(), keep every RatingKey Plex
    # returns: the same film/show may be catalogued independently in 4K,
    # Arabic and archive libraries on the same server.
    guid_values = []
    if want['imdb_id']:
        guid_values.extend(('imdb://%s' % want['imdb_id'],
                            'com.plexapp.agents.imdb://%s?lang=en' % want['imdb_id']))
    if want['tmdb_id']:
        guid_values.extend(('tmdb://%s' % want['tmdb_id'],
                            'themoviedb://%s' % want['tmdb_id'],
                            'com.plexapp.agents.themoviedb://%s?lang=en' % want['tmdb_id']))
        if kind == 'show':
            guid_values.append('themoviedb://tv-%s' % want['tmdb_id'])
    if want['tvdb_id']:
        guid_values.extend(('tvdb://%s' % want['tvdb_id'],
                            'thetvdb://%s' % want['tvdb_id'],
                            'com.plexapp.agents.thetvdb://%s?lang=en' % want['tvdb_id']))
    guid_values = list(dict.fromkeys(guid_values))

    def _guid_rows(guid):
        try:
            root, base = _server_xml(server, '/library/all', {
                'guid': guid, 'includeGuids': 1,
                'X-Plex-Container-Start': 0,
                'X-Plex-Container-Size': max(20, int(limit)),
            })
        except Exception:
            return []
        rows = []
        for node in list(root):
            if node.tag.rsplit('}', 1)[-1] not in ('Video', 'Directory'):
                continue
            row = item_from_node(node, server, base)
            if row.get('media_type') in (('show',) if kind == 'show' else ('movie',)):
                rows.append(row)
        return rows

    if guid_values:
        with ThreadPoolExecutor(max_workers=min(6, len(guid_values))) as pool:
            futures = [pool.submit(_guid_rows, guid) for guid in guid_values]
            for future in as_completed(futures):
                try:
                    exact_rows = future.result() or []
                except Exception:
                    exact_rows = []
                for row in exact_rows:
                    key = str(row.get('rating_key') or '')
                    if not key or key in seen:
                        continue
                    detailed = row
                    try:
                        detailed = metadata(server, key)
                    except Exception:
                        pass
                    row_ids = detailed.get('ids') or {}
                    same_id = any(want[k] and str(row_ids.get(k) or '').lower() == want[k]
                                  for k in want)
                    # A response from /library/all?guid=<exact> can omit Guid
                    # children. The server already applied the exact filter.
                    if same_id or not any(row_ids.values()):
                        seen.add(key)
                        found.append(detailed)
    try:
        rows = search_server(server, title or '', media_type=kind, limit=max(20, int(limit)))
    except Exception:
        rows = []
    for row in rows or []:
        row_ids = row.get('ids') or {}
        same_id = any(want[k] and str(row_ids.get(k) or '').lower() == want[k] for k in want)
        if not same_id and not (row.get('ids') or {}):
            # The search response carries no guids. Ask the item itself before
            # dismissing it: that is where Plex keeps the imdb/tmdb ids.
            try:
                full = metadata(server, row.get('rating_key'))
            except Exception:
                full = None
            if full:
                full_ids = full.get('ids') or {}
                if any(want[k] and str(full_ids.get(k) or '').lower() == want[k]
                       for k in want):
                    key = str(full.get('rating_key') or '')
                    if key and key not in seen:
                        seen.add(key)
                        found.append(full)
                        xbmc.log('[NuvioHub] Plex matched by ID (via metadata): '
                                 'server=%s title=%s' % (server.get('name') or '?',
                                                         full.get('title') or '?'),
                                 xbmc.LOGINFO)
                    continue
                row = full          # judge the title on the full record
                row_ids = full_ids
                same_id = False
        same_title = _titles_match(row.get('title'), title)
        if not (same_id or same_title):
            rejected.append('%s [%s]' % (row.get('title') or '?',
                                         ','.join('%s=%s' % (k, v)
                                                  for k, v in (row.get('ids') or {}).items() if v)
                                         or 'no ids'))
            continue
        key = str(row.get('rating_key') or '')
        if key and key not in seen:
            seen.add(key)
            found.append(row)
    if not found and rejected:
        # The single most useful line in the log: what the library ACTUALLY
        # holds under this name, and whether those items carry any ids at all.
        xbmc.log('[NuvioHub] Plex saw but rejected: %s' % ' | '.join(rejected[:6]),
                 xbmc.LOGWARNING)

    # v3.9.223 — why only ONE server ever produced sources.
    #
    # The log showed all three servers MATCHING (hits=1/3/3) but only one
    # reporting a result. After the match, the full record of every hit was
    # fetched ONE AT A TIME — ~9 seconds per server — so the slower servers
    # were still fetching when the source scan's deadline cut them off.
    #
    # /library/all already returns the Media/Part children, so most hits need
    # no second request at all; the rest are fetched in parallel.
    return _resolve_details(server, found, limit)


def _resolve_details(server, found, limit):
    """Fill in the Media/Part records — in parallel, and only when missing."""
    rows = found[:int(limit)]
    need_detail = [r for r in rows if not (r.get('versions') or [])]
    detailed = {}
    if need_detail:
        with ThreadPoolExecutor(max_workers=min(6, len(need_detail))) as pool:
            futures = {pool.submit(metadata, server, r.get('rating_key')): r
                       for r in need_detail if r.get('rating_key')}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    detailed[str(row.get('rating_key'))] = future.result()
                except Exception:
                    pass
    return [detailed.get(str(r.get('rating_key')), r) for r in rows]


def find_by_ids(server, ids, media_type='movie', title='', limit=12):
    """Resolve a Plex item by GUID first, then strong text fallback.

    Plex title search is intentionally only a fallback: translated titles and
    alternate library names frequently miss while the item's Guid is exact.
    Every accessible matching library is queried, and duplicate rating keys
    are collapsed without discarding copies on other servers.
    """
    ids = ids or {}
    wanted_type = {'movie': '1', 'show': '2', 'series': '2', 'episode': '2'}.get(
        str(media_type or '').lower(), '')
    sections = [lib for lib in libraries(server)
                if lib.get('type') in (('show',) if wanted_type == '2' else ('movie', 'show'))]
    if not sections:
        try:
            sections = [lib for lib in libraries(server, force=True)
                        if lib.get('type') in (('show',) if wanted_type == '2' else ('movie', 'show'))]
        except Exception:
            sections = []
    # Do not return when section discovery is empty. DPlex's successful path
    # searches /library/all?guid=... directly on every server and does not
    # require /library/sections to succeed first. Shared/remote servers can
    # deny or delay the section list while still answering exact GUID lookup.

    guid_values = []
    imdb = str(ids.get('imdb_id') or '').strip()
    tmdb = str(ids.get('tmdb_id') or '').strip()
    tvdb = str(ids.get('tvdb_id') or '').strip()
    if imdb:
        guid_values.extend([
            'imdb://%s' % imdb,
            'com.plexapp.agents.imdb://%s?lang=en' % imdb,
        ])
    if tmdb:
        guid_values.extend([
            'tmdb://%s' % tmdb,
            'themoviedb://%s' % tmdb,
            'com.plexapp.agents.themoviedb://%s?lang=en' % tmdb,
        ])
        if wanted_type == '2':
            guid_values.append('themoviedb://tv-%s' % tmdb)
    if tvdb:
        guid_values.extend([
            'tvdb://%s' % tvdb,
            'thetvdb://%s' % tvdb,
            'com.plexapp.agents.thetvdb://%s?lang=en' % tvdb,
        ])
    # Preserve order while removing duplicates from mixed/legacy IDs.
    guid_values = list(dict.fromkeys(guid_values))

    def _match_ids(row):
        row_ids = row.get('ids') or {}
        return bool((imdb and str(row_ids.get('imdb_id') or '').lower() == imdb.lower()) or
                    (tmdb and str(row_ids.get('tmdb_id') or '') == tmdb) or
                    (tvdb and str(row_ids.get('tvdb_id') or '') == tvdb))

    # DPlex's proven fast path: /library/all applies the GUID across every
    # section in one request. The previous per-section implementation was both
    # slower and returned zero on servers that only implement global GUID
    # matching. Independent GUID aliases still run concurrently.
    def _guid_lookup(guid):
        try:
            root_xml, base = _server_xml(server, '/library/all', {
                'guid': guid, 'includeGuids': 1,
                'X-Plex-Container-Start': 0,
                'X-Plex-Container-Size': int(limit),
            })
        except PlexError:
            return []
        rows = []
        for node in list(root_xml):
            if node.tag.rsplit('}', 1)[-1] not in ('Video', 'Directory'):
                continue
            row = item_from_node(node, server, base)
            if row.get('media_type') in ('movie', 'show', 'episode'):
                rows.append(row)
        return rows

    if guid_values:
        with ThreadPoolExecutor(max_workers=min(6, len(guid_values))) as pool:
            futures = [pool.submit(_guid_lookup, guid) for guid in guid_values]
            for future in as_completed(futures):
                try:
                    rows = future.result() or []
                except Exception:
                    rows = []
                for row in rows:
                    # Some Plex versions apply the exact GUID filter but omit
                    # Guid children in the response. Refresh metadata once;
                    # if IDs are still absent, the exact filtered hit is safe.
                    detailed = row
                    try:
                        detailed = metadata(server, row.get('rating_key'))
                    except Exception:
                        pass
                    if _match_ids(detailed) or not any((detailed.get('ids') or {}).values()):
                        return detailed

    # Strong title fallback, but verify IDs when Plex returned them.
    if title:
        rows = search_server(server, title, media_type=('show' if wanted_type == '2' else 'movie'), limit=max(10, int(limit)))
        normalized = str(title or '').strip().casefold()
        first_title = None
        for row in rows:
            if _match_ids(row):
                return row
            raw = str(row.get('raw_title') or row.get('title') or '').strip().casefold()
            if raw == normalized and first_title is None:
                first_title = row
        if first_title is not None:
            return first_title
        if rows and not guid_values:
            return rows[0]
    return None

def logo_url(item, base_url=''):
    """Plex ships a clearLogo per item; Nuvio Hub never asked for it."""
    key = str(item.get('rating_key') or '').strip()
    if not key:
        return ''
    return artwork_url(item, '/library/metadata/%s/clearLogo' % key)


def artwork_url(item, path):
    """Turn a Plex artwork path into a token-authenticated image URL."""
    value = str(path or '').strip()
    if not value:
        return ''
    if value.startswith(('http://', 'https://')):
        return value
    base = _normalise_uri(item.get('server_url'))
    token = item.get('token') or ''
    if not base:
        return ''
    parts = urlsplit(base + '/' + value.lstrip('/'))
    pairs = list(parse_qsl(parts.query, keep_blank_values=True))
    if token and not any(k == 'X-Plex-Token' for k, _v in pairs):
        pairs.append(('X-Plex-Token', token))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def playback_url(item, part_key=''):
    """Direct Play URL (token included) for a chosen part, default first."""
    part = str(part_key or item.get('part_key') or '').strip()
    if not part:
        raise PlexError('No directly playable version of this item in Plex')
    return artwork_url(item, part)
