# -*- coding: utf-8 -*-
"""Native Emby/Jellyfin client for Nuvio Hub.

Same contract as plex_client: no UI, no Kodi directory code, returns plain
dicts in the SAME item shape as Plex items, so rendering, the source picker,
the switch-source index, resume and subtitles all reuse one code path.

Endpoints follow EmbyCon's proven usage (AuthenticateByName +
X-Emby-Authorization) and MediaSources for versions/sizes.
"""
from __future__ import absolute_import

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl, quote
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui


def _addon():
    """A FRESH Addon handle per access.

    v3.9.186: the module-level singleton was built once per warm Python
    interpreter (reuselanguageinvoker=true), so the interpreter rendering the
    home page could hold a settings snapshot from BEFORE sign-in and keep
    reading an empty token — linking "worked" yet no section, no search results
    and no sources ever appeared.
    """
    return xbmcaddon.Addon('plugin.video.nuviohub')

WINDOW_ID = 10000
CACHE_SECONDS = 15 * 60
PAGE_SIZE = 80
WINDOW_ID = 10000
_VIEWS_MEM = {}

BROWSE_FIELDS = ('Overview,Genres,Studios,ProviderIds,OfficialRating,'
                 'CommunityRating,PremiereDate,ProductionYear,DateCreated')
DETAIL_FIELDS = ('MediaSources,Overview,Genres,Studios,People,ProviderIds,'
                 'OfficialRating,CommunityRating,PremiereDate,ProductionYear,Path')


class EmbyError(Exception):
    pass


def _setting(name, value=None):
    if value is None:
        try:
            return _addon().getSetting(name) or ''
        except Exception:
            return ''
    try:
        _addon().setSetting(name, value)
    except Exception:
        pass
    return value


def _auth_prop(name):
    return 'nuviohub.emby.auth' if name.endswith('auth_json') else ''


def _parse_json_setting(name, default):
    try:
        raw = _setting(name)
        if not raw:
            key = _auth_prop(name)
            if key:
                raw = xbmcgui.Window(WINDOW_ID).getProperty(key) or ''
        return json.loads(raw) if raw else default
    except Exception:
        return default


def _save_json_setting(name, value):
    try:
        blob = json.dumps(value)
        _setting(name, blob)
        key = _auth_prop(name)
        if key:
            # Shared by every warm interpreter, so the home page sees the new
            # sign-in immediately even if a cached Addon handle lags behind.
            xbmcgui.Window(WINDOW_ID).setProperty(key, blob)
    except Exception:
        pass


def _timeout():
    try:
        return max(5, int(_addon().getSetting('timeout') or '20'))
    except Exception:
        return 20


def _device_id():
    value = _setting('emby_device_id')
    if not value:
        value = uuid.uuid4().hex
        _setting('emby_device_id', value)
    return value


# 6.0.39: Jellyfin 12 (September 2026) removed the legacy Emby ways to sign
# requests (X-Emby-Authorization / X-Emby-Token / X-MediaBrowser-Token headers,
# the api_key query parameter) and the /emby route prefix. Jellyfin servers get
# the standard `Authorization: MediaBrowser ..., Token="..."` header, the
# ApiKey query parameter and root paths (all valid since Jellyfin 10.x);
# Emby servers keep their own scheme. The flavor comes from
# /System/Info/Public and is stored with the sign-in.
JELLYFIN, EMBY = 'jellyfin', 'emby'


def _version():
    try:
        return _addon().getAddonInfo('version') or '6'
    except Exception:
        return '6'


def _auth_value(token=''):
    value = ('MediaBrowser Client="MegaNexus", Device="Kodi", DeviceId="%s", Version="%s"'
             % (_device_id(), _version()))
    if token:
        value += ', Token="%s"' % token
    return value


def _headers(token='', flavor=JELLYFIN):
    headers = {
        'Accept': 'application/json',
        'Accept-Charset': 'UTF-8,*',
        'Content-Type': 'application/json',
    }
    if flavor == EMBY:
        headers['X-Emby-Authorization'] = _auth_value()
        if token:
            headers['X-Emby-Token'] = token
    else:
        headers['Authorization'] = _auth_value(token)
    return headers


def flavor_of(server):
    return EMBY if str((server or {}).get('flavor') or '').lower() == EMBY else JELLYFIN


def token_param(server):
    """Query parameter that carries the token in stream/image URLs."""
    return 'api_key' if flavor_of(server) == EMBY else 'ApiKey'


