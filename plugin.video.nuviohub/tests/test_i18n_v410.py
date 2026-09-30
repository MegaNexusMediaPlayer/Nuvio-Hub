# -*- coding: utf-8 -*-
"""i18n regression tests (v4.1.0).

Two guards from the 4.0.1 audit, re-armed:
  1. no duplicate keys in the STRINGS dict (22 crept back between 4.0.1→4.0.7
     and were removed in 4.1.0),
  2. every Arabic literal passed to tr() in the NEW code paths has a STRINGS
     entry, so English users never see leaked Arabic.
"""
import ast
import io
import os
import re
import unittest

import kodi_stub

LIB = kodi_stub.LIB
i18n = kodi_stub.import_lib_module('i18n')

NEW_FILES = ('simkl.py',)  # fully-new modules: every tr() literal must resolve
NEW_MARKER_FILES = ('plugin.py', 'source_browser.py', 'mdblist.py')


def _strings_dict_keys():
    src = io.open(os.path.join(LIB, 'i18n.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'STRINGS':
            return [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
    return []


def _tr_literals(path):
    src = io.open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'tr'
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            out.append(node.args[0].value)
    return out


def _has_arabic(text):
    return any('\u0600' <= ch <= '\u06ff' for ch in text)


class TestNoDuplicateStringKeys(unittest.TestCase):
    def test_strings_dict_has_no_duplicates(self):
        keys = _strings_dict_keys()
        self.assertTrue(len(keys) > 1000, 'STRINGS dict unexpectedly small')
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        self.assertEqual(dupes, [], 'duplicate STRINGS keys: %s' % dupes)


class TestNewTrLiteralsCovered(unittest.TestCase):
    def test_simkl_module_fully_covered(self):
        keys = set(_strings_dict_keys())
        missing = []
        for name in NEW_FILES:
            for lit in _tr_literals(os.path.join(LIB, name)):
                if _has_arabic(lit) and lit not in keys:
                    missing.append((name, lit))
        self.assertEqual(missing, [], 'Arabic tr() literals with no STRINGS entry: %s' % missing)

    def test_v410_markers_covered_in_touched_files(self):
        """Every Arabic tr() literal that mentions Simkl/MDBList or the new
        shelf labels must resolve to English."""
        keys = set(_strings_dict_keys())
        probes = re.compile(r'Simkl|MDBList|أشاهد|خطة المشاهدة|TYPE')
        missing = []
        for name in NEW_MARKER_FILES:
            for lit in _tr_literals(os.path.join(LIB, name)):
                if _has_arabic(lit) and probes.search(lit) and lit not in keys:
                    missing.append((name, lit))
        self.assertEqual(missing, [], 'untranslated v4.1.0 literals: %s' % missing)

    def test_tr_resolves_to_english(self):
        i18n._lang_cache = 'en'
        i18n._TR_MEMO.clear()
        self.assertEqual(i18n.tr('لستاتي في Simkl'), 'My Simkl lists')
        self.assertEqual(i18n.tr('حالة MDBList: %s') % 'X', 'MDBList status: X')
        self.assertFalse(_has_arabic(i18n.tr('مسلسلات • أشاهدها')))
        i18n._lang_cache = None
        i18n._TR_MEMO.clear()


if __name__ == '__main__':
    unittest.main(verbosity=2)
