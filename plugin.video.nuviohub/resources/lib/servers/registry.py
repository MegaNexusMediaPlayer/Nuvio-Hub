# -*- coding: utf-8 -*-
"""Lazy registry for user-owned media servers."""
from __future__ import absolute_import


def providers():
    # Imports are intentionally local: browsing Stremio catalogs should not
    # import Plex/Emby clients or parse their account stores.
    from .plex import PlexServerProvider
    from .emby import EmbyServerProvider
    return (PlexServerProvider(), EmbyServerProvider())


def signed_in():
    rows = []
    for provider in providers():
        try:
            if provider.is_signed_in():
                rows.append(provider)
        except Exception:
            continue
    return rows


def targets(identity, limit=24):
    """Return lazy zero-argument search jobs for every healthy server."""
    from .health import should_query, server_key
    jobs = []
    for provider in signed_in():
        try:
            servers = provider.servers() or []
        except Exception:
            servers = []
        for server in servers:
            if not should_query(provider.backend, server):
                continue
            key = server_key(provider.backend, server)
            jobs.append((key, provider, server, lambda p=provider, s=server: p.find(s, identity, limit=limit)))
    return jobs
