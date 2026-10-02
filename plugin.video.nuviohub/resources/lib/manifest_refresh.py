"""Keep add-on manifests current (6.0.36).

Add-ons such as AIOMetadata / Xperience get new catalogs when the user changes
their configuration. The Nuvio apps re-read manifests; MegaNexus stored one
copy when the add-on was added (and a Nuvio re-import even reused it), so new
catalogs - e.g. streaming services used by collections - showed as "not
installed". The service now refreshes every manifest at start and every
REFRESH_EVERY seconds; Settings can do it on demand.
"""
import time

REFRESH_EVERY = 6 * 3600
STAMP_SETTING = 'nuvio_manifests_refreshed'


def valid(manifest):
    return (isinstance(manifest, dict) and all(k in manifest for k in ('id', 'version', 'resources', 'types'))
            and isinstance(manifest['resources'], list) and isinstance(manifest['types'], list))


def fetch(url, timeout=8):
    """Fresh manifest from the add-on (no HTTP cache), or None."""
    from .nuviohub import client
    try:
        data = client.get_json(url, ttl_seconds=0, timeout_override=timeout, retry=False, rate_wait=.25)
    except Exception:
        return None
    return data if valid(data) else None


def refresh_all(timeout=8, stopped=None):
    """Re-read every add-on's manifest; returns the names whose catalogs changed.
    URLs can carry account tokens: they are never logged."""
    from .nuviohub import store
    changed = []
    for row in store.list_providers():
        if stopped and stopped():
            break
        url = row.get('manifest_url') or ''
        if not url:
            continue
        fresh = fetch(url, timeout)
        if fresh is None or fresh == row.get('manifest'):
            continue
        store.refresh_provider_manifest(row['id'], fresh)
        changed.append(row.get('name') or fresh.get('name') or row['id'])
    try:
        from . import settings_cache
        settings_cache.cached_addon().setSetting(STAMP_SETTING, str(int(time.time())))
        settings_cache.invalidate()
    except Exception:
        pass
    return changed


def due(addon, now=None):
    try:
        last = float(addon.getSetting(STAMP_SETTING) or 0)
    except ValueError:
        last = 0
    return (now or time.time()) - last >= REFRESH_EVERY


def service_loop(monitor, busy=lambda: False, first_wait=60, poll=300):
    """Service thread: refresh when due, never while video plays."""
    import xbmc
    import xbmcaddon
    if monitor.waitForAbort(first_wait):
        return
    while not monitor.abortRequested():
        addon = xbmcaddon.Addon('plugin.video.nuviohub')
        if due(addon) and not xbmc.Player().isPlayingVideo() and not busy():
            try:
                changed = refresh_all(stopped=monitor.abortRequested)
                if changed:
                    xbmc.log('[MegaNexus] Add-on catalogs updated: %d add-on(s).' % len(changed), xbmc.LOGINFO)
            except Exception as exc:
                xbmc.log('[MegaNexus] Manifest refresh skipped: %s' % type(exc).__name__, xbmc.LOGWARNING)
        if monitor.waitForAbort(poll):
            return
