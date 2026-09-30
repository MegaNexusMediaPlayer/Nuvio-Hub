# -*- coding: utf-8 -*-
"""v4.4.0/v4.5.1 regression tests — theme presets, the classic-only sources
look (v4.5.1 reverted the fanart composition entirely; Theme E is the addon
default), live search summary, and the opt-in XML home."""
import io
import os
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
skin_theme = kodi_stub.import_lib_module('skin_theme')

PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()
SB = io.open(os.path.join(ROOT, 'resources', 'lib', 'source_browser.py'), encoding='utf-8').read()
SKIN = io.open(os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'sources_results.xml'), encoding='utf-8').read()
SETTINGS = io.open(os.path.join(ROOT, 'resources', 'settings.xml'), encoding='utf-8').read()
HOME_XML = os.path.join(ROOT, 'resources', 'skins', 'Default', '1080i', 'dexhub_home.xml')


class TestThemePresets(unittest.TestCase):
    def test_six_presets_defined(self):
        self.assertEqual(set(skin_theme.THEME_PRESETS), {'1', '2', '3', '4', '5', '6'})

    def test_preset_palette_overrides_surfaces(self):
        pal = skin_theme._preset_palette('2')
        self.assertEqual(pal['accent'], 'FF22D3EE')
        self.assertEqual(pal['surface'], 'FF070B14')
        self.assertIn('accent_dim', pal)  # derived tokens still present

    def test_auto_remains_default_resolution(self):
        _pal, _skin, source = skin_theme.resolve_palette()
        self.assertNotIn('preset', source)  # setting stub returns '' → auto

    def test_glass_token_published(self):
        # Token still derived for future skins, but the classic sources skin
        # must not consume it (solid surface_card rows only).
        self.assertIn("card_glass", io.open(os.path.join(ROOT, 'resources', 'lib', 'skin_theme.py'), encoding='utf-8').read())
        self.assertNotIn('card_glass', SKIN)


class TestClassicOnlyLook(unittest.TestCase):
    """v4.5.1: the 4.3.2 classic composition is the one and only sources look."""

    def test_look_machinery_fully_removed(self):
        self.assertNotIn('dexhub.look', SKIN)
        self.assertNotIn('dexhub.look', SB)
        self.assertNotIn('sources_look', SETTINGS)

    def test_single_heavy_dim_and_unconditional_poster(self):
        # v4.6.1: fanart-forward backdrop per user request — full-bleed art
        # with a LIGHTER global dim (82); readability moves to the solid
        # panel behind the rows. Still exactly one full-screen dim layer.
        self.assertIn('82000000', SKIN)
        self.assertNotIn('DB000000', SKIN)   # the 4.6.0 heavy dim is gone
        self.assertNotIn('C0000000', SKIN)
        self.assertNotIn('6E000000', SKIN)   # fanart light dim is gone
        self.assertNotIn('<animation', SKIN.split('<controls>')[-1].split('>')[0])

    def test_dex_crimson_is_addon_default(self):
        # v4.7.1 user decision: Dex Crimson (preset 1) is the brand default
        # (was Amber Cinema through 4.4-4.7.0).
        seg = SETTINGS.split('id="theme_preset"')[1][:220]
        self.assertIn('default="1"', seg)

    def test_search_style_default(self):
        # v4.7.0 release decision: the rebuilt cinematic search IS the
        # headline feature, so it ships as the default (was classic in
        # 4.4-4.6). Classic remains one toggle away in Appearance.
        seg = SETTINGS.split('id="search_style"')[1][:220]
        self.assertIn('default="0"', seg)


class TestSearchSummary(unittest.TestCase):
    def test_browser_builds_summary_from_row_list(self):
        self.assertIn("dexhub.search.summary", SB)
        self.assertIn("provider_name", SB.split('dexhub.search.summary')[0][-1200:])

    def test_skin_renders_summary_strip(self):
        self.assertIn('Window.Property(dexhub.search.summary)', SKIN)


class TestXmlHome(unittest.TestCase):
    def test_payload_reuses_continue_pipeline(self):
        start = PLUGIN.index('def _home_payload')
        body = PLUGIN[start:PLUGIN.index('\ndef home_xml(', start)]
        for probe in ('list_continue_items', "action='cw_resume'",
                      '_cw_target_key', '_apply_continue_art_style'):
            self.assertIn(probe, body)
        # v4.4.1: the art filler can reach the network — banned from home.
        self.assertNotIn('_lazy_fill_row_art', body)
