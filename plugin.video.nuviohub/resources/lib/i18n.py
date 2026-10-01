# -*- coding: utf-8 -*-
"""Nuvio Hub English-only runtime text helpers.

The 6.0.8 build ships a single UI language: English. ``tr`` and ``trf`` remain
as compatibility helpers because the codebase calls them extensively, but the
old runtime Arabic-to-English translation table has been removed.
"""

_lang_cache = "en"
STRINGS = {}

try:
    import xbmcaddon
    ADDON = xbmcaddon.Addon('plugin.video.nuviohub')
except Exception:
    ADDON = None


def _read_language_setting():
    return "en"


def reset_language_cache():
    global _lang_cache
    _lang_cache = "en"


def current_language():
    return "en"


def is_english():
    return True


def tr(text):
    return text


def trf(template, *args, **kwargs):
    translated = tr(template)
    try:
        if args:
            return translated % (args if len(args) != 1 else args[0])
        if kwargs:
            return translated.format(**kwargs)
        return translated
    except Exception:
        return translated
