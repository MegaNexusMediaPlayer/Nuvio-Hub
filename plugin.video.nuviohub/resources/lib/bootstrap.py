# -*- coding: utf-8 -*-
"""Small Kodi entry point.

Keep default.py stable and defer the very large legacy compatibility module
until an invocation actually runs. This also gives future versions one place
to swap the legacy router for fully split routes.
"""

def run():
    # --- nuviohub-401-patch ---
    try:
        from .settings_cache import invalidate as _dh_invalidate
        _dh_invalidate()
    except Exception:
        pass
    try:
        from .i18n import reset_language_cache
        reset_language_cache()
    except Exception:
        pass
    from .plugin import run as plugin_run
    return plugin_run()
