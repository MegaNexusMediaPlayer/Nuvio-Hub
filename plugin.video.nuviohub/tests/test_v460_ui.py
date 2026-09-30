# -*- coding: utf-8 -*-
"""v4.6.0 regression tests.

Covers the three user-visible contracts of this release:

1. THEME DISCOVERABILITY — theme_preset (and the other appearance settings)
   live in their own settings category, and the new theme_select action is
   both defined and registered in the dispatcher (a missing router entry is
   a known silent-failure class in this codebase).

2. THE "WHITE SELECTION" FIX — Kodi 22 does not resolve per-item
   $INFO[ListItem.Property(...)] inside <itemlayout>/<focusedlayout>
   colordiffuse; the texture renders raw white and erases the text drawn on
   it. Per-item colour must therefore only ever be expressed as static
   colour layers switched by String.IsEqual on RAW keys (quality_key /
   type_key / pcolor — raw because the display copies pass through
   _bidi_anchor, whose leading LRM breaks String.IsEqual).

3. STABLE PROVIDER IDENTITY COLOURS — one provider = one colour everywhere
   (loading dashboard, result rows, chips strip), derived from the name so
   it survives ordering changes and restarts.
"""
import io
import os
import re
import unittest
import xml.etree.ElementTree as ET

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
skin_theme = kodi_stub.import_lib_module('skin_theme')
sources_loading = kodi_stub.import_lib_module('sources_loading')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()
I18N = io.open(os.path.join(ROOT, 'resources', 'lib', 'i18n.py'), encoding='utf-8').read()
SETTINGS = io.open(os.path.join(ROOT, 'resources', 'settings.xml'), encoding='utf-8').read()
RESULTS_XML_PATH = os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'sources_results.xml')
LOADING_XML_PATH = os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'sources_loading.xml')
RESULTS_XML = io.open(RESULTS_XML_PATH, encoding='utf-8').read()
LOADING_XML = io.open(LOADING_XML_PATH, encoding='utf-8').read()
PO_EN = io.open(os.path.join(ROOT, 'resources', 'language',
                             'resource.language.en_gb', 'strings.po'), encoding='utf-8').read()
PO_AR = io.open(os.path.join(ROOT, 'resources', 'language',
                             'resource.language.ar_sa', 'strings.po'), encoding='utf-8').read()


class _FakeWin(object):
    """Property-recording stand-in for the WindowXMLDialog."""

    def __init__(self):
        self.props = {}

    def setProperty(self, key, value):
        self.props[key] = value

    def getProperty(self, key):
        return self.props.get(key, '')

    def setFocusId(self, *_a):
        pass

    def _push_art_controls(self, *_a, **_k):
        pass


def _dialog_with_fake_win(**kwargs):
    dlg = sources_loading.SourcesLoadingDialog(**kwargs)
    dlg._win = _FakeWin()
    dlg._apply_initial_props()
    return dlg


# ─────────────────────────────────────────────────────────────────────────────
#  1. Theme discoverability
# ─────────────────────────────────────────────────────────────────────────────

