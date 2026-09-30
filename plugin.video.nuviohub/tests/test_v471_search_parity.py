# -*- coding: utf-8 -*-
"""v4.7.1 — Stremio-parity catalog search + Dex Crimson default.

The addon search kept returning alphabetical "letter A" results because
every search request attached an UNDECLARED `limit` prop to the extra
path segment. stremio-core only ever sends catalog-DECLARED extras;
strict addon routers that see an unknown prop miss the search handler
and fall through to the unfiltered catalog — on the very addons that
search perfectly inside Stremio itself. Five call sites carried the
stray prop; all now send declared extras only.
"""
import io
import os
import re
import unittest

import kodi_stub

ROOT = kodi_stub.ADDON_ROOT
client = kodi_stub.import_lib_module('dexhub.client')
PLUGIN = io.open(os.path.join(ROOT, 'resources', 'lib', 'plugin.py'), encoding='utf-8').read()


class TestDeclaredExtrasOnly(unittest.TestCase):
    def test_no_search_call_carries_limit(self):
        """THE regression guard for the letter-A results."""
        self.assertIsNone(re.search(r"'search':\s*query[^\n]*'limit'", PLUGIN))
        self.assertIsNone(re.search(r"'limit'[^\n]*'search':\s*query", PLUGIN))

    def test_all_five_sites_send_search_alone(self):
        self.assertGreaterEqual(PLUGIN.count("extra={'search': query}"), 4)
        self.assertIn("extra.update({'search': query})", PLUGIN)

    def test_browse_pagination_untouched(self):
        # limit-only browse paging is NuvioHub-internal and stays
        self.assertIn("extra = {'limit': str(page_size)}", PLUGIN)


class TestResourceUrlShape(unittest.TestCase):
    """The extra segment must be the exact Stremio path shape:
    /catalog/{type}/{id}/search=<encoded>.json"""

    PROVIDER = {'manifest_url': 'https://addon.example/stremio/manifest.json'}

    def test_search_extra_path_segment(self):
        url = client.build_resource_url(
            self.PROVIDER, 'catalog', 'movie', 'top',
            extra={'search': 'hello world'})
        self.assertTrue(url.endswith('/catalog/movie/top/search=hello%20world.json'), url)
        self.assertNotIn('?', url)

    def test_arabic_query_percent_encoded(self):
        url = client.build_resource_url(
            self.PROVIDER, 'catalog', 'series', 'top',
            extra={'search': 'مسلسل'})
        seg = url.rsplit('/', 1)[1]
        self.assertTrue(seg.startswith('search=%D9%85'), seg)
        self.assertTrue(seg.endswith('.json'))

    def test_manifest_query_survives_after_json(self):
        provider = {'manifest_url': 'https://addon.example/manifest.json?key=abc'}
        url = client.build_resource_url(provider, 'catalog', 'movie', 'top',
                                        extra={'search': 'x'})
        self.assertIn('/search=x.json?key=abc', url)


class TestDexCrimsonDefault(unittest.TestCase):
    def test_settings_default_is_preset_one(self):
        import xml.etree.ElementTree as ET
        d = {s.get('id'): s.get('default')
             for s in ET.parse(os.path.join(ROOT, 'resources', 'settings.xml')
                               ).getroot().iter('setting')}
        self.assertEqual(d['theme_preset'], '1')

    def test_preset_one_is_dex_crimson(self):
        skin_theme = kodi_stub.import_lib_module('skin_theme')
        preset = skin_theme.THEME_PRESETS['1']
        self.assertEqual(preset['name'], 'Dex Crimson')
        self.assertEqual(preset['accent'], 'FFE0314A')


if __name__ == '__main__':
    unittest.main(verbosity=2)
