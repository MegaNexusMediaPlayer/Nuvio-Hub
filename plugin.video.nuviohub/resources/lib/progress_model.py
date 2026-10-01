"""Pure wire conversions: Kodi seconds, Nuvio milliseconds, canonical episode keys."""
import math
import re


def number(value, default=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (ValueError, TypeError, OverflowError):
        return default


def timestamp(value):
    value = max(0.0, number(value))
    return value / 1000.0 if value >= 100000000000 else value


def kind(row):
    return 'series' if row.get('media_type', row.get('content_type')) in ('series', 'tv', 'show', 'tvshow', 'episode', 'anime') else 'movie'


def canonical(row):
    cid = str(row.get('canonical_id') or row.get('content_id') or '')
    if cid:
        return cid
    imdb = str(row.get('imdb_id') or '')
    if imdb.startswith('tt'):
        return imdb
    tmdb = str(row.get('tmdb_id') or '')
    return ('tmdb:' + tmdb if tmdb.isdigit() else tmdb) if tmdb else ''


def episode_numbers(row):
    if kind(row) != 'series':
        return None, None
    season, episode = row.get('season'), row.get('episode')
    if season is None or episode is None:
        match = re.search(r':([0-9]+):([0-9]+)$', str(row.get('video_id') or ''))
        if match:
            season, episode = match.groups()
    try:
        season, episode = int(season), int(episode)
        return (season, episode) if season >= 0 and episode > 0 else (None, None)
    except (TypeError, ValueError, OverflowError):
        return None, None


def wire_key(row):
    cid = canonical(row)
    season, episode = episode_numbers(row)
    return '%s_s%de%d' % (cid, season, episode) if season is not None else cid


def identity(row):
    # The explicit IMDb alias can join a TMDb catalog card to an IMDb cloud row.
    cid = str(row.get('imdb_id') or canonical(row))
    season, episode = episode_numbers(row)
    return kind(row), cid, season, episode


def percent(row):
    duration, position = number(row.get('duration')), number(row.get('position'))
    if row.get('event_type') == 'watched':
        return 100.0
    value = 100 * position / duration if duration > 0 else number(row.get('percent'))
    return min(100.0, max(0.0, value))


def to_wire(row):
    cid = canonical(row)
    duration, position = max(0.0, number(row.get('duration'))), max(0.0, number(row.get('position')))
    if not cid or duration <= 0:
        return None  # A percentage alone is NOT a measured millisecond position.
    season, episode = episode_numbers(row)
    if kind(row) == 'series' and (season is None or episode is None):
        return None
    if percent(row) >= 95:
        position = duration
    video_id = str(row.get('video_id') or (('%s:%d:%d' % (cid, season, episode)) if season is not None else cid))
    return {'content_id': cid, 'content_type': kind(row), 'video_id': video_id,
            'season': season, 'episode': episode, 'position': int(round(min(position, duration)*1000)),
            'duration': int(round(duration*1000)), 'last_watched': int(round(timestamp(row.get('updated_at'))*1000)),
            'progress_key': wire_key(row)}


def from_wire(entry):
    if not isinstance(entry, dict) or not entry.get('content_id'):
        return None
    cid = str(entry['content_id'])
    row = {'canonical_id': cid, 'media_type': kind(entry), 'video_id': str(entry.get('video_id') or cid),
           'season': entry.get('season'), 'episode': entry.get('episode'),
           'position': max(0.0, number(entry.get('position')))/1000.0,
           'duration': max(0.0, number(entry.get('duration')))/1000.0,
           'updated_at': timestamp(entry.get('last_watched')),
           'progress_key': str(entry.get('progress_key') or ''),
           'imdb_id': cid if re.fullmatch(r'tt[0-9]+', cid) else '',
           'tmdb_id': cid.split(':', 1)[1] if re.fullmatch(r'tmdb:[0-9]+', cid) else ''}
    row['season'], row['episode'] = episode_numbers(row)
    row['percent'] = percent(row)
    row['event_type'] = 'watched' if row['percent'] >= 95 else 'account_sync'
    return row