def _prefix(server):
    return '/emby' if flavor_of(server) == EMBY else ''


def detect(url, timeout=8):
    """{'flavor', 'name', 'version'} from the server's public info (no sign-in)."""
    base = _base({'url': url})
    if not base:
        raise EmbyError('Enter the server address')
    info = {}
    for path in ('/System/Info/Public', '/emby/System/Info/Public'):
        try:
            info = _json(_request(base + path, timeout=timeout))
            break
        except EmbyError:
            continue
    product = str(info.get('ProductName') or '')
    if not info:
        raise EmbyError('No Jellyfin or Emby server answered at this address')
    flavor = EMBY if 'emby' in product.lower() and 'jellyfin' not in product.lower() else JELLYFIN
    return {'flavor': flavor, 'name': str(info.get('ServerName') or product or 'Server'),
            'version': str(info.get('Version') or ''), 'url': base}


def _request(url, method='GET', token='', data=None, timeout=None, flavor=JELLYFIN):
    body = None
    if data is not None:
        body = json.dumps(data).encode('utf-8')
    req = Request(url, data=body, headers=_headers(token, flavor), method=method)
    try:
        with urlopen(req, timeout=(timeout or _timeout())) as response:
            return response.read()
    except Exception as exc:
        raise EmbyError('%s' % exc)


def _json(raw):
    try:
        return json.loads((raw or b'').decode('utf-8'))
    except Exception as exc:
        raise EmbyError('Emby returned an unreadable response (%s)' % exc)


def _base(server):
    url = str((server or {}).get('url') or '').strip().rstrip('/')
    if url and not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    return url


def _api(server, path, params=None, token='', method='GET', data=None):
    pairs = [(str(k), str(v)) for k, v in (params or {}).items() if v not in (None, '')]
    query = urlencode(pairs)
    url = '%s%s%s' % (_base(server), _prefix(server), '/' + str(path or '').lstrip('/'))
    if query:
        url += '?' + query
    raw = _request(url, method=method, token=token or server.get('token') or '', data=data, flavor=flavor_of(server))
    return _json(raw) if raw else {}


# ─────────────────────────── auth ───────────────────────────

_DETECT_RETRY = {'at': 0.0}


def account():
    auth = _parse_json_setting('emby_auth_json', {}) or {}
    if auth.get('token') and auth.get('url') and not auth.get('flavor'):
        # Signed in before 6.0.39: learn the server flavor once (an offline
        # server is asked again at most every 10 minutes).
        if time.time() - _DETECT_RETRY['at'] > 600:
            _DETECT_RETRY['at'] = time.time()
            try:
                auth.update(flavor=detect(auth['url'], timeout=4)['flavor'])
                _save_json_setting('emby_auth_json', auth)
                return auth
            except Exception:
                pass
        auth = dict(auth, flavor=EMBY)   # old sign-ins were made the Emby way
    return auth


def is_signed_in():
    auth = account()
    return bool(auth.get('token') and auth.get('user_id') and auth.get('url'))


def sign_out():
    _setting('emby_auth_json', '')
    try:
        xbmcgui.Window(WINDOW_ID).clearProperty('nuviohub.emby.auth')
    except Exception:
        pass
    _VIEWS_MEM.clear()


def _save_sign_in(server, value, username=''):
    token = value.get('AccessToken') or ''
    user = value.get('User') or {}
    if not token or not user.get('Id'):
        raise EmbyError('Sign-in failed')
    auth = {
        'url': server['url'],
        'flavor': server['flavor'],
        'token': str(token),
        'user_id': str(user.get('Id')),
        'username': user.get('Name') or username or '',
        'server_name': value.get('ServerName') or server.get('name') or ('Emby' if server['flavor'] == EMBY else 'Jellyfin'),
        'server_version': server.get('version') or '',
        'signed_in_at': int(time.time()),
    }
    _save_json_setting('emby_auth_json', auth)
    _VIEWS_MEM.clear()
    return auth


def sign_in(url, username, password=''):
    """AuthenticateByName (Jellyfin and Emby)."""
    server = detect(url)
    raw = _request('%s%s/Users/AuthenticateByName' % (server['url'], _prefix(server)),
                   method='POST', flavor=server['flavor'],
                   data={'Username': str(username or ''), 'Pw': str(password or '')})
    return _save_sign_in(server, _json(raw), username)


