"""6.0.29: glass cards, shadows, glass focus and buttons, poster transparency, no repeated poster screen."""
import importlib
from pathlib import Path
import re
import sys
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
DEFAULT = ROOT / 'script.nuvio/resources/skins/Default/1080i'
MEDIA = ROOT / 'script.nuvio/resources/media'
theme = importlib.import_module('resources.lib.theme')
startup = importlib.import_module('nuvio_ui.startup')
sys.path.insert(0, str(ROOT / 'review'))
glass = importlib.import_module('make_glass_ui')


class Settings:
    def __init__(self, **values):
        self.values = dict(values)

    def getSetting(self, key):
        return self.values.get(key, '')

    def setSetting(self, key, value):
        self.values[key] = value


def png_size(path):
    data = path.read_bytes()
    return int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')


class GlassAssets(unittest.TestCase):
    def test_assets_ship_and_have_room_for_glow_and_shadow(self):
        for name in ('nuvio_tile_glass.png', 'nuvio_poster_glass.png', 'nuvio_tile_shadow.png', 'nuvio_poster_shadow.png',
                     'nuvio_tile_focus_glass.png', 'nuvio_poster_focus_glass.png', 'nuvio_pill_glass.png',
                     'nuvio_pill_glass_focus.png'):
            self.assertTrue((MEDIA / name).is_file(), name)
        self.assertEqual(png_size(MEDIA / 'nuvio_tile_glass.png'), png_size(MEDIA / 'nuvio_tile_mask_v2.png'))
        self.assertEqual(png_size(MEDIA / 'nuvio_tile_focus_glass.png'), (936 + 24, 537 + 24))
        self.assertEqual(png_size(MEDIA / 'nuvio_tile_shadow.png'), (912 + 36, 513 + 54))
        for name in ('nuvio_pill_glass.png', 'nuvio_pill_glass_focus.png'):
            self.assertTrue((ROOT / 'skin.nuvio/media/nuvio' / name).is_file())


class Windows(unittest.TestCase):
    def test_every_grey_box_became_glass_with_a_shadow_behind(self):
        for path in DEFAULT.glob('*.xml'):
            text = path.read_text(encoding='utf-8')
            self.assertIsNone(glass.BOX.search(text), path.name)
            self.assertIsNone(glass.FOCUS.search(text), path.name)
            self.assertIsNone(glass.PILL_REST.search(text), path.name)
        home = (DEFAULT / 'nuvio_home.xml').read_text(encoding='utf-8')
        for kind in ('tile', 'poster'):
            shadows = [m.start() for m in re.finditer('nuvio_%s_shadow.png' % kind, home)]
            boxes = [m.start() for m in re.finditer('nuvio_%s_glass.png' % kind, home)]
            self.assertEqual(len(shadows), len(boxes))
            self.assertTrue(all(s < b for s, b in zip(shadows, boxes)), 'shadow is drawn first')

    def test_focus_ring_grew_by_the_glow_room(self):
        home = (DEFAULT / 'nuvio_home.xml').read_text(encoding='utf-8')
        block = re.search(r'<left>(\d+)</left>\s*<top>(-?\d+)</top>\s*<width>(\d+)</width>\s*<height>(\d+)</height>\s*'
                          r'<aspectratio>stretch</aspectratio>\s*<texture colordiffuse="FFDBECFF">[^<]*nuvio_tile_focus_glass', home)
        self.assertEqual(tuple(int(v) for v in block.groups()), (2, -2, 320, 187))

    def test_posters_follow_the_transparency_setting(self):
        home = (DEFAULT / 'nuvio_home.xml').read_text(encoding='utf-8')
        art = len(re.findall(r'diffuse="[^"]*nuvio_(?:tile|poster)_mask_v2\.png">', home))
        for key, alpha in (('10', 90), ('20', 80), ('30', 70)):
            line = ('<animation effect="fade" start="%d" end="%d" time="0" condition="String.IsEqual('
                    'Window(Home).Property(nuvio.card_opacity),%s)">Conditional</animation>' % (alpha, alpha, key))
            self.assertEqual(home.count(line), art, key)

    def test_clock_and_weather_sit_on_glass(self):
        for name in ('nuvio_home.xml', 'nuvio_home_compact.xml'):
            text = (DEFAULT / name).read_text(encoding='utf-8')
            self.assertEqual(text.count('Glass capsule behind weather and clock'), 1, name)
            self.assertLess(text.index('Glass capsule'), text.index('System.Time(hh:mm)'))

    def test_hub_buttons_are_glass(self):
        for name in ('Home.xml', 'SkinSettings.xml'):
            text = (ROOT / 'skin.nuvio/xml' / name).read_text(encoding='utf-8')
            self.assertNotIn('nuvio/nuvio_pill.png<', text, name)
            self.assertIn('nuvio/nuvio_pill_glass_focus.png', text, name)

    def test_dark_and_dim_carry_the_glass_look(self):
        for folder in ('Dark', 'Dim'):
            text = (ROOT / 'script.nuvio/resources/skins' / folder / '1080i/nuvio_home.xml').read_text(encoding='utf-8')
            self.assertIn('nuvio_tile_glass.png', text)
            self.assertIn('nuvio.card_opacity', text)