class TestThemeDiscoverability(unittest.TestCase):
    def _categories(self):
        return ET.fromstring(SETTINGS).findall('category')

    def test_appearance_category_exists_and_is_early(self):
        labels = [c.get('label') for c in self._categories()]
        self.assertIn('30880', labels)
        # A discoverability fix that hides the category at the end would be
        # no fix at all: it must sit right after the first (General) category.
        self.assertEqual(labels.index('30880'), 1)

    def test_appearance_settings_moved_not_duplicated(self):
        cats = {c.get('label'): c for c in self._categories()}
        appearance_ids = {s.get('id') for s in cats['30880'].findall('setting') if s.get('id')}
        for sid in ('theme_preset', 'home_style', 'search_style', 'continue_art_style'):
            self.assertIn(sid, appearance_ids, sid)
            # exactly once addon-wide — duplicates make Kodi persist one and
            # display the other (a silent-failure class fixed in 4.0.1)
            self.assertEqual(SETTINGS.count('id="%s"' % sid), 1, sid)

    def test_theme_select_action_in_settings(self):
        cats = {c.get('label'): c for c in self._categories()}
        actions = [s.get('action') or '' for s in cats['30880'].findall('setting')]
        self.assertTrue(any('action=theme_select' in a for a in actions))

    def test_theme_select_defined_and_routed(self):
        self.assertIn('def theme_select_action():', PLUGIN)
        # dispatcher registration — the known silent-failure class
        self.assertIn("if action == 'theme_select':", PLUGIN)
        self.assertIn('return theme_select_action()', PLUGIN)

    def test_theme_select_applies_immediately(self):
        body = PLUGIN.split('def theme_select_action():', 1)[1]
        body = body.split('\ndef ', 1)[0]
        self.assertIn("setSetting('theme_preset'", body)
        self.assertIn('publish_theme', body)

    def test_category_label_translated_in_both_po(self):
        for po, name in ((PO_EN, 'en'), (PO_AR, 'ar')):
            self.assertIn('msgctxt "#30880"', po, name)
            self.assertIn('msgctxt "#30881"', po, name)
        self.assertIn('msgstr "المظهر"', PO_AR)
        self.assertIn('msgstr "Appearance"', PO_EN)

    def test_i18n_strings_added_once(self):
        for key in ("'اختيار الثيم'", "'تم تطبيق الثيم: %s'",
                    "'تلقائي (حسب السكين)'", "'بالانتظار'",
                    "'اكتمل'", "'بدون نتائج'",
                    "'(الحالي)'", "'إضافة • %s'"):
            self.assertEqual(I18N.count(key), 1, key)


# ─────────────────────────────────────────────────────────────────────────────
#  2. The "white selection" fix (results window)
# ─────────────────────────────────────────────────────────────────────────────

class TestWhiteSelectionFix(unittest.TestCase):
    def test_results_xml_parses(self):
        ET.parse(RESULTS_XML_PATH)

    def test_no_per_item_info_colordiffuse_anywhere(self):
        """THE regression guard. If this fails, the white-selection bug is
        back: Kodi 22 renders $INFO[ListItem...] colordiffuse as raw white
        inside list layouts."""
        self.assertNotIn('colordiffuse="$INFO[ListItem', RESULTS_XML)
        self.assertNotIn("colordiffuse='$INFO[ListItem", RESULTS_XML)

    def test_old_highlight_binding_fully_gone(self):
        self.assertNotIn('ListItem.Property(highlight)', RESULTS_XML)

    def test_colours_switched_on_raw_keys(self):
        for key in ('quality_key', 'type_key', 'pcolor'):
            self.assertIn('String.IsEqual(ListItem.Property(%s)' % key,
                          RESULTS_XML, key)

    def test_quality_variants_cover_all_python_values(self):
        # _quality_badge returns exactly these five labels
        for value in ('4K', '1080P', '720P', '480P', '--'):
            self.assertIn(
                'String.IsEqual(ListItem.Property(quality_key),%s)' % value,
                RESULTS_XML, value)

    def test_type_chip_variants_match_plugin_styles(self):
        styles = re.search(r'_SOURCE_TYPE_STYLES = \{(.*?)\}', PLUGIN, re.S).group(1)
        pairs = re.findall(r"'(\w+)':\s*\('([A-Z+]+)',\s*'([0-9A-F]{8})'\)", styles)
        self.assertEqual(len(pairs), 6)
        for key, _label, color in pairs:
            self.assertIn(
                'String.IsEqual(ListItem.Property(type_key),%s)' % key,
                RESULTS_XML, key)
            variant = re.search(
                r'colordiffuse="%s">[^<]*circle\.png</texture>'
                r'<visible>String\.IsEqual\(ListItem\.Property\(type_key\),%s\)'
                % (color, key), RESULTS_XML)
            self.assertIsNotNone(variant, '%s chip must be tinted %s' % (key, color))

    def test_raw_keys_set_by_source_browser(self):
        # display copies pass through _bidi_anchor (leading LRM) which breaks
        # String.IsEqual — the raw keys must bypass it
        self.assertIn("li.setProperty('quality_key'", SB)
        self.assertIn("li.setProperty('type_key'", SB)
        self.assertIn("li.setProperty('pcolor'", SB)
        raw_block = SB.split("li.setProperty('quality_key'", 1)[1][:400]
        self.assertNotIn('_bidi_anchor', raw_block)

    def test_focused_row_stays_dark_with_accent_outline(self):
        rows = RESULTS_XML.split('<control type="list" id="2000">', 1)[1]
        focused = rows.split('<focusedlayout', 1)[1].split('</focusedlayout>')[0]
        # dark card, not a light fill
        self.assertIn('F2151B29', focused)
        # accent outline strips driven by HOME window props (those DO resolve)
        self.assertGreaterEqual(
            focused.count('$INFO[Window(Home).Property(dexhub.theme.accent)]'), 4)


