# -*- coding: utf-8 -*-
import os
import sys

addon_path = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(addon_path, 'resources', 'lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from resources.lib.bootstrap import run

if __name__ == '__main__':
    from resources.lib.fork_profile import ensure_profile
    ensure_profile()
    run()
