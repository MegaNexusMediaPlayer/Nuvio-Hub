"""MegaNexus Library (6.0.35): one place for "Add to Library" and the Library screen.

* Local: the device's own library (favorites_store, source 'local'), also
  synced with the Nuvio account library.
* Tracking services: Trakt watchlist + Simkl Plan to Watch (+ MDBList), merged
  into the external mirror (favorites_store source 'trakt').
Adding saves locally and, when connected, to Trakt and Simkl as well; a
tracking service that fails never loses the local save.
"""
import xbmc

LOCAL = 'local'
TRACKING = 'trakt'   # favorites_store source of the merged Trakt/Simkl/MDBList mirror


def _kind(media_type):
    return 'movie' if media_type == 'movie' else 'series'


def tracking_connected():
    """Trakt or Simkl is connected (the Library opens on Tracking services)."""
    try:
        from . import trakt
        if trakt.authorized():
            return True
    except Exception:
        pass
    try:
        from . import simkl
        return bool(simkl.enabled() and simkl.authorized())
    except Exception:
        return False


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


def rows(source):
    """(movies, series) cards for the Library screen."""
    from . import favorites_store
    try:
        items = favorites_store.list_favorites(limit=500, source=source)
    except Exception:
        items = []
    movies, series = [], []
    for item in items:
        kind = _kind(item.get('media_type'))
        card = {'title': item.get('title') or item.get('canonical_id'), 'poster': item.get('poster') or '',
                'fanart': item.get('background') or '', 'landscape': item.get('background') or '',
                'clearlogo': item.get('clearlogo') or '', 'plot': item.get('plot') or '',
                'target': {'media_type': kind, 'canonical_id': item.get('canonical_id')}}
        (movies if kind == 'movie' else series).append(card)
    return movies, series


def refresh_tracking():
    """Pull the Trakt / Simkl watchlists into the mirror (network; call off the GUI thread)."""
    from . import favorites_store
    return favorites_store.refresh_external_mirror(include_trakt=True)