# ─────────────────────────────────────────────────────────────────────────────
#  3. Stable provider identity colours
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderColours(unittest.TestCase):
    def test_palette_is_eight_valid_argb(self):
        self.assertEqual(len(skin_theme.PROVIDER_PALETTE), 8)
        for col in skin_theme.PROVIDER_PALETTE:
            self.assertRegex(col, r'^FF[0-9A-F]{6}$')

    def test_index_deterministic_case_insensitive_in_range(self):
        for name in ('Dexstreams', 'Arabmedia', 'Plexio (ARPX)', 'DexWorld Pro'):
            idx = skin_theme.provider_color_index(name)
            self.assertTrue(1 <= idx <= 8, name)
            self.assertEqual(idx, skin_theme.provider_color_index(name.upper()))
            self.assertEqual(skin_theme.provider_color(name),
                             skin_theme.PROVIDER_PALETTE[idx - 1])
        self.assertEqual(skin_theme.provider_color_index(''), 1)

    def _assert_palette_wired(self, xml_text, prop_expr, label):
        for i, col in enumerate(skin_theme.PROVIDER_PALETTE, start=1):
            pat = (r'colordiffuse="%s">[^<]*(?:white|circle)\.png</texture>'
                   r'<visible>String\.IsEqual\(%s\),%d\)' % (col, prop_expr, i))
            self.assertIsNotNone(re.search(pat, xml_text),
                                 '%s: slot %d must be %s' % (label, i, col))

    def test_results_rows_use_palette_by_pcolor(self):
        self._assert_palette_wired(RESULTS_XML, r'ListItem\.Property\(pcolor',
                                   'results row bar')

    def test_results_chips_use_palette_by_coloridx(self):
        # v4.6.1: the chips are a real horizontal list (2300); identity dots
        # switch on the RAW ListItem coloridx like every other per-item colour.
        self._assert_palette_wired(RESULTS_XML,
                                   r'ListItem\.Property\(coloridx',
                                   'chip dot')

    def test_loading_cards_use_palette_by_coloridx(self):
        self._assert_palette_wired(LOADING_XML, r'Window\.Property\(pv1_coloridx',
                                   'loading card 1 bar')


