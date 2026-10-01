"""Mandatory validated collections, not a mandatory Nuvio account."""
import xbmcgui
from resources.lib import collection_profile, collection_validation, metadata_providers, stream_providers


def ready():
    groups = collection_profile.load()
    return bool(groups and metadata_providers.enabled() and stream_providers.enabled() and
                collection_validation.stored_proof(groups))


def missing():
    """Human-readable reasons Home cannot open yet (empty when ready)."""
    reasons = []
    if not metadata_providers.candidates():
        reasons.append('no metadata add-on installed')
    elif not metadata_providers.enabled():
        reasons.append('all metadata add-ons are OFF')
    if not stream_providers.candidates():
        reasons.append('no stream add-on installed')
    elif not stream_providers.enabled():
        reasons.append('all stream add-ons are OFF')
    groups = collection_profile.load()
    if not groups:
        reasons.append('no collections imported')
    elif not collection_validation.stored_proof(groups):
        reasons.append('collections not checked yet')
    return reasons


def offer_switch_on(module, kind, dialog=None):
    """All installed add-ons of one kind are OFF: offer to turn them on."""
    available = module.candidates()
    if not available or module.enabled():
        return False
    dialog = dialog or xbmcgui.Dialog()
    names = ', '.join(p.get('name') or p['id'] for p in available[:4])
    if len(available) > 4:
        names += ' …'
    if not dialog.yesno('Nuvio Hub', 'All %s add-ons are switched OFF, so Home cannot open.\n'
                        'Turn ON: %s?' % (kind, names)):
        return False
    for provider in available:
        module.set_enabled(provider['id'], True)
    return True


def ensure_ready():
    from . import settings, collection_editor
    try:
        kept = stream_providers.repair_all_on()
    except Exception:
        kept = None
    if kept:
        xbmcgui.Dialog().notification('Stream add-ons', 'Only %s is ON now for faster playback. Change it in Settings > Add-ons.'
                                      % (kept.get('name') or kept['id']), time=6000)
    offer_switch_on(metadata_providers, 'metadata')
    offer_switch_on(stream_providers, 'stream')
    # Previously saved collections are kept; verify them without replacing layout.
    groups = collection_profile.load()
    if groups and not collection_validation.stored_proof(groups):
        settings.commit_collections(groups)
    while not ready():
        reasons = missing()
        heading = 'Finish setup · ' + ('; '.join(reasons) if reasons else 'a Nuvio account is optional')
        pick = xbmcgui.Dialog().select(heading, [
            'Configure metadata and stream add-ons',
            'Import collections from Nuvio account',
            'Import collections JSON without an account',
            'Create a collection from my installed catalogs',
            'Validate internal presets against my add-ons',
            'Sign in to Nuvio (optional)', 'Recheck current collections', 'Return to HUB'])
        if pick < 0 or pick == 7:
            return False
        try:
            if pick == 0:
                settings.addons()
                offer_switch_on(metadata_providers, 'metadata')
                offer_switch_on(stream_providers, 'stream')
                current = collection_profile.load()
                if current and not collection_validation.stored_proof(current):
                    settings.commit_collections(current)
            elif pick == 1:
                settings.import_nuvio_collections()
            elif pick == 2:
                collection_editor.import_json()
            elif pick == 3:
                collection_editor.create_collection()
            elif pick == 4:
                settings.commit_collections(collection_profile.defaults())
            elif pick == 5:
                settings.accounts()
            elif pick == 6:
                current = collection_profile.load()
                if current:
                    settings.commit_collections(current, force=True)
            if groups and not collection_validation.stored_proof(collection_profile.load()):
                groups = collection_profile.load()
        except (ValueError, OSError):
            xbmcgui.Dialog().ok('Setup', 'Setup could not be verified. Your existing collection file was kept.')
    return True
