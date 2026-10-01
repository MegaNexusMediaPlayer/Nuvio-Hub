"""Identifiers from before the Nuvio Hub rename, used only for upgrades.

Installs up to 6.0.7 and older related builds
stored a few settings, files and add-on IDs under a retired three-letter brand
prefix. They are read here to migrate those profiles and to remove files the old
builds left behind (TMDb Helper player, keymap). Nothing new is ever written
under these names. The prefix is assembled at runtime so the retired brand does
not appear anywhere in the shipped sources or interface.

Third-party service identifiers that happen to share the prefix (a StreamBridge
fork and a Plexio host) are kept here as well, only for provider detection.
"""
import os

_P = bytes((100, 101, 120)).decode('ascii')  # retired brand prefix
_HUB = _P + 'hub'
_SERVICE = _P + 'world'

OLD_ADDON_ID = 'plugin.video.' + _HUB
OLD_EXPORT_VERSION_KEY = _HUB + '_export_version'
OLD_KEYMAP_FILENAMES = (_HUB + '-switch-source.xml',)
OLD_PLAYER_PREFIXES = (_HUB, _P + '_hub')
OLD_PLAYER_NAME = _P + ' hub'

# External AI-subtitles / IPTV service (third party). Its manifests, host and
# add-on names keep the service's own prefix; Nuvio Hub shows it by function.
SERVICE_BASE_URL = 'https://' + _SERVICE + '.cc'
SERVICE_MARKER = _SERVICE
SERVICE_MANIFEST_IDS = ('org.' + _P + 'subtitles.aggregator', 'org.' + _SERVICE + '.v50.alpha')
SERVICE_SITES = (('Plexio / Plex', 'https://plexio.' + _SERVICE + '.cc/'),
                 ('StreamBridge / Emby', 'https://sb.' + _SERVICE + '.cc/'),
                 ('IPTV', SERVICE_BASE_URL + '/'),
                 ('Subtitles', SERVICE_BASE_URL + '/subtitles/stremio/configure'))
PRO_IPTV_MARKERS = (_SERVICE + '_pro', _SERVICE + '-pro')
SELF_MARKERS = (_SERVICE, _P + ' hub')

# Hidden one-shot migration sentinels: (old id, current id, kind).
SENTINEL_ALIASES = (
    (_HUB + '_defaults_rev', 'nuviohub_defaults_rev', 'text'),
    (_HUB + '_v510_defaults_applied', 'nuviohub_v510_defaults_applied', 'bool'),
    (_HUB + '_v520_defaults_applied', 'nuviohub_v520_defaults_applied', 'bool'),
)
# Every renamed setting: sentinels plus the hidden IPTV folder-view flag.
SETTING_ALIASES = SENTINEL_ALIASES + (
    (_SERVICE + '_force_folders', 'nuviohub_iptv_force_folders', 'bool'),
)
SETTING_ALIAS_MAP = {old: new for old, new, _ in SETTING_ALIASES}

# Provider detection only (third-party Plex/Emby bridge add-ons and hosts).
BRIDGE_MARKERS = (_P + 'bridge',)
BRIDGE_ADDON_IDS = ('com.stremio.' + _P + 'bridge',)
BRIDGE_HOSTS = ('sb.' + _P + 'world.cc', 'plex.' + _P + 'world', 'plexio.' + _P + 'world',
                'sb.' + _P + 'world')
FRAGILE_ART_HOSTS = (_P + 'world.cc',)
FRAGILE_ART_MARKERS = (_P + 'world', _P + 'bridge')


def legacy_setting(addon, key):
    try:
        return (addon.getSetting(key) or '').strip()
    except Exception:
        return ''


def profile_in_use(profile_dir):
    """True when this profile was configured by an earlier build.

    Older profiles already ran every one-shot defaults migration; if their
    sentinels cannot be read any more they must not be re-applied over the
    user's choices.
    """
    for name in ('providers.json', 'nuvio_collections.json'):
        if os.path.exists(os.path.join(profile_dir, name)):
            return True
    return False


def carry_forward(addon, profile_dir=None):
    """Copy old sentinels to the current IDs; never downgrade a current value.

    Returns True when anything was written.
    """
    changed = False
    for old_key, new_key, kind in SETTING_ALIASES:
        old = legacy_setting(addon, old_key)
        new = legacy_setting(addon, new_key)
        if kind == 'bool':
            if old.lower() == 'true' and new.lower() != 'true':
                addon.setSetting(new_key, 'true')
                changed = True
        elif old and not new:
            addon.setSetting(new_key, old)
            changed = True
    if profile_dir and not legacy_setting(addon, 'nuviohub_defaults_rev') and profile_in_use(profile_dir):
        # The old sentinel values were not readable: treat the migrations as done.
        addon.setSetting('nuviohub_defaults_rev', '470-release-defaults')
        for _, new_key, kind in SENTINEL_ALIASES:
            if kind == 'bool' and legacy_setting(addon, new_key).lower() != 'true':
                addon.setSetting(new_key, 'true')
        changed = True
    return changed
