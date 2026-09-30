# -*- coding: utf-8 -*-
"""Native Nuvio + Stremio account sync — no external Hub server required.

This replaces the whole web-Hub architecture with a small, self-contained
module that talks to Nuvio (api.nuvio.tv) and Stremio (api.strem.io) directly
from the addon. The user enters their account credentials in the addon
settings; we log in once, store the resulting token locally (like trakt.py
stores its token), and sync from then on using the stored token — the password
is never persisted.

Design mirrors resources/lib/trakt.py:
  * tokens live in profile_path()/nuvio_token.json and stremio_token.json
  * save/clear/refresh helpers, all failures degrade gracefully
  * stdlib urllib only

Everything here was reverse-engineered from Nuvio's open source + APK and
Stremio's official API, and was validated end-to-end in the previous Hub
implementation before being ported to Python.
"""
import json
import os
import time
import urllib.request
import urllib.error

try:
    import xbmc
except Exception:
    xbmc = None

from .common import profile_path, addon
from .safe_io import read_json, write_json

# ── endpoints / constants ──────────────────────────────────────────────────
NUVIO_URL = 'https://api.nuvio.tv'
# Public anon JWT (role=anon, exp 2031) shipped in Nuvio's own APK — safe to
# embed; it only permits what Nuvio's row-level-security allows a logged-in
# user to do.
NUVIO_ANON = ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
              'eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIiwiaWF0IjoxNzgxNTIxMzQ2LCJleHAiOjE5MzkyMDEzNDZ9.'
              'tmQaj682pwzehpqlgCDMnySOqiUvpgRbrE43T4VJpDI')
STREMIO_URL = 'https://api.strem.io'

_NUVIO_TOKEN = os.path.join(profile_path(), 'nuvio_token.json')
_STREMIO_TOKEN = os.path.join(profile_path(), 'stremio_token.json')

_UA = 'Mozilla/5.0 (compatible; NuvioHub Kodi)'


def _log(msg):
    if xbmc is None:
        return
    try:
        xbmc.log('[NuvioHub][sync] ' + str(msg), xbmc.LOGINFO)
    except Exception:
        pass


def _setting(key, default=''):
    try:
        return (addon().getSetting(key) or default).strip()
    except Exception:
        return default


def _setting_bool(key, default=False):
    v = _setting(key, '')
    if v == '':
        return default
    return v.lower() in ('true', '1', 'yes', 'on')