def quick_connect_start(url):
    """Jellyfin Quick Connect: a 6-digit code the user approves in another
    signed-in Jellyfin app (Settings > Quick Connect). Returns the state to poll."""
    server = detect(url)
    if server['flavor'] != JELLYFIN:
        raise EmbyError('Quick Connect is a Jellyfin feature. Use the username and password for Emby.')
    try:
        enabled = _json(_request(server['url'] + '/QuickConnect/Enabled'))
    except EmbyError:
        enabled = False
    if enabled is not True:
        raise EmbyError('Quick Connect is turned off on this server. Use the username and password.')
    value = _json(_request(server['url'] + '/QuickConnect/Initiate', method='POST'))
    if not value.get('Secret') or not value.get('Code'):
        raise EmbyError('The server did not start Quick Connect')
    return {'server': server, 'secret': str(value['Secret']), 'code': str(value['Code'])}


def quick_connect_poll(state):
    """None while waiting; the saved sign-in once the user approved the code."""
    server = state['server']
    value = _json(_request('%s/QuickConnect/Connect?%s' % (server['url'], urlencode({'Secret': state['secret']}))))
    if not value.get('Authenticated'):
        return None
    raw = _request(server['url'] + '/Users/AuthenticateWithQuickConnect', method='POST',
                   data={'Secret': state['secret']})
    return _save_sign_in(server, _json(raw))


def servers():
    """Emby is one configured server; keep the Plex-shaped list contract."""
    auth = account()
    if not is_signed_in():
        return []
    return [{
        'id': auth.get('user_id') or 'emby',
        'name': auth.get('server_name') or 'Emby',
        'url': auth.get('url') or '',
        'token': auth.get('token') or '',
        'user_id': auth.get('user_id') or '',
        'backend': 'emby',
        'flavor': flavor_of(auth),
    }]


# ─────────────────────── versions & items ───────────────────────

_CH_MAP = {1: '1.0', 2: '2.0', 6: '5.1', 8: '7.1'}


def _size_label(nbytes):
    try:
        n = int(nbytes or 0)
    except (TypeError, ValueError):
        return ''
    if n <= 0:
        return ''
    gb = n / (1024.0 ** 3)
    return '%.1f GB' % gb if gb >= 1 else '%.0f MB' % (n / (1024.0 ** 2))


def _resolution_label(height, width=0):
    try:
        h = int(height or 0)
        w = int(width or 0)
    except (TypeError, ValueError):
        return ''
    if h > 1088 or w >= 3800:
        return '4K'
    if h >= 1080:
        return '1080p'
    if h >= 720:
        return '720p'
    return 'SD' if h else ''


_BITMAP_SUBTITLE_CODECS = {
    'pgs', 'hdmv_pgs_subtitle', 'hdmv-pgs-subtitle', 'vobsub',
    'dvd_subtitle', 'dvd-subtitle', 'dvdsub', 'dvb_subtitle',
    'dvb-subtitle', 'dvbsub', 'xsub',
}


def _subtitle_ext(codec):
    value = str(codec or '').lower()
    return {
        'subrip': 'srt', 'srt': 'srt', 'ass': 'ass', 'ssa': 'ssa',
        'webvtt': 'vtt', 'vtt': 'vtt', 'mov_text': 'srt',
    }.get(value, value or 'srt')


def _with_emby_token(url, token, server=None):
    if not url or not token:
        return url
    name = token_param(server or account())
    try:
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        lowered = {str(k).lower() for k, _v in pairs}
        if not lowered & {'api_key', 'apikey', 'x-emby-token'}:
            pairs.append((name, str(token)))
        return urlunsplit((parts.scheme, parts.netloc, parts.path,
                           urlencode(pairs), parts.fragment))
    except Exception:
        return url + ('&' if '?' in url else '?') + urlencode({name: token})


