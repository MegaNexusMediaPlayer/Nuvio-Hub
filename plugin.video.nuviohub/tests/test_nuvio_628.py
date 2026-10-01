"""6.0.28: Light / Dark (OLED) / Semi-dark themes; catalog card boxes keep their original colour."""
import importlib
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
SKINS = ROOT / 'script.nuvio/resources/skins'
theme = importlib.import_module('resources.lib.theme')
sys.path.insert(0, str(ROOT / 'review'))
variants = importlib.import_module('make_theme_variants')


class Settings:
    def __init__(self, **values):
        self.values = dict(values)

    def getSetting(self, key):
        return self.values.get(key, '')

    def setSetting(self, key, value):
        self.values[key] = value


class ThemeModule(unittest.TestCase):
    def test_light_is_the_default_and_folders_banners_match(self):
        self.assertEqual(theme.current(Settings()), 'light')
        self.assertEqual(theme.current(Settings(nuvio_theme='bogus')), 'light')
        for key, folder in (('light', 'Default'), ('dark', 'Dark'), ('dim', 'Dim')):
            settings = Settings(nuvio_theme=key)
            self.assertEqual(theme.folder(settings), folder)
            self.assertTrue((SKINS / folder / '1080i/nuvio_home.xml').is_file())
            banner = theme.banner(settings).replace('special://home/addons/', '')
            self.assertTrue((ROOT / banner).is_file(), banner)

    def test_apply_sets_the_setting_skin_string_and_skin_colours(self):
        settings = Settings()
        builtins, rpcs = [], []
        with mock.patch.object(theme, '_rpc', side_effect=lambda m, p: rpcs.append((m, p)) or {'value': 'SKINDEFAULT'}), \
                mock.patch('xbmc.executebuiltin', side_effect=builtins.append), \
                mock.patch('xbmc.getInfoLabel', return_value='light'), \
                mock.patch('xbmc.getSkinDir', return_value='skin.nuvio'):
            theme.apply('dark', settings)
        self.assertEqual(settings.values['nuvio_theme'], 'dark')
        self.assertIn('Skin.SetString(nuvio.theme,dark)', builtins)
        self.assertIn(('Settings.SetSettingValue', {'setting': 'lookandfeel.skincolors', 'value': 'dark'}), rpcs)
        with self.assertRaises(ValueError):
            theme.apply('purple', settings)

    def test_other_skins_are_not_touched(self):
        rpcs = []
        with mock.patch.object(theme, '_rpc', side_effect=lambda m, p: rpcs.append(m)), \
                mock.patch('xbmc.executebuiltin'), mock.patch('xbmc.getInfoLabel', return_value=''), \
                mock.patch('xbmc.getSkinDir', return_value='skin.estuary'):
            theme.sync(Settings(nuvio_theme='dim'))
        self.assertEqual(rpcs, [])


