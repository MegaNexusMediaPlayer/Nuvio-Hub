# -*- coding: utf-8 -*-
import os
import time

import xbmcaddon
import xbmcvfs

ADDON_ID = 'plugin.video.nuviohub'
# 6.0.35 (GitHub issue #6): watched at 90 %, like the Nuvio apps
# (WatchProgress.COMPLETED_THRESHOLD = 0.90; Simkl 0.80). Titles stopped in
# the end credits no longer stay in Continue Watching.
WATCHED_PERCENT = 90
SIMKL_WATCHED_PERCENT = 80

# v3.9.17: cache the Addon() instance with a short TTL.
# Each xbmcaddon.Addon(ADDON_ID) construction crosses the Python↔C++ boundary
# and re-loads addon metadata. A folder render calls _get_setting() many
# times, each of which used to construct a new instance. Caching for 2s
# eliminates that overhead inside one render while still letting user
# settings changes propagate within a heartbeat.
#
# Why not cache forever? Under reuselanguageinvoker=true the module persists
# across invocations; an instance held forever can return stale settings if
# the user opens the settings dialog and changes something.
_ADDON_INSTANCE = None
_ADDON_INSTANCE_TS = 0.0
_ADDON_TTL = 2.0


def addon():
    global _ADDON_INSTANCE, _ADDON_INSTANCE_TS
    now = time.time()
    if _ADDON_INSTANCE is None or (now - _ADDON_INSTANCE_TS) > _ADDON_TTL:
        try:
            _ADDON_INSTANCE = xbmcaddon.Addon(ADDON_ID)
        except Exception:
            try:
                _ADDON_INSTANCE = xbmcaddon.Addon('plugin.video.nuviohub')
            except Exception:
                # Total failure — return a fresh attempt without caching so
                # the next call retries.
                return xbmcaddon.Addon(ADDON_ID)
        _ADDON_INSTANCE_TS = now
    return _ADDON_INSTANCE


def profile_path():
    path = xbmcvfs.translatePath(addon().getAddonInfo('profile'))
    os.makedirs(path, exist_ok=True)
    return path
