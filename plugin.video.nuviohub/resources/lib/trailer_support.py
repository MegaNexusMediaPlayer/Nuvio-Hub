"""Opt-in, delayed windowed previews. Never stop a player we do not own."""
import re
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import xbmc
import xbmcaddon
import xbmcgui


def trailer_url(meta,allow_youtube=True):
    trailers = meta.get('trailers') or []
    if not isinstance(trailers, list): trailers = [trailers]
    streams=meta.get('trailerStreams') or meta.get('trailer_streams') or []
    if not isinstance(streams,list):streams=[streams]
    values = [meta.get('trailer')] + streams + trailers
    for item in values:
        if isinstance(item, dict): item = item.get('url') or item.get('source') or item.get('ytId') or item.get('videoId')
        if not isinstance(item, str) or not item.strip(): continue
        value = item.strip()
        if any(c in value for c in ('\r', '\n', '"', '|')): continue
        parts = urlsplit(value)
        video_id = ''
        if re.fullmatch(r'[A-Za-z0-9_-]{11}', value): video_id = value
        elif parts.hostname in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
            video_id = (parse_qs(parts.query).get('v') or [''])[0]
        elif parts.hostname == 'youtu.be': video_id = parts.path.strip('/')
        elif parts.scheme == 'plugin' and parts.netloc == 'plugin.video.youtube':
            video_id = (parse_qs(parts.query).get('video_id') or [''])[0]
        elif parts.scheme in ('https', 'http') and parts.netloc and parts.path.lower().endswith(('.mp4', '.m3u8', '.webm')):
            return value
        if re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            if not allow_youtube:continue
            return 'plugin://plugin.video.youtube/play/?video_id=' + video_id
    return ''


def trailer_candidates(youtube_url='', records=(), direct_only=False, addon=None):
    """Playable trailer URLs in the user's source order (Settings > Trailers).

    ``youtube_url`` is the add-on/metadata trailer (YouTube or a direct file);
    IMDb trailers are looked up from the IMDb ID in ``records``. A YouTube link
    is skipped when ``direct_only`` or when the YouTube add-on is missing.
    """
    from . import imdb_trailers
    urls = []
    for source in imdb_trailers.order(imdb_trailers.source_setting(addon)):
        if source == 'imdb':
            title_id = imdb_trailers.imdb_id(*records)
            if title_id:
                urls.extend(imdb_trailers.resolve_all(title_id)[:2])
        elif youtube_url:
            if youtube_url.startswith('plugin://plugin.video.youtube/') and (
                    direct_only or not xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)')):
                continue
            urls.append(youtube_url)
    return list(dict.fromkeys(urls))


def _provider_trailer(row, direct_only):
    url = trailer_url({'trailer':row.get('trailer')},allow_youtube=not direct_only)
    if not url and row.get('target'):
        from . import backend_api
        target = row['target']
        source=backend_api.provider('metadata')
        if not source:return ''
        from .nuviohub.client import get_json,build_resource_url
        data=get_json(build_resource_url(source,'meta',target.get('media_type') or 'movie',target['canonical_id']),ttl_seconds=3600,timeout_override=3,retry=False,rate_wait=.1)
        url=trailer_url((data or {}).get('meta') or {},allow_youtube=not direct_only)
    return url


def selected_trailers(row,direct_only=False):
    """Candidates for a Home card, in the chosen source order (a generator).

    The next source is only looked up when the caller could not use the
    previous candidates, so a Home focus normally costs one lookup - and a
    YouTube trailer the device cannot resolve still falls back to IMDb.
    """
    from . import imdb_trailers
    for source in imdb_trailers.order(imdb_trailers.source_setting()):
        if source == 'imdb':
            title_id = imdb_trailers.imdb_id(row.get('target') or {}, row)
            if title_id:
                for url in imdb_trailers.resolve_all(title_id)[:2]:
                    yield url
        else:
            try:
                url = _provider_trailer(row, direct_only)
            except Exception:
                url = ''
            if url.startswith('plugin://plugin.video.youtube/') and not xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'):
                url = ''
            if url:
                yield url


def playable(url, prepare, cancelled=None):
    """Local cached clip for downloadable trailers; IMDb CDN files stream directly."""
    from . import imdb_trailers
    if imdb_trailers.direct_stream(url):
        return url
    return prepare({'trailer': url}, cancelled)


def youtube_allowed():
    """Kodi's own trailer buttons may use a YouTube link only when it can play it."""
    from . import imdb_trailers
    return (imdb_trailers.source_setting() != 'imdb' and
            xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'))


def selected_trailer(row,direct_only=False):
    return next(iter(selected_trailers(row, direct_only)), '')
