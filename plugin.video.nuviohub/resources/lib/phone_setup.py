"""Phone setup: a local web page served by Kodi itself (6.0.22).

The TV shows a QR code with ``http://<lan-ip>:<port>/?k=<key>``. The phone,
on the same Wi-Fi, opens that page directly from this Kodi device - there is
no external server. The page edits accounts, add-ons, collections and display
options through the same backend functions the TV settings use. "Save" applies
everything, stops the service and lets the caller open MegaNexus. The service
runs only while its TV window is open (closed by Save, Back or idle timeout).

Security: every API call needs the one-time key from the QR code (compared in
constant time); a page opened without it gets nothing. Personalized manifest
URLs are never sent to the phone. Passwords exist only in RAM for the sign-in
request. Traffic is plain HTTP inside the local network.
"""
import hmac
import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import xbmcaddon

ADDON_ID = 'plugin.video.nuviohub'
IDLE_TIMEOUT = 15 * 60          # seconds without a phone request
MAX_BODY = 64 * 1024
PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'phone_setup', 'index.html')
DISPLAY_KEYS = {
    # page field: (setting id, kind)
    'card_shape': ('nuvio_card_shape', ('poster', 'landscape')),
    'show_ratings': ('nuvio_show_ratings', 'bool_default_on'),
    'auto_trailers': ('nuvio_auto_trailers', 'bool'),
    'continue_row': ('nuvio_home_continue', 'bool_default_on'),
}


