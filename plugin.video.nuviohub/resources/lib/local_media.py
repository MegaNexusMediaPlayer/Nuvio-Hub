"""Local storage (6.0.37): movies and series from the device's own storage.

Kodi already scans folders (USB disk, NAS, SMB/NFS shares) into its video
library and keeps resume points and watched state for them. MegaNexus reads
that library through JSON-RPC and shows it as "Local Movies" / "Local Series"
rows on Home (Settings > Collections > Home rows, or HUB Settings > Local
storage). Playback opens the library item itself, so Kodi's own resume and
watched marks keep working; MegaNexus' stream tracking stays out of it.
"""
import json
import time

import xbmc

HOME_SETTING = 'nuvio_home_local'
SOURCES_WINDOW = 'ActivateWindow(Videos,sources://video/,return)'
KINDS = ('movie', 'series')
TITLES = {'movie': 'Local Movies', 'series': 'Local Series'}
ROW_LIMIT = 40
_COUNTS = {'at': 0.0, 'value': None}
COUNT_SECONDS = 60


def rpc(method, params=None):
    request = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params:
        request['params'] = params
    try:
        reply = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    except (TypeError, ValueError):
        return {}
    return (reply.get('result') or {}) if isinstance(reply, dict) else {}


def enabled(addon=None):
    try:
        if addon is None:
            from .settings_cache import cached_addon
            addon = cached_addon()
        return addon.getSetting(HOME_SETTING) == 'true'
    except Exception:
        return False


def counts(fresh=False):
    """{'movie': n, 'series': n} - cached for a minute, Home asks on every paint."""
    now = time.monotonic()
    if not fresh and _COUNTS['value'] is not None and now - _COUNTS['at'] < COUNT_SECONDS:
        return dict(_COUNTS['value'])
    value = {'movie': int((rpc('VideoLibrary.GetMovies', {'limits': {'start': 0, 'end': 1}}).get('limits') or {}).get('total') or 0),
             'series': int((rpc('VideoLibrary.GetTVShows', {'limits': {'start': 0, 'end': 1}}).get('limits') or {}).get('total') or 0)}
    _COUNTS.update(at=now, value=value)
    return dict(value)


def forget_counts():
    _COUNTS.update(at=0.0, value=None)


def shelves(addon=None):
    """Home shelves for the local library; only kinds that have titles."""
    if not enabled(addon):
        return []
    have = counts()
    return [{'title': TITLES[kind], 'local_job': kind, 'rows': [loading_card(kind)]} for kind in KINDS if have.get(kind)]


def loading_card(kind):
    return {'title': 'Loading…', 'plot': 'Reading your %s from this device.' % ('movies' if kind == 'movie' else 'series'),
            'path': '', 'is_folder': False, 'poster': '', 'fanart': '', 'subtitle': '', 'meta_line': ''}


def _art(art, *keys):
    for key in keys:
        value = (art or {}).get(key)
        if value:
            return value
    return ''


def _percent(resume):
    try:
        position, total = float((resume or {}).get('position') or 0), float((resume or {}).get('total') or 0)
    except (TypeError, ValueError):
        return 0
    return int(position * 100 / total) if position > 0 and total > 0 else 0


MOVIE_FIELDS = ['title', 'year', 'plot', 'art', 'rating', 'runtime', 'playcount', 'resume', 'genre', 'dateadded']
SHOW_FIELDS = ['title', 'year', 'plot', 'art', 'rating', 'playcount', 'episode', 'watchedepisodes', 'season', 'genre', 'dateadded']


def movie_card(movie):
    percent = _percent(movie.get('resume'))
    year = str(movie.get('year') or '')
    watched = bool(movie.get('playcount'))
    state = ('%d%% watched' % percent) if percent else ('Watched' if watched else '')
    rating = ('%.1f' % float(movie['rating'])) if movie.get('rating') else ''
    art = movie.get('art') or {}
    return {'title': movie.get('label') or movie.get('title') or 'Untitled',
            'subtitle': '  ·  '.join(x for x in (year, state) if x),
            'meta_line': '  |  '.join(x for x in (year, 'Movie', 'Local', rating) if x),
            'plot': movie.get('plot') or '', 'poster': _art(art, 'poster', 'thumb'),
            'fanart': _art(art, 'fanart'), 'landscape': _art(art, 'landscape', 'fanart'),
            'clearlogo': _art(art, 'clearlogo'), 'percent_value': percent, 'watched': '1' if watched and not percent else '',
            'local': {'type': 'movie', 'id': movie.get('movieid'), 'title': movie.get('label') or movie.get('title') or ''},
            'path': '', 'is_folder': False}