def _external_subtitles(item_id, source, server):
    rows = []
    source_id = str(source.get('Id') or '')
    base = _base(server)
    token = str(server.get('token') or '')
    for stream in (source.get('MediaStreams') or []):
        if str(stream.get('Type') or '').lower() != 'subtitle':
            continue
        codec = str(stream.get('Codec') or '').lower()
        if codec in _BITMAP_SUBTITLE_CODECS:
            continue
        # Emby/Jellyfin expose sidecars through DeliveryUrl when available.
        # Otherwise build the same direct subtitle route used by EmbyCon.
        delivery = str(stream.get('DeliveryUrl') or '').strip()
        if delivery:
            if delivery.startswith(('http://', 'https://')):
                url = delivery
            else:
                url = base.rstrip('/') + '/' + delivery.lstrip('/')
        elif stream.get('IsExternal') or stream.get('Path'):
            try:
                index = int(stream.get('Index'))
            except Exception:
                continue
            ext = _subtitle_ext(codec)
            url = '%s%s/Videos/%s/%s/Subtitles/%s/Stream.%s' % (
                base.rstrip('/'), _prefix(server), quote(str(item_id), safe=''),
                quote(source_id, safe=''), index, ext)
        else:
            continue
        url = _with_emby_token(url, token, server)
        lang = str(stream.get('Language') or 'und')
        rows.append({
            'id': str(stream.get('Index') if stream.get('Index') is not None else len(rows) + 1),
            'url': url,
            'key': url,
            'lang': lang,
            'language': lang,
            'languageCode': lang,
            'codec': codec or 'subrip',
            'format': _subtitle_ext(codec),
            'sourceType': 'stream',
            'sourceName': server.get('name') or 'Emby',
            'title': str(stream.get('DisplayTitle') or stream.get('Title') or ''),
            'forced': bool(stream.get('IsForced')),
            'selected': bool(stream.get('IsDefault')),
        })
    return rows


def _media_versions(item, server):
    """Every MediaSource as a version: resolution, HDR, codecs, audio, SIZE."""
    versions = []
    for source in (item.get('MediaSources') or []):
        video = audio = None
        for stream in (source.get('MediaStreams') or []):
            kind = str(stream.get('Type') or '')
            if kind == 'Video' and video is None:
                video = stream
            elif kind == 'Audio' and audio is None:
                audio = stream
        video = video or {}
        audio = audio or {}
        res = _resolution_label(video.get('Height'), video.get('Width'))
        vrange = str(video.get('VideoRange') or '')
        title = str(video.get('DisplayTitle') or '')
        hdr = ''
        if 'DOVI' in title.upper() or 'DOLBY VISION' in title.upper() or 'DOVI' in vrange.upper():
            hdr = 'Dolby Vision'
        elif 'HDR' in vrange.upper() or 'HDR' in title.upper():
            hdr = 'HDR'
        vcodec = str(video.get('Codec') or '').upper()
        acodec = str(audio.get('Codec') or '').upper()
        atitle = str(audio.get('DisplayTitle') or '')
        if acodec:
            channels = audio.get('Channels')
            try:
                if channels:
                    acodec += ' %s' % _CH_MAP.get(int(channels), '%sch' % int(channels))
            except (TypeError, ValueError):
                pass
            if 'Atmos' in atitle:
                acodec += ' Atmos'
        size_bytes = source.get('Size') or 0
        size = _size_label(size_bytes)
        container = str(source.get('Container') or '').upper()
        blocks = ['[ %s ]' % v for v in (res, hdr, vcodec, acodec, size) if v]
        short = [v for v in (res, hdr, size, container) if v]
        versions.append({
            'media_source_id': str(source.get('Id') or ''),
            'file': str(source.get('Path') or ''),
            'resolution': res,
            'hdr': hdr,
            'video_codec': vcodec,
            'audio': acodec,
            'container': container,
            'size_bytes': size_bytes,
            'size_label': size,
            'info_line': ' • '.join(blocks),
            'version_label': ' · '.join(short) or 'Version %d' % (len(versions) + 1),
            'subtitles': _external_subtitles(item.get('Id') or '', source, server),
        })
    return versions


def _ids(item):
    provider = item.get('ProviderIds') or {}
    lower = {str(k).lower(): str(v) for k, v in provider.items() if v}
    return {
        'imdb_id': lower.get('imdb', ''),
        'tmdb_id': lower.get('tmdb', ''),
        'tvdb_id': lower.get('tvdb', ''),
    }