# ─────────────────────────────────────────────────────────────────────────────
#  Loading dashboard (cards model + XML contract)
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadingDashboard(unittest.TestCase):
    def test_loading_xml_parses_and_keeps_control_contract(self):
        ET.parse(LOADING_XML_PATH)
        for cid in ('id="9000"', 'id="9001"', 'id="9002"',
                    'id="5101"', 'id="5102"', 'id="5103"'):
            self.assertIn(cid, LOADING_XML, cid)

    def test_loading_xml_binds_every_card_slot(self):
        """v5.4.6: the dashboard shows six cards, not eight — each card costs
        ~15 skin expressions that Kodi re-evaluates while providers are still
        answering, and a real setup runs four to six. The contract is that the
        skin and _CARD_SLOTS agree, and that pv_more still reports overflow."""
        import kodi_stub as _ks
        mod = _ks.import_lib_module('sources_loading')
        slots = sorted({int(n) for n in re.findall(r'pv(\d)_name', LOADING_XML)})
        self.assertEqual(slots, list(range(1, mod.SourcesLoadingDialog._CARD_SLOTS + 1)))
        for slot in slots:
            for suffix in ('_name', '_count', '_state', '_coloridx'):
                self.assertIn('pv%d%s' % (slot, suffix), LOADING_XML,
                              'slot %d missing %s' % (slot, suffix))
        self.assertIn('pv_more', LOADING_XML)

    def test_cards_prepopulate_as_waiting(self):
        dlg = _dialog_with_fake_win(title='t',
                                    provider_names=['Dexstreams', 'Arabmedia'])
        p = dlg._win.props
        self.assertEqual(p['pv1_name'], 'Dexstreams')
        self.assertEqual(p['pv1_state'], 'wait')
        self.assertEqual(p['pv1_count'], '')
        self.assertEqual(p['pv2_name'], 'Arabmedia')
        self.assertEqual(p['pv3_name'], '')
        self.assertEqual(p['pv1_coloridx'],
                         str(skin_theme.provider_color_index('Dexstreams')))

    def test_update_marks_provider_done_and_zero_when_empty(self):
        dlg = _dialog_with_fake_win(title='t',
                                    provider_names=['Dexstreams', 'Arabmedia'])
        # iter_parallel yields a provider when it FINISHED answering
        dlg.update(provider_name='Arabmedia', index=1)
        self.assertEqual(dlg._win.props['pv2_state'], 'zero')  # done, 0 results
        dlg.add_results(3, provider_name='Dexstreams')
        self.assertEqual(dlg._win.props['pv1_state'], 'done')
        self.assertEqual(dlg._win.props['pv1_count'], '3')
        dlg.add_results(2, provider_name='Dexstreams')
        self.assertEqual(dlg._win.props['pv1_count'], '5')

    def test_unknown_provider_appends_and_overflow_counts(self):
        names = ['P%d' % i for i in range(1, 9)]
        dlg = _dialog_with_fake_win(title='t', provider_names=names)
        dlg.add_results(1, provider_name='Latecomer')
        # 9 providers, 6 card slots -> the first six are shown, +3 noted
        slots = sources_loading.SourcesLoadingDialog._CARD_SLOTS
        self.assertEqual(dlg._win.props['pv_more'], '+%d' % (9 - slots))
        self.assertEqual(dlg._win.props['pv%d_name' % slots], 'P%d' % slots)
        # nothing is published beyond the last slot
        self.assertNotIn('pv%d_name' % (slots + 1), dlg._win.props)

    def test_provider_count_derived_from_names_when_omitted(self):
        dlg = sources_loading.SourcesLoadingDialog(title='t',
                                                   provider_names=['A', 'B', 'C'])
        self.assertEqual(dlg._provider_count, 3)

    def test_both_plugin_call_sites_pass_names(self):
        self.assertEqual(PLUGIN.count('provider_names=_loader_names'), 2)


# ─────────────────────────────────────────────────────────────────────────────
#  Results chips strip (Nuvio-style)
# ─────────────────────────────────────────────────────────────────────────────

