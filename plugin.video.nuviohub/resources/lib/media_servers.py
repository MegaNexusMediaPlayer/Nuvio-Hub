"""Plex and Jellyfin / Emby in MegaNexus (6.0.39, beta).

Everything is OFF until the user signs in and turns the server on (HUB
Settings > Accounts > Plex / Jellyfin): no request, no import of the server
clients, no row. When on:

* Sources: when a title is played, the user's own servers are searched by its
  IMDb / TMDb ID (episode by season and number) at the same time as the
  stream add-ons, and their copies come FIRST in the list ("Plex · <server>"),
  so autoplay prefers the own copy. Playback reports progress and watched
  back to the server (companion reporters).
* Home rows: "<Server> · Continue watching" and "<Server> · Recently added"
  (Home rows switch, off by default). Posters come from the server itself,
  resized there; MegaNexus metadata is used only to open the title page of a
  title that has an IMDb / TMDb ID, never to download a second poster.
"""
import time

PLEX, JELLYFIN = 'plex', 'jellyfin'
KINDS = (PLEX, JELLYFIN)
ENABLED = {PLEX: 'nuvio_plex_enabled', JELLYFIN: 'nuvio_jellyfin_enabled'}
SOURCES = {PLEX: 'plex_in_sources', JELLYFIN: 'emby_in_sources'}
HOME = {PLEX: 'nuvio_home_plex', JELLYFIN: 'nuvio_home_jellyfin'}
SOURCE_ID = {PLEX: '__plex__', JELLYFIN: '__emby__'}
ROW_LIMIT = 30
ROW_SECONDS = 120          # a Home repaint reuses server rows this long
MAX_VERSIONS = 3
_ROWS = {}


def _addon(addon=None):
    if addon is not None:
        return addon
    from .settings_cache import cached_addon
    return cached_addon()


def _setting(addon, key, default=''):
    try:
        return addon.getSetting(key) or default
    except Exception:
        return default


def signed_in(kind):
    try:
        if kind == PLEX:
            from . import plex_client
            return plex_client.is_signed_in()
        from . import emby_client
        return emby_client.is_signed_in()
    except Exception:
        return False


def enabled(kind, addon=None):
    """On only after sign-in AND the switch (default off)."""
    return _setting(_addon(addon), ENABLED[kind]) == 'true' and signed_in(kind)


def label(kind):
    if kind == PLEX:
        return 'Plex'
    try:
        from . import emby_client
        return 'Emby' if emby_client.flavor_of(emby_client.account()) == emby_client.EMBY else 'Jellyfin'
    except Exception:
        return 'Jellyfin'


def status(kind):
    """Short account line for Settings (no network)."""
    if not signed_in(kind):
        return 'Not connected'
    try:
        if kind == PLEX:
            from . import plex_client
            user = plex_client.account().get('username') or 'connected'
            return 'Connected · %s' % user
        from . import emby_client
        auth = emby_client.account()
        return 'Connected · %s · %s' % (auth.get('server_name') or label(kind), auth.get('username') or '')
    except Exception:
        return 'Connected'


# ------------------------------------------------------------------ sources --

def parse_video_id(media_type, video_id):
    """'tt1:2:3' / 'tmdb:5:2:3' -> ({'imdb_id'|'tmdb_id': ...}, season, episode)."""
    parts = str(video_id or '').split(':')
    if parts and parts[0] == 'tmdb' and len(parts) > 1:
        ids, rest = {'tmdb_id': parts[1]}, parts[2:]
    elif parts and parts[0].startswith('tt'):
        ids, rest = {'imdb_id': parts[0]}, parts[1:]
    else:
        return None, None, None
    if media_type == 'series':
        try:
            return ids, int(rest[0]), int(rest[1])
        except (IndexError, TypeError, ValueError):
            return None, None, None   # a series without an episode is not playable
    return ids, None, None