def item_from_node(item, server):
    """Plex-shaped dict so the whole Nuvio Hub pipeline is reused verbatim."""
    kind = str(item.get('Type') or 'Movie')
    media = {'Movie': 'movie', 'Series': 'show', 'Season': 'season',
             'Episode': 'episode'}.get(kind, 'movie')
    versions = _media_versions(item, server)
    ticks = item.get('RunTimeTicks') or 0
    try:
        duration_ms = int(ticks) // 10000
    except (TypeError, ValueError):
        duration_ms = 0
    out = {
        'backend': 'emby',
        'server_id': str(server.get('id') or ''),
        'server_name': server.get('name') or 'Emby',
        'rating_key': str(item.get('Id') or ''),
        'key': str(item.get('Id') or ''),
        'media_type': media,
        'title': str(item.get('Name') or 'Emby'),
        'raw_title': str(item.get('Name') or ''),
        'summary': str(item.get('Overview') or ''),
        'year': item.get('ProductionYear') or 0,
        'duration_ms': duration_ms,
        'index': item.get('IndexNumber') or 0,
        'season': item.get('ParentIndexNumber') or 0,
        'thumb': str(item.get('Id') or ''),
        'art': str(item.get('Id') or ''),
        'rating': float(item.get('CommunityRating') or 0) or 0,
        'content_rating': str(item.get('OfficialRating') or ''),
        'studio': ', '.join(s.get('Name') for s in (item.get('Studios') or []) if s.get('Name'))[:60],
        'tagline': '',
        'premiered': str(item.get('PremiereDate') or '')[:10],
        'genres': [g for g in (item.get('Genres') or [])][:6],
        'directors': [p.get('Name') for p in (item.get('People') or [])
                      if p.get('Type') == 'Director' and p.get('Name')][:4],
        'writers': [p.get('Name') for p in (item.get('People') or [])
                    if p.get('Type') == 'Writer' and p.get('Name')][:4],
        'cast': [p.get('Name') for p in (item.get('People') or [])
                 if p.get('Type') == 'Actor' and p.get('Name')][:10],
        'versions': versions,
        'ids': _ids(item),
        'series_id': str(item.get('SeriesId') or ''),
        'show_title': str(item.get('SeriesName') or ''),
        'info_line': versions[0]['info_line'] if versions else '',
        'size_label': versions[0]['size_label'] if versions else '',
    }
    return out


def logo_url(server, item_id):
    """Emby exposes the clear logo as the `Logo` image type."""
    return artwork_url(server, item_id, kind='Logo') if item_id else ''


def artwork_url(server, item_id, kind='Primary', width=0):
    """Server-side resized image (posters 500 px, backdrops 1280 px by default):
    the server already has the artwork, so MegaNexus downloads no other copy."""
    if not item_id:
        return ''
    width = width or (1280 if kind in ('Backdrop', 'Thumb') else 500)
    return '%s%s/Items/%s/Images/%s?%s' % (
        _base(server), _prefix(server), quote(str(item_id), safe=''), quote(str(kind), safe=''),
        urlencode({'maxWidth': width, 'quality': 90, token_param(server): server.get('token') or ''}))


def playback_url(server, item_id, media_source_id=''):
    params = {
        'static': 'true',
        token_param(server): server.get('token') or '',
    }
    if media_source_id:
        params['MediaSourceId'] = media_source_id
    return '%s%s/Videos/%s/stream?%s' % (_base(server), _prefix(server), item_id, urlencode(params))


def playback_info(server, item_id):
    """Return a fresh PlaybackInfo response for the current user/device.

    MediaSources cached in library metadata can be stale and do not carry a
    PlaySessionId. Emby/Jellyfin expect clients to refresh PlaybackInfo at the
    actual handoff, especially for remote, STRM and live-stream sources.
    """
    params = {
        'UserId': server.get('user_id') or '',
        'StartTimeTicks': 0,
        'AutoOpenLiveStream': 'false',
    }
    body = {
        'UserId': server.get('user_id') or '',
        'DeviceId': _device_id(),
    }
    return _api(server, '/Items/%s/PlaybackInfo' % quote(str(item_id), safe=''),
                params=params, method='POST', data=body)


