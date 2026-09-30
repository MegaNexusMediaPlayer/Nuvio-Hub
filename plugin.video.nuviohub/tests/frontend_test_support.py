"""Expose the existing Kodi stub package under the production backend namespace."""
from pathlib import Path
import sys
import types
import kodi_stub


def install():
    kodi_stub.import_lib_module('plugin')
    root=Path(kodi_stub.ADDON_ROOT)
    sys.path.insert(0,str(root.parent/'script.nuvio'))
    resources=types.ModuleType('resources')
    resources.__path__=[str(root/'resources')]
    sys.modules['resources']=resources
    resources.lib=sys.modules['dexlib']
    sys.modules['resources.lib']=resources.lib
    for key,value in list(sys.modules.items()):
        if key.startswith('dexlib.'):
            sys.modules['resources.lib'+key[len('dexlib'):]]=value