# ── low-level HTTP ─────────────────────────────────────────────────────────
def _http(url, payload=None, headers=None, method='GET', timeout=10):
    data = None
    hdrs = {'Accept': 'application/json', 'User-Agent': _UA}
    if headers:
        hdrs.update(headers)
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        hdrs['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode('utf-8', 'replace')
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8', 'replace')
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {}
        msg = (parsed.get('error_description') or parsed.get('msg')
               or parsed.get('message') or parsed.get('error') or ('HTTP %s' % e.code))
        raise RuntimeError(str(msg))
    # other exceptions bubble up to the caller


# ═══════════════════════════════════════════════════════════════════════════
# NUVIO  (self-hosted Supabase: GoTrue auth + PostgREST RPCs)
# ═══════════════════════════════════════════════════════════════════════════
class Nuvio:
    @staticmethod
    def token():
        return read_json(_NUVIO_TOKEN, {}) or {}

    @staticmethod
    def save_token(data):
        d = dict(data or {})
        d.setdefault('created_at', int(time.time()))
        write_json(_NUVIO_TOKEN, d)

    @staticmethod
    def clear():
        # A deleted primary is otherwise recovered from the previous login backup.
        write_json(_NUVIO_TOKEN, {})
        try:
            os.remove(_NUVIO_TOKEN + '.bak')
        except FileNotFoundError:
            pass

    @staticmethod
    def is_linked():
        return bool(Nuvio.token().get('access_token'))

    @staticmethod
    def authenticate(email, password):
        """Fetch a session without committing a cancelled UI operation."""
        body = _http(
            NUVIO_URL + '/auth/v1/token?grant_type=password',
            payload={'email': email, 'password': password},
            headers={'apikey': NUVIO_ANON}, method='POST')
        if not body.get('access_token'):
            raise RuntimeError('login failed: no access_token')
        return {
            'access_token': body.get('access_token'),
            'refresh_token': body.get('refresh_token'),
            'expires_in': int(body.get('expires_in') or 3600),
            'created_at': int(time.time()),
            'user_id': (body.get('user') or {}).get('id'),
            'email': email,
        }

    @staticmethod
    def login(email, password):
        Nuvio.save_token(Nuvio.authenticate(email, password))
        return True

    @staticmethod
    def _ensure_token():
        data = Nuvio.token()
        if not data.get('access_token'):
            raise RuntimeError('not linked to Nuvio')
        created = int(data.get('created_at') or 0)
        exp = int(data.get('expires_in') or 3600)
        if (created + exp - 60) > int(time.time()):
            return data
        # refresh
        if not data.get('refresh_token'):
            return data
        try:
            body = _http(
                NUVIO_URL + '/auth/v1/token?grant_type=refresh_token',
                payload={'refresh_token': data.get('refresh_token')},
                headers={'apikey': NUVIO_ANON}, method='POST')
            if body.get('access_token'):
                current = Nuvio.token()
                if current.get('access_token') != data.get('access_token'):
                    return current  # A newer login or logout wins over this refresh.
                Nuvio.save_token({
                    'access_token': body.get('access_token'),
                    'refresh_token': body.get('refresh_token') or data.get('refresh_token'),
                    'expires_in': int(body.get('expires_in') or 3600),
                    'created_at': int(time.time()),
                    'user_id': (body.get('user') or {}).get('id') or data.get('user_id'),
                    'email': data.get('email'),
                    'profile_index': current.get('profile_index'),
                    'profile_name': current.get('profile_name'),
                    'uses_primary_addons': current.get('uses_primary_addons', False),
                })
                return Nuvio.token()
        except Exception as e:
            _log('nuvio refresh failed: %s' % e)
        return data

    @staticmethod
    def _rpc(fn, params, timeout=9):
        data = Nuvio._ensure_token()
        return _http(
            NUVIO_URL + '/rest/v1/rpc/' + fn,
            payload=params or {},
            headers={'apikey': NUVIO_ANON,
                     'Authorization': 'Bearer %s' % data.get('access_token')},
            method='POST', timeout=timeout)

    @staticmethod
    def _profile_id():
        """Nuvio sync RPCs need the integer profile_index (NOT the UUID id)."""
        data = Nuvio.token()
        cached = data.get('profile_index')
        try:
            n = int(cached)
            if n > 0:
                return n
        except Exception:
            pass
        rows = Nuvio.profiles()
        if len(rows) != 1:
            raise ValueError('Choose your Nuvio profile in Settings > Nuvio account before importing.')
        Nuvio.select_profile(rows[0])
        return rows[0]['profile_index']

    @staticmethod
    def profiles():
        rows = Nuvio._unwrap_list(Nuvio._rpc('sync_pull_profiles', {}), ('profiles', 'data'))
        profiles = []
        for row in rows:
            if not isinstance(row, dict):continue
            try:index = int(row.get('profile_index', row.get('profileIndex', row.get('index'))))
            except (ValueError, TypeError):continue
            if index > 0:
                profiles.append({'profile_index':index, 'profile_name':str(row.get('name') or 'Profile %d' % index),
                                 'uses_primary_addons':row.get('uses_primary_addons') is True})
        if not profiles:raise ValueError('No Nuvio profiles were returned. Create a profile in Nuvio, then retry.')
        return profiles

    @staticmethod
    def select_profile(profile):
        data = Nuvio.token()
        if not data.get('access_token'):raise ValueError('Sign in to Nuvio first.')
        data.update(profile_index=int(profile['profile_index']), profile_name=profile['profile_name'])
        data['uses_primary_addons'] = profile.get('uses_primary_addons') is True
        Nuvio.save_token(data)

    # ── mappers: NuvioHub ⇄ Nuvio ──
    @staticmethod
    def _addons_to_nuvio(providers):
        out, seen = [], set()
        for p in providers or []:
            url = (p.get('manifest_url') or p.get('transportUrl') or p.get('url') or '').strip()
            if not url.lower().startswith(('http://', 'https://')):
                continue
            k = url.lower()
            if k in seen:
                continue
            seen.add(k)
            # Exact AddonPushItem shape from Nuvio's client: url/name/enabled/sort_order.
            out.append({
                'url': _ensure_manifest_suffix(url),
                'name': str(p.get('name') or ''),
                'enabled': p.get('enabled') is not False,
                'sort_order': len(out),
            })
        return out

    @staticmethod
    def _addons_to_dex(addons):
        out, seen = [], set()
        for a in addons or []:
            url = (a.get('url') or a.get('transportUrl') or a.get('manifestUrl')
                   or a.get('manifest_url') or '').strip()
            if not url.lower().startswith(('http://', 'https://')):
                continue
            k = url.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append({'manifest_url': url, 'name': str(a.get('name') or '')})
        return out

    @staticmethod
    def _progress_to_nuvio(rows):
        out = []
        for r in rows or []:
            cid = r.get('imdb_id') or r.get('tmdb_id') or r.get('canonical_id') or ''
            if not cid:
                continue
            is_series = (r.get('media_type') in ('tv', 'series') or r.get('season') is not None)
            out.append({
                'content_id': str(cid),
                'content_type': 'series' if is_series else 'movie',
                'video_id': str(r.get('video_id') or cid),
                'season': int(r['season']) if r.get('season') is not None else None,
                'episode': int(r['episode']) if r.get('episode') is not None else None,
                'position': int(round((float(r.get('position') or 0)) * 1000)),
                'duration': int(round((float(r.get('duration') or 0)) * 1000)),
                'last_watched': int(r.get('updated_at') or time.time()),
                'progress_key': r.get('progress_key') or ('%s:%s' % (cid, r.get('video_id') or '')),
            })
        return out

    @staticmethod
    def _progress_to_dex(entries):
        out = []
        for e in entries or []:
            cid = e.get('content_id') or ''
            out.append({
                'imdb_id': cid if cid.startswith('tt') else '',
                'tmdb_id': '' if cid.startswith('tt') else cid,
                'canonical_id': cid,
                'media_type': 'tv' if e.get('content_type') == 'series' else 'movie',
                'video_id': e.get('video_id') or cid,
                'season': e.get('season'),
                'episode': e.get('episode'),
                'position': (float(e.get('position') or 0)) / 1000.0,
                'duration': (float(e.get('duration') or 0)) / 1000.0,
                'updated_at': int(e.get('last_watched') or time.time()),
                'progress_key': e.get('progress_key') or '',
            })
        return out

    # ── high-level sync ops ──
    @staticmethod
    def _unwrap_list(payload, keys):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in keys:
                val = payload.get(key)
                if isinstance(val, list):
                    return val
                if isinstance(val, str):
                    try:
                        parsed = json.loads(val)
                        if isinstance(parsed, list):
                            return parsed
                    except Exception:
                        pass
        return []

    @staticmethod
    def _extract_addons_from_payload(payload):
        """Extract manifest URLs from profile/state payloads used by Nuvio versions."""
        out, seen = [], set()
        def walk(node):
            if isinstance(node, str):
                text = node.strip()
                if text.startswith(('http://', 'https://')) and 'manifest' in text.lower():
                    key = text.lower().rstrip('/')
                    if key not in seen:
                        seen.add(key); out.append({'manifest_url': text, 'name': ''})
                else:
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, (dict, list)): walk(parsed)
                    except Exception:
                        pass
                return
            if isinstance(node, list):
                for item in node: walk(item)
                return
            if not isinstance(node, dict): return
            url = node.get('transportUrl') or node.get('manifestUrl') or node.get('manifest_url') or node.get('url')
            if url:
                walk(url)
            for key in ('addons','installedAddons','addonCollection','providers','sources','profile_data','settings','data','payload'):
                if key in node: walk(node.get(key))
        walk(payload)
        return out

    @staticmethod
    def _rest_get(path, timeout=8):
        """Direct PostgREST table read — same access path Nuvio's own client uses."""
        data = Nuvio._ensure_token()
        return _http(
            NUVIO_URL + path,
            headers={'apikey': NUVIO_ANON,
                     'Authorization': 'Bearer %s' % data.get('access_token')},
            method='GET', timeout=timeout)

    @staticmethod
    def sync_addons(providers, direction='both'):
        """Sync installed addons with the Nuvio account.

        Verified against Nuvio's open source (NuvioMobile AddonRepository.kt):
          * PULL: there is NO ``sync_pull_addons`` RPC on api.nuvio.tv — the
            old probe 404'd every time. Nuvio's app reads the ``addons`` table
            directly:  GET /rest/v1/addons?profile_id=eq.N&order=sort_order.asc
            Rows may store the base URL, so ``/manifest.json`` is appended when
            missing (mirrors Nuvio's ensureManifestSuffix).
          * PUSH: RPC ``sync_push_addons(p_profile_id, p_addons,
            p_origin_client_id)`` with rows shaped {url, name, enabled,
            sort_order}. Nuvio always pushes the full list (replace-set
            semantics), so we MUST pull + merge before pushing — the old
            push-first order would have wiped Nuvio-only addons.
        """
        pid = Nuvio._profile_id()
        merged = list(providers or [])
        if direction != 'push':
            addon_pid = 1 if Nuvio.token().get('uses_primary_addons') else pid
            rows = Nuvio._rest_get(
                '/rest/v1/addons?profile_id=eq.%d'
                '&select=url,name,enabled,sort_order&order=sort_order.asc' % addon_pid)
            remote_dex, disabled = [], 0
            for r in (rows if isinstance(rows, list) else []):
                if not isinstance(r, dict):
                    continue
                url = _ensure_manifest_suffix(str(r.get('url') or '').strip())
                if not url.lower().startswith(('http://', 'https://')):
                    continue
                if r.get('enabled') is False:
                    disabled += 1
                    continue
                remote_dex.append({'manifest_url': url, 'name': str(r.get('name') or '')})
            _log('nuvio addons pull: %d enabled, %d disabled skipped (profile %s)'
                 % (len(remote_dex), disabled, pid))
            merged = _merge_by_url(merged, remote_dex)
        if direction != 'pull':
            addons = Nuvio._addons_to_nuvio(merged)
            if addons:
                Nuvio._rpc('sync_push_addons', {
                    'p_profile_id': pid, 'p_addons': addons,
                    'p_origin_client_id': 'dexhub-kodi'})
                _log('nuvio addons push: %d rows' % len(addons))
        return merged

    @staticmethod
    def sync_collections(collections, direction='both'):
        pid = Nuvio._profile_id()
        merged = collections or []
        if direction != 'pull':
            Nuvio._rpc('sync_push_collections',
                       {'p_profile_id': pid, 'p_collections_json': collections or []})
        if direction != 'push':
            rows = Nuvio._rpc('sync_pull_collections', {'p_profile_id': pid})
            remote = []
            candidates = Nuvio._unwrap_list(rows, ('collections', 'items', 'data', 'collections_json'))
            if candidates:
                # Supabase RPC can return either the collection list directly
                # or one wrapper row containing collections_json.
                if len(candidates) == 1 and isinstance(candidates[0], dict) and 'collections_json' in candidates[0]:
                    raw = candidates[0].get('collections_json')
                    if isinstance(raw, str):
                        try: raw = json.loads(raw)
                        except Exception: raw = []
                    remote = raw if isinstance(raw, list) else []
                else:
                    remote = candidates
            elif isinstance(rows, dict):
                raw = rows.get('collections_json')
                if isinstance(raw, str):
                    try: raw = json.loads(raw)
                    except Exception: raw = []
                remote = raw if isinstance(raw, list) else []
            merged = _merge_collections(collections, remote)
        return merged

    # ── mappers: NuvioHub favourites ⇄ Nuvio saved library ──
    # Contract verified against NuvioWeb (js/core/profile/
    # savedLibrarySyncService.js): RPCs sync_pull_library(p_profile_id,
    # p_limit, p_offset) and sync_push_library(p_profile_id, p_items), with
    # rows shaped content_id / content_type / name / poster / poster_shape /
    # background / description / release_info / imdb_rating / genres /
    # addon_base_url / added_at (epoch ms).
    _LIB_PAGE = 500

    @staticmethod
    def _library_to_nuvio(rows):
        out, seen = [], set()
        for r in rows or []:
            cid = str((r or {}).get('canonical_id') or '').strip()
            if not cid or cid in seen:
                continue
            seen.add(cid)
            mt = str(r.get('media_type') or 'movie').strip().lower()
            try:
                added = int(float(r.get('added_at') or 0)) * 1000
            except Exception:
                added = 0
            out.append({
                'content_id': cid,
                'content_type': 'series' if mt in ('series', 'show', 'tv', 'anime') else 'movie',
                'name': r.get('title') or 'Untitled',
                'poster': r.get('poster') or None,
                'poster_shape': 'POSTER',
                'background': r.get('background') or None,
                'description': r.get('plot') or '',
                'release_info': str(r.get('year') or '') or '',
                'imdb_rating': None,
                'genres': [],
                'addon_base_url': None,
                'added_at': added or int(time.time() * 1000),
            })
        return out

    @staticmethod
    def _library_to_dex(rows):
        out = []
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            cid = r.get('content_id') or r.get('contentId') or r.get('id') or ''
            if not cid:
                continue
            ctype = str(r.get('content_type') or r.get('contentType') or 'movie').lower()
            year = str(r.get('release_info') or r.get('releaseInfo') or '')[:4]
            out.append({
                'canonical_id': str(cid),
                'media_type': 'series' if ctype in ('series', 'show', 'tv') else 'movie',
                'title': r.get('name') or r.get('title') or 'Untitled',
                'poster': r.get('poster') or '',
                'background': r.get('background') or '',
                'plot': r.get('description') or '',
                'year': int(year) if year.isdigit() else 0,
            })
        return out

    @staticmethod
    def sync_library(rows, direction='both'):
        """Sync the saved library (NuvioHub favourites) with Nuvio.

        v4.8.1: Nuvio's own clients keep the saved library in this RPC pair,
        so a title added on the phone shows up in NuvioHub's favourites and
        the reverse. Pull is paged exactly like NuvioWeb does.
        """
        pid = Nuvio._profile_id()
        merged = list(rows or [])
        if direction != 'push':
            remote_rows, offset = [], 0
            for _page in range(20):          # 10k items ceiling, same as web
                page = Nuvio._rpc('sync_pull_library', {
                    'p_profile_id': pid, 'p_limit': Nuvio._LIB_PAGE,
                    'p_offset': offset})
                batch = page if isinstance(page, list) else []
                remote_rows.extend(batch)
                if len(batch) < Nuvio._LIB_PAGE:
                    break
                offset += Nuvio._LIB_PAGE
            remote_dex = Nuvio._library_to_dex(remote_rows)
            _log('nuvio library pull: %d item(s)' % len(remote_dex))
            merged = _merge_library(merged, remote_dex)
        if direction != 'pull':
            items = Nuvio._library_to_nuvio(merged)
            if items:
                Nuvio._rpc('sync_push_library', {'p_profile_id': pid, 'p_items': items})
                _log('nuvio library push: %d item(s)' % len(items))
        return merged

    @staticmethod
    def sync_progress(rows, direction='both'):
        pid = Nuvio._profile_id()
        merged = rows or []
        if direction != 'pull':
            entries = Nuvio._progress_to_nuvio(rows)
            if entries:
                Nuvio._rpc('sync_push_watch_progress', {'p_profile_id': pid, 'p_entries': entries})
        if direction != 'push':
            remote = Nuvio._rpc('sync_pull_watch_progress', {'p_profile_id': pid})
            remote_dex = Nuvio._progress_to_dex(remote if isinstance(remote, list) else [])
            merged = _merge_progress(rows, remote_dex)
        return merged


