"""MegaNexus Library (6.0.35): one place for "Add to Library" and the Library screen.

* Local: the device's own library (favorites_store, source 'local'), also
  synced with the Nuvio account library.
* Tracking services: Trakt watchlist + Simkl Plan to Watch (+ MDBList), merged
  into the external mirror (favorites_store source 'trakt'). TRACKERS is the
  one list to extend for another service: its name labels the Library tab and
  the small badge on each card.
* Calendar: everything in the Library by the month it was added.
Adding saves locally and, when connected, to Trakt and Simkl as well; a
tracking service that fails never loses the local save.
"""
import xbmc

LOCAL = 'local'
TRACKING = 'trakt'   # favorites_store source of the merged Trakt/Simkl/MDBList mirror


def _kind(media_type):
    return 'movie' if media_type == 'movie' else 'series'


def _trakt_connected():
    from . import trakt
    return trakt.authorized()


def _simkl_connected():
    from . import simkl
    return bool(simkl.enabled() and simkl.authorized())


def _mdblist_connected():
    from . import mdblist
    return bool(mdblist.configured())


def _trakt_rows():
    from . import trakt
    return trakt.fetch_watchlist(limit=200) or []


def _simkl_rows():
    from . import simkl
    return simkl.watchlist_mirror_rows(limit=200) or []


def _mdblist_rows():
    from . import mdblist
    return mdblist.watchlist_mirror_rows(limit=200) or []


# id, name, connected(), watchlist rows(). Add a service here and the Library
# tab label, the card badges and the refresh follow.
TRACKERS = (
    ('trakt', 'Trakt', _trakt_connected, _trakt_rows),
    ('simkl', 'Simkl', _simkl_connected, _simkl_rows),
    ('mdblist', 'MDBList', _mdblist_connected, _mdblist_rows),
)


def connected_trackers():
    found = []
    for tid, name, connected, _ in TRACKERS:
        try:
            if connected():
                found.append((tid, name))
        except Exception:
            continue
    return found


def tracking_connected():
    """A tracking service is connected (the Library opens on its tab)."""
    return bool(connected_trackers())


def tracking_label():
    names = [name for _, name in connected_trackers()]
    return ' · '.join(names) if names else 'Tracking'


def _origins_path():
    from . import favorites_store
    return favorites_store.ORIGINS_PATH


def _origins():
    from .nuviohub.safe_io import read_json
    data = read_json(_origins_path(), {})
    return data if isinstance(data, dict) else {}


def contains(media_type, canonical_id):
    from . import favorites_store
    try:
        rows = favorites_store.list_favorites(limit=5000, source=LOCAL)
    except Exception:
        return False
    kind = _kind(media_type)
    return any(_kind(r.get('media_type')) == kind and r.get('canonical_id') == canonical_id for r in rows)


def _ids(item):
    ids = {}
    for key in ('imdb_id', 'tmdb_id', 'tvdb_id'):
        if item.get(key):
            ids[key] = str(item[key])
    cid = str(item.get('canonical_id') or item.get('id') or '')
    if cid.startswith('tt') and 'imdb_id' not in ids:
        ids['imdb_id'] = cid.split(':')[0]
    if cid.startswith('tmdb:') and 'tmdb_id' not in ids:
        ids['tmdb_id'] = cid.split(':')[1]
    return ids


def _trakt_add(item):
    from . import trakt
    if not trakt.authorized():
        return False
    ids = trakt._ids_payload(_ids(item))
    if not ids:
        return False
    kind = 'movies' if _kind(item.get('media_type')) == 'movie' else 'shows'
    trakt._request('/sync/watchlist', payload={kind: [{'ids': ids}]}, method='POST', auth=True, timeout=8)
    trakt.invalidate_cache('/users/me/watchlist')
    return True


def _simkl_add(item):
    from . import simkl
    if not (simkl.enabled() and simkl.authorized()):
        return False
    ctx = dict(_ids(item), media_type=_kind(item.get('media_type')), title=item.get('title') or '')
    return bool(simkl.add_to_library(ctx))


