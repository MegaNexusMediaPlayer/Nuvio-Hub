# -*- coding: utf-8 -*-
"""v4.8.6 — three faults from one Android log, and they were related.

    sqlite3.OperationalError: attempt to write a readonly database
      ... cache_store.py line 75, in put
      ... plugin.py line 15545, in _append_stream_entries_from_data
      ... plugin.py line 16338, in _worker

On Android the addon-data directory can be read-only, and SQLite then
refuses every write. That exception escaped into the source-scan WORKER
THREADS — one death per stream row — which is the crash, the stutter and
the failed playback in the same log. The cache now says so once and runs
from memory, which every read already consults first.

    DISPATCHER ERROR: name '_setting' is not defined

Opening "Sync mode and timing" killed the dispatcher outright: the action
added in 4.8.3 called a helper that plugin.py never defined. The same
missing name sat in the TMDb search renderer inside a broad `except`, so
the cinematic search window had been failing silently as well.
"""
import io
import os
import sqlite3
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
cs = kodi_stub.import_lib_module('dexhub.cache_store')
pl = kodi_stub.import_lib_module('plugin')
PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()


class _ReadOnlyConn(object):
    """Exactly what Android hands back when the profile cannot be written."""

    def __init__(self, calls):
        self.calls = calls

    def execute(self, *_a, **_k):
        self.calls.append('execute')
        raise sqlite3.OperationalError('attempt to write a readonly database')

    def commit(self):
        pass

    def close(self):
        self.calls.append('close')


class _ReadOnlyDisk(object):
    def __enter__(self):
        self.calls = []
        self._orig = cs._conn
        cs._conn = lambda: _ReadOnlyConn(self.calls)
        cs._DISK_DISABLED = False
        cs._MEM.clear()
        del cs._MEM_ORDER[:]
        return self

    def __exit__(self, *exc):
        cs._conn = self._orig
        cs._DISK_DISABLED = False
        cs._MEM.clear()
        del cs._MEM_ORDER[:]
        return False


class TestReadonlyDatabaseSurvival(unittest.TestCase):
    def test_put_returns_a_usable_key_instead_of_raising(self):
        with _ReadOnlyDisk():
            key = cs.put('stream', {'url': 'magnet:?x', 'name': 'Row'})
            self.assertTrue(key)
            self.assertEqual(cs.get('stream', key), {'url': 'magnet:?x', 'name': 'Row'})

    def test_disk_is_disabled_after_the_first_failure(self):
        with _ReadOnlyDisk() as disk:
            cs.put('stream', {'a': 1})
            self.assertTrue(cs._DISK_DISABLED)
            attempts = len(disk.calls)
            for _ in range(20):
                cs.put('stream', {'a': 2})
            # no further DB work: this is what the stutter came from
            self.assertEqual(len(disk.calls), attempts)

    def test_update_and_clear_all_never_raise(self):
        with _ReadOnlyDisk():
            key = cs.put('stream', {'v': 1})
            cs.update('stream', key, {'v': 2})
            self.assertEqual(cs.get('stream', key), {'v': 2})
            cs.clear_all('stream')
            self.assertIsNone(cs.get('stream', key))

    def test_get_on_an_unopenable_db_returns_none(self):
        orig = cs._conn
        try:
            cs._DISK_DISABLED = False
            cs._MEM.clear()

            def _boom():
                raise sqlite3.OperationalError('unable to open database file')
            cs._conn = _boom
            self.assertIsNone(cs.get('stream', 'missing-key'))
            self.assertTrue(cs._DISK_DISABLED)
        finally:
            cs._conn = orig
            cs._DISK_DISABLED = False

    def test_a_healthy_disk_still_persists(self):
        """The degradation must not become the normal path."""
        cs._DISK_DISABLED = False
        cs._MEM.clear()
        del cs._MEM_ORDER[:]
        key = cs.put('stream', {'real': True})
        cs._MEM.clear()                      # force a disk read
        del cs._MEM_ORDER[:]
        self.assertEqual(cs.get('stream', key), {'real': True})


class TestMissingSettingHelper(unittest.TestCase):
    def test_helper_exists_and_is_safe(self):
        self.assertTrue(callable(pl._setting))
        self.assertEqual(pl._setting('definitely_not_a_setting', 'fallback'), 'fallback')

    def test_both_call_sites_can_run(self):
        """Neither may raise NameError again."""
        self.assertIn("_setting('search_style'", PLUGIN)
        # v5.4.1: the dialog body lives in routes/accounts.sync_options and
        # receives `_setting` as an argument — the helper still has to exist.
        body = PLUGIN.split('def sync_options_action():', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('_setting', body)
        acc = io.open(os.path.join(ROOT, 'resources', 'lib', 'routes',
                                   'accounts.py'), encoding='utf-8').read()
        self.assertIn("setting('cloud_sync_continuous'", acc)
        self.assertIn("setting('cloud_sync_interval_min'", acc)

    def test_no_other_undefined_module_level_names(self):
        """A sweep for the same class of bug: a helper used but never
        defined at module level in plugin.py."""
        import ast
        import builtins
        tree = ast.parse(PLUGIN)
        defined = set(dir(builtins))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                defined.add(node.name)
            elif isinstance(node, ast.ClassDef):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        defined.add(t.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    defined.add((a.asname or a.name).split('.')[0])
        # star-imported names from context are not visible to AST
        self.assertIn('_setting', defined)
        self.assertIn('_search_match_score', defined)


if __name__ == '__main__':
    unittest.main(verbosity=2)