def resolve_playback(server, item_id, media_source_id=''):
    """Resolve one source from fresh PlaybackInfo into a playable URL.

    DirectStreamUrl/TranscodingUrl returned by the server wins. The stable
    static stream endpoint remains a fallback for older Emby servers.
    """
    info = playback_info(server, item_id)
    sources = list(info.get('MediaSources') or [])
    wanted = str(media_source_id or '')
    source = next((s for s in sources if str(s.get('Id') or '') == wanted), None)
    if source is None and sources:
        source = sources[0]
    source = source or {}
    source_id = str(source.get('Id') or wanted)
    play_session_id = str(info.get('PlaySessionId') or '')
    candidate = (source.get('DirectStreamUrl') or source.get('DirectUrl') or
                 source.get('TranscodingUrl') or '')
    if candidate:
        if not str(candidate).startswith(('http://', 'https://')):
            candidate = _base(server).rstrip('/') + '/' + str(candidate).lstrip('/')
        url = _with_emby_token(str(candidate), str(server.get('token') or ''), server)
    else:
        params = {
            'static': 'true',
            token_param(server): server.get('token') or '',
        }
        if source_id:
            params['MediaSourceId'] = source_id
        if play_session_id:
            params['PlaySessionId'] = play_session_id
        container = str(source.get('Container') or '').strip().lower()
        suffix = ('.' + container) if container and container.isalnum() else ''
        url = '%s%s/Videos/%s/stream%s?%s' % (
            _base(server), _prefix(server), quote(str(item_id), safe=''), suffix, urlencode(params))
    version = (_media_versions({'Id': item_id, 'MediaSources': [source]}, server) or [{}])[0]
    return {
        'url': url,
        'media_source_id': source_id,
        'play_session_id': play_session_id,
        'version': version,
    }


# ─────────────────────── browsing & search ───────────────────────

def libraries(server, force=False):
    key = str(server.get('id') or '')
    cached = _VIEWS_MEM.get(key) or {}
    if not force and cached.get('rows') is not None and cached.get('at', 0) + CACHE_SECONDS > time.time():
        return list(cached['rows'])
    if not force and key:
        try:
            raw = xbmcgui.Window(WINDOW_ID).getProperty('nuviohub.emby.libs.%s' % key) or ''
            if raw:
                data = json.loads(raw)
                if data.get('at', 0) + CACHE_SECONDS > time.time():
                    _VIEWS_MEM[key] = data
                    return list(data.get('rows') or [])
        except Exception:
            pass
    data = _api(server, '/Users/%s/Views' % server.get('user_id'))
    rows = []
    for view in (data.get('Items') or []):
        kind = str(view.get('CollectionType') or '').lower()
        if kind not in ('movies', 'tvshows', 'boxsets', ''):
            continue
        rows.append({
            'key': str(view.get('Id') or ''),
            'title': str(view.get('Name') or 'Library'),
            'type': 'show' if kind == 'tvshows' else 'movie',
        })
    payload = {'at': time.time(), 'rows': rows}
    _VIEWS_MEM[key] = payload
    if key:
        try:
            xbmcgui.Window(WINDOW_ID).setProperty('nuviohub.emby.libs.%s' % key,
                                                  json.dumps(payload))
        except Exception:
            pass
    return list(rows)


def children(server, parent_id, start=0, size=PAGE_SIZE, sort='', include_types='', recursive=False):
    """Browse an Emby/Jellyfin container.

    For top-level movie/TV libraries Nuvio Hub asks for recursive typed rows so
    virtual folders and filesystem folders are flattened instead of being
    rendered as fake movies. Season/episode navigation keeps the normal direct
    child behaviour.
    """
    params = {
        'ParentId': parent_id,
        'StartIndex': int(start or 0),
        'Limit': int(size or PAGE_SIZE),
        'Fields': BROWSE_FIELDS,
        'SortBy': sort or 'SortName',
        'SortOrder': 'Descending' if str(sort or '').endswith(':desc') else 'Ascending',
    }
    if str(sort or '').endswith(':desc'):
        params['SortBy'] = str(sort).split(':', 1)[0]
    if include_types:
        params['IncludeItemTypes'] = str(include_types)
    if recursive:
        params['Recursive'] = 'true'
    data = _api(server, '/Users/%s/Items' % server.get('user_id'), params)
    rows = []
    allowed = {x.strip().lower() for x in str(include_types or '').split(',') if x.strip()}
    for node in (data.get('Items') or []):
        node_type = str(node.get('Type') or '').lower()
        if node_type in ('folder', 'collectionfolder', 'userrootfolder'):
            continue
        if allowed and node_type not in allowed:
            continue
        rows.append(item_from_node(node, server))
    return rows, int(data.get('TotalRecordCount') or len(rows))


