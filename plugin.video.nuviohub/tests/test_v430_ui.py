# -*- coding: utf-8 -*-
"""v4.3.0 regression tests — sources-window polish + continue art style.

Grounded in the two screenshots that drove this release:
  * 'EAC3 • 5 1 • NaN Mbps • NaN fps' rendering where the overview belongs,
  * release filenames shown as the hero plot,
  * 'Emby • Emby • EMBY EMBY' origin line,
  * quality badge clipped/flipped under the Arabic UI,
  * mismatched rating icons,
  * the new poster/banner Continue Watching setting.
"""
import io
import os
import re
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SB_PATH = os.path.join(ROOT, 'resources', 'lib', 'source_browser.py')
SB = io.open(SB_PATH, encoding='utf-8').read()
SKIN = io.open(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'sources_results.xml'), encoding='utf-8').read()
SETTINGS = io.open(os.path.join(ROOT, 'resources', 'settings.xml'), encoding='utf-8').read()


def _load_plot_cleaner():
    """Extract _clean_header_plot + its regex constants from source_browser."""
    import ast
    tree = ast.parse(SB)
    pieces = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == '_clean_header_plot':
            pieces.append(ast.get_source_segment(SB, node))
        elif isinstance(node, ast.Assign):
            names = {getattr(t, 'id', '') for t in node.targets}
            if any(n.startswith('_PLOT_') for n in names):
                pieces.append(ast.get_source_segment(SB, node))
    ns = {'re': re}
    exec(compile('\n\n'.join(pieces), SB_PATH, 'exec'), ns)
    return ns['_clean_header_plot']


clean_plot = _load_plot_cleaner()


def _load_origin_line():
    """Extract _source_origin_line with lite stubs for its extractors."""
    import ast
    tree = ast.parse(PLUGIN)
    piece = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == '_source_origin_line':
            piece = ast.get_source_segment(PLUGIN, node)
    ns = {
        're': re,
        'MULTI_WS_RE': re.compile(r'\s+'),
        '_extract_addon_name': lambda row, provider_name: row.get('addon') or '',
        '_extract_indexer_name': lambda row, provider_name, addon_name='': row.get('indexer') or '',
        '_extract_service_name': lambda row: row.get('service') or '',
    }
    exec(compile(piece, 'plugin.py', 'exec'), ns)
    return ns['_source_origin_line']


origin_line = _load_origin_line()


class TestHeaderPlotCleaner(unittest.TestCase):
    def test_nan_tokens_removed_and_channels_fixed(self):
        out = clean_plot('EAC3 • 5 1 • NaN Mbps • NaN fps')
        self.assertNotIn('NaN', out)
        self.assertNotIn('5 1', out)

    def test_release_filename_hidden(self):
        junk = 'The Death of Robin Hood (2026) [WEBDL-2160p HEVC 8-bit EAC3 Atmos 5 1]-SCOPE'
        self.assertEqual(clean_plot(junk), '')

    def test_tech_summary_line_hidden(self):
        self.assertEqual(clean_plot('MKV • 1440p • HDR10 • HEVC'), '')

    def test_real_overview_untouched(self):
        text = ('Sophie, a quiet girl working in a hat shop, finds her life '
                'thrown into turmoil when she is literally swept off her feet '
                'by a handsome but mysterious wizard named Howl.')
        self.assertEqual(clean_plot(text), text)

    def test_overview_mentioning_one_format_survives(self):
        text = ('The film was remastered in 1080p for its anniversary. '
                'Critics praised the restoration, and audiences returned to '
                'theaters in record numbers for the re-release.')
        self.assertEqual(clean_plot(text), text)


class TestOriginLineDedupe(unittest.TestCase):
    def test_server_named_after_product_collapses(self):
        # The screenshot case: provider 'Emby • Emby' + service 'EMBY EMBY'.
        line = origin_line({'service': 'EMBY EMBY'}, 'Emby • Emby')
        self.assertEqual(line, 'Emby')

    def test_distinct_parts_survive(self):
        line = origin_line(
            {'addon': 'MediaFusion', 'service': 'ElfHosted', 'indexer': 'Comet'},
            'Vidstreams')
        for part in ('Vidstreams', 'MediaFusion', 'ElfHosted', 'Comet'):
            self.assertIn(part, line)
        self.assertEqual(line.count('Vidstreams'), 1)

    def test_repeated_word_inside_token_collapses(self):
        line = origin_line({}, 'Plex Plex')
        self.assertEqual(line, 'Plex')


class TestQualityBandSkin(unittest.TestCase):
    def test_label_widened_and_ltr_locked(self):
        # v4.6.0: the single $INFO-coloured quality label became FIVE
        # static-colour variants per layout (per-item $INFO colordiffuse /
        # colour does not resolve in Kodi 22 list layouts). The widened
        # geometry survives (62/122 in both layouts, one control per
        # quality value) and the LRM-anchored display copy is still what
        # every variant prints, so the Arabic UI cannot bidi-flip '1080P'.
        self.assertEqual(SKIN.count('<left>62</left><top>12</top><width>122</width>'), 10)
        self.assertEqual(SKIN.count('$INFO[ListItem.Property(quality)]'), 10)
        # raw quality_key drives the variant switch — display copy does not
        self.assertEqual(SKIN.count('String.IsEqual(ListItem.Property(quality_key)'), 10)
        self.assertNotIn('<left>64</left><top>22</top><width>94</width>', SKIN)


