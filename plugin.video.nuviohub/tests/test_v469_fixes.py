# -*- coding: utf-8 -*-
"""v4.6.9 regression tests.

1. SEARCH HISTORY ORDER — "البحث يجيب من حرف A": the history listing ended
   with content=None, which registered the alphabetical sort method, and
   Kodi's per-path sort memory then showed the history A→Z instead of
   most-recent-first — burying the word the user just searched. Recency
   listings now register UNSORTED only (sortable=False through end_dir).

2. BADGES BACK — the AIO fast path trusted the formatter for video/audio
   facts with NO raw scan; when the user's AIOStreams preset omits those
   labelled fields the bits came back empty, and the badge builder emits a
   tag only when it appears in the bits — so the whole badge row vanished.
   The raw regex scan is back as a gap-filler; formatter values stay
   authoritative when present.

3. THIRD FROZEN HANDLE — ui_core captured its own module-level HANDLE at
   import time and end_dir()/setContent() ran on it; 4.6.4 fixed
   context/plugin but missed this copy. The dispatch reset now rebinds it.
"""
import io
import os
import re
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
UI_CORE = io.open(os.path.join(ROOT, 'resources', 'lib', 'ui_core.py'), encoding='utf-8').read()


class TestHistoryRecencyOrder(unittest.TestCase):
    def test_sortable_gate_registers_unsorted_only(self):
        self.assertIn('def _apply_sort_methods(content=None, sortable=True):', PLUGIN)
        body = PLUGIN.split('def _apply_sort_methods(content=None, sortable=True):', 1)[1]
        body = body.split('\ndef ', 1)[0]
        gate = body.split('if not sortable:', 1)[1].split('if content in', 1)[0]
        self.assertIn('SORT_METHOD_UNSORTED', gate)
        self.assertIn('return', gate)
        self.assertNotIn('LABEL', gate)

    def test_end_dir_passes_sortable_through(self):
        self.assertIn('def end_dir(content=None, cache=True, sortable=True):', UI_CORE)
        self.assertIn('_apply_sort_methods(resolved_content, sortable=sortable)', UI_CORE)

    def test_history_view_opts_out_of_alphabetical(self):
        body = PLUGIN.split('def search_history_view(', 1)[1].split('\ndef ', 1)[0]
        self.assertIn('sortable=False', body)
        # storage order is already most-recent-first; the view must not
        # hand Kodi a way to re-sort it
        sh = io.open(os.path.join(ROOT, 'resources', 'lib', 'search_history.py'),
                     encoding='utf-8').read()
        self.assertIn('ORDER BY last_used DESC', sh)


class TestAioBadgeFallback(unittest.TestCase):
    """v4.8.5: behavioural. The analysis moved to stream_facts.py, and
    these now CALL _stream_facts instead of grepping plugin.py for the
    branch — which is what the bug deserved in the first place: badges
    vanished for several releases because the AIO fast path trusted the
    formatter with no fallback, and no test ever ran a row through it.
    """

    # _stream_facts is the ORCHESTRATOR and deliberately stayed in
    # plugin.py when the leaf-pure analysis moved to stream_facts.py, so
    # the behavioural check runs against plugin — which is also where a
    # real caller reaches it from.
    import kodi_stub as _ks
    _plugin = _ks.import_lib_module('plugin')

    # The formatter labels are bare words, not 'Video:' — verified against
    # _FORMATTER_LINE_RE. Getting this wrong is precisely how the original
    # bug hid: a preset that does not emit these lines leaves the parser
    # with nothing and the fast path with empty bits.
    AIO_ROW = {
        'name': 'AIOStreams',
        'description': ('FILE Movie.2024.2160p.WEB-DL.DV.HDR10.DDP5.1.Atmos.x265-GRP.mkv\n'
                        'SIZE 24.5 GB'),
    }

    def _facts(self, row):
        return self._plugin._stream_facts(row, provider_name='AIOStreams')

    def test_raw_scan_fills_empty_formatter_bits(self):
        """No labelled video:/audio: fields — the badge facts must still
        come out of the release name."""
        facts = self._facts(dict(self.AIO_ROW))
        blob = ' '.join(str(v) for v in facts.values() if isinstance(v, str))
        blob += ' ' + ' '.join(map(str, facts.get('video_bits') or []))
        blob += ' ' + ' '.join(map(str, facts.get('audio_bits') or []))
        upper = blob.upper()
        self.assertTrue(facts.get('video_bits'), 'no video facts recovered')
        for token in ('2160P', 'DV'):
            self.assertIn(token, upper, token)

    def test_formatter_stays_authoritative_when_present(self):
        """When the preset DOES emit labelled fields, they are used and the
        name scan does not run — the 4.6.9 contract, now executed."""
        row = {'name': 'AIOStreams',
               'description': ('FILE Movie.2024.2160p.WEB-DL.DV.Atmos.mkv\n'
                               'VIDEO 1080p, HDR10\n'
                               'AUDIO AAC')}
        parsed = self._plugin._parse_formatter_fields(row)
        self.assertEqual(parsed.get('video'), '1080p, HDR10')   # fixture is real
        facts = self._facts(row)
        video = ' '.join(map(str, facts.get('video_bits') or [])).upper()
        audio = ' '.join(map(str, facts.get('audio_bits') or [])).upper()
        self.assertIn('1080P', video)
        self.assertNotIn('2160P', video)      # the filename did not override it
        self.assertIn('AAC', audio)
        self.assertNotIn('ATMOS', audio)

    def test_empty_row_never_raises(self):
        for row in ({}, {'name': ''}, {'description': None}):
            self.assertIsInstance(self._facts(dict(row)), dict)

    def test_badge_builder_still_keyed_on_bits(self):
        sb = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'),
                     encoding='utf-8').read()
        self.assertIn('if key in all_bits_up and key not in seen:', sb)


class TestThirdFrozenHandle(unittest.TestCase):
    def test_dispatch_rebinds_ui_core_handle(self):
        body = PLUGIN.split('def _reset_invocation_state():', 1)[1]
        body = body.split('\ndef ', 1)[0]
        self.assertIn('_ui_mod.HANDLE = HANDLE', body)

    def test_no_other_frozen_module_level_captures(self):
        lib = os.path.join(ROOT, 'resources', 'lib')
        offenders = []
        for name in os.listdir(lib):
            if not name.endswith('.py') or name in ('context.py', 'ui_core.py'):
                continue
            text = io.open(os.path.join(lib, name), encoding='utf-8').read()
            for m in re.finditer(r'^HANDLE\s*=\s*int\(sys\.argv', text, re.M):
                offenders.append(name)
        self.assertEqual(offenders, [], offenders)

    def test_end_dir_runs_on_the_rebound_handle(self):
        self.assertIn('xbmcplugin.endOfDirectory(HANDLE', UI_CORE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