# ═══════════════════════════════════════════════════════════════════════════
# STREMIO  (official API: POST /api/<method>)
# ═══════════════════════════════════════════════════════════════════════════
class Stremio:
    LIB = 'libraryItem'

    @staticmethod
    def token():
        return read_json(_STREMIO_TOKEN, {}) or {}

    @staticmethod
    def save_token(data):
        write_json(_STREMIO_TOKEN, dict(data or {}))

    @staticmethod
    def clear():
        try:
            os.remove(_STREMIO_TOKEN)
        except FileNotFoundError:
            pass

    @staticmethod
    def is_linked():
        return bool(Stremio.token().get('authKey'))

    @staticmethod
    def _api(method, params):
        body = _http(STREMIO_URL + '/api/' + method, payload=params or {}, method='POST')
        if isinstance(body, dict) and body.get('error'):
            err = body['error']
            msg = err.get('message') if isinstance(err, dict) else str(err)
            raise RuntimeError('Stremio %s: %s' % (method, msg))
        return body.get('result') if isinstance(body, dict) else None

    @staticmethod
    def login(email, password):
        result = Stremio._api('login', {'email': email, 'password': password})
        if not result or not result.get('authKey'):
            raise RuntimeError('login failed: no authKey')
        Stremio.save_token({
            'authKey': result.get('authKey'),
            'user_id': (result.get('user') or {}).get('_id'),
            'email': email,
            'created_at': int(time.time()),
        })
        return True

    @staticmethod
    def _auth_key():
        data = Stremio.token()
        if not data.get('authKey'):
            raise RuntimeError('not linked to Stremio')
        return data['authKey']

    # ── mappers ──
    @staticmethod
    def _addons_to_dex(addons):
        out = []
        for a in addons or []:
            manifest = a.get('manifest') or {}
            url = a.get('transportUrl') or manifest.get('url') or ''
            if url:
                out.append({'manifest_url': url, 'name': manifest.get('name') or a.get('transportName') or ''})
        return out

    @staticmethod
    def _fetch_manifest(url):
        try:
            return _http(url, method='GET', timeout=12)
        except Exception:
            return None

    @staticmethod
    def _library_to_dex(items):
        out = []
        for it in items or []:
            if not it or it.get('removed'):
                continue
            st = it.get('state') or {}
            if not st.get('timeOffset') and not st.get('duration'):
                continue
            is_series = it.get('type') == 'series'
            _id = it.get('_id') or ''
            dur = float(st.get('duration') or 0)
            off = float(st.get('timeOffset') or 0)
            out.append({
                'imdb_id': _id if _id.startswith('tt') else '',
                'tmdb_id': '' if _id.startswith('tt') else _id,
                'canonical_id': _id,
                'media_type': 'tv' if is_series else 'movie',
                'title': it.get('name') or '',
                'video_id': st.get('video_id') or _id,
                'season': st.get('season') if is_series else None,
                'episode': st.get('episode') if is_series else None,
                'position': off / 1000.0,
                'duration': dur / 1000.0,
                'percent': (min(100.0, off / dur * 100.0) if dur else 0.0),
                'updated_at': int(_parse_ts(it.get('_mtime'))),
            })
        return out

    @staticmethod
    def _progress_to_stremio(rows, existing_by_id):
        changes = []
        for r in rows or []:
            _id = r.get('imdb_id') or r.get('canonical_id') or r.get('tmdb_id') or ''
            if not _id:
                continue
            is_series = (r.get('media_type') in ('tv', 'series') or r.get('season') is not None)
            mtime = int(r.get('updated_at') or time.time())
            iso = _to_iso(mtime)
            prev = existing_by_id.get(_id)
            item = dict(prev) if prev else {
                '_id': str(_id), 'name': r.get('title') or '',
                'type': 'series' if is_series else 'movie',
                'poster': r.get('poster') or '', 'background': r.get('background') or '',
                'logo': r.get('clearlogo') or '', 'removed': False, 'temp': True,
                '_ctime': iso,
            }
            item['_mtime'] = iso
            state = dict(item.get('state') or {})
            pct = float(r.get('percent') or 0)
            state.update({
                'timeOffset': int(round((float(r.get('position') or 0)) * 1000)),
                'duration': int(round((float(r.get('duration') or 0)) * 1000)),
                'video_id': (str(r.get('video_id') or ('%s:%s:%s' % (_id, r.get('season'), r.get('episode'))))
                             if is_series else str(_id)),
                'lastWatched': iso,
                'watched': iso if pct >= 95 else (state.get('watched') or ''),
                'flaggedWatched': 1 if pct >= 95 else 0,
            })
            if is_series:
                state['season'] = int(r.get('season') or 0)
                state['episode'] = int(r.get('episode') or 0)
            item['state'] = state
            changes.append(item)
        return changes

    # ── high-level ops ──
    @staticmethod
    def sync_addons(providers, direction='both'):
        key = Stremio._auth_key()
        merged = providers or []
        remote = Stremio._api('addonCollectionGet', {'authKey': key, 'update': True}) or {}
        remote_addons = remote.get('addons') or []
        if direction != 'push':
            merged = _merge_by_url(providers, Stremio._addons_to_dex(remote_addons))
        if direction != 'pull':
            # build collection: keep protected/existing, fetch manifests for new
            remote_by_url = {}
            for a in remote_addons:
                u = a.get('transportUrl') or (a.get('manifest') or {}).get('url') or ''
                if u:
                    remote_by_url[u] = a
            collection, seen = [], set()
            for a in remote_addons:
                if (a.get('flags') or {}).get('protected'):
                    collection.append(a)
                    seen.add(a.get('transportUrl') or '')
            for p in merged:
                url = (p.get('manifest_url') or p.get('transportUrl') or p.get('url') or '')
                if not url or url in seen:
                    continue
                seen.add(url)
                if url in remote_by_url:
                    collection.append(remote_by_url[url])
                else:
                    manifest = Stremio._fetch_manifest(url)
                    if manifest and manifest.get('id'):
                        collection.append({'transportUrl': url,
                                           'transportName': manifest.get('name') or '',
                                           'manifest': manifest, 'flags': {}})
            Stremio._api('addonCollectionSet', {'authKey': key, 'addons': collection})
        return merged

    @staticmethod
    def sync_progress(rows, direction='both'):
        key = Stremio._auth_key()
        merged = rows or []
        items = Stremio._api('datastoreGet', {'authKey': key, 'collection': Stremio.LIB, 'all': True}) or []
        by_id = {}
        for it in items:
            if it and it.get('_id'):
                by_id[it['_id']] = it
        if direction != 'push':
            merged = _merge_progress(rows, Stremio._library_to_dex(items))
        if direction != 'pull':
            changes = Stremio._progress_to_stremio(merged, by_id)
            # v4.4.2: never push a datetime stremio-core would choke on —
            # this also stops old poisoned _ctime values from re-propagating
            # through the dict(prev) clone path.
            changes = [_sanitize_stremio_item(c)[0] for c in (changes or [])]
            if changes:
                Stremio._api('datastorePut', {'authKey': key, 'collection': Stremio.LIB, 'changes': changes})
        return merged

    @staticmethod
    def repair_library():
        """v4.4.2: scan the entire Stremio cloud library and rewrite every
        item whose datetime fields stremio-core cannot parse. Heals libraries
        poisoned by older writers regardless of which app wrote the value.
        Returns (scanned, repaired)."""
        key = Stremio._auth_key()
        items = Stremio._api('datastoreGet', {'authKey': key, 'collection': Stremio.LIB, 'all': True}) or []
        fixes = []
        for it in items:
            fixed, changed = _sanitize_stremio_item(it)
            if changed:
                fixes.append(fixed)
        if fixes:
            Stremio._api('datastorePut', {'authKey': key, 'collection': Stremio.LIB, 'changes': fixes})
        return len(items), len(fixes)


