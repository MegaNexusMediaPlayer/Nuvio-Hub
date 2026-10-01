"""6.0.25: no "Welcome to Nuvio"; the settings focus bar is blue."""
import colorsys
from pathlib import Path
import re
import unittest
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
SHIPPED = ('plugin.video.nuviohub', 'script.nuvio', 'skin.nuvio', 'screensaver.nuvio')


class Wording(unittest.TestCase):
    def test_no_nuvio_welcome_or_setup_titles(self):
        found = []
        for component in SHIPPED:
            for path in (ROOT / component).rglob('*'):
                if path.suffix not in ('.py', '.xml', '.po', '.html') or 'tests' in path.parts:
                    continue
                text = path.read_text(encoding='utf-8', errors='ignore')
                for phrase in ('Welcome to Nuvio', "'Nuvio setup'"):
                    if phrase in text:
                        found.append((str(path.relative_to(ROOT)), phrase))
        self.assertEqual(found, [])

    def test_welcome_texts_say_meganexus(self):
        self.assertIn("'Welcome to MegaNexus'", (ROOT / 'script.nuvio/nuvio_ui/home_window.py').read_text(encoding='utf-8'))
        self.assertIn('Welcome to MegaNexus — start setup', (ROOT / 'plugin.video.nuviohub/resources/lib/plugin.py').read_text(encoding='utf-8'))


class SettingsFocus(unittest.TestCase):
    def test_settings_focus_bar_is_blue(self):
        xml = (ROOT / 'script.nuvio/resources/skins/Default/1080i/nuvio_settings.xml').read_text(encoding='utf-8')
        for alpha, rgb in re.findall(r'colordiffuse="([0-9A-Fa-f]{2})([0-9A-Fa-f]{6})"', xml):
            r, g, b = (int(rgb[i:i + 2], 16) / 255 for i in (0, 2, 4))
            h, l, s = colorsys.rgb_to_hls(r, g, b)
            self.assertFalse(235 <= h * 360 <= 300 and s > 0.12, rgb)


if __name__ == '__main__':
    unittest.main()
