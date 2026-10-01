"""Resolve and cache trailers before handing anything to Kodi's video player.

Never pass plugin URLs to Player.play: a cancelled resolver must not start a
late video or open a Playback failed dialog over a different screen.
"""
import hashlib
import os
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from .nuviohub.common import profile_path
from .trailer_support import trailer_url

_LOCK = threading.Lock()
_MISSES = {}
MAX_BYTES = 32 * 1024 * 1024


def _module_paths(aid, seen=None):
    # Kodi does not add another plugin's module dependencies to our invoker.
    import xbmcaddon
    import xml.etree.ElementTree as ET
    seen=seen if seen is not None else set()
    if aid in seen or aid.startswith('xbmc.'):return
    seen.add(aid)
    try:
        root=xbmcaddon.Addon(aid).getAddonInfo('path')
        manifest=ET.parse(os.path.join(root,'addon.xml')).getroot()
    except Exception:return
    for dependency in manifest.findall('./requires/import'):
        child=dependency.get('addon') or ''
        if child.startswith('script.module.'):_module_paths(child,seen)
    for extension in manifest.findall("extension[@point='xbmc.python.module']"):
        path=os.path.join(root,extension.get('library') or 'lib')
        if path not in sys.path:sys.path.append(path)


def _youtube(url):
    """Optional read-only adapter to the installed YouTube stream resolver.

    No play handler, setup wizard, quality prompt, login or playback callback.
    Incompatible resolver versions simply leave the poster visible.
    """
    import xbmcaddon
    _module_paths('plugin.video.youtube')
    path = os.path.join(xbmcaddon.Addon('plugin.video.youtube').getAddonInfo('path'), 'resources', 'lib')
    if path not in sys.path: sys.path.append(path)
    from youtube_plugin.kodion.context import XbmcContext
    from youtube_plugin.youtube.provider import Provider
    ctx = XbmcContext(path='/play/', params={'video_id': parse_qs(urlsplit(url).query)['video_id'][0], 'incognito': True}, plugin_id='plugin.video.youtube')
    ui = ctx.get_ui()
    class QuietUI:
        def __getattr__(self, name):
            if name.startswith(('on_', 'show_', 'open_')):
                return lambda *args, **kwargs: False
            return getattr(ui, name)
    ctx._ui = QuietUI()
    # load_stream_info is a data operation; deliberately do not call yt_play.
    data = Provider().get_client(ctx).load_stream_info(
        video_id=parse_qs(urlsplit(url).query)['video_id'][0],
        # Ask the data resolver for every format; no quality-selection UI is
        # invoked here. Otherwise it may return only the first HLS option.
        ask_for_quality=True, audio_only=False, incognito=True, use_mpd=False)
    streams = data[0] if isinstance(data, tuple) else data
    return select_stream(streams)


def select_stream(streams):
    """Select a compact complete AV file, preferring TV-compatible H.264."""
    eligible = [s for s in streams if isinstance(s, dict) and not s.get('adaptive')
                and str(s.get('container') or '').lower() in ('mp4','webm')
                and s.get('video') and s.get('audio') and (s['video'].get('height') or 0) <= 720
                and str(s.get('url') or '').startswith(('https://', 'http://'))]
    if not eligible: return '', {}
    # Prefer H.264/MP4 over VP9/AV1 WebM on hardware video planes.
    compatible=[s for s in eligible if str(s.get('container') or '').lower()=='mp4'
                and any(c in str((s.get('video') or {}).get('encoding') or (s.get('video') or {}).get('codec') or '').lower() for c in ('h264','h.264','avc'))]
    if compatible:eligible=compatible
    # A small complete preview is cheap to cache on CoreELEC and starts once.
    compact=[s for s in eligible if (s['video'].get('height') or 0)<=480]
    selected = max(compact or eligible, key=lambda s: s['video'].get('height') or 0)
    headers = selected.get('headers') or {}
    if isinstance(headers, str): headers = {k: v[0] for k, v in parse_qs(headers).items()}
    return selected['url'], headers


def prepare(meta, cancelled=None):
    if cancelled and cancelled.is_set():return ''
    url = trailer_url(meta)
    if not url or _MISSES.get(url, 0) > time.monotonic(): return ''
    directory = os.path.join(profile_path(), 'trailer-cache')
    path = os.path.join(directory, hashlib.sha256(('preview-v2|'+url).encode()).hexdigest() + '.mp4')
    if os.path.isfile(path) and os.path.getsize(path) > 1024:
        os.utime(path, None)
        return path
    if not _LOCK.acquire(False): return ''
    temporary = path + '.part'
    def stopped(): return bool(cancelled and cancelled.is_set())
    try:
        if stopped(): return ''
        headers = {}
        if url.startswith('plugin://'): url, headers = _youtube(url)
        if stopped() or not url: return ''
        # HLS/DASH cannot be safely cached as a single complete clip here.
        if urlsplit(url).path.lower().endswith(('.m3u8', '.mpd')): return ''
        os.makedirs(directory, exist_ok=True)
        deadline = time.monotonic() + 20
        with urlopen(Request(url, headers=headers), timeout=3) as response:
            if int(response.headers.get('Content-Length') or 0) > MAX_BYTES: return ''
            count = 0
            with open(temporary, 'wb') as output:
                while not stopped() and time.monotonic() < deadline:
                    chunk = response.read(128 * 1024)
                    if not chunk: break
                    if not count and b'ftyp' not in chunk[:64] and not chunk.startswith(b'\x1aE\xdf\xa3'):
                        return ''  # HTML/error body is never sent to the player.
                    count += len(chunk)
                    if count > MAX_BYTES: return ''
                    output.write(chunk)
                else: return ''
        expected = int(response.headers.get('Content-Length') or 0)
        if count < 1024 or expected and count != expected or stopped(): return ''
        os.replace(temporary, path)
        files = sorted((os.path.join(directory, f) for f in os.listdir(directory) if f.endswith('.mp4')), key=os.path.getmtime, reverse=True)
        total = 0
        for index, old in enumerate(files):
            total += os.path.getsize(old)
            if index >= 6 or total > 128 * 1024 * 1024:
                try: os.remove(old)
                except OSError: pass
        return path
    except Exception:
        return ''
    finally:
        original = trailer_url(meta)
        if not os.path.isfile(path) and not stopped(): _MISSES[original] = time.monotonic() + 60
        while len(_MISSES) > 64: _MISSES.pop(next(iter(_MISSES)))
        try: os.remove(temporary)
        except OSError: pass
        _LOCK.release()
