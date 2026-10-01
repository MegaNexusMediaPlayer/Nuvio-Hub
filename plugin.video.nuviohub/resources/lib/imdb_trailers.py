"""IMDb trailers as an alternative to YouTube.

IMDb's public GraphQL endpoint (the one imdb.com itself uses) returns signed,
direct MP4 files for a title's trailers, so no YouTube add-on and no extra Kodi
add-on is needed. The files come from IMDb's video CDN and are streamed by
Kodi directly (see ``direct_stream``), so a trailer starts in about a second
instead of waiting for a download. Lookups are cached per title and never
raise: a failure just means "no IMDb trailer" and the other source is used.
"""
import json
import re
import threading
import time
from urllib.request import Request, urlopen

ENDPOINT = 'https://caching.graphql.imdb.com/'
HEADERS = {'Content-Type': 'application/json', 'Accept': 'application/json',
           'x-imdb-client-name': 'imdb-web-next', 'Origin': 'https://www.imdb.com',
           'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/120.0 Safari/537.36'}
QUERY = ('query($id: ID!) { title(id: $id) { primaryVideos(first: 8) { edges { node { id '
         'contentType { id } playbackURLs { url videoMimeType videoDefinition } } } } } }')
QUALITIES = {'480': ('DEF_480p', 'DEF_SD', 'DEF_720p', 'DEF_1080p'),
             '720': ('DEF_720p', 'DEF_480p', 'DEF_1080p', 'DEF_SD'),
             '1080': ('DEF_1080p', 'DEF_720p', 'DEF_480p', 'DEF_SD')}
QUALITY_LABELS = {'480': '480p · fastest start', '720': '720p', '1080': '1080p · most data'}
QUALITY_SETTING = 'nuvio_imdb_trailer_quality'
PREFERRED = QUALITIES['480']
DEFAULT_SOURCE = 'imdb_youtube'  # 6.0.27: IMDb first (no add-on), then the add-on's own trailer
CDN_SUFFIX = '.media-imdb.com'
SOURCES = ('imdb_youtube', 'imdb', 'youtube', 'youtube_imdb')
LABELS = {'youtube': 'Add-on trailer / YouTube', 'imdb': 'IMDb only', 'imdb_youtube': 'IMDb, then add-on trailer / YouTube',
          'youtube_imdb': 'Add-on trailer / YouTube, then IMDb'}
SETTING = 'nuvio_trailer_source'
_TTL = 1800
_CACHE = {}
_LOCK = threading.Lock()


def source_setting(addon=None):
    """Chosen trailer source; unset means IMDb first (no add-on needed), then the
    metadata add-on's own trailer - a direct file plays without any add-on,
    a YouTube link only when the YouTube add-on is installed."""
    try:
        if addon is None:
            import xbmcaddon
            addon = xbmcaddon.Addon('plugin.video.nuviohub')
        value = (addon.getSetting(SETTING) or '').strip()
    except Exception:
        value = ''
    return value if value in SOURCES else DEFAULT_SOURCE


DEFAULTS_627 = 'nuvio_trailer_defaults_627'


def migrate_defaults(addon):
    """Once (6.0.27): IMDb comes first and automatic trailers are switched on,
    where the profile still holds the previous defaults (YouTube-then-IMDb,
    trailers off). Later choices are never changed."""
    if addon.getSetting(DEFAULTS_627) == 'true':
        return False
    if (addon.getSetting(SETTING) or '').strip() in ('', 'youtube_imdb'):
        addon.setSetting(SETTING, DEFAULT_SOURCE)
    if (addon.getSetting('nuvio_auto_trailers') or '').strip() in ('', 'false'):
        addon.setSetting('nuvio_auto_trailers', 'true')
    addon.setSetting(DEFAULTS_627, 'true')
    return True


def quality_setting(addon=None):
    try:
        if addon is None:
            import xbmcaddon
            addon = xbmcaddon.Addon('plugin.video.nuviohub')
        value = (addon.getSetting(QUALITY_SETTING) or '').strip()
    except Exception:
        value = ''
    return value if value in QUALITIES else '480'


def direct_stream(url):
    """IMDb CDN files are complete MP4s that Kodi can stream immediately."""
    from urllib.parse import urlsplit
    parts = urlsplit(str(url or ''))
    return parts.scheme == 'https' and (parts.hostname or '').endswith(CDN_SUFFIX) and parts.path.lower().endswith('.mp4')


def order(source):
    return {'youtube': ('youtube',), 'imdb': ('imdb',), 'imdb_youtube': ('imdb', 'youtube'),
            'youtube_imdb': ('youtube', 'imdb')}.get(source, ('youtube',))


def imdb_id(*records):
    """First IMDb title ID found in metadata, a card target or a card."""
    for record in records:
        if not isinstance(record, dict):
            continue
        ids = record.get('ids') if isinstance(record.get('ids'), dict) else {}
        for value in (record.get('imdb_id'), record.get('imdbId'), ids.get('imdb'),
                      record.get('canonical_id'), record.get('id')):
            value = str(value or '').strip()
            if value.isdigit():
                value = 'tt' + value.zfill(7)
            if re.fullmatch(r'tt\d{5,10}', value):
                return value
    return ''


def pick_all(nodes, preferred=PREFERRED):
    """MP4 files of the first trailer (any video when a title has no trailer),
    in ``preferred`` quality order."""
    nodes = [n for n in nodes or [] if isinstance(n, dict)]
    trailers = [n for n in nodes if str((n.get('contentType') or {}).get('id') or '').endswith('.trailer')]
    for node in trailers or nodes:
        files = {}
        for item in node.get('playbackURLs') or []:
            url = str((item or {}).get('url') or '')
            if item.get('videoMimeType') == 'MP4' and url.startswith('https://'):
                files.setdefault(item.get('videoDefinition'), url)
        if files:
            ranked = [files[d] for d in preferred if d in files]
            return ranked + [u for d, u in files.items() if d not in preferred]
    return []


def pick(nodes):
    found = pick_all(nodes)
    return found[0] if found else ''


def resolve_all(title_id, timeout=5, opener=urlopen, quality=None):
    """Signed MP4 URLs for the title's trailer, best first ([] on any failure)."""
    preferred = QUALITIES.get(quality or quality_setting(), PREFERRED)
    title_id = imdb_id({'id': title_id})
    if not title_id:
        return []
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get((title_id, preferred))
        if hit and hit[0] > now:
            return list(hit[1])
    urls = []
    try:
        body = json.dumps({'query': QUERY, 'variables': {'id': title_id}}).encode('utf-8')
        with opener(Request(ENDPOINT, data=body, headers=HEADERS, method='POST'), timeout=timeout) as response:
            data = json.loads(response.read(2 * 1024 * 1024).decode('utf-8'))
        edges = ((((data or {}).get('data') or {}).get('title') or {}).get('primaryVideos') or {}).get('edges') or []
        urls = pick_all([edge.get('node') for edge in edges if isinstance(edge, dict)], preferred)
    except Exception:
        urls = []
    with _LOCK:
        # Misses are remembered briefly so a title without trailers is not re-queried per focus.
        _CACHE[(title_id, preferred)] = (now + (_TTL if urls else 120), tuple(urls))
        while len(_CACHE) > 256:
            _CACHE.pop(next(iter(_CACHE)))
    return list(urls)


def resolve(title_id, timeout=5, opener=urlopen, quality=None):
    """Best signed MP4 URL for the title's trailer, or '' (never raises)."""
    found = resolve_all(title_id, timeout, opener, quality)
    return found[0] if found else ''
