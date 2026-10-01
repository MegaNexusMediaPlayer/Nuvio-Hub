"""IMDb trailers as an alternative to YouTube.

IMDb's public GraphQL endpoint (the one imdb.com itself uses) returns signed,
direct MP4 files for a title's trailers, so no YouTube add-on is needed. The
result is a plain HTTPS .mp4 URL that ``trailer_cache.prepare`` downloads and
plays exactly like any other direct trailer. Lookups are cached per title and
never raise: a failure just means "no IMDb trailer" and the other source is used.
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
# Compact first: previews are cached whole on the device (32 MiB cap).
PREFERRED = ('DEF_480p', 'DEF_SD', 'DEF_720p', 'DEF_1080p')
SOURCES = ('youtube', 'imdb', 'imdb_youtube', 'youtube_imdb')
LABELS = {'youtube': 'YouTube', 'imdb': 'IMDb', 'imdb_youtube': 'IMDb, then YouTube',
          'youtube_imdb': 'YouTube, then IMDb'}
SETTING = 'nuvio_trailer_source'
_TTL = 1800
_CACHE = {}
_LOCK = threading.Lock()


def source_setting(addon=None):
    """Chosen trailer source; unknown or unset values mean YouTube (previous behaviour)."""
    try:
        if addon is None:
            import xbmcaddon
            addon = xbmcaddon.Addon('plugin.video.nuviohub')
        value = (addon.getSetting(SETTING) or '').strip()
    except Exception:
        value = ''
    return value if value in SOURCES else 'youtube'


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


def pick_all(nodes):
    """MP4 files of the first trailer (any video when a title has no trailer),
    most suitable first."""
    nodes = [n for n in nodes or [] if isinstance(n, dict)]
    trailers = [n for n in nodes if str((n.get('contentType') or {}).get('id') or '').endswith('.trailer')]
    for node in trailers or nodes:
        files = {}
        for item in node.get('playbackURLs') or []:
            url = str((item or {}).get('url') or '')
            if item.get('videoMimeType') == 'MP4' and url.startswith('https://'):
                files.setdefault(item.get('videoDefinition'), url)
        if files:
            ranked = [files[d] for d in PREFERRED if d in files]
            return ranked + [u for d, u in files.items() if d not in PREFERRED]
    return []


def pick(nodes):
    found = pick_all(nodes)
    return found[0] if found else ''


def resolve_all(title_id, timeout=5, opener=urlopen):
    """Signed MP4 URLs for the title's trailer, best first ([] on any failure)."""
    title_id = imdb_id({'id': title_id})
    if not title_id:
        return []
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(title_id)
        if hit and hit[0] > now:
            return list(hit[1])
    urls = []
    try:
        body = json.dumps({'query': QUERY, 'variables': {'id': title_id}}).encode('utf-8')
        with opener(Request(ENDPOINT, data=body, headers=HEADERS, method='POST'), timeout=timeout) as response:
            data = json.loads(response.read(2 * 1024 * 1024).decode('utf-8'))
        edges = ((((data or {}).get('data') or {}).get('title') or {}).get('primaryVideos') or {}).get('edges') or []
        urls = pick_all([edge.get('node') for edge in edges if isinstance(edge, dict)])
    except Exception:
        urls = []
    with _LOCK:
        # Misses are remembered briefly so a title without trailers is not re-queried per focus.
        _CACHE[title_id] = (now + (_TTL if urls else 120), tuple(urls))
        while len(_CACHE) > 256:
            _CACHE.pop(next(iter(_CACHE)))
    return list(urls)


def resolve(title_id, timeout=5, opener=urlopen):
    """Best signed MP4 URL for the title's trailer, or '' (never raises)."""
    found = resolve_all(title_id, timeout, opener)
    return found[0] if found else ''
