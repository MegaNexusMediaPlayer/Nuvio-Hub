"""Fetch first, then commit a manual account import after the UI job completes."""
from . import collection_profile, backend_api
from .dexhub import nuvio_stremio_sync as sync, store, client


def fetch():
    result = {'providers': [], 'collections': None, 'progress': None, 'errors': []}
    # This is deliberately independent of the optional background-sync toggles.
    try:
        remote = sync.Nuvio.sync_addons([], direction='pull')
        existing = {p.get('manifest_url'): p for p in store.list_providers()}
        for row in remote:
            url = row['manifest_url']
            try:
                manifest = (existing.get(url) or {}).get('manifest')
                if not manifest:
                    manifest = client.get_json(url, ttl_seconds=300, timeout_override=6,
                                               retry=False, rate_wait=0.25)
                if not isinstance(manifest, dict) or any(k not in manifest for k in ('id','version','resources','types')):
                    raise ValueError('Invalid manifest')
                if not isinstance(manifest['resources'], list) or not isinstance(manifest['types'], list):
                    raise ValueError('Invalid manifest resources')
                result['providers'].append(dict(row, manifest=manifest))
            except Exception:
                # Never expose configured URLs or tokens in errors.
                result['errors'].append('An add-on manifest could not load. Retry the import.')
    except Exception:
        result['errors'].append('Add-ons could not be fetched from the selected profile.')
    # Layout import is a separate, explicit Skin configuration action. Ordinary
    # account/add-on sync must never replace the user's fixed Home design.
    try:
        result['progress'] = sync.Nuvio.sync_progress([], direction='pull')
    except Exception:
        result['errors'].append('Watch progress could not be fetched. Existing progress is unchanged.')
    return result


def apply(result):
    report = {'providers': 0, 'collections': 0, 'progress': 0, 'errors': list(result['errors'])}
    for row in result['providers']:
        try:
            store.add_provider(row.get('name') or row['manifest'].get('name') or 'Add-on',
                               row['manifest_url'], row['manifest'])
            report['providers'] += 1
        except Exception:
            report['errors'].append('An add-on could not be saved. Check Kodi storage space.')
    if result['collections']:
        try:report['collections'] = collection_profile.save(result['collections'])
        except Exception:report['errors'].append('Collections could not be saved or have an unsupported format.')
    elif result['collections'] is not None:
        report['errors'].append('This profile has no collections. Existing collections were kept.')
    if result['progress']:
        try:
            report['progress'] = sync._writeback_progress(result['progress'])
            if not report['progress']:report['errors'].append('No watch progress was saved; retry sync from Account settings.')
        except Exception:report['errors'].append('Watch progress could not be saved.')
    # Auto-select only an unambiguous provider. Never replace a valid user choice.
    import xbmcaddon
    addon = xbmcaddon.Addon('plugin.video.nuviohub')
    for role in ('metadata', 'streams'):
        if not addon.getSetting('nuvio_' + role + '_provider'):
            selected = backend_api.provider(role)
            if selected:addon.setSetting('nuvio_' + role + '_provider', selected['id'])
    return report