# ── merge helpers (shared) ─────────────────────────────────────────────────
def _ensure_manifest_suffix(url):
    """Mirror Nuvio's ensureManifestSuffix: `addons` table rows may store the
    base addon URL without the trailing /manifest.json."""
    if not url:
        return url
    path, sep, query = url.partition('?')
    path = path.rstrip('/')
    if not path.endswith('/manifest.json'):
        path += '/manifest.json'
    return path + (('?' + query) if sep else '')


def _merge_by_url(local, remote):
    seen = {}
    for x in local or []:
        u = (x.get('manifest_url') or x.get('transportUrl') or x.get('url') or '').lower()
        if u:
            seen[u] = x
    for x in remote or []:
        u = (x.get('manifest_url') or x.get('transportUrl') or x.get('url') or '').lower()
        if u and u not in seen:
            seen[u] = x
    return list(seen.values())


def _merge_collections(local, remote):
    by_id = {}
    for c in local or []:
        by_id[c.get('id') or c.get('name')] = c
    for c in remote or []:
        k = c.get('id') or c.get('name')
        if k not in by_id:
            by_id[k] = c
    return list(by_id.values())


def _merge_progress(local, remote):
    def key(e):
        return '%s:%s' % (e.get('canonical_id') or e.get('imdb_id') or e.get('tmdb_id'), e.get('video_id') or '')
    m = {}
    for e in local or []:
        m[key(e)] = e
    for e in remote or []:
        k = key(e)
        cur = m.get(k)
        if not cur or (int(e.get('updated_at') or 0) > int(cur.get('updated_at') or 0)):
            m[k] = e
    return list(m.values())


