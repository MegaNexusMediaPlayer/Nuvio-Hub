# -*- coding: utf-8 -*-
from .base import MediaServerProvider
from ..providers import plex_provider

class PlexServerProvider(MediaServerProvider):
    backend = 'plex'
    def is_signed_in(self): return plex_provider.is_signed_in()
    def servers(self): return plex_provider.servers()
    def find(self, server, identity, limit=24):
        return plex_provider.find_all_by_ids(server, identity.ids,
            media_type=identity.media_type, title='', limit=limit)
    def episode(self, server, parent, season, episode):
        return plex_provider.episode_item(server, parent, season, episode)
    def metadata(self, server, item_id): return plex_provider.metadata(server, item_id)
