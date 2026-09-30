"""Playback resolver boundary.

Kept deliberately small in phase one; provider-specific URL resolution stays
inside each native provider until migrated with regression coverage.
"""
def resolve(provider, item, **kwargs):
    fn = getattr(provider, 'resolve_playback', None)
    if callable(fn):
        return fn(item=item, **kwargs)
    return item