def show_card(show):
    total, seen = int(show.get('episode') or 0), int(show.get('watchedepisodes') or 0)
    left = max(0, total - seen)
    if total and not left:
        state = 'Watched'
    elif seen:
        state = '%d new episode%s' % (left, '' if left == 1 else 's')
    else:
        state = '%d episode%s' % (total, '' if total == 1 else 's') if total else ''
    year = str(show.get('year') or '')
    rating = ('%.1f' % float(show['rating'])) if show.get('rating') else ''
    art = show.get('art') or {}
    return {'title': show.get('label') or show.get('title') or 'Untitled',
            'subtitle': '  ·  '.join(x for x in (year, state) if x),
            'meta_line': '  |  '.join(x for x in (year, 'Series', 'Local', rating) if x),
            'plot': show.get('plot') or '', 'poster': _art(art, 'poster', 'thumb'),
            'fanart': _art(art, 'fanart'), 'landscape': _art(art, 'landscape', 'fanart'),
            'clearlogo': _art(art, 'clearlogo'), 'watched': '1' if total and not left else '',
            'local': {'type': 'series', 'id': show.get('tvshowid'), 'title': show.get('label') or show.get('title') or ''},
            'path': '', 'is_folder': False}


def rows(kind, limit=ROW_LIMIT):
    """Newest first, like a streaming row of recently added titles."""
    sort = {'method': 'dateadded', 'order': 'descending'}
    if kind == 'movie':
        found = rpc('VideoLibrary.GetMovies', {'properties': MOVIE_FIELDS, 'sort': sort, 'limits': {'start': 0, 'end': limit}})
        cards = [movie_card(m) for m in found.get('movies') or [] if m.get('movieid')]
    else:
        found = rpc('VideoLibrary.GetTVShows', {'properties': SHOW_FIELDS, 'sort': sort, 'limits': {'start': 0, 'end': limit}})
        cards = [show_card(s) for s in found.get('tvshows') or [] if s.get('tvshowid')]
    total = int((found.get('limits') or {}).get('total') or len(cards))
    if total > len(cards):
        cards.append({'title': 'All local %s' % ('movies' if kind == 'movie' else 'series'),
                      'plot': '%d titles on this device. Open the full list in Kodi.' % total, 'subtitle': 'Browse',
                      'poster': '', 'fanart': '', 'meta_line': '', 'is_folder': False, 'path': '',
                      'local': {'type': 'all', 'kind': kind}})
    return cards or [{'title': 'No local %s' % ('movies' if kind == 'movie' else 'series'),
                      'plot': 'Add a folder in HUB Settings > Local storage.', 'subtitle': 'Settings',
                      'poster': '', 'fanart': '', 'meta_line': '', 'is_folder': True,
                      'path': 'plugin://plugin.video.nuviohub/?action=setup_center'}]


def library_window(kind):
    return 'ActivateWindow(Videos,videodb://%s/titles/,return)' % ('movies' if kind == 'movie' else 'tvshows')


def seasons(tvshow_id):
    found = rpc('VideoLibrary.GetSeasons', {'tvshowid': int(tvshow_id), 'properties': ['season', 'episode', 'watchedepisodes', 'art'],
                                           'sort': {'method': 'season'}})
    return [s for s in found.get('seasons') or [] if s.get('episode')]


def episodes(tvshow_id, season=None):
    params = {'tvshowid': int(tvshow_id), 'properties': ['title', 'season', 'episode', 'plot', 'art', 'playcount', 'resume', 'runtime', 'firstaired'],
              'sort': {'method': 'episode'}}
    if season is not None:
        params['season'] = int(season)
    return rpc('VideoLibrary.GetEpisodes', params).get('episodes') or []


def next_episode(items):
    """Index of the episode to preselect: one in progress, else the first unwatched."""
    for index, item in enumerate(items):
        if _percent(item.get('resume')):
            return index
    for index, item in enumerate(items):
        if not item.get('playcount'):
            return index
    return 0


def resume_seconds(kind, item_id):
    method, key, field = (('VideoLibrary.GetMovieDetails', 'movieid', 'moviedetails') if kind == 'movie'
                          else ('VideoLibrary.GetEpisodeDetails', 'episodeid', 'episodedetails'))
    details = rpc(method, {key: int(item_id), 'properties': ['resume']}).get(field) or {}
    try:
        return float((details.get('resume') or {}).get('position') or 0)
    except (TypeError, ValueError):
        return 0.0


def play(kind, item_id, resume=True):
    """Play a library movie / episode; Kodi keeps its own resume point and watched mark."""
    key = 'movieid' if kind == 'movie' else 'episodeid'
    reply = json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'Player.Open',
                                                       'params': {'item': {key: int(item_id)}, 'options': {'resume': bool(resume)}}})))
    return not reply.get('error')


def scan():
    forget_counts()
    xbmc.executebuiltin('UpdateLibrary(video)')


def clean():
    forget_counts()
    xbmc.executebuiltin('CleanLibrary(video)')


def sources():
    return [s for s in rpc('Files.GetSources', {'media': 'video'}).get('sources') or [] if s.get('file')]
