# -*- coding: utf-8 -*-
from .base import MediaServerProvider
from ..providers import emby_provider

class EmbyServerProvider(MediaServerProvider):
    backend = 'emby'
    def is_signed_in(self): return emby_provider.is_signed_in()
    def servers(self): return emby_provider.servers()
    def find(self, server, identity, limit=24):
        return emby_provider.find_all_by_ids(server, identity.ids,
            media_type=identity.media_type, title='', limit=limit)
    def episode(self, server, parent, season, episode):
        return emby_provider.episode_item(server, parent, season, episode)
    def metadata(self, server, item_id): return emby_provider.metadata(server, item_id)