_ISO_STRICT_RE = None


def _iso_is_valid(value):
    """True when stremio-core's chrono parser will accept this string."""
    global _ISO_STRICT_RE
    if _ISO_STRICT_RE is None:
        import re as _re
        # re.ASCII is essential: Python's \d matches Arabic-Indic digits,
        # but stremio-core's chrono parser rejects them as invalid characters.
        _ISO_STRICT_RE = _re.compile(
            r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$', _re.ASCII)
    return bool(value) and bool(_ISO_STRICT_RE.match(str(value)))


def _coerce_iso(value, fallback_epoch=None):
    """Best-effort: any timestampish input → strict UTC ISO with Z."""
    if _iso_is_valid(value):
        return str(value)
    text = str(value or '').strip().replace(' ', 'T')
    if text:
        try:
            import calendar
            t = time.strptime(text[:19], '%Y-%m-%dT%H:%M:%S')
            return _to_iso(calendar.timegm(t))
        except Exception:
            pass
    return _to_iso(fallback_epoch if fallback_epoch is not None else time.time())


def _sanitize_stremio_item(item):
    """v4.4.2: heal every datetime field stremio-core parses strictly.

    A single library item with a malformed `_ctime` (a space instead of the
    'T', localized digits, an empty string…) makes stremio-core reject the
    WHOLE LibraryItemsPulledFromAPI response — the exact
    'result[N]._ctime: input contains invalid characters' failure seen on
    web.strem.io. Poisoned values also self-perpetuate because the sync
    clones existing items via dict(prev). Sanitize on every write AND on
    demand via repair_library().
    Returns (item, changed).
    """
    if not isinstance(item, dict):
        return item, False
    changed = False
    out = dict(item)
    mtime_epoch = _parse_ts(out.get('_mtime')) if out.get('_mtime') else time.time()
    for key in ('_mtime', '_ctime'):
        if not _iso_is_valid(out.get(key)):
            out[key] = _coerce_iso(out.get(key), fallback_epoch=mtime_epoch)
            changed = True
    state = out.get('state')
    if isinstance(state, dict):
        state = dict(state)
        if state.get('lastWatched') and not _iso_is_valid(state.get('lastWatched')):
            state['lastWatched'] = _coerce_iso(state.get('lastWatched'), fallback_epoch=mtime_epoch)
            changed = True
        if state.get('lastVidReleased') and not _iso_is_valid(state.get('lastVidReleased')):
            state.pop('lastVidReleased', None)
            changed = True
        if 'watched' in state and not isinstance(state.get('watched'), str):
            state['watched'] = str(state.get('watched') or '')
            changed = True
        if changed:
            out['state'] = state
    return out, changed


def _parse_ts(iso):
    if not iso:
        return time.time()
    try:
        import calendar
        t = time.strptime(str(iso)[:19], '%Y-%m-%dT%H:%M:%S')
        return calendar.timegm(t)
    except Exception:
        return time.time()


def _to_iso(epoch):
    try:
        return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(int(epoch)))
    except Exception:
        return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())


