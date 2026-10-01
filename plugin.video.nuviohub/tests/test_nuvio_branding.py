"""Protect the unified release and the version users actually see in About."""
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

import kodi_stub
import frontend_test_support
frontend_test_support.install()
ROOT=Path(kodi_stub.ADDON_ROOT).parent
spec=importlib.util.spec_from_file_location('nuvio_bundle_build',ROOT/'review/build_bundle.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BrandingTests(unittest.TestCase):
    def test_mixed_component_release_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for aid in builder.NAMES:
                (root/aid).mkdir()
                (root/aid/'addon.xml').write_bytes((ROOT/aid/'addon.xml').read_bytes())
            self.assertEqual(builder.release_version(root),builder.release_version())
            path=root/'script.nuvio/addon.xml'
            tree=ET.parse(path);tree.getroot().set('version','1.1.6');tree.write(path)
            with self.assertRaisesRegex(ValueError,'same release version'):
                builder.release_version(root)

    def test_stale_dependency_and_old_display_name_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for aid in builder.NAMES:
                (root/aid).mkdir()
                (root/aid/'addon.xml').write_bytes((ROOT/aid/'addon.xml').read_bytes())
            path=root/'script.nuvio/addon.xml';tree=ET.parse(path)
            dependency=tree.find('./requires/import[@addon="plugin.video.nuviohub"]')
            version=dependency.get('version');dependency.set('version','5.4.12.10');tree.write(path)
            with self.assertRaisesRegex(ValueError,'dependency version mismatch'):
                builder.release_version(root)
            dependency.set('version',version);tree.getroot().set('name','Nuvio Hub');tree.write(path)
            with self.assertRaisesRegex(ValueError,'component identity'):
                builder.release_version(root)

    def test_settings_and_about_use_installed_frontend_version(self):
        settings=importlib.import_module('nuvio_ui.settings')
        dialog=mock.Mock()
        def show(title,rows,choose,**kwargs):
            self.assertEqual(rows()[0]['value'],'9.8.7')
            choose(0)
        with mock.patch.object(settings.xbmcaddon,'Addon') as addon, \
             mock.patch.object(settings.xbmcgui,'Dialog',return_value=dialog), \
             mock.patch.object(settings,'nuvio_status',return_value='Not connected'), \
             mock.patch.object(settings.page,'show',side_effect=show):
            addon.return_value.getAddonInfo.return_value='9.8.7'
            settings.maintenance()
        self.assertEqual(dialog.ok.call_args.args[0],'Nuvio 9.8.7')


if __name__=='__main__':unittest.main()
