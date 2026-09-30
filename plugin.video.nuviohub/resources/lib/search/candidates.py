# -*- coding: utf-8 -*-
"""Normalized source candidate independent from provider response format."""
class StreamCandidate(object):
    __slots__ = ('provider', 'server', 'url', 'title', 'quality', 'size_bytes',
                 'direct_play', 'raw')
    def __init__(self, provider='', server='', url='', title='', quality='',
                 size_bytes=0, direct_play=False, raw=None):
        self.provider = str(provider or '')
        self.server = str(server or '')
        self.url = str(url or '')
        self.title = str(title or '')
        self.quality = str(quality or '')
        try: self.size_bytes = int(size_bytes or 0)
        except Exception: self.size_bytes = 0
        self.direct_play = bool(direct_play)
        self.raw = raw or {}

    @classmethod
    def from_stream(cls, stream):
        stream = stream or {}
        hints = stream.get('behaviorHints') or {}
        return cls(
            provider=hints.get('nativeProvider') or stream.get('addon') or '',
            server=hints.get('serverId') or hints.get('serverUrl') or '',
            url=stream.get('url') or stream.get('externalUrl') or '',
            title=stream.get('title') or stream.get('name') or '',
            size_bytes=hints.get('videoSize') or 0,
            direct_play=bool(hints.get('nativeProvider')),
            raw=stream,
        )