# ═══════════════════════════════════════════════════════════════════════════
# ORCHESTRATION — gather local data, sync enabled targets, write back
# ═══════════════════════════════════════════════════════════════════════════
def _gather_providers():
    try:
        from . import store
        rows = store.list_providers() or []
    except Exception:
        return []
    return [{'manifest_url': r.get('manifest_url', ''), 'name': r.get('name', '')}
            for r in rows if r.get('manifest_url')]


def _merge_library(local, remote):
    """Union by canonical id; the newer 'added_at' wins on a collision."""
    by_id = {}
    for row in list(local or []) + list(remote or []):
        cid = str((row or {}).get('canonical_id') or '').strip()
        if not cid:
            continue
        prev = by_id.get(cid)
        if not prev:
            by_id[cid] = row
            continue
        try:
            if float(row.get('added_at') or 0) > float(prev.get('added_at') or 0):
                by_id[cid] = row
        except Exception:
            pass
    return list(by_id.values())


def _gather_library(limit=1000):
    try:
        from .. import favorites_store
        return favorites_store.list_favorites(limit=limit) or []
    except Exception:
        return []


def _writeback_library(rows):
    if not isinstance(rows, list):
        return 0
    try:
        from .. import favorites_store
    except Exception:
        return 0
    try:
        have = favorites_store.favorite_keys()
    except Exception:
        have = set()
    added, failed = 0, []
    for r in rows:
        mt = str(r.get('media_type') or 'movie')
        cid = str(r.get('canonical_id') or '')
        if not cid or (mt, cid) in have:
            continue
        try:
            favorites_store.add(mt, cid, r.get('title') or cid,
                                poster=r.get('poster') or '',
                                background=r.get('background') or '',
                                year=int(r.get('year') or 0),
                                plot=r.get('plot') or '',
                                source='nuvio')
            added += 1
        except Exception as exc:
            failed.append('%s (%s)' % (cid, str(exc)[:50]))
    _log('library writeback: %d added%s'
         % (added, (', %d FAILED -> %s' % (len(failed), ' | '.join(failed[:3])))
            if failed else ''))
    return added


def _gather_collections():
    try:
        from .. import collection_sets
        return collection_sets.list_sets() or []
    except Exception:
        return []


def _gather_progress(limit=400):
    try:
        from . import playback_store
        return playback_store.list_continue_items(limit=limit) or []
    except Exception:
        return []


def _writeback_providers(providers):
    if not isinstance(providers, list):
        return 0
    try:
        from . import store
        from .. import collection_sets
    except Exception:
        return 0
    have = set((r.get('manifest_url') or '').lower() for r in (store.list_providers() or []))
    added, failed = 0, []
    for p in providers:
        url = (p.get('manifest_url') or '').lower()
        if not url or url in have:
            continue
        try:
            collection_sets.ensure_addon_registered(p.get('manifest_url'))
            added += 1
            have.add(url)
        except Exception as exc:
            # v4.7.9: this used to be a bare `continue`. A pulled addon whose
            # manifest was briefly unreachable vanished without a trace, and
            # the sync still reported success with "+0 addons".
            failed.append('%s (%s)' % (p.get('manifest_url') or '?', str(exc)[:60]))
    if failed:
        _log('addon writeback: %d added, %d FAILED -> %s'
             % (added, len(failed), ' | '.join(failed[:5])))
    else:
        _log('addon writeback: %d added' % added)
    return added


def _writeback_collections(rows):
    if not isinstance(rows, list):
        return 0
    try:
        from .. import collection_sets
        return int(collection_sets.import_sets(rows) or 0)
    except Exception as exc:
        _log('collection writeback failed: %s' % exc)
        return 0