class Variants(unittest.TestCase):
    def test_generated_variants_are_up_to_date(self):
        with tempfile.TemporaryDirectory() as temp:
            out, colors = Path(temp) / 'skins', Path(temp) / 'colors'
            colors.mkdir()
            variants.build(out, colors)
            for folder in ('Dark', 'Dim'):
                for path in sorted((out / folder / '1080i').glob('*.xml')):
                    committed = SKINS / folder / '1080i' / path.name
                    self.assertEqual(committed.read_text(encoding='utf-8'), path.read_text(encoding='utf-8'),
                                     'run review/make_theme_variants.py (%s/%s)' % (folder, path.name))
            for name in ('dark.xml', 'dim.xml'):
                self.assertEqual((ROOT / 'skin.nuvio/colors' / name).read_text(encoding='utf-8'),
                                 (colors / name).read_text(encoding='utf-8'))

    def test_dark_has_no_blue_background_and_dim_a_blue_bottom(self):
        dark = (SKINS / 'Dark/1080i/nuvio_home.xml').read_text(encoding='utf-8')
        self.assertNotIn('FF040F22', dark)
        self.assertIn('nuvio_banner_dark.png', (SKINS / 'Dark/1080i/nuvio_phone_setup.xml').read_text(encoding='utf-8'))
        self.assertIn('meganexus_saver_bg_dark.png', (SKINS / 'Dark/1080i/nuvio_screensaver.xml').read_text(encoding='utf-8'))
        dim = (SKINS / 'Dim/1080i/nuvio_home.xml').read_text(encoding='utf-8')
        self.assertIn('colordiffuse="%s">special://home/addons/script.nuvio/resources/media/nuvio_bottom_fade.png' % variants.BOTTOM_BLUE, dim)
        self.assertIn('meganexus_saver_bg_dim.png', (SKINS / 'Dim/1080i/nuvio_screensaver.xml').read_text(encoding='utf-8'))

    def test_catalog_card_boxes_keep_the_original_colour_in_every_theme(self):
        for folder in ('Default', 'Dark', 'Dim'):
            for name in ('nuvio_home.xml', 'nuvio_home_compact.xml'):
                text = (SKINS / folder / '1080i' / name).read_text(encoding='utf-8')
                colours = set(re.findall(r'colordiffuse="([0-9A-F]{8})">special://home/addons/script\.nuvio/resources/media/nuvio_(?:tile|poster)_mask', text))
                self.assertEqual(colours, {'FF202532'}, (folder, name))

    def test_hero_gradients_follow_the_theme_background(self):
        for folder, colour in (('Default', 'FF040F22'), ('Dark', 'FF000000'), ('Dim', 'FF000000')):
            text = (SKINS / folder / '1080i/nuvio_home.xml').read_text(encoding='utf-8')
            found = set(re.findall(r'colordiffuse="([0-9A-F]{8})">special://home/addons/script\.nuvio/resources/media/nuvio_hero_(?:shade|fade)', text))
            self.assertEqual(found, {colour}, folder)

    def test_all_variant_xml_parses(self):
        for folder in ('Dark', 'Dim'):
            files = sorted((SKINS / folder / '1080i').glob('*.xml'))
            self.assertEqual(len(files), len(list((SKINS / 'Default/1080i').glob('*.xml'))))
            for path in files:
                ET.parse(path)


class Wiring(unittest.TestCase):
    def test_every_window_opens_in_the_theme_folder(self):
        for path in (ROOT / 'script.nuvio/nuvio_ui').glob('*.py'):
            text = path.read_text(encoding='utf-8')
            self.assertIsNone(re.search(r"'Default',\s*'1080i'", text), path.name)

    def test_settings_theme_row(self):
        settings = importlib.import_module('nuvio_ui.settings')
        captured = {}
        def show(title, rows, choose, **kwargs):
            captured['rows'] = rows();captured['choose'] = choose
        dialog = mock.Mock();dialog.select.return_value = 2
        with mock.patch.object(settings.page, 'show', side_effect=show), \
                mock.patch.object(settings, 'rpc', return_value={}), \
                mock.patch.object(settings.xbmcgui, 'Dialog', return_value=dialog), \
                mock.patch.object(theme, 'apply') as apply:
            settings.appearance()
            self.assertEqual(captured['rows'][1]['label'], 'Theme')
            self.assertIsNone(captured['choose'](1))
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[0], 'dim')

    def test_phone_display_applies_the_theme(self):
        phone = importlib.import_module('resources.lib.phone_setup')
        settings = Settings(nuvio_theme='light')
        with mock.patch.object(phone, '_addon', return_value=settings), mock.patch.object(theme, 'apply') as apply:
            phone._apply_display({'theme': 'dark'})
            phone._apply_display({'theme': 'neon'})
        apply.assert_called_once_with('dark', settings)
        page = (ROOT / 'plugin.video.nuviohub/resources/phone_setup/index.html').read_text(encoding='utf-8')
        self.assertIn("['dark', 'Dark (OLED)']", page)

    def test_hub_skin_shows_the_theme_banner_and_colours(self):
        home = (ROOT / 'skin.nuvio/xml/Home.xml').read_text(encoding='utf-8')
        for banner in ('nuvio_banner.png', 'nuvio_banner_dark.png', 'nuvio_banner_dim.png'):
            self.assertIn('nuvio/' + banner, home)
            self.assertTrue((ROOT / 'skin.nuvio/media/nuvio' / banner).is_file())
        self.assertNotIn('FF092554', home)
        for name in ('defaults.xml', 'dark.xml', 'dim.xml'):
            names = {c.get('name') for c in ET.parse(ROOT / 'skin.nuvio/colors' / name).getroot()}
            self.assertTrue({'nuvio_pill', 'nuvio_bg'} <= names, name)

    def test_screensaver_uses_the_theme_banner(self):
        source = (ROOT / 'script.nuvio/nuvio_ui/saver.py').read_text(encoding='utf-8')
        self.assertIn("addon.getSetting('nuvio_screensaver_art') or theme.banner(addon)", source)


if __name__ == '__main__':
    unittest.main()