def resume(server, start=0, size=PAGE_SIZE):
    "Emby's Continue Watching — the direct equivalent of Plex's On Deck.\n\n    Emby exposes partially-played items on /Users/{id}/Items/Resume. Nuvio Hub\n    never called it, which is why Emby had no \"\u0645\u062a\u0627\u0628\u0639\u0629 \u0627\u0644\u0645\u0634\u0627\u0647\u062f\u0629\" while Plex did.\n    "
    params = {
        'StartIndex': int(start or 0),
        'Limit': int(size or PAGE_SIZE),
        'Fields': BROWSE_FIELDS,
        'MediaTypes': 'Video',
        'Recursive': 'true',
        'EnableTotalRecordCount': 'true',
    }
    data = _api(server, '/Users/%s/Items/Resume' % server.get('user_id'), params)
    rows = []
    for node in (data.get('Items') or []):
        row = item_from_node(node, server)
        row['resume_ms'] = _resume_ms(node)
        rows.append(row)
    return rows, int(data.get('TotalRecordCount') or len(rows))


def next_up(server, limit=PAGE_SIZE):
    """Next unwatched episode per series — completes Continue Watching.

    Resume only returns items that were *started*. A finished episode should
    surface the NEXT one, exactly as Plex's On Deck does.
    """
    params = {
        'UserId': server.get('user_id'),
        'Limit': int(limit or PAGE_SIZE),
        'Fields': BROWSE_FIELDS,
    }
    try:
        data = _api(server, '/Shows/NextUp', params)
    except Exception:
        return []
    rows = []
    for node in (data.get('Items') or []):
        row = item_from_node(node, server)
        row['resume_ms'] = _resume_ms(node)
        rows.append(row)
    return rows


def latest(server, limit=PAGE_SIZE):
    """Recently added movies and series (6.0.39 Home row)."""
    data = _api(server, '/Users/%s/Items/Latest' % server.get('user_id'), {
        'IncludeItemTypes': 'Movie,Series', 'Limit': int(limit or PAGE_SIZE),
        'Fields': BROWSE_FIELDS, 'GroupItems': 'true'})
    nodes = data if isinstance(data, list) else (data.get('Items') or [])
    return [item_from_node(node, server) for node in nodes if str(node.get('Type') or '') in ('Movie', 'Series')]


def _resume_ms(node):
    """Playback position in ms from an Emby node's UserData (ticks -> ms)."""
    try:
        ticks = ((node.get('UserData') or {}).get('PlaybackPositionTicks')) or 0
        return int(ticks) // 10000
    except Exception:
        return 0


def search_server(server, query, media_type='', limit=40):
    types = {'movie': 'Movie', 'show': 'Series', 'series': 'Series',
             'episode': 'Episode'}.get((media_type or '').lower(), 'Movie,Series,Episode')
    data = _api(server, '/Users/%s/Items' % server.get('user_id'), {
        'SearchTerm': query,
        'IncludeItemTypes': types,
        'Recursive': 'true',
        'Limit': int(limit),
        'Fields': BROWSE_FIELDS,
    })
    rows = []
    for item in (data.get('Items') or []):
        row = item_from_node(item, server)
        if row['media_type'] in ('movie', 'show', 'episode'):
            rows.append(row)
    return rows


def metadata(server, item_id):
    data = _api(server, '/Users/%s/Items/%s' % (server.get('user_id'), item_id),
                {'Fields': DETAIL_FIELDS})
    return item_from_node(data, server)


