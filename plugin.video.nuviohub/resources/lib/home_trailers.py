"""Opt-in, delayed windowed previews. Never stop a player we do not own."""
import re
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import xbmc
import xbmcaddon
import xbmcgui


def trailer_url(meta):
    trailers = meta.get('trailers') or []
    if not isinstance(trailers, list): trailers = [trailers]
    values = [meta.get('trailer')] + trailers
    for item in values:
        if isinstance(item, dict): item = item.get('source') or item.get('url')
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
            return 'plugin://plugin.video.youtube/play/?video_id=' + video_id
    return ''


def selected_trailer(row):
    url = row.get('trailer') or ''
    if not url and row.get('target'):
        from .dexhub import store
        from .dexhub.client import fetch_meta
        target = row['target']
        provider = next((p for p in store.list_providers() if p.get('id') == target.get('source_provider_id')), None)
        if provider:
            result = fetch_meta(provider, target.get('media_type') or 'movie', target['canonical_id'], timeout_override=4)
            url = trailer_url((result or {}).get('meta') or {})
    if url.startswith('plugin://plugin.video.youtube/') and not xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'):
        return ''
    return url


class PreviewPlayer(xbmc.Player):
    def __init__(self):
        super(PreviewPlayer, self).__init__()
        self.token = ''
        self.cancelled = False

    def owns(self):
        try:
            return bool(self.token and self.isPlayingVideo() and self.getPlayingItem().getProperty('nuvio.preview') == self.token)
        except Exception:
            return False

    def onAVStarted(self):
        if self.cancelled and self.owns(): self.stop()

    def cancel(self):
        self.cancelled = True
        if self.owns(): self.stop()


class Controller:
    def __init__(self, window):
        self.window = window
        self.stop_event = threading.Event()
        self.player = PreviewPlayer()
        self.lock = threading.RLock()
        self.thread = threading.Thread(target=self.run, name='NuvioHomePreview', daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        with self.lock:
            self.stop_event.set()
            self.player.cancel()
            self.window.setProperty('nuvio.preview', '')
            xbmcgui.Window(10000).clearProperty('nuvio.preview.active')

    def run(self):
        previous, changed, attempted, started = None, 0, False, 0
        while not self.stop_event.wait(0.4):
            try:
                selection = self.window.preview_selection()
                key, row = selection if selection else (None, {})
                enabled = xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_auto_trailers') == 'true'
                if key != previous or not enabled:
                    with self.lock:
                        self.player.cancel()
                        self.window.setProperty('nuvio.preview', '')
                        xbmcgui.Window(10000).clearProperty('nuvio.preview.active')
                    previous, changed, attempted, started = key, time.monotonic(), False, 0
                if not enabled or not key: continue
                if started and time.monotonic() - started >= 30:
                    self.player.cancel()
                    self.window.setProperty('nuvio.preview', '')
                    xbmcgui.Window(10000).clearProperty('nuvio.preview.active')
                    started = 0
                if attempted or time.monotonic() - changed < 6: continue
                attempted = True
                if self.player.isPlaying(): continue
                url = selected_trailer(row)
                with self.lock:
                    latest = self.window.preview_selection()
                    if not url or self.stop_event.is_set() or not latest or latest[0] != key or self.player.isPlaying(): continue
                    self.player = PreviewPlayer()
                    self.player.token = uuid.uuid4().hex
                    item = xbmcgui.ListItem(label='Nuvio Hub preview: ' + row.get('title', ''))
                    item.setProperty('nuvio.preview', self.player.token)
                    item.setProperty('IsPlayable', 'true')
                    xbmcgui.Window(10000).setProperty('nuvio.preview.active', self.player.token)
                    self.window.setProperty('nuvio.preview', '1')
                    self.player.play(url, item, windowed=True)
                    started = time.monotonic()
            except Exception:
                # Preview failures must not close Home or start a fallback stream.
                continue
