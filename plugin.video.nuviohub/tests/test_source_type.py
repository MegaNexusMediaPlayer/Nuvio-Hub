# -*- coding: utf-8 -*-
"""Source-type chip classification tests (v4.1.0).

The classifier lives inside plugin.py, which cannot be imported standalone;
these tests extract _stream_source_type + its regex/constants + the two tiny
helpers it calls into an isolated namespace and run the real code — same
technique as auditing against real log rows.
"""
import ast
import io
import os
import re
import unittest

import kodi_stub  # noqa: F401  (path side-effects)

PLUGIN = os.path.join(kodi_stub.LIB, 'plugin.py')


STREAM_FACTS = os.path.join(kodi_stub.LIB, 'stream_facts.py')


def _load_classifier():
    wanted_funcs = {'_stream_source_type', '_provider_badge', '_collect_stream_texts',
                    '_iter_stream_values'}
    wanted_assigns = {'_SOURCE_TYPE_STYLES', '_USENET_RE', '_TORRENT_HINT_RE',
                      '_DEBRID_BADGES',
                      # v4.2.2 factored the collected field list into a
                      # module constant — extract it with the functions.
                      '_STREAM_TEXT_FIELDS', '_STREAM_HINT_TEXT_FIELDS'}
    # v4.8.5: the release-name analysis moved to stream_facts.py, so the
    # pieces this classifier needs now live in two files. Scan both.
    pieces = []
    seen = set()
    for path in (STREAM_FACTS, PLUGIN):
        src = io.open(path, encoding='utf-8').read()
        for node in ast.parse(src).body:
            if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
                if node.name in seen:
                    continue
                seen.add(node.name)
                pieces.append(ast.get_source_segment(src, node))
            elif isinstance(node, ast.Assign):
                names = {getattr(t, 'id', '') for t in node.targets}
                hit = names & wanted_assigns
                # plugin.py re-exports the moved names as aliases
                # (`X = _sf.X`); take the real definition, skip the alias.
                if not hit or (hit & seen):
                    continue
                seen |= hit
                pieces.append(ast.get_source_segment(src, node))
    # _normalize_ascii drags in the whole stream-text cleaning subsystem
    # (HEX_ENTITIES, flag/icon regexes, …). The classifier only needs its
    # contract — non-ASCII stripped, whitespace collapsed — so a faithful
    # lite version keeps this test focused on classification logic.
    def _normalize_ascii(text):
        text = re.sub(r'[^\x00-\x7F]', '', str(text or ''))
        return re.sub(r'\s+', ' ', text).strip(' -|_')

    ns = {'re': re, 'json': __import__('json'),
          '_normalize_ascii': _normalize_ascii,
          'MULTI_WS_RE': re.compile(r'\s+')}
    exec(compile('\n\n'.join(pieces), PLUGIN, 'exec'), ns)
    assert '_stream_source_type' in ns, 'classifier not found in plugin.py'
    return ns['_stream_source_type']


classify = _load_classifier()


class TestSourceTypeClassifier(unittest.TestCase):
    def _key(self, row, provider='AIOStreams'):
        return classify(row, provider)[0]

    # ── usenet ──
    def test_torbox_usenet_row_is_usenet_not_debrid(self):
        # TorBox usenet rows mention both "TB" and "Usenet" — usenet must win.
        row = {'name': '[TB+] TorBox Usenet', 'title': 'Movie.2024.1080p.WEB-DL',
               'description': 'Usenet | 4.2 GB'}
        self.assertEqual(self._key(row), 'usenet')

    def test_easynews_is_usenet(self):
        row = {'name': 'Easynews+', 'title': 'Show.S01E01.720p', 'url': 'https://members.easynews.com/x.mkv'}
        self.assertEqual(self._key(row, 'Easynews'), 'usenet')

    def test_nzb_keyword_is_usenet(self):
        row = {'name': 'Newznab', 'description': 'NZB result via SABnzbd'}
        self.assertEqual(self._key(row), 'usenet')

    # ── debrid ──
    def test_realdebrid_tagged_row(self):
        row = {'name': '[RD+] Torrentio', 'title': 'Movie.2160p.REMUX',
               'url': 'https://real-debrid.example/dl.mkv'}
        self.assertEqual(self._key(row, 'Torrentio'), 'debrid')

    def test_alldebrid_tagged_row(self):
        row = {'name': 'AD+ AIOStreams', 'title': 'Movie 1080p'}
        self.assertEqual(self._key(row), 'debrid')

    def test_debrid_keyword_row(self):
        row = {'name': 'StremThru', 'description': 'EasyDebrid cached'}
        self.assertEqual(self._key(row, 'StremThru'), 'debrid')

    # ── torrent ──
    def test_infohash_row_is_torrent(self):
        row = {'name': 'Torrentio', 'title': 'Movie.1080p.WEB 👤 87',
               'infoHash': 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef'}
        self.assertEqual(self._key(row, 'Torrentio'), 'torrent')

    def test_magnet_url_is_torrent(self):
        row = {'name': 'Comet', 'url': 'magnet:?xt=urn:btih:abc'}
        self.assertEqual(self._key(row, 'Comet'), 'torrent')

    def test_seeders_text_is_torrent(self):
        row = {'name': 'MediaFusion', 'description': '1080p | Seeders: 120'}
        self.assertEqual(self._key(row, 'MediaFusion'), 'torrent')

    # ── native servers ──
    def test_native_plex_hint(self):
        row = {'name': 'Movie', 'behaviorHints': {'nativeProvider': 'plex'}}
        self.assertEqual(self._key(row, 'Plex \u2022 Home'), 'plex')

    def test_native_emby_hint(self):
        row = {'name': 'Movie', 'behaviorHints': {'nativeProvider': 'emby'}}
        self.assertEqual(self._key(row, 'Emby \u2022 NAS'), 'emby')

    def test_provider_name_prefix_without_hint(self):
        row = {'name': 'Direct Play 1080p'}
        self.assertEqual(self._key(row, 'Plex \u2022 Home'), 'plex')

    # ── direct fallback ──
    def test_plain_http_host_is_direct(self):
        row = {'name': 'WebStreamr', 'title': 'Movie 1080p',
               'url': 'https://cdn.example.com/stream.m3u8'}
        self.assertEqual(self._key(row, 'WebStreamr'), 'direct')

    # ── contract: label + colour always present ──
    def test_every_key_has_label_and_argb_colour(self):
        rows = [
            ({'name': 'Usenet x'}, 'usenet'),
            ({'name': '[RD+] y'}, 'debrid'),
            ({'infoHash': 'ab'}, 'torrent'),
            ({'url': 'https://a/b'}, 'direct'),
        ]
        for row, expected in rows:
            key, label, colour = classify(row, 'X')
            self.assertEqual(key, expected)
            self.assertTrue(label.isupper() and label)
            self.assertRegex(colour, r'^[0-9A-F]{8}$')


if __name__ == '__main__':
    unittest.main(verbosity=2)
