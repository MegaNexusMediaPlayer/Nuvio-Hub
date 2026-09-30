# -*- coding: utf-8 -*-
"""Run the full NuvioHub regression suite: python3 tests/run_all.py"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import kodi_stub  # noqa: E402
kodi_stub.install()

loader = unittest.TestLoader()
suite = loader.discover(HERE, pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
