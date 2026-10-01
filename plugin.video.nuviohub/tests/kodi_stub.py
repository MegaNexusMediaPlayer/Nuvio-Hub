# -*- coding: utf-8 -*-
"""Minimal Kodi API stubs so addon modules import under plain CPython.

Injects fake xbmc* modules into sys.modules and puts resources/lib on the
path as the package root, mirroring how Kodi's interpreter resolves the
addon's relative imports. stdlib only — no external deps.
"""
import os
import sys
import types

ADDON_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LIB = os.path.join(ADDON_ROOT, 'resources', 'lib')


class _Addon(object):
    _settings = {}

    def __init__(self, *_a, **_k):
        pass

    def getSetting(self, key):
        return self._settings.get(key, '')

    def setSetting(self, key, value):
        self._settings[key] = value

    def getSettingBool(self, key):
        return str(self._settings.get(key, '')).lower() == 'true'

    def getAddonInfo(self, key):
        return {'version': '4.1.0', 'id': 'plugin.video.nuviohub',
                'path': ADDON_ROOT, 'profile': os.environ.get('NUVIO_TEST_PROFILE') or os.path.join(ADDON_ROOT, '.test-profile')}.get(key, '')


def install():
    if 'xbmc' in sys.modules:
        return sys.modules['xbmc']
    xbmc = types.ModuleType('xbmc')
    xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = 0, 1, 2, 3
    xbmc.LOGNONE, xbmc.LOGFATAL = -1, 4
    xbmc.log = lambda *_a, **_k: None
    xbmc.sleep = lambda *_a, **_k: None
    xbmc.executebuiltin = lambda *_a, **_k: None
    xbmc.getInfoLabel = lambda *_a, **_k: ''
    xbmc.getSkinDir = lambda: 'skin.nuvio'
    xbmc.getCondVisibility = lambda *_a, **_k: False
    xbmc.Monitor = type('Monitor', (), {'abortRequested': lambda self: False,
                                        'waitForAbort': lambda self, *_a: True})
    xbmc.Player = type('Player', (), {})

    xbmcaddon = types.ModuleType('xbmcaddon')
    xbmcaddon.Addon = _Addon

    xbmcgui = types.ModuleType('xbmcgui')
    xbmcgui.NOTIFICATION_INFO = 'info'
    # v4.7.5: window properties are a real cross-process channel in Kodi
    # (the badges live-value bridge rides on them), so the stub keeps one
    # shared store per window id instead of swallowing writes.
    _WINDOW_PROPS = {}

    def _stub_window(win_id=0, *_a, **_k):
        store = _WINDOW_PROPS.setdefault(int(win_id or 0), {})
        return types.SimpleNamespace(
            getProperty=lambda key: store.get(key, ''),
            setProperty=lambda key, value: store.__setitem__(key, value),
            clearProperty=lambda key: store.pop(key, None))

    xbmcgui.Window = _stub_window
    xbmcgui.ListItem = type('ListItem', (), {
        '__init__': lambda self, *a, **k: setattr(self, '_p', {}),
        'setProperty': lambda self, k, v: self._p.__setitem__(k, v),
        'getProperty': lambda self, k: self._p.get(k, ''),
    })
    xbmcgui.Dialog = lambda: types.SimpleNamespace(
        ok=lambda *_a, **_k: True, notification=lambda *_a, **_k: None,
        input=lambda *_a, **_k: '')
    xbmcgui.DialogProgress = type('DialogProgress', (), {
        'create': lambda self, *a: None, 'update': lambda self, *a: None,
        'close': lambda self: None, 'iscanceled': lambda self: True})
    xbmcgui.WindowXMLDialog = type('WindowXMLDialog', (), {})
    xbmcgui.WindowXML = type('WindowXML', (), {})
    # v4.6.7: plex_qr.QRLinkWindow imports need the plain borderless dialog
    # and its bare controls.
    xbmcgui.WindowDialog = type('WindowDialog', (), {
        'addControl': lambda self, *a, **k: None,
        'show': lambda self: None, 'close': lambda self: None})
    xbmcgui.ControlImage = type('ControlImage', (), {
        '__init__': lambda self, *a, **k: None})
    xbmcgui.ControlLabel = type('ControlLabel', (), {
        '__init__': lambda self, *a, **k: None})
    xbmcgui.ControlTextBox = type('ControlTextBox', (), {
        '__init__': lambda self, *a, **k: None,
        'setText': lambda self, *a: None})

    xbmcplugin = types.ModuleType('xbmcplugin')
    xbmcvfs = types.ModuleType('xbmcvfs')
    # v4.7.7: Kodi only rewrites special:// paths and returns anything else
    # unchanged. The old stub swallowed its argument, which hid whether code
    # was reading the profile path it was actually given.
    xbmcvfs.translatePath = lambda p: (
        os.path.join(ADDON_ROOT, '.test-profile') if str(p or '').startswith('special://') else str(p or ''))
    xbmcvfs.exists = lambda p: os.path.exists(p)
    xbmcvfs.mkdirs = lambda p: os.makedirs(p, exist_ok=True) or True

    for name, mod in (('xbmc', xbmc), ('xbmcaddon', xbmcaddon), ('xbmcgui', xbmcgui),
                      ('xbmcplugin', xbmcplugin), ('xbmcvfs', xbmcvfs)):
        sys.modules[name] = mod

    os.makedirs(os.path.join(ADDON_ROOT, '.test-profile'), exist_ok=True)
    if LIB not in sys.path:
        sys.path.insert(0, LIB)
    return xbmc


def import_lib_module(name):
    """Import resources/lib/<name>.py as part of a package so its relative
    imports (`from . import x`, `from .nuviohub...`) resolve like inside Kodi."""
    install()
    import importlib
    pkg_name = 'nuviolib'
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [LIB]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    return importlib.import_module('%s.%s' % (pkg_name, name))