def find_all_by_ids(server, ids, media_type='movie', title='', limit=10):
    """EVERY library item that matches — not just the first one.

    v3.9.209: find_by_ids() returned inside its own loop, so only the FIRST hit
    ever came back. A library that holds the same film several times — a 4K
    rip and a 1080p rip catalogued as separate items, which is exactly what
    Arabic libraries look like — surfaced ONE source in Nuvio Hub while other
    clients listed three.
    """
    want_type = 'Series' if str(media_type).lower() in ('series', 'show', 'episode') else 'Movie'
    found, seen = [], set()

    def _take(row):
        key = str(row.get('rating_key') or '')
        if key and key not in seen:
            seen.add(key)
            found.append(row)

    for provider, key in (('Imdb', 'imdb_id'), ('Tmdb', 'tmdb_id'), ('Tvdb', 'tvdb_id')):
        value = str((ids or {}).get(key) or '')
        if not value:
            continue
        try:
            data = _api(server, '/Users/%s/Items' % server.get('user_id'), {
                'AnyProviderIdEquals': '%s.%s' % (provider.lower(), value),
                'IncludeItemTypes': want_type,
                'Recursive': 'true',
                'Limit': int(limit),
                'Fields': DETAIL_FIELDS,
            })
        except EmbyError:
            continue
        for item in (data.get('Items') or []):
            _take(item_from_node(item, server))

    if found:
        # v3.9.226 — the same waste that cost Plex 43 seconds per server.
        #
        # AnyProviderIdEquals is EXACT: Emby resolved the id and handed back the
        # item. Yet the code carried on into a title search because the only
        # gate was `len(found) < limit` — and a film has two or three copies,
        # never ten. Every extra pass is a full recursive library scan.
        xbmc.log('[NuvioHub] Emby exact id match — skipping the title pass '
                 '(server=%s, %d copies)' % (server.get('name') or '?', len(found)),
                 xbmc.LOGINFO)
        return _resolve_details(server, found, limit)

    # A title pass catches library copies whose provider ids were never set —
    # the unidentified Arabic/Turkish releases the user actually cares about.
    if title and len(found) < int(limit):
        want_ids = {k: str((ids or {}).get(k) or '') for k in ('imdb_id', 'tmdb_id')}
        for row in search_server(server, title, media_type=media_type, limit=int(limit)):
            row_ids = row.get('ids') or {}
            same_id = any(want_ids[k] and row_ids.get(k) == want_ids[k] for k in want_ids)
            same_title = (str(row.get('title') or '').strip().lower()
                          == str(title).strip().lower())
            if same_id or same_title:
                _take(row)

    return _resolve_details(server, found, limit)


def _resolve_details(server, found, limit):
    """Fill in the MediaSources — in parallel, and only when they are missing."""
    rows = found[:int(limit)]
    need = [r for r in rows if not (r.get('versions') or []) and r.get('rating_key')]
    detailed = {}
    if need:
        with ThreadPoolExecutor(max_workers=min(6, len(need))) as pool:
            futures = {pool.submit(metadata, server, r.get('rating_key')): r for r in need}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    detailed[str(row.get('rating_key'))] = future.result()
                except Exception:
                    pass
    return [detailed.get(str(r.get('rating_key')), r) for r in rows]


def find_by_ids(server, ids, media_type='movie', title=''):
    """GUID-first match (imdb/tmdb), title fallback — like the Plex path."""
    want_type = 'Series' if str(media_type).lower() in ('series', 'show', 'episode') else 'Movie'
    for provider, key in (('Imdb', 'imdb_id'), ('Tmdb', 'tmdb_id'), ('Tvdb', 'tvdb_id')):
        value = str((ids or {}).get(key) or '')
        if not value:
            continue
        try:
            data = _api(server, '/Users/%s/Items' % server.get('user_id'), {
                'AnyProviderIdEquals': '%s.%s' % (provider.lower(), value),
                'IncludeItemTypes': want_type,
                'Recursive': 'true',
                'Limit': 5,
                'Fields': BROWSE_FIELDS,
            })
        except EmbyError:
            continue
        for item in (data.get('Items') or []):
            item_id = str(item.get('Id') or '')
            if item_id:
                try:
                    return metadata(server, item_id)
                except EmbyError:
                    return item_from_node(item, server)
    if title:
        normalized_title = str(title or '').strip().casefold()
        first_title = None
        for row in search_server(server, title, media_type=media_type, limit=10):
            row_ids = row.get('ids') or {}
            for key in ('imdb_id', 'tmdb_id'):
                if (ids or {}).get(key) and row_ids.get(key) == str((ids or {}).get(key)):
                    try:
                        return metadata(server, row.get('rating_key'))
                    except EmbyError:
                        return row
            row_title = str(row.get('raw_title') or row.get('title') or '').strip().casefold()
            if row_title == normalized_title and first_title is None:
                first_title = row
        if first_title is not None:
            try:
                return metadata(server, first_title.get('rating_key'))
            except EmbyError:
                return first_title
    return None


def episode_item(server, show_item, season, episode):
    """Walk Series → Episodes and return the exact episode with MediaSources."""
    try:
        data = _api(server, '/Shows/%s/Episodes' % show_item.get('rating_key'), {
            'UserId': server.get('user_id'),
            'Season': int(season),
            'Fields': DETAIL_FIELDS,
        })
    except (EmbyError, TypeError, ValueError):
        return None
    for item in (data.get('Items') or []):
        try:
            if int(item.get('IndexNumber') or -1) == int(episode):
                return item_from_node(item, server)
        except (TypeError, ValueError):
            continue
    return None
