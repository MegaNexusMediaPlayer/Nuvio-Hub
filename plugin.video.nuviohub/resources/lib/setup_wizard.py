"""One entry point for the bundled interface, providers, metadata and playback."""
import json
from urllib.parse import urlsplit

import xbmc
import xbmcaddon
import xbmcgui


def resources(provider):
    return {r.get('name') if isinstance(r, dict) else r for r in (provider.get('manifest') or {}).get('resources', [])}


def status(providers):
    return {'catalog': any('catalog' in resources(p) for p in providers),
            'stream': any('stream' in resources(p) for p in providers),
            'aio': any((p.get('manifest') or {}).get('id') == 'aio-metadata' for p in providers)}


def configure_metadata(addon, providers):
    """Preserve deliberate per-provider overrides; fill only unset mappings."""
    aio = next((p for p in providers if (p.get('manifest') or {}).get('id') == 'aio-metadata' and 'meta' in resources(p)), None)
    if not aio:
        return False
    try:
        mapping = json.loads(addon.getSetting('provider_meta_map') or '{}')
        if not isinstance(mapping, dict): mapping = {}
    except (ValueError, TypeError):
        mapping = {}
    for provider in providers:
        if provider.get('id'):
            mapping.setdefault(provider['id'], 'native' if provider['id'] == aio['id'] else aio['id'])
    addon.setSetting('provider_meta_map', json.dumps(mapping))
    addon.setSetting('default_meta_source', 'Auto (smart)')
    from . import meta_source
    meta_source._invalidate_map_cache()
    return True


def add_manifest(dialog):
    from .nuviohub.client import validate_manifest
    from .nuviohub import store
    value = dialog.input('Paste your configured provider manifest URL').strip()
    if not value:
        return False
    if value.startswith('stremio://'):
        value = 'https://' + value[len('stremio://'):]
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or not parsed.path.endswith('/manifest.json'):
        dialog.ok('Nuvio Hub', 'Enter a complete http(s) manifest.json URL. Include your provider configuration.')
        return False
    busy = xbmcgui.DialogProgressBG()
    busy.create('Nuvio Hub', 'Checking provider...')
    try:
        manifest = validate_manifest(value)
        store.add_provider(manifest.get('name') or manifest['id'], value, manifest)
        dialog.notification('Nuvio Hub', 'Provider connected')
        return True
    except Exception:
        # Configured URLs may contain credentials. Do not display/log them.
        dialog.ok('Nuvio Hub', 'Could not validate this manifest. Check the URL, provider configuration and connection, then try again.')
        return False
    finally:
        busy.close()


def link_account(service, addon, dialog):
    from .routes import accounts
    email = dialog.input('%s email' % service.title(), addon.getSetting(service + '_email') or '')
    if not email: return
    password = dialog.input('%s password' % service.title(), option=xbmcgui.ALPHANUM_HIDE_INPUT)
    if not password: return
    addon.setSetting(service + '_email', email.strip())
    addon.setSetting(service + '_password', password)
    try:
        if accounts.login(service, addon, lambda value: __import__('resources.lib.i18n', fromlist=['tr']).tr(value)):
            from .i18n import tr
            accounts.sync_now(addon, tr, only=service)
    finally:
        addon.setSetting(service + '_password', '')


def run():
    """Legacy entry point delegates onboarding to the independent interface."""
    xbmc.executebuiltin('RunScript(script.nuvio,wizard)')
