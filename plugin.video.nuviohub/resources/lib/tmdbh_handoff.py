# -*- coding: utf-8 -*-
"""TMDb Helper handoff state machine.

Replaces the scattered Window(10000) properties (nuviohub.invoked_by_tmdbh,
nuviohub.tmdbh_seed_ids, nuviohub.tmdbh_seed_for, nuviohub.tmdbh_handoff_until)
with a single class that owns the handoff lifecycle.

Lifecycle:

    [idle]
       │  begin(action, ids, ttl=60)
       ▼
    [active]  ◄──── stays active until end() OR ttl expires
       │  consume_seed_ids(canonical_id)  → returns ids and clears them
       │
       │  end()  OR  TTL elapsed
       ▼
    [idle]

Properties live on Window(10000) so they survive plugin invocations
under reuselanguageinvoker.

The TTL is essential because users sometimes back out of TMDb Helper's
player chooser dialog without making a selection — without a TTL we'd
think we were in a handoff forever and silently steal future plays.
"""
import json
import time

import xbmcgui

from .log import log

_WIN_ID = 10000

# Public property names — kept identical to legacy so existing skin XMLs
# that read them keep working without skin updates.
_PROP_ACTIVE     = 'nuviohub.invoked_by_tmdbh'
_PROP_SEED_IDS   = 'nuviohub.tmdbh_seed_ids'
_PROP_SEED_FOR   = 'nuviohub.tmdbh_seed_for'
_PROP_UNTIL      = 'nuviohub.tmdbh_handoff_until'

ALL_PROPS = (_PROP_ACTIVE, _PROP_SEED_IDS, _PROP_SEED_FOR, _PROP_UNTIL)


def _w():
    try:
        return xbmcgui.Window(_WIN_ID)
    except Exception:
        return None


class _Handoff:
    """All operations are class-stateless — state lives on the Kodi window."""

    def begin(self, canonical_id, seed_ids=None, ttl=60):
        """Mark a handoff as active. seed_ids are an {imdb_id, tmdb_id, tvdb_id}
        dict that downstream play_item() will consume and use to bypass meta
        resolution — this is what makes "TMDb Helper opens NuvioHub" actually
        play the right item even when canonical_id is ambiguous."""
        win = _w()
        if win is None:
            return
        until = time.time() + max(2, int(ttl or 60))
        try:
            win.setProperty(_PROP_ACTIVE, '1')
            win.setProperty(_PROP_UNTIL, '%.3f' % until)
            if canonical_id:
                win.setProperty(_PROP_SEED_FOR, str(canonical_id))
            if isinstance(seed_ids, dict):
                clean = {k: str(v) for k, v in seed_ids.items() if v}
                win.setProperty(_PROP_SEED_IDS, json.dumps(clean) if clean else '')
        except Exception as exc:
            log.warn('TMDBH', 'begin failed: %s', exc)

    def is_active(self):
        win = _w()
        if win is None:
            return False
        try:
            if (win.getProperty(_PROP_ACTIVE) or '').strip() != '1':
                return False
            raw_until = (win.getProperty(_PROP_UNTIL) or '').strip()
            if not raw_until:
                return True  # active flag set, no expiry — treat as live
            try:
                if float(raw_until) > time.time():
                    return True
            except Exception:
                return True
            # expired — clean up
            self.end()
            return False
        except Exception:
            return False

    def consume_seed_ids(self, canonical_id=None):
        """Return seed ids dict for the given canonical_id (if it matches the
        active scope). Caller should immediately use them; this does NOT
        clear them so a second consume in the same handoff still works
        (e.g. art lookup THEN play)."""
        win = _w()
        if win is None:
            return {}
        try:
            scope = (win.getProperty(_PROP_SEED_FOR) or '').strip()
            if canonical_id and scope and scope != str(canonical_id):
                return {}
            raw = win.getProperty(_PROP_SEED_IDS) or ''
            if not raw:
                return {}
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items() if v}
            except Exception:
                return {}
        except Exception:
            return {}
        return {}

    def end(self):
        """Clear all handoff state. Idempotent."""
        win = _w()
        if win is None:
            return
        for prop in ALL_PROPS:
            try:
                win.clearProperty(prop)
            except Exception:
                pass


handoff = _Handoff()


# ── Back-compat shims ────────────────────────────────────────────────────
# Existing call sites (plugin.py, companion.py, tmdbh_player.py) use these
# function names. Keep them as thin wrappers so we can refactor the new
# unified class without touching every old caller in this release.

def mark_tmdbh_handoff(seconds=45):
    """Legacy: just touches the until-timestamp without changing seed ids."""
    win = _w()
    if win is None:
        return
    until = time.time() + max(5, int(seconds or 45))
    try:
        win.setProperty(_PROP_ACTIVE, '1')
        win.setProperty(_PROP_UNTIL, '%.3f' % until)
    except Exception:
        pass


def tmdbh_handoff_active():
    return handoff.is_active()


def get_tmdbh_seed_ids(canonical_id=None):
    return handoff.consume_seed_ids(canonical_id)


def clear_tmdbh_transient():
    handoff.end()
