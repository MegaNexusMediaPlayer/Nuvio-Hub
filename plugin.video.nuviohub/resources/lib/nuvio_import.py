"""Fetch first, then commit a manual account import after the UI job completes."""
from . import collection_profile, backend_api
from .nuviohub import nuvio_stremio_sync as sync, store, client


def enable_imported(provider_ids):
    """Add-ons just imported from the user's Nuvio profile are switched ON, in
    both lists - they are the add-ons the user runs in the Nuvio apps (6.0.35,
    GitHub issue #3). Playback no longer waits for the slowest stream add-on
    (backend_api.streams grace window), so several may be ON."""
    from . import metadata_providers, stream_providers
    wanted = set(provider_ids or [])
    for module in (metadata_providers, stream_providers):
        for provider, on in module.entries():
            if provider['id'] in wanted and not on:
                try:
                    module.set_enabled(provider['id'], True)
                except ValueError:
                    pass


def enable_collection_metadata(groups):
    """Switch ON the metadata add-ons whose catalogs the collections use, so the
    first Home screen loads. Add-ons that are not used are left as they are."""
    from . import metadata_providers, collection_validation
    from .collections_home import matching_catalog
    providers = store.list_providers()
    switches = {p['id']: on for p, on in metadata_providers.entries(providers)}
    turned = []
    for _, source in collection_validation.sources(groups or []):
        match = matching_catalog(source, providers)
        pid = match[0]['id'] if match else None
        if pid and switches.get(pid) is False:
            try:
                metadata_providers.set_enabled(pid, True)
            except ValueError:
                continue
            switches[pid] = True
            turned.append(match[0].get('name') or pid)
    return turned


def layout_is_users_own():
    """True when Home shows a layout the user chose or edited (not automatic)."""
    import xbmcaddon
    from . import default_setup
    groups = collection_profile.load()
    if not groups:
        return False
    mode = xbmcaddon.Addon('plugin.video.nuviohub').getSetting(default_setup.AUTO_LAYOUT)
    return not mode and not default_setup.is_cinemeta_layout(groups)


def fetch(collections=False):
    """``collections``: also pull the profile's Home collections (6.0.25: done
    automatically when an account is connected and Home is still automatic)."""
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
    # Ordinary account/add-on sync never replaces the Home design; only an
    # explicit import or the first connection (caller decides) pulls collections.
    if collections:
        try:
            result['collections'] = sync.Nuvio.sync_collections([], direction='pull') or []
        except Exception:
            result['errors'].append('Collections could not be fetched. Existing collections were kept.')
    try:
        result['progress'] = sync.Nuvio.sync_progress([], direction='pull')
    except Exception:
        result['errors'].append('Watch progress could not be fetched. Existing progress is unchanged.')
    return result


def apply(result):
    report = {'providers': 0, 'collections': 0, 'progress': 0, 'errors': list(result['errors'])}
    before = {p.get('id') for p in store.list_providers()}
    added = []
    for row in result['providers']:
        try:
            saved = store.add_provider(row.get('name') or row['manifest'].get('name') or 'Add-on',
                                       row['manifest_url'], row['manifest'])
            report['providers'] += 1
            if (saved or {}).get('id') and saved['id'] not in before:
                added.append(saved['id'])
        except Exception:
            report['errors'].append('An add-on could not be saved. Check Kodi storage space.')
    enable_imported(added)
    report['metadata_on'] = []
    if result['collections']:
        try:
            report['collections'] = collection_profile.save(result['collections'])
            report['metadata_on'] = enable_collection_metadata(collection_profile.load())
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
    # Own metadata now exists: an automatically switched-on Cinemeta goes OFF
    # (same rule as every Home entry); a user-owned layout is never touched.
    try:
        from . import default_setup
        default_setup.apply_defaults(addon, store.list_providers(), collection_profile.load(),
                                     collection_profile.save, install=lambda: None, add=lambda: None)
    except Exception:
        pass
    for role in ('metadata', 'streams'):
        if not addon.getSetting('nuvio_' + role + '_provider'):
            selected = backend_api.provider(role)
            if selected:addon.setSetting('nuvio_' + role + '_provider', selected['id'])
    return report