def _writeback_progress(rows):
    if not isinstance(rows, list):
        return 0
    try:
        from . import playback_store
    except Exception:
        return 0
    pending = []
    for r in rows:
        try:
            cid = r.get('canonical_id') or r.get('imdb_id') or r.get('tmdb_id') or ''
            if not cid:
                continue
            pending.append({
                'media_type': r.get('media_type') or 'movie',
                'canonical_id': cid, 'video_id': r.get('video_id') or cid,
                'title': r.get('title', ''),
                'provider_name': r.get('provider_name', ''),
                'poster': r.get('poster', ''),
                'background': r.get('background', ''),
                'clearlogo': r.get('clearlogo', ''),
                'season': r.get('season'), 'episode': r.get('episode'),
                'position': float(r.get('position') or 0.0),
                'duration': float(r.get('duration') or 0.0),
                'percent': float(r.get('percent') or 0.0),
                'stream_url': '', 'event_type': 'account_sync',
                'ext_updated_at': r.get('updated_at'),
                'tmdb_id': r.get('tmdb_id', ''),
                'imdb_id': r.get('imdb_id', ''),
                'tvdb_id': r.get('tvdb_id', ''),
                'show_tmdb_id': r.get('show_tmdb_id', ''),
                'native_server_id': r.get('native_server_id', ''),
                'native_item_id': r.get('native_item_id', ''),
            })
        except Exception:
            continue
    if not pending:
        return 0
    if hasattr(playback_store, 'upsert_entries'):
        # Pulled cloud rows must not mark the database dirty again; doing so
        # creates a pull -> write -> dirty -> sync feedback loop.
        return int(playback_store.upsert_entries(pending, mark_dirty=False) or 0)
    # Compatibility for older embedded test/runtime modules.
    written = 0
    for row in pending:
        try:
            args = (
                row['media_type'], row['canonical_id'], row['video_id'],
                row['title'], row['provider_name'], row['poster'],
                row['background'], row['clearlogo'], row['season'],
                row['episode'], row['position'], row['duration'],
                row['percent'], row['stream_url'], row['event_type'])
            kwargs = {
                'ext_updated_at': row['ext_updated_at'],
                'tmdb_id': row['tmdb_id'], 'imdb_id': row['imdb_id'],
                'tvdb_id': row['tvdb_id'],
                'show_tmdb_id': row['show_tmdb_id'],
                'mark_dirty': False,
            }
            try:
                playback_store.upsert_entry(*args, **kwargs)
            except TypeError:
                # Only for an older embedded store without the new flag.
                kwargs.pop('mark_dirty', None)
                playback_store.upsert_entry(*args, **kwargs)
            written += 1
        except Exception:
            continue
    return written


def enabled_targets():
    """Which services are both linked and enabled in settings.

    v4.7.9: a LINKED account whose master toggle was never written is
    treated as enabled, and the toggle is repaired on the spot. Accounts
    paired by QR never got that toggle (only the password path wrote it),
    so they sat linked-but-disabled forever and every sync run reported
    'no linked/enabled accounts' — silently, because nothing surfaced it.
    An explicit 'false' is still respected: only the unwritten state heals.
    """
    out = []
    for svc, linked in (('nuvio', Nuvio.is_linked()),):
        if not linked:
            continue
        raw = str(_setting('%s_sync_enabled' % svc, '') or '').strip().lower()
        if raw in ('true', '1', 'yes', 'on'):
            out.append(svc)
            continue
        if raw in ('false', '0', 'no', 'off'):
            _log('%s is linked but its sync toggle is OFF — skipping' % svc)
            continue
        # never written: linking implied consent to sync
        try:
            addon().setSetting('%s_sync_enabled' % svc, 'true')
        except Exception:
            pass
        _log('%s was linked with no sync toggle — enabling it now' % svc)
        out.append(svc)
    return out


def _direction_for(svc):
    """v4.0.0: per-service direction. Falls back to the global setting when
    the service is set to 'Follow global' (or on legacy installs where the
    per-service setting does not exist yet)."""
    raw = _setting('%s_sync_direction' % svc, '')
    if raw in ('', 'Follow global', 'اتباع الإعداد العام'):
        raw = _setting('cloud_sync_direction', 'Two-way') or 'Two-way'
    if raw in ('Upload only', 'رفع فقط'):
        return 'push'
    if raw in ('Download only', 'سحب فقط'):
        return 'pull'
    return 'both'


def _sections_for(svc):
    """Per-service section toggles.

    v4.8.0: 'collections' was HARD-CODED to False, so the
    nuvio_sync_collections setting was dead — turning it on changed
    nothing and the section never ran. It now reads its setting like the
    others. Nuvio defaults to on (its sync_push/pull_collections RPCs are
    verified and it is the account users expect to carry everything);
    Stremio defaults to off because its API stores add-ons and library
    progress, not folder layouts — run_sync already reports that plainly.
    """
    return {
        'addons': _setting_bool('%s_sync_addons' % svc, True),
        'collections': _setting_bool('%s_sync_collections' % svc,
                                     svc == 'nuvio'),
        'progress': _setting_bool('%s_sync_progress' % svc, True),
        # v4.8.1: the saved library. Nuvio only — Stremio's own library is
        # already carried by its progress/library API in sync_progress.
        'library': (svc == 'nuvio') and _setting_bool('nuvio_sync_library', True),
    }


def _fingerprint(rows):
    """Stable short hash of a list (order-independent). '' on any failure."""
    try:
        import hashlib
        norm = sorted(
            json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            for r in (rows or []))
        return hashlib.sha1('\u0001'.join(norm).encode('utf-8', 'replace')).hexdigest()[:16]
    except Exception:
        return ''


_FP_FILE = os.path.join(profile_path(), 'account_sync_fp.json')


def _load_sync_state():
    return read_json(_FP_FILE, {}) or {}


def _save_sync_state(state):
    try:
        write_json(_FP_FILE, state)
    except Exception:
        pass


