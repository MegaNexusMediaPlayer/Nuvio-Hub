# -*- coding: utf-8 -*-
"""Provider contract for user-owned media servers."""
class MediaServerProvider(object):
    backend = ''

    def is_signed_in(self):
        raise NotImplementedError

    def servers(self):
        raise NotImplementedError

    def find(self, server, identity, limit=24):
        raise NotImplementedError

    def episode(self, server, parent, season, episode):
        raise NotImplementedError

    def metadata(self, server, item_id):
        raise NotImplementedError