class Transparency(unittest.TestCase):
    def test_default_ten_percent_and_choices(self):
        self.assertEqual(theme.card_opacity(Settings()), '10')
        self.assertEqual(theme.card_opacity(Settings(nuvio_card_opacity='99')), '10')
        props = {}
        with mock.patch('xbmcgui.Window', return_value=SimpleNamespace(setProperty=props.__setitem__)):
            settings = Settings()
            theme.set_card_opacity('0', settings)
            self.assertEqual((settings.values['nuvio_card_opacity'], props['nuvio.card_opacity']), ('0', '0'))
            with self.assertRaises(ValueError):
                theme.set_card_opacity('50', settings)

    def test_sync_publishes_the_level(self):
        props = {}
        with mock.patch('xbmcgui.Window', return_value=SimpleNamespace(setProperty=props.__setitem__)), \
                mock.patch('xbmc.getInfoLabel', return_value='light'), mock.patch('xbmc.getSkinDir', return_value='skin.estuary'):
            theme.sync(Settings(nuvio_card_opacity='20'))
        self.assertEqual(props['nuvio.card_opacity'], '20')

    def test_settings_row(self):
        settings = importlib.import_module('nuvio_ui.settings')
        captured = {}
        def show(title, rows, choose, **kwargs):
            captured['rows'] = rows();captured['choose'] = choose
        dialog = mock.Mock();dialog.select.return_value = 3
        with mock.patch.object(settings.page, 'show', side_effect=show), mock.patch.object(settings, 'rpc', return_value={}), \
                mock.patch.object(settings.xbmcgui, 'Dialog', return_value=dialog), \
                mock.patch.object(theme, 'set_card_opacity') as setter:
            settings.appearance()
            self.assertEqual(captured['rows'][2]['label'], 'Poster and catalog transparency')
            captured['choose'](2)
        self.assertEqual(setter.call_args.args[0], '30')


class NoRepeatedPosterScreen(unittest.TestCase):
    def test_return_from_hub_skips_the_poster_screen(self):
        props = {'nuvio.art_warm.front': 'http://127.0.0.1:9'}
        home = SimpleNamespace(getProperty=lambda k: props.get(k, ''), setProperty=props.__setitem__)
        cache = mock.Mock(lookup_many=lambda keys: {'k': True})
        with mock.patch.object(startup, 'jobs', return_value=[('k', {}, {}, {})]), \
                mock.patch.object(startup.browse_cache, 'instance', return_value=cache), \
                mock.patch.object(startup, 'art_cold', return_value='http://127.0.0.1:9'), \
                mock.patch.object(startup.xbmcgui, 'Window', return_value=home), \
                mock.patch.object(startup, 'Loading') as loading:
            report = startup.prepare()
        loading.assert_not_called()
        self.assertEqual(report['posters'], 0)


if __name__ == '__main__':
    unittest.main()