def run_sync(direction=None, targets=None, force_full=False, sections=None):
    """Synchronize selected sections independently.

    v4.0.0: `direction` and `sections` are now optional *overrides*. When
    None (the normal case), each service resolves its own direction and
    section toggles from its per-service settings, so Nuvio and Stremio are
    fully independent. A failure in one section never blocks the others.
    """
    targets = [svc for svc in (targets or enabled_targets()) if svc == 'nuvio']
    if not targets:
        return {'ok': False, 'error': 'no linked/enabled accounts'}

    svc_dir = dict((svc, direction or _direction_for(svc)) for svc in targets)
    svc_sections = dict((svc, dict(sections) if sections else _sections_for(svc))
                        for svc in targets)
    # Gather local data once for every section any service wants.
    want = {
        'addons': any(s.get('addons') for s in svc_sections.values()),
        'collections': any(s.get('collections') for s in svc_sections.values()),
        'progress': any(s.get('progress') for s in svc_sections.values()),
        'library': any(s.get('library') for s in svc_sections.values()),
    }
    addons = _gather_providers() if want['addons'] else []
    collections = _gather_collections() if want['collections'] else []
    progress = _gather_progress() if want['progress'] else []
    merged_library = _gather_library() if want['library'] else []

    state = {} if force_full else _load_sync_state()
    last_ok = int(state.get('last_ok_at') or 0)
    fp_addons = _fingerprint(addons)
    fp_collections = _fingerprint(collections)
    addons_changed = want['addons'] and (force_full or not fp_addons or state.get('fp_addons') != fp_addons)
    collections_changed = want['collections'] and (force_full or not fp_collections or state.get('fp_collections') != fp_collections)
    progress_delta_push = progress if (force_full or not last_ok) else [
        r for r in progress if int(r.get('updated_at') or 0) > last_ok]

    _log('sync plan: %s' % ' '.join(
        '%s[%s:%s]' % (svc, svc_dir[svc],
                       ','.join(k for k in ('addons', 'collections', 'progress')
                                if svc_sections[svc].get(k)) or 'none')
        for svc in targets))

    report=[]
    merged_addons=list(addons)
    merged_collections=list(collections)
    merged_progress=list(progress)

    for svc in targets:
        d = svc_dir[svc]
        sec = svc_sections[svc]
        impl = Nuvio if svc == 'nuvio' else Stremio
        section_report = {'service': svc, 'ok': False, 'direction': d, 'sections': {}}
        any_ok = False
        if svc == 'stremio' and sec.get('collections'):
            section_report['sections']['collections'] = {
                'ok': False,
                'error': 'Stremio account stores add-ons and library progress, not Kaptain folder layouts; use JSON import for collections.'
            }
        if svc == 'nuvio' and sec.get('collections'):
            # v5.4.9: the missing link. v4.8.0 fixed the dead setting read
            # but never added this call — the section was gathered, gated,
            # fingerprinted and counted in totals without a single RPC
            # firing. Same skip contract as addons: unchanged local data
            # pulls only, and a push-only direction with nothing new skips.
            try:
                c_dir = 'pull'  # Nuvio owns collection layout; never upload local presets.
                if c_dir != 'skip':
                    merged_collections = impl.sync_collections(merged_collections, c_dir)
                section_report['sections']['collections'] = {'ok': True, 'count': len(merged_collections)}
                any_ok = True
            except Exception as e:
                section_report['sections']['collections'] = {'ok': False, 'error': str(e)}
                _log('%s collections sync failed: %s' % (svc, e))
        if sec.get('addons'):
            try:
                a_dir = 'pull'  # Provider configuration belongs to the linked Nuvio account.
                if a_dir != 'skip':
                    merged_addons = impl.sync_addons(merged_addons, a_dir)
                section_report['sections']['addons'] = {'ok': True, 'count': len(merged_addons)}
                any_ok = True
            except Exception as e:
                section_report['sections']['addons'] = {'ok': False, 'error': str(e)}
                _log('%s addons sync failed: %s' % (svc, e))
        if sec.get('progress'):
            try:
                seed = progress_delta_push if d in ('both', 'push') else merged_progress
                merged_progress = impl.sync_progress(seed, d)
                section_report['sections']['progress'] = {'ok': True, 'count': len(merged_progress)}
                any_ok = True
            except Exception as e:
                section_report['sections']['progress'] = {'ok': False, 'error': str(e)}
                _log('%s progress sync failed: %s' % (svc, e))
        if sec.get('library') and hasattr(impl, 'sync_library'):
            # v4.8.1: the saved library (NuvioHub favourites) — Nuvio's own
            # clients keep it in sync_pull_library / sync_push_library.
            try:
                merged_library = impl.sync_library(merged_library, d)
                section_report['sections']['library'] = {'ok': True, 'count': len(merged_library)}
                any_ok = True
            except Exception as e:
                section_report['sections']['library'] = {'ok': False, 'error': str(e)}
                _log('%s library sync failed: %s' % (svc, e))
        section_report['ok'] = any_ok
        report.append(section_report)

    wb = {'providers': 0, 'collections': 0, 'progress': 0, 'library': 0}

    def _pulled(section):
        return any(svc_dir[s] != 'push' and svc_sections[s].get(section) for s in targets)

    if _pulled('addons'):
        wb['providers'] = _writeback_providers(merged_addons)
    if _pulled('collections'):
        wb['collections'] = _writeback_collections(merged_collections)
    if _pulled('progress'):
        wb['progress'] = _writeback_progress(merged_progress)
    if _pulled('library'):
        wb['library'] = _writeback_library(merged_library)

    ok=any(r.get('ok') for r in report)
    if ok:
        _save_sync_state({'last_ok_at':int(time.time()),'fp_addons':fp_addons,'fp_collections':fp_collections})
    try: addon().setSetting('last_account_sync_at', str(int(time.time())))
    except Exception: pass
    _log('sync result: providers +%d collections +%d progress %d library +%d'
         % (wb['providers'], wb['collections'], wb['progress'], wb['library']))
    return {'ok':ok,'report':report,'writeback':wb,
            'totals':{'addons':len(merged_addons),'collections':len(merged_collections),
                      'progress':len(merged_progress),'library':len(merged_library)}}
