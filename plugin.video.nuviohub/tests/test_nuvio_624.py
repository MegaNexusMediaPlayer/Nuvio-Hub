"""6.0.24: MegaNexus License for own code; third-party licenses kept."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
OWN = ('plugin.video.nuviohub', 'script.nuvio', 'screensaver.nuvio', 'repository.meganexus')


class License(unittest.TestCase):
    def test_root_license_reserves_rights_and_lists_third_party_parts(self):
        text = (ROOT / 'LICENSE.md').read_text(encoding='utf-8')
        self.assertIn('All rights reserved', text)
        self.assertIn('without prior written permission', text)
        self.assertIn('GPL-2.0', text)
        self.assertIn('python-qrcode', text)
        self.assertIn('up to and including 6.0.23 were published under the MIT license', text)

    def test_own_components_carry_the_meganexus_license(self):
        for component in OWN:
            text = (ROOT / component / 'LICENSE.txt').read_text(encoding='utf-8')
            self.assertTrue(text.startswith('MegaNexus License'), component)
            self.assertNotIn('Permission is hereby granted, free of charge', text, component)
            license = ET.parse(ROOT / component / 'addon.xml').getroot().find('.//license').text
            self.assertIn('MegaNexus License', license, component)

    def test_skin_keeps_estuary_gpl(self):
        self.assertIn('GNU General Public License', (ROOT / 'skin.nuvio/LICENSE.txt').read_text(encoding='utf-8'))
        self.assertTrue((ROOT / 'skin.nuvio/resources/licenses/GPL-2.0.txt').is_file())
        license = ET.parse(ROOT / 'skin.nuvio/addon.xml').getroot().find('.//license').text
        self.assertIn('GPL-2.0', license)

    def test_bundled_qrcode_keeps_its_bsd_notice(self):
        text = (ROOT / 'plugin.video.nuviohub/resources/lib/qrcode/LICENSE').read_text(encoding='utf-8')
        self.assertIn('Lincoln Loop', text)
        self.assertIn('Redistributions of source code must retain', text)


if __name__ == '__main__':
    unittest.main()
