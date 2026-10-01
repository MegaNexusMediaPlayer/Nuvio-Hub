"""Entry into Nuvio is never blocked (6.0.15).

With nothing configured - no Nuvio import, no metadata add-on, no collections -
Cinemeta supplies metadata and a default Home layout. Collections, add-ons and
accounts are changed in Settings at any time; an unavailable catalog simply
stays empty on Home.
"""
import xbmcgui
from resources.lib import collection_profile, default_setup, metadata_providers, stream_providers


def ready():
    return bool(collection_profile.load())


def offer_switch_on(module, kind, dialog=None):
    """All installed add-ons of one kind are OFF: offer to turn them on."""
    available = module.candidates()
    if not available or module.enabled():
        return False
    dialog = dialog or xbmcgui.Dialog()
    names = ', '.join(p.get('name') or p['id'] for p in available[:4])
    if len(available) > 4:
        names += ' …'
    if not dialog.yesno('Nuvio Hub', 'All %s add-ons are switched OFF.\nTurn ON: %s?' % (kind, names)):
        return False
    for provider in available:
        module.set_enabled(provider['id'], True)
    return True


def ensure_defaults(job=None):
    """Automatic layout and Cinemeta switch (rules in default_setup). Failures
    (offline) never block entry; the bundled Cinemeta manifest is used offline."""
    import xbmcaddon
    from resources.lib.nuviohub import store

    def install():
        return job(default_setup.install_cinemeta, label='Setting up Cinemeta') if job else default_setup.install_cinemeta()

    def add():
        return job(default_setup.add_cinemeta_off, label='Adding Cinemeta') if job else default_setup.add_cinemeta_off()
    try:
        default_setup.apply_defaults(xbmcaddon.Addon('plugin.video.nuviohub'), store.list_providers(),
                                     collection_profile.load(), collection_profile.save, install, add)
    except (ValueError, OSError):
        pass


def ensure_ready():
    try:
        kept = stream_providers.repair_all_on()
    except Exception:
        kept = None
    if kept:
        xbmcgui.Dialog().notification('Stream add-ons', 'Only %s is ON now for faster playback. Change it in Settings > Add-ons.'
                                      % (kept.get('name') or kept['id']), time=6000)
    from .playback import job
    ensure_defaults(job)
    offer_switch_on(metadata_providers, 'metadata')
    return True
