"""Collection sources that are not add-on catalogs (6.0.37): Trakt lists and
TMDB (lists, collections, companies, networks, people, discover), as in the
Nuvio apps. Each becomes a virtual catalog for the normal loaders and cache."""
from . import tmdb_lists, trakt_lists

MODULES = {trakt_lists.KIND: trakt_lists, tmdb_lists.KIND: tmdb_lists}


def module(source):
    if not isinstance(source, dict):
        return None
    found = MODULES.get(str(source.get('provider') or '').lower())
    if found is trakt_lists and trakt_lists.is_trakt(source):
        return found
    if found is tmdb_lists and tmdb_lists.is_tmdb(source):
        return found
    return None


def normalize(source):
    """Export/stored source -> stored source, or None when not one of ours."""
    found = MODULES.get(str((source or {}).get('provider') or '').lower())
    return found.normalize(source) if found else None


def is_virtual(source):
    return module(source) is not None


def job(source):
    return module(source).job(source)


def label(source):
    return module(source).label(source)


def usable(source):
    """False only when the source needs something the user has not set (TMDb key)."""
    found = module(source)
    return found is not tmdb_lists or tmdb_lists.has_key()


def fetch(provider, catalog, extra=None, timeout=8):
    return MODULES[provider['kind']].fetch(catalog, extra or {}, timeout)
