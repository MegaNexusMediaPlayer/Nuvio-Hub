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


def selected_trailer(row,direct_only=False):
    url = trailer_url({'trailer':row.get('trailer')},allow_youtube=not direct_only)
    if not url and row.get('target'):
        from . import backend_api
        target = row['target']
        source=backend_api.provider('metadata')
        if not source:return ''
        from .nuviohub.client import get_json,build_resource_url
        data=get_json(build_resource_url(source,'meta',target.get('media_type') or 'movie',target['canonical_id']),ttl_seconds=3600,timeout_override=3,retry=False,rate_wait=.1)
        url=trailer_url((data or {}).get('meta') or {},allow_youtube=not direct_only)
    if url.startswith('plugin://plugin.video.youtube/') and not xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'):
        return ''
    return url
