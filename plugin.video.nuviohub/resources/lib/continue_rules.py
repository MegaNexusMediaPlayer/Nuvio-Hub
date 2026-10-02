"""Continue Watching rules shared by the resume and next-episode cards (6.0.35).

* Remove (GitHub issue #5): hides a title from Continue Watching without
  touching its progress or watched state. It comes back by itself once the
  title is played again (a newer progress time than the removal).
* Period (issue #7): only titles watched in the last N days, like the Nuvio
  apps (default 60 days; 0 = no limit).
* Unaired next episodes (issue #7): "airs tomorrow" cards can be switched
  off. Like in the Nuvio apps this is a setting of this device.
"""
import json
import os
import threading
import time

PERIOD_SETTING = 'nuvio_cw_days'
PERIODS = ('30', '60', '90', '0')
PERIOD_DEFAULT = '60'
PERIOD_LABELS = {'30': '30 days', '60': '60 days', '90': '90 days', '0': 'No limit'}
UNAIRED_SETTING = 'nuvio_cw_unaired'
_LOCK = threading.RLock()
_MEM = {}


def _addon(addon=None):
    if addon is not None:
        return addon
    from . import settings_cache
    return settings_cache.cached_addon()


def period_days(addon=None):
    try:
        value = _addon(addon).getSetting(PERIOD_SETTING)
    except Exception:
        value = ''
    return int(value if value in PERIODS else PERIOD_DEFAULT)


def show_unaired(addon=None):
    try:
        return _addon(addon).getSetting(UNAIRED_SETTING) != 'false'
    except Exception:
        return True


def recent_enough(updated_at, addon=None, now=None):
    days = period_days(addon)
    if not days:
        return True
    from .progress_model import timestamp
    return timestamp(updated_at) >= (now or time.time()) - days * 86400


def key(media_type, canonical_id):
    kind = 'movie' if media_type == 'movie' else 'series'
    return '%s|%s' % (kind, canonical_id or '')


def _path():
    from .nuviohub.common import profile_path
    return os.path.join(profile_path(), 'continue_hidden.json')


def _read():
    path = _path()
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return {}
    with _LOCK:
        if _MEM.get('stamp') == (path, stamp):
            return dict(_MEM['data'])
        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        data = data if isinstance(data, dict) else {}
        _MEM.update(stamp=(path, stamp), data=data)
        return dict(data)


def hide(media_type, canonical_id, now=None):
    """Remove a title from Continue Watching until it is played again."""
    from .nuviohub.safe_io import write_json
    with _LOCK:
        data = _read()
        data[key(media_type, canonical_id)] = float(now or time.time())
        # Bounded: the oldest removals go first.
        data = dict(sorted(data.items(), key=lambda pair: pair[1], reverse=True)[:500])
        path = _path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json(path, data)
        _MEM.clear()


def hidden(media_type, canonical_id, updated_at, data=None):
    """True while the title was removed after its latest progress."""
    data = _read() if data is None else data
    removed = data.get(key(media_type, canonical_id))
    if not removed:
        return False
    from .progress_model import timestamp
    return timestamp(updated_at) <= float(removed)


def snapshot():
    return _read()