def _plex_rows(ids, media_type, season, episode):
    from . import plex_client
    from .servers import health
    rows = []
    for server in plex_client.servers() or []:
        if not health.should_query('plex', server):
            continue
        try:
            found = plex_client.find_all_by_ids(server, ids, media_type=media_type, title='', limit=3)
            if season is not None:
                found = [e for e in (plex_client.episode_item(server, show, season, episode) for show in found[:1]) if e]
        except Exception:
            continue
        for item in found:
            # Since 2025/2026 Plex needs Plex Pass or Remote Watch Pass to stream
            # outside the home network; say so instead of a bare failure.
            away = not plex_client.is_local_connection(server, item.get('server_url'))
            for version in [v for v in (item.get('versions') or []) if v.get('part_key')][:MAX_VERSIONS]:
                name = 'Plex · %s' % (item.get('server_name') or 'Server')
                title = version.get('info_line') or version.get('version_label') or 'Direct play'
                rows.append({
                    'name': name, 'title': title + (' · away from home: needs Plex Pass or Remote Watch Pass' if away else ''),
                    'url': plex_client.playback_url(item, version['part_key']),
                    'subtitles': list(version.get('subtitles') or []),
                    '_nuvio_source': {'id': SOURCE_ID[PLEX], 'name': name, 'base_url': ''},
                    '_nuvio_server': {'server_type': 'plex', 'server_url': item.get('server_url') or '',
                                      'token': item.get('token') or '', 'rating_key': str(item.get('rating_key') or ''),
                                      'client_id': plex_client.client_identifier(), 'product': 'MegaNexus',
                                      'device_name': 'Kodi', 'duration_ms': int(item.get('duration_ms') or 0)},
                })
    return rows


def _jellyfin_rows(ids, media_type, season, episode):
    from . import emby_client
    rows = []
    for server in emby_client.servers() or []:
        try:
            found = emby_client.find_all_by_ids(server, ids, media_type=media_type, title='', limit=3)
            if season is not None:
                found = [e for e in (emby_client.episode_item(server, show, season, episode) for show in found[:1]) if e]
        except Exception:
            continue
        for item in found:
            for version in (item.get('versions') or [{}])[:MAX_VERSIONS]:
                try:
                    resolved = emby_client.resolve_playback(server, item['rating_key'], version.get('media_source_id') or '')
                except Exception:
                    continue
                version = resolved.get('version') or version
                name = '%s · %s' % (label(JELLYFIN), server.get('name') or 'Server')
                rows.append({
                    'name': name, 'title': version.get('info_line') or version.get('version_label') or 'Direct play',
                    'url': resolved['url'], 'subtitles': list(version.get('subtitles') or []),
                    '_nuvio_source': {'id': SOURCE_ID[JELLYFIN], 'name': name, 'base_url': ''},
                    '_nuvio_server': {'server_type': 'emby', 'server_url': server.get('url') or '',
                                      'server_flavor': emby_client.flavor_of(server), 'token': server.get('token') or '',
                                      'item_id': str(item['rating_key']), 'device_id': emby_client._device_id(),
                                      'session_id': resolved.get('play_session_id') or '',
                                      'play_session_id': resolved.get('play_session_id') or '',
                                      'media_source_id': resolved.get('media_source_id') or '',
                                      'duration_ms': int(item.get('duration_ms') or 0)},
                })
    return rows


def source_jobs(media_type, video_id, addon=None):
    """[(name, fn)] - one job per enabled server kind; [] costs nothing."""
    addon = _addon(addon)
    ids, season, episode = parse_video_id(media_type, video_id)
    if not ids:
        return []
    jobs = []
    for kind, fn in ((PLEX, _plex_rows), (JELLYFIN, _jellyfin_rows)):
        if _setting(addon, SOURCES[kind], 'true') != 'false' and enabled(kind, addon):
            jobs.append((label(kind), lambda fn=fn: fn(ids, media_type, season, episode)))
    return jobs


def playback_keys(row):
    """Server reporting keys for the playback context of a server row."""
    keys = dict(row.get('_nuvio_server') or {})
    if keys.get('server_type') == 'plex':
        try:
            from .settings_cache import cached_addon
            keys['product_version'] = cached_addon().getAddonInfo('version') or ''
        except Exception:
            pass
    return keys


# ---------------------------------------------------------------- Home rows --

def shelves(addon=None):
    """Home shelves (no network): filled later by load_rows in a worker."""
    addon = _addon(addon)
    out = []
    for kind in KINDS:
        if _setting(addon, HOME[kind]) == 'true' and enabled(kind, addon):
            name = label(kind)
            for part, title in (('continue', 'Continue watching'), ('recent', 'Recently added')):
                out.append({'title': '%s · %s' % (name, title), 'server_job': [kind, part],
                            'rows': [{'title': 'Loading…', 'plot': 'Reading your %s server.' % name, 'path': '',
                                      'is_folder': False, 'poster': '', 'fanart': '', 'subtitle': '', 'meta_line': ''}]})
    return out


def _target(ids, media_type, title, poster, fanart):
    imdb = str(ids.get('imdb_id') or '')
    canonical = imdb if imdb.startswith('tt') else ('tmdb:%s' % ids['tmdb_id'] if ids.get('tmdb_id') else '')
    if not canonical:
        return None
    return dict(media_type=media_type, canonical_id=canonical, title=title, source_provider_id='',
                season='', episode='', video_id='', tmdb_id=ids.get('tmdb_id') or '', imdb_id=imdb,
                tvdb_id=ids.get('tvdb_id') or '', ui_seed={'poster': poster, 'fanart': fanart, 'clearlogo': ''})