class TestUnifiedIconSet(unittest.TestCase):
    def test_all_ten_icons_exist_in_ratings_folder(self):
        # v4.3.1: chips live under media/ratings/ — a Kodi-cache-fresh path.
        for icon in ('imdb', 'tmdb', 'trakt', 'rt_critics', 'rt_audience',
                     'metacritic', 'letterboxd', 'mdblist', 'mal', 'simkl'):
            path = os.path.join(ROOT, 'resources', 'media', 'ratings', '%s.png' % icon)
            self.assertTrue(os.path.exists(path), icon)
            self.assertGreater(os.path.getsize(path), 800, icon)

    def test_skin_chips_use_ratings_folder(self):
        self.assertEqual(SKIN.count('resources/media/ratings/'), 9)
        # primary texture is ours on every row-1 chip; skin extras only fall back
        self.assertEqual(SKIN.count('fallback="special://skin/extras/flags/color/ratings/'), 6)


class TestV431Fixes(unittest.TestCase):
    def test_metacritic_scale_stays_percentile(self):
        ctx = io.open(os.path.join(ROOT, 'resources', 'lib', 'tmdbh_context.py'), encoding='utf-8').read()
        self.assertIn("is_pct = key in ('rt_crit', 'rt_aud', 'metacritic')", ctx)

    def test_bidi_anchor_behaviour(self):
        import ast as _ast
        tree = _ast.parse(SB)
        pieces = []
        for node in tree.body:
            if isinstance(node, _ast.FunctionDef) and node.name == '_bidi_anchor':
                pieces.append(_ast.get_source_segment(SB, node))
            elif isinstance(node, _ast.Assign):
                names = {getattr(t, 'id', '') for t in node.targets}
                if names & {'_RTL_STRONG_RE', '_LTR_STRONG_RE'}:
                    pieces.append(_ast.get_source_segment(SB, node))
        ns = {'re': re}
        exec(compile('\n\n'.join(pieces), 'sb', 'exec'), ns)
        anchor = ns['_bidi_anchor']
        # digit-leading release names get pinned LTR
        self.assertTrue(anchor('3840X2160_ALQ-8_SDR_FINAL MKV').startswith('\u200e'))
        self.assertTrue(anchor('[TB+] Vidstreams 4K').startswith('\u200e'))
        # Arabic-leading labels stay untouched
        self.assertEqual(anchor('مسلسلات أشاهدها'), 'مسلسلات أشاهدها')
        self.assertEqual(anchor(''), '')

    def test_bidi_anchor_wired_into_row_properties(self):
        self.assertIn('_bidi_anchor(_kodi_safe_text(value))', SB)

    def test_fit_label_keeps_start_and_marks_ellipsis(self):
        import ast as _ast
        tree = _ast.parse(SB)
        piece = None
        for node in tree.body:
            if isinstance(node, _ast.FunctionDef) and node.name == '_fit_label':
                piece = _ast.get_source_segment(SB, node)
        ns = {}
        exec(compile(piece, 'sb', 'exec'), ns)
        fit = ns['_fit_label']
        long_name = 'MULTI 1080P WEB X264-FTMVHD ALL HAIL KING JULIEN 2014 INTERNAL COMPLETE'
        out = fit(long_name)
        self.assertTrue(out.startswith('MULTI 1080P'))
        self.assertTrue(out.endswith('…'))
        self.assertLessEqual(len(out), 52)
        self.assertEqual(fit('SHORT NAME'), 'SHORT NAME')

    def test_unfocused_layout_binds_fitted_name(self):
        # v4.6.1: the chips list (2300) precedes the rows list in document
        # order, so both extractions anchor AFTER list id="2000".
        rows = SKIN[SKIN.index('<control type="list" id="2000">'):]
        start = rows.index('<itemlayout')
        seg = rows[start:rows.index('</itemlayout>', start)]
        self.assertIn('ListItem.Property(name_fit)', seg)
        fstart = rows.index('<focusedlayout')
        fseg = rows[fstart:rows.index('</focusedlayout>', fstart)]
        self.assertIn('ListItem.Property(name)', fseg)
        self.assertNotIn('ListItem.Property(name_fit)', fseg)
        self.assertIn("li.setProperty('name_fit'", SB)

    def test_focused_row_scrolls_name_and_provider(self):
        rows = SKIN[SKIN.index('<control type="list" id="2000">'):]
        start = rows.index('<focusedlayout')
        seg = rows[start:rows.index('</focusedlayout>', start)]
        self.assertEqual(seg.count('<scroll>true</scroll>'), 2)


class TestContinueArtStyle(unittest.TestCase):
    def _helper_body(self):
        start = PLUGIN.index('def _apply_continue_art_style')
        return PLUGIN[start:PLUGIN.index('\ndef continue_watching(', start)]

    def test_helper_promotes_wide_art(self):
        body = self._helper_body()
        self.assertIn("art.get('landscape') or art.get('fanart')", body)
        self.assertIn("art['banner']", body)

    def test_called_from_both_renderers(self):
        self.assertGreaterEqual(PLUGIN.count('_apply_continue_art_style(art)'), 2)

    def test_setting_and_labels_registered(self):
        self.assertIn('id="continue_art_style"', SETTINGS)
        self.assertIn('lvalues="30854|30855"', SETTINGS)
        for po in ('resources/language/resource.language.ar_sa/strings.po',
                   'resources/language/resource.language.en_gb/strings.po'):
            text = io.open(os.path.join(ROOT, po), encoding='utf-8').read()
            for num in ('30853', '30854', '30855'):
                self.assertIn('msgctxt "#%s"' % num, text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
