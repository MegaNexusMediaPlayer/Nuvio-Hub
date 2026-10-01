"""Stremio capability/identity checks shared by metadata and stream routing.

Resource objects have their own filters. Missing idPrefixes on an object means
all IDs, NOT inheritance from the manifest (SDK manifest specification).
"""


def supports(provider, resource_name, media_type, content_id=''):
    manifest = provider.get('manifest') or {}
    for resource in manifest.get('resources') or []:
        if isinstance(resource, dict):
            if resource.get('name') != resource_name:
                continue
            types = resource.get('types')
            prefixes = resource.get('idPrefixes')
        elif resource == resource_name:
            types = manifest.get('types')
            prefixes = manifest.get('idPrefixes')
        else:
            continue
        if types is not None and (not isinstance(types, list) or media_type not in types):
            continue
        if prefixes is not None and (not isinstance(prefixes, list) or
                not any(isinstance(prefix, str) and str(content_id).startswith(prefix) for prefix in prefixes)):
            continue
        return True
    return False


def media_type(value):
    value = str(value or '')
    return 'series' if value in ('tv', 'show', 'tvshow', 'episode') else value


def same_identity(meta, kind, content_id):
    """Allow only exact IDs or explicit provider-declared external-ID aliases."""
    if not isinstance(meta, dict):
        return False
    if meta.get('type') and media_type(meta['type']) != media_type(kind):
        return False
    aliases = {str(meta.get('id') or '')}
    ids = meta.get('ids') if isinstance(meta.get('ids'), dict) else {}
    for family, fields in (('imdb', ('imdb_id', 'imdbId')), ('tmdb', ('tmdb_id', 'tmdbId', 'moviedb_id')),
                           ('tvdb', ('tvdb_id', 'tvdbId'))):
        values = [meta.get(field) for field in fields] + [ids.get(family)]
        for value in values:
            if value is None or str(value) == '':
                continue
            value = str(value)
            aliases.add(value if family == 'imdb' or value.startswith(family + ':') else family + ':' + value)
    return str(content_id) in aliases and bool(content_id)
