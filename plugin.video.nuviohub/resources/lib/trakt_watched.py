"""Trakt watched marks (6.0.39): the same watched view Simkl gives, for people
who track with Trakt only (before 6.0.39 only Simkl filled the watched badges).

Synced the way Trakt asks apps to sync: /sync/last_activities first, then
/sync/watched/movies or /sync/watched/shows only when their watched time
moved. Stored per Trakt account in trakt_watched.json in the format of
simkl_watched, which merges both into one view.
"""
import hashlib
import os
import time

from . import trakt


def _path():
    return os.path.join(os.path.dirname(trakt.TOKEN_PATH), 'trakt_watched.json')


def account():
    """The signed-in Trakt user (network; service thread only). Cached in the
    token file, so it is asked once per sign-in or token refresh."""
    data = trakt.token_data()
    if not data.get('access_token'):
        return ''
    user = data.get('nuvio_user')
    if not user:
        me = trakt._request('/users/me', method='GET', auth=True, timeout=8) or {}
        user = str(((me.get('ids') or {}).get('slug')) or me.get('username') or '')
        if not user:
            raise ValueError('Trakt did not return the account.')
        data = dict(trakt.token_data(), nuvio_user=user)
        trakt.save_token(data)
    return hashlib.sha256(user.encode()).hexdigest()


def snapshot():
    """{'account', 'updated', 'activities', 'items'} - no network (Home paints it)."""
    if not trakt.authorized():
        return {'items': {}}
    data = trakt._read_json(_path(), {})
    return data if isinstance(data, dict) and data.get('items') is not None else {'items': {}}


def forget():
    try:
        os.remove(_path())
    except OSError:
        pass


def _aliases(ids):
    from .simkl_watched import aliases
    return aliases({k: v for k, v in (ids or {}).items() if k in ('imdb', 'tmdb', 'tvdb')})


def parse_movies(rows):
    items = {}
    for row in rows or []:
        movie = (row or {}).get('movie') or {}
        entry = {'watched': True, 'episodes': [], 'seasons': []}
        stamp = trakt._parse_trakt_ts(row.get('last_watched_at'))
        if stamp:
            entry['watched_at'] = stamp
        for mid in _aliases(movie.get('ids')):
            items['movie|' + mid] = entry
    return items


def parse_shows(rows):
    items = {}
    for row in rows or []:
        show = (row or {}).get('show') or {}
        episodes, times = [], {}
        for season in row.get('seasons') or []:
            for episode in season.get('episodes') or []:
                key = '%s:%s' % (season.get('number'), episode.get('number'))
                episodes.append(key)
                stamp = trakt._parse_trakt_ts(episode.get('last_watched_at'))
                if stamp:
                    times[key] = stamp
        aired = int(show.get('aired_episodes') or 0)
        seen = len([e for e in episodes if not e.startswith('0:')])   # specials do not count
        entry = {'watched': bool(aired and seen >= aired), 'episodes': episodes, 'seasons': []}
        if times:
            entry['episode_watched_at'] = times
        for mid in _aliases(show.get('ids')):
            items['series|' + mid] = entry
    return items


def refresh(force=False, max_age=900):
    if not trakt.authorized():
        return {'items': {}}
    old = snapshot()
    start = time.time()
    if not force and start - float(old.get('updated') or 0) < max_age:
        return old
    current = account()
    if old.get('account') != current:
        old = {'account': current, 'items': {}}   # another Trakt account: start over
    activities = trakt._request('/sync/last_activities', method='GET', auth=True, timeout=8)
    if not isinstance(activities, dict) or not activities.get('all'):
        raise ValueError('Trakt did not return its activity times.')
    previous = old.get('activities') or {}
    items = dict(old.get('items') or {})
    changed = False
    for section, prefix, path, parser in (
            ('movies', 'movie|', '/sync/watched/movies', parse_movies),
            ('episodes', 'series|', '/sync/watched/shows?extended=full', parse_shows)):
        now = str((activities.get(section) or {}).get('watched_at') or '')
        if previous and now == str((previous.get(section) or {}).get('watched_at') or ''):
            continue
        rows = trakt._request(path, method='GET', auth=True, timeout=15)
        if not isinstance(rows, list):
            raise ValueError('Trakt did not return the watched list.')
        items = {k: v for k, v in items.items() if not k.startswith(prefix)}
        items.update(parser(rows))
        changed = True
    result = {'account': current, 'updated': time.time(), 'activities': activities, 'items': items}
    trakt._write_json(_path(), result)
    if changed:
        from .simkl_watched import _invalidate_view
        _invalidate_view()
    return result


def mark(ctx, scope='title', season=None, episode=None):
    """Add to Trakt history (Mark watched), then to the local view."""
    if not trakt.authorized():
        raise ValueError('Connect Trakt in HUB Settings first.')
    ids = trakt._ids_payload(ctx)
    if not ids:
        raise ValueError('This title has no IMDb, TMDb or TVDb ID for Trakt.')
    series = ctx.get('media_type') != 'movie'
    item = {'ids': ids}
    if series and scope in ('season', 'episode'):
        part = {'number': int(season)}
        if scope == 'episode':
            part['episodes'] = [{'number': int(episode)}]
        item['seasons'] = [part]
    reply = trakt._request('/sync/history', payload={'shows' if series else 'movies': [item]},
                           method='POST', auth=True, timeout=10)
    added = (reply or {}).get('added') or {}
    if not any(int(added.get(k) or 0) for k in ('movies', 'episodes')):
        raise ValueError('Trakt did not confirm the change. Refresh and retry.')
    data = snapshot()
    data.setdefault('account', account())
    items = data.setdefault('items', {})
    media = 'series' if series else 'movie'
    mids = _aliases({'imdb': ids.get('imdb'), 'tmdb': ids.get('tmdb'), 'tvdb': ids.get('tvdb')})
    if ctx.get('canonical_id'):
        mids.append(ctx['canonical_id'])
    for mid in set(mids):
        entry = dict(items.get(media + '|' + mid) or {'watched': False, 'seasons': [], 'episodes': []})
        if not series or scope == 'title':
            entry['watched'] = True
        elif scope == 'season':
            entry['seasons'] = sorted(set(entry.get('seasons', [])) | {str(season)})
        else:
            entry['episodes'] = sorted(set(entry.get('episodes', [])) | {'%s:%s' % (season, episode)})
        items[media + '|' + mid] = entry
    data['updated'] = time.time()
    trakt._write_json(_path(), data)
    from .simkl_watched import _invalidate_view
    _invalidate_view()
    return True