def lan_ip():
    """LAN address of this device (a UDP connect sends no packet)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return '127.0.0.1'


def _addon():
    return xbmcaddon.Addon(ADDON_ID)


# ---------------------------------------------------------------- state ----

def _source_label(source, providers):
    from .collections_home import matching_catalog
    kind = 'Series' if source.get('type') == 'series' else 'Movies'
    match = matching_catalog(source, providers)
    if not match:
        return '%s (%s) · not installed' % (source.get('catalogId'), kind)
    provider, catalog = match
    genre = source.get('genre') if source.get('genre') not in (None, '', 'None') else ''
    return '%s · %s (%s%s)' % (provider.get('name') or provider['id'], catalog.get('name') or catalog.get('id'),
                               kind, ', ' + genre if genre else '')


def _bool(addon, key, default_on):
    value = addon.getSetting(key)
    return value != 'false' if default_on else value == 'true'


def state():
    """Everything the phone page shows. No manifest URLs, tokens or passwords."""
    from . import metadata_providers, stream_providers, collection_profile, default_setup
    from .nuviohub import store
    from .nuviohub import nuvio_stremio_sync as sync
    addon = _addon()
    providers = store.list_providers()
    token = sync.Nuvio.token()
    display = {}
    for field, (key, kind) in DISPLAY_KEYS.items():
        if isinstance(kind, tuple):
            display[field] = addon.getSetting(key) if addon.getSetting(key) in kind else kind[0]
        else:
            display[field] = _bool(addon, key, kind == 'bool_default_on')
    kind = addon.getSetting('nuvio_screensaver_type') or 'image'
    from . import theme
    display['theme'] = theme.current(addon)
    display['screensaver'] = 'animated' if kind == 'animated' else ('custom' if kind == 'video' or addon.getSetting('nuvio_screensaver_art') else 'image')
    return {
        'nuvio': {'linked': bool(token.get('access_token')), 'profile': token.get('profile_name') or '',
                  'email': token.get('email') or ''},
        'metadata': [{'id': p['id'], 'name': p.get('name') or p['id'], 'enabled': bool(on),
                      'builtin': (p.get('manifest') or {}).get('id') == default_setup.CINEMETA_ID}
                     for p, on in metadata_providers.entries(providers)],
        'streams': [{'id': p['id'], 'name': p.get('name') or p['id'], 'enabled': bool(on)}
                    for p, on in stream_providers.entries(providers)],
        'providers': [{'id': p['id'], 'name': p.get('name') or p['id']} for p in providers],
        'groups': [{'id': g['id'], 'title': g['title'], 'hidden': bool(g.get('hidden')),
                    'folders': [{'id': f['id'], 'title': f['title'], 'hidden': bool(f.get('hidden')),
                                 'hideTitle': bool(f.get('hideTitle')),
                                 'sources': [{'label': _source_label(s, providers), 'enabled': s.get('enabled') is not False}
                                             for s in f['sources']]}
                                for f in g['folders']]}
                   for g in collection_profile.load()],
        'display': display,
        'tracking': _tracking_status(),
    }


def _tracking_status():
    try:
        from . import tracking_link
        return tracking_link.status()
    except Exception:
        return {}


def tracking_start(service):
    from . import tracking_link
    return tracking_link.start(service)


def tracking_disconnect(service):
    from . import tracking_link
    return tracking_link.disconnect(service)


# --------------------------------------------------------------- actions ----

def add_manifest(url):
    from urllib.parse import urlsplit as split
    from .nuviohub.client import validate_manifest
    from .nuviohub import store
    from . import metadata_providers, stream_providers
    value = (url or '').strip()
    if value.startswith('stremio://'):
        value = 'https://' + value[len('stremio://'):]
    parsed = split(value)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or not parsed.path.endswith('/manifest.json'):
        raise ValueError('Enter a complete http(s) …/manifest.json link, including your add-on configuration.')
    try:
        manifest = validate_manifest(value)
    except Exception:
        # The URL may contain credentials: never echo or log it.
        raise ValueError('This manifest could not be checked. Verify the link and the connection.')
    before = {p['id'] for p in store.list_providers()}
    store.add_provider(manifest.get('name') or manifest['id'], value, manifest)
    added = [p for p in store.list_providers() if p['id'] not in before]
    # Same rule as the TV pages: a newly added add-on starts ON in its lists.
    for provider in added:
        if any(p['id'] == provider['id'] for p in metadata_providers.candidates()):
            metadata_providers.set_enabled(provider['id'], True)
        if any(p['id'] == provider['id'] for p in stream_providers.candidates()):
            stream_providers.set_enabled(provider['id'], True)
    return {'added': [p.get('name') or p['id'] for p in added]}


def remove_provider(provider_id):
    from .nuviohub import store
    from . import settings_cache
    if not store.get_provider(provider_id):
        raise ValueError('This add-on is no longer installed.')
    store.remove_provider(provider_id)
    addon = _addon()
    for role in ('metadata', 'streams'):
        if addon.getSetting('nuvio_' + role + '_provider') == provider_id:
            addon.setSetting('nuvio_' + role + '_provider', '')
    settings_cache.invalidate()
    return {}


def nuvio_sign_in(email, password):
    from .nuviohub import nuvio_stremio_sync as sync
    if not email or not password:
        raise ValueError('Enter your Nuvio email and password.')
    try:
        token = sync.Nuvio.authenticate(email.strip(), password)
    except Exception:
        raise ValueError('Sign-in failed. Check the email and password.')
    sync.Nuvio.save_token(token)
    _addon().setSetting('nuvio_sync_enabled', 'true')
    result = nuvio_profiles()
    if len(result['profiles']) == 1:
        # One profile: connect = import add-ons, collections and progress now.
        result['imported'] = first_import()
    return result


def nuvio_profiles():
    from .nuviohub import nuvio_stremio_sync as sync
    try:
        rows = sync.Nuvio.profiles() or []
    except Exception:
        raise ValueError('Nuvio profiles could not be loaded. Check the connection.')
    if len(rows) == 1:
        sync.Nuvio.select_profile(rows[0])
    return {'profiles': [{'index': r.get('profile_index'), 'name': r.get('profile_name') or 'Profile'} for r in rows]}


def nuvio_select_profile(index):
    from .nuviohub import nuvio_stremio_sync as sync
    rows = sync.Nuvio.profiles() or []
    match = next((r for r in rows if str(r.get('profile_index')) == str(index)), None)
    if not match:
        raise ValueError('That Nuvio profile was not found.')
    sync.Nuvio.select_profile(match)
    return {'imported': first_import()}


def first_import():
    """After connecting: add-ons, progress and - unless Home already shows the
    user's own layout - the profile's collections with their metadata ON."""
    from . import nuvio_import as importer
    return nuvio_import(collections=not importer.layout_is_users_own())


def nuvio_sign_out():
    from .nuviohub import nuvio_stremio_sync as sync
    sync.Nuvio.clear()
    _addon().setSetting('nuvio_sync_enabled', 'false')
    return {}


def nuvio_import(collections):
    """Import add-ons (and optionally the collection layout) from the Nuvio profile."""
    from .nuviohub import nuvio_stremio_sync as sync
    from . import nuvio_import as importer, collection_profile, settings_cache
    if not sync.Nuvio.is_linked():
        raise ValueError('Sign in to Nuvio first.')
    result = importer.fetch(collections=collections)
    report = importer.apply(result)
    layout = report.get('collections') or 0
    settings_cache.invalidate()
    return {'providers': report['providers'], 'collections': layout,
            'metadata_on': report.get('metadata_on') or [],
            'errors': list(dict.fromkeys(report['errors']))[:3]}


def _apply_switches(module, rows, on_change=None):
    current = {p['id']: (p, on) for p, on in module.entries()}
    for row in rows or []:
        pid = row.get('id') if isinstance(row, dict) else None
        if pid in current and bool(row.get('enabled')) != current[pid][1]:
            module.set_enabled(pid, bool(row.get('enabled')))
            if on_change:
                on_change(current[pid][0], bool(row.get('enabled')))


def _manual_cinemeta(provider, on):
    """Same rule as the TV Metadata page: a hand-made Cinemeta choice is kept
    (never switched back automatically)."""
    from . import default_setup
    if (provider.get('manifest') or {}).get('id') == default_setup.CINEMETA_ID:
        _addon().setSetting(default_setup.CINEMETA_AUTO, '' if on else 'off')


def _apply_groups(rows):
    """Order, visibility, titles and catalog switches. Unknown IDs are ignored;
    collections the page did not send keep their place at the end."""
    from . import collection_profile
    groups = collection_profile.load()
    if not groups or not isinstance(rows, list):
        return False
    by_id = {g['id']: g for g in groups}
    ordered, before = [], json.dumps(groups, sort_keys=True)
    for row in rows:
        group = by_id.pop(row.get('id'), None) if isinstance(row, dict) else None
        if group is None:
            continue
        group['hidden'] = bool(row.get('hidden'))
        folders = {f['id']: f for f in group['folders']}
        new_folders = []
        for item in row.get('folders') or []:
            folder = folders.pop(item.get('id'), None) if isinstance(item, dict) else None
            if folder is None:
                continue
            title = str(item.get('title') or '').strip()
            if title:
                folder['title'] = title[:80]
            folder['hidden'] = bool(item.get('hidden'))
            folder['hideTitle'] = bool(item.get('hideTitle'))
            switches = item.get('sources')
            if isinstance(switches, list) and len(switches) == len(folder['sources']):
                for source, on in zip(folder['sources'], switches):
                    source['enabled'] = bool(on)
            new_folders.append(folder)
        new_folders.extend(folders.values())
        group['folders'] = new_folders
        ordered.append(group)
    ordered.extend(by_id.values())
    if json.dumps(ordered, sort_keys=True) == before:
        return False
    collection_profile.save(ordered)
    return True


def _apply_display(values):
    addon = _addon()
    if not isinstance(values, dict):
        return
    for field, (key, kind) in DISPLAY_KEYS.items():
        if field not in values:
            continue
        value = values[field]
        if isinstance(kind, tuple):
            if value in kind:
                addon.setSetting(key, value)
        else:
            addon.setSetting(key, 'true' if value else 'false')
    from . import theme
    if values.get('theme') in theme.THEMES and values['theme'] != theme.current(addon):
        theme.apply(values['theme'], addon)
    saver = values.get('screensaver')
    if saver in ('image', 'animated'):
        addon.setSetting('nuvio_screensaver_type', saver)
        addon.setSetting('nuvio_screensaver_art', '')
        addon.setSetting('nuvio_screensaver_video', '')


def save(payload):
    from . import settings_cache
    if not isinstance(payload, dict):
        raise ValueError('Nothing to save.')
    from . import metadata_providers, stream_providers
    _apply_switches(metadata_providers, payload.get('metadata'), _manual_cinemeta)
    _apply_switches(stream_providers, payload.get('streams'))
    _apply_groups(payload.get('groups'))
    _apply_display(payload.get('display'))
    settings_cache.invalidate()
    return {}


# --------------------------------------------------------------- server ----

class SetupService:
    """Local HTTP service. ``events`` are read by the TV window."""

    def __init__(self, host=None, port=0):
        self.key = secrets.token_urlsafe(18)
        self.host = host or lan_ip()
        self.lock = threading.Lock()
        self.connected = False
        self.saved = False
        self.status = ''
        self.last_seen = time.monotonic()
        service = self

        class Handler(BaseHTTPRequestHandler):
            server_version = 'MegaNexusSetup'
            sys_version = ''

            def log_message(self, *args):
                pass  # URLs carry the key; never log requests

            def _send(self, code, body, ctype='application/json; charset=utf-8', cache='no-store'):
                data = body if isinstance(body, bytes) else body.encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', cache)
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                self.wfile.write(data)

            def _json(self, code, value):
                self._send(code, json.dumps(value, ensure_ascii=False))

            def _authorized(self, query_key=''):
                given = self.headers.get('X-Setup-Key') or query_key or ''
                return hmac.compare_digest(given.encode('utf-8'), service.key.encode('utf-8'))

            def do_GET(self):
                parts = urlsplit(self.path)
                query = parse_qs(parts.query)
                if parts.path == '/logo.png':
                    return self._send(200, service.logo(), 'image/png', 'max-age=3600')
                if parts.path == '/':
                    if not self._authorized((query.get('k') or [''])[0]):
                        return self._send(403, service.locked_page(), 'text/html; charset=utf-8')
                    service.touch(connected=True)
                    return self._send(200, service.page(), 'text/html; charset=utf-8')
                if parts.path == '/api/state':
                    if not self._authorized():
                        return self._json(403, {'ok': False, 'error': 'Scan the QR code on your TV again.'})
                    service.touch(connected=True)
                    return service.respond(self, state)
                return self._json(404, {'ok': False})

            def do_POST(self):
                parts = urlsplit(self.path)
                if not self._authorized():
                    return self._json(403, {'ok': False, 'error': 'Scan the QR code on your TV again.'})
                try:
                    length = int(self.headers.get('Content-Length') or 0)
                    if length > MAX_BODY:
                        raise ValueError
                    body = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                    if not isinstance(body, dict):
                        raise ValueError
                except (ValueError, UnicodeDecodeError):
                    return self._json(400, {'ok': False, 'error': 'Bad request.'})
                service.touch(connected=True)
                actions = {
                    '/api/addons/add': lambda: add_manifest(body.get('url')),
                    '/api/addons/remove': lambda: remove_provider(body.get('id')),
                    '/api/nuvio/login': lambda: nuvio_sign_in(body.get('email') or '', body.get('password') or ''),
                    '/api/nuvio/profiles': nuvio_profiles,
                    '/api/nuvio/profile': lambda: nuvio_select_profile(body.get('index')),
                    '/api/nuvio/logout': nuvio_sign_out,
                    '/api/nuvio/import': lambda: nuvio_import(bool(body.get('collections'))),
                    '/api/save': lambda: save(body),
                    '/api/tracking/start': lambda: tracking_start(body.get('service')),
                    '/api/tracking/disconnect': lambda: tracking_disconnect(body.get('service')),
                }
                action = actions.get(parts.path)
                if action is None:
                    return self._json(404, {'ok': False})
                done = service.respond(self, action)
                if done and parts.path == '/api/save':
                    service.finish()

        self.server = ThreadingHTTPServer((self.host, port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, name='MegaNexusPhoneSetup', daemon=True)

    # -- helpers used by the handler
    def respond(self, handler, action):
        try:
            result = action() or {}
        except ValueError as exc:
            handler._json(200, {'ok': False, 'error': str(exc)})
            return False
        except Exception:
            handler._json(200, {'ok': False, 'error': 'This change could not be completed. Try again.'})
            return False
        result = dict(result);result['ok'] = True
        handler._json(200, result)
        return True

    def touch(self, connected=False):
        with self.lock:
            self.last_seen = time.monotonic()
            if connected:
                self.connected = True

    def finish(self):
        with self.lock:
            self.saved = True

    def page(self):
        with open(PAGE, 'rb') as f:
            return f.read()

    def locked_page(self):
        return ('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<body style="background:#040F22;color:#DBECFF;font-family:sans-serif;padding:32px">'
                '<h2>MegaNexus</h2><p>Open this page by scanning the QR code shown on your TV.</p></body>')

    def logo(self):
        try:
            path = os.path.join(xbmcaddon.Addon('script.nuvio').getAddonInfo('path'), 'resources', 'media', 'nuvio_wordmark.png')
            with open(path, 'rb') as f:
                return f.read()
        except Exception:
            return b''

    # -- public
    @property
    def url(self):
        return 'http://%s:%d/?k=%s' % (self.host, self.port, self.key)

    @property
    def address(self):
        return 'http://%s:%d' % (self.host, self.port)

    def start(self):
        self.thread.start()
        return self

    def idle(self):
        with self.lock:
            return time.monotonic() - self.last_seen > IDLE_TIMEOUT

    def stop(self):
        try:
            if self.thread.is_alive():
                self.server.shutdown()  # waits for serve_forever; never call from a handler
        finally:
            self.server.server_close()