class TestResultsChips(unittest.TestCase):
    """v4.6.1: interactive top-level-addon chips (list 2300)."""

    def test_builder_defined_and_wired_into_apply_filter(self):
        self.assertIn('def _build_provider_chips(self):', SB)
        apply_body = SB.split('def _apply_filter(self, filter_value):', 1)[1]
        apply_body = apply_body.split('\n    def ', 1)[0]
        self.assertIn('self._build_provider_chips()', apply_body)

    def test_chips_group_on_top_level_addon_not_inner_scraper(self):
        # the 4.6.0 strip aggregated on row['addon'] and produced six
        # near-identical "EASYNEWS SEARCH …" chips; grouping is provider-level
        self.assertIn('def _row_group_name(row):', SB)
        body = SB.split('def _build_provider_chips(self):', 1)[1].split('\n    def ', 1)[0]
        self.assertIn('_row_group_name(row)', body)
        self.assertNotIn("row.get('addon')", body)

    def test_chip_click_applies_and_toggles_v_filter(self):
        self.assertIn("elif controlId == 2300:", SB)
        self.assertIn('def _apply_chip_filter(self):', SB)
        body = SB.split('def _apply_chip_filter(self):', 1)[1].split('\n    def ', 1)[0]
        self.assertIn("target = 'ALL'", body)           # re-select toggles off

    def test_v_filter_machinery_complete(self):
        # missing any one of these is the silent-failure class: chips render
        # but do nothing, or a live-session refresh resets the filter to ALL
        self.assertIn("startswith('V:')", SB)
        self.assertIn('def _row_group_filter(row):', SB)
        build = SB.split('def _build_filters(self):', 1)[1].split('\n    def ', 1)[0]
        self.assertIn('_row_group_filter(row)', build)
        self.assertIn("tr('إضافة • %s')", SB)

    def test_xml_list_2300_exists_with_nav_and_states(self):
        self.assertIn('<control type="list" id="2300">', RESULTS_XML)
        # nav chain: pill → chips → rows
        self.assertIn('<onup>2200</onup><ondown>2300</ondown>', RESULTS_XML)
        self.assertIn('<onup>2300</onup><ondown>2000</ondown><onleft>2100</onleft>',
                      RESULTS_XML)
        # applied-filter underline is per-item and focus-independent
        self.assertIn('String.IsEqual(ListItem.Property(active),1)', RESULTS_XML)
        # old window-prop strip fully gone
        self.assertNotIn('dexhub.results.pv1_label', RESULTS_XML)


class TestFanartForwardAndLayout(unittest.TestCase):
    """v4.6.1: full-bleed art behind both windows; ratings moved up."""

    def test_results_backdrop_fanart_forward(self):
        self.assertIn('end="100" time="600"', RESULTS_XML)   # fanart full fade
        self.assertIn('82000000', RESULTS_XML)               # lighter global dim
        self.assertIn('EE0A0E16', RESULTS_XML)               # stronger row panel

    def test_loading_backdrop_fanart_forward(self):
        # v4.6.2: the left scrim block drew a hard vertical seam across the
        # art — gone. One soft veil + the shelf gradient only.
        self.assertNotIn('9A030A12', LOADING_XML)
        self.assertNotIn('E60A101B', LOADING_XML)            # boxed panel gone
        self.assertIn('60000000', LOADING_XML)               # single soft veil

    def test_loading_identity_is_banner_sized(self):
        self.assertIn('<left>70</left><top>96</top><width>900</width><height>240</height>',
                      LOADING_XML)                           # big clearlogo
        self.assertIn('<font>font24</font>', LOADING_XML)    # big title fallback

    def test_ratings_single_row_and_plot_clear_of_chips(self):
        # v4.6.2: ONE ratings row (all nine chips inline, row-2 group gone)
        # at 152; the plot sits at 206 — the 4.6.1 layout put the plot at the
        # chips' exact Y (title-group 284 = absolute 394 vs chips at 390).
        self.assertIn('<left>2</left><top>152</top><width>1400</width><height>48</height>',
                      RESULTS_XML)
        self.assertNotIn('Ratings row 2', RESULTS_XML)
        for x in ('970', '1130', '1290'):
            self.assertIn('<left>%s</left>' % x, RESULTS_XML)
        self.assertIn('<left>0</left><top>206</top><width>1020</width><height>70</height>',
                      RESULTS_XML)
        self.assertNotIn('<top>284</top><width>1020</width>', RESULTS_XML)

    def test_chip_focus_is_filled_pill_and_active_wash(self):
        # v4.6.2: focused chip = accent-filled pill with DARK text (the thin
        # outline read as a bare rectangle); applied filter keeps the
        # underline plus a soft accent wash in the idle layout.
        chips = RESULTS_XML.split('<control type="list" id="2300">', 1)[1]
        chips = chips.split('</control>\n\n', 1)[0]
        focused = chips.split('<focusedlayout', 1)[1]
        self.assertIn('border="19" colordiffuse="$INFO[Window(Home).Property(dexhub.theme.accent)]"',
                      focused)
        self.assertIn('<textcolor>FF12141C</textcolor>', focused)
        item = chips.split('<focusedlayout', 1)[0]
        self.assertIn('dexhub.theme.accent_dim', item)

    def test_poster_modern_card(self):
        # real rounded corners: the poster texture carries a diffuse alpha
        # mask; shadow + theme glow behind it; the flat grey plate is gone.
        # v4.6.4: circle.png's radius STRETCHES with the target size and
        # rendered posters as ovals — a fixed-size 340x510 mask replaces it.
        self.assertIn('diffuse="special://home/addons/plugin.video.nuviohub/resources/media/poster_mask.png"',
                      RESULTS_XML)
        self.assertNotIn('diffuse="special://home/addons/plugin.video.nuviohub/resources/media/circle.png"',
                         RESULTS_XML)
        self.assertNotIn('Subtle amber outline shadow', RESULTS_XML)

    def test_drawer_header_fixed_geometry(self):
        # the FILTERS label had no width/height and rendered mid-list
        self.assertIn('<left>48</left><top>134</top><width>290</width><height>38</height>',
                      RESULTS_XML)