def _card(kind, item, poster, fanart, play_path, resume_ms=0):
    media = item.get('media_type')
    title = item.get('raw_title') or item.get('title') or 'Untitled'
    if media == 'episode':
        show = item.get('show_title') or ''
        title = '%s · S%s E%s' % (show, item.get('season') or 0, item.get('index') or 0) if show else title
    duration = int(item.get('duration_ms') or 0)
    percent = int(resume_ms * 100 / duration) if resume_ms and duration else 0
    year = str(item.get('year') or '') if item.get('year') else ''
    card = {'title': title, 'subtitle': ('%d%% watched' % percent) if percent else year,
            'plot': item.get('summary') or '', 'poster': poster, 'fanart': fanart, 'landscape': fanart,
            'clearlogo': '', 'percent_value': percent,
            'meta_line': '  |  '.join(x for x in (year, 'Series' if media in ('show', 'episode') else 'Movie', label(kind)) if x),
            'path': '', 'is_folder': False}
    target = _target(item.get('ids') or {}, 'series' if media == 'show' else 'movie', title, poster, fanart) \
        if media in ('movie', 'show') else None
    if target and not percent:
        card['target'] = target          # opens the MegaNexus title page (server copy is the first source)
    else:
        card['server_play'] = play_path  # episodes, resumes and unidentified titles play from the server
    return card


def _plex_items(part):
    from . import plex_client
    items = []
    for server in plex_client.servers() or []:
        try:
            if part == 'continue':
                found = plex_client.on_deck(server, 0, ROW_LIMIT)
            else:
                root, base = plex_client._server_xml(server, '/library/recentlyAdded',
                                                     {'X-Plex-Container-Start': 0, 'X-Plex-Container-Size': ROW_LIMIT})
                found = [plex_client.item_from_node(n, server, base) for n in list(root.findall('./Video')) + list(root.findall('./Directory'))
                         if (n.attrib.get('type') or '') in ('movie', 'show', 'episode')]
        except Exception:
            continue
        for item in found:
            thumb = item.get('parent_thumb') if item.get('media_type') == 'episode' and item.get('parent_thumb') else item.get('thumb')
            play = 'plugin://plugin.video.nuviohub/?action=plex_play&server_id=%s&rating_key=%s' % (
                item.get('server_id'), item.get('rating_key'))
            items.append(_card(PLEX, item, plex_client.poster_url(item, thumb), plex_client.poster_url(item, item.get('art'), 1280, 720),
                               play, item.get('view_offset_ms') or 0))
    return items


def _jellyfin_items(part):
    from . import emby_client
    items = []
    for server in emby_client.servers() or []:
        try:
            if part == 'continue':
                found, _ = emby_client.resume(server, 0, ROW_LIMIT)
                seen = {f.get('rating_key') for f in found}
                found += [n for n in emby_client.next_up(server, ROW_LIMIT) if n.get('rating_key') not in seen]
            else:
                found = emby_client.latest(server, ROW_LIMIT)
        except Exception:
            continue
        for item in found[:ROW_LIMIT]:
            image = item.get('series_id') if item.get('media_type') == 'episode' and item.get('series_id') else item.get('rating_key')
            play = 'plugin://plugin.video.nuviohub/?action=emby_play&item_id=%s' % item.get('rating_key')
            items.append(_card(JELLYFIN, item, emby_client.artwork_url(server, image),
                               emby_client.artwork_url(server, image, kind='Backdrop'), play, item.get('resume_ms') or 0))
    return items


def load_rows(kind, part):
    """Cards for one server shelf (network; Home worker thread)."""
    key = (kind, part)
    hit = _ROWS.get(key)
    if hit and time.monotonic() - hit[0] < ROW_SECONDS:
        return list(hit[1])
    rows = (_plex_items if kind == PLEX else _jellyfin_items)(part)
    if not rows:
        rows = [{'title': 'Nothing here yet' if part == 'continue' else 'No new titles',
                 'plot': 'Titles you start on %s appear here.' % label(kind) if part == 'continue'
                 else 'Titles added to your %s server appear here.' % label(kind),
                 'subtitle': '', 'poster': '', 'fanart': '', 'meta_line': '', 'path': '', 'is_folder': False}]
    _ROWS[key] = (time.monotonic(), rows)
    return list(rows)


def forget():
    _ROWS.clear()