def add(item):
    """Save a title (row/meta-like dict). Returns the tracking services it also reached."""
    from . import favorites_store
    media_type = _kind(item.get('media_type') or item.get('type'))
    cid = str(item.get('canonical_id') or item.get('id') or '')
    if not cid:
        raise ValueError('This title has no ID to save.')
    favorites_store.add(media_type, cid, item.get('title') or item.get('name') or cid,
                        poster=item.get('poster') or '', background=item.get('background') or item.get('fanart') or '',
                        clearlogo=item.get('clearlogo') or item.get('logo') or '', plot=item.get('plot') or item.get('description') or '',
                        source=LOCAL)
    reached = []
    for name, fn in (('Trakt', _trakt_add), ('Simkl', _simkl_add)):
        try:
            if fn(dict(item, media_type=media_type, canonical_id=cid)):
                reached.append(name)
        except Exception as exc:
            xbmc.log('[MegaNexus] Library: %s save skipped: %s' % (name, exc), xbmc.LOGWARNING)
    return reached


def remove(media_type, canonical_id):
    from . import favorites_store
    favorites_store.remove(_kind(media_type), canonical_id, source=LOCAL)


def _card(item, badge):
    kind = _kind(item.get('media_type'))
    return {'title': item.get('title') or item.get('canonical_id'), 'poster': item.get('poster') or '',
            'fanart': item.get('background') or '', 'landscape': item.get('background') or '',
            'clearlogo': item.get('clearlogo') or '', 'plot': item.get('plot') or '', 'badge': badge,
            'added_at': int(item.get('added_at') or 0),
            'target': {'media_type': kind, 'canonical_id': item.get('canonical_id')}}


def _items(source):
    from . import favorites_store
    try:
        return favorites_store.list_favorites(limit=500, source=source)
    except Exception:
        return []


def _badge(item, source, origins):
    if source == LOCAL:
        return 'Local'
    key = '%s|%s' % (_kind(item.get('media_type')), item.get('canonical_id'))
    names = dict((tid, name) for tid, name, _, _ in TRACKERS)
    return names.get(origins.get(key), '') or tracking_label()


def rows(source):
    """(movies, series) cards for the Library screen."""
    origins = _origins() if source == TRACKING else {}
    movies, series = [], []
    for item in _items(source):
        card = _card(item, _badge(item, source, origins))
        (movies if card['target']['media_type'] == 'movie' else series).append(card)
    return movies, series


MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
          'September', 'October', 'November', 'December')


def calendar(limit=14):
    """[(\"October 2026\", cards)] - everything in the Library by the month it
    was added, newest first (month and year only). Older months share the
    last row."""
    import time as _time
    origins = _origins()
    merged = {}
    for source in (LOCAL, TRACKING):
        for item in _items(source):
            key = (_kind(item.get('media_type')), item.get('canonical_id'))
            badge = _badge(item, source, origins)
            if key in merged:
                old = merged[key]
                if badge not in old['badge'].split(' · '):
                    old['badge'] += ' · ' + badge
                old['added_at'] = max(old['added_at'], int(item.get('added_at') or 0))
            else:
                merged[key] = _card(item, badge)
    months = {}
    for card in sorted(merged.values(), key=lambda c: c['added_at'], reverse=True):
        stamp = _time.localtime(card['added_at'] or _time.time())
        months.setdefault((stamp.tm_year, stamp.tm_mon), []).append(card)
    ordered = sorted(months.items(), reverse=True)
    result = [('%s %d' % (MONTHS[mon - 1], year), cards) for (year, mon), cards in ordered]
    if len(result) > limit:
        result = result[:limit - 1] + [('Earlier', [c for _, cards in result[limit - 1:] for c in cards])]
    return result


def refresh_tracking():
    """Pull the connected services' watchlists into the mirror (network; call
    off the GUI thread). One path for the Library, the service and Settings."""
    from . import favorites_store
    return favorites_store.refresh_external_mirror(include_trakt=True)
