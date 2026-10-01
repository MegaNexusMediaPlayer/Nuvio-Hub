"""Mandatory validated collections, not a mandatory Nuvio account."""
import xbmcgui
from resources.lib import collection_profile, collection_validation, metadata_providers, stream_providers


def ready():
    groups = collection_profile.load()
    return bool(groups and metadata_providers.enabled() and stream_providers.enabled() and
                collection_validation.stored_proof(groups))


def ensure_ready():
    from . import settings, collection_editor
    # Previously saved collections are kept; verify them without replacing layout.
    groups = collection_profile.load()
    if groups and not collection_validation.stored_proof(groups):
        settings.commit_collections(groups)
    while not ready():
        pick = xbmcgui.Dialog().select('Finish setup · a Nuvio account is optional', [
            'Configure metadata and stream add-ons',
            'Import collections from Nuvio account',
            'Import collections JSON without an account',
            'Create a collection from my installed catalogs',
            'Validate internal presets against my add-ons',
            'Sign in to Nuvio (optional)', 'Return to HUB'])
        if pick < 0 or pick == 6:
            return False
        try:
            if pick == 0:
                settings.addons()
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
            if groups and not collection_validation.stored_proof(collection_profile.load()):
                groups = collection_profile.load()
        except (ValueError, OSError):
            xbmcgui.Dialog().ok('Setup', 'Setup could not be verified. Your existing collection file was kept.')
    return True