class TestProgressBarAndGlyphs(unittest.TestCase):
    def test_progress_bar_is_hand_drawn(self):
        """Kodi's <progress> caps render at raw texture size and ignore the
        transparent diffuse — the 4.6.0 full-width bar AND the 4.6.1 white
        block. The bar is now rail + fill images; sources_loading.py drives
        the fill width (control 5110) at init, update and finish."""
        self.assertNotIn('<control type="progress">', LOADING_XML)
        self.assertIn('id="5110"', LOADING_XML)
        self.assertIn('colordiffuse="9A333B4A"', LOADING_XML)   # rail
        sl = io.open(os.path.join(ROOT, 'resources', 'lib', 'sources_loading.py'),
                     encoding='utf-8').read()
        self.assertIn('def _set_progress_width(self, pct):', sl)
        self.assertEqual(sl.count('self._set_progress_width('), 3)
        self.assertIn('getControl(5110).setWidth', sl)

    def test_no_duplicate_enough_banner(self):
        # mark_sufficient writes the message into status; the extra green
        # banner doubled it on screen.
        self.assertNotIn('Window.Property(enough_label)]', LOADING_XML)

    def test_no_tofu_pictographs_anywhere(self):
        """The active skin font lacks these glyphs — they rendered as boxes."""
        for glyph, name in (('\u2713', 'check mark'), ('\u25c0', 'left arrow'),
                            ('\u2b24', 'big dot'), ('\u25d4', 'quarter dot')):
            for blob, where in ((RESULTS_XML, 'results xml'),
                                (LOADING_XML, 'loading xml'),
                                (SB, 'source_browser'),):
                self.assertNotIn(glyph, blob, '%s in %s' % (name, where))
        picker = PLUGIN.split('def theme_select_action():', 1)[1].split('\ndef ', 1)[0]
        for glyph in ('\u2713', '\u2b24', '\u25d4'):
            self.assertNotIn(glyph, picker)
        # the NAME itself is now the colour swatch
        self.assertIn("'[COLOR %s][B]%s[/B][/COLOR]'", picker)


class TestReleaseMeta(unittest.TestCase):
    def test_version_bumped_with_news(self):
        addon = io.open(os.path.join(ROOT, 'addon.xml'), encoding='utf-8').read()
        self.assertIn('version="5.4.12.2"', addon)
        self.assertIn('v5.4.12', addon.split('<news>', 1)[1][:80])


if __name__ == '__main__':
    unittest.main(verbosity=2)
