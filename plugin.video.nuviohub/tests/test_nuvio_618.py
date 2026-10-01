"""6.0.18: no hidden dialogs behind settings, poster preload, Configure page, sleep."""
import importlib
from pathlib import Path
import unittest
from unittest import mock
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import frontend_test_support
frontend_test_support.install()
import kodi_stub

ROOT = Path(kodi_stub.ADDON_ROOT).parent
page = importlib.import_module('nuvio_ui.settings_page')


class SettingsDialogsNeverHidden(unittest.TestCase):
    def window(self, rows, choose):
        win = page.SettingsPage(title='T', rows=lambda: rows, choose=choose)
        win._rendered_rows = rows
        win.getControl = lambda cid: SimpleNamespace(getSelectedPosition=lambda: self.position)
        win.refresh = mock.Mock()
        win.close = mock.Mock()
        win.child = mock.Mock(side_effect=lambda fn, *a, **k: fn(*a, **k))
        return win

    def test_row_that_may_open_kodi_dialogs_runs_with_the_page_hidden(self):
        self.position = 0
        win = self.window([page.item('Collections'), page.item('Back')], lambda i: None)
        win.onClick(500)
        win.drain_events()
        win.child.assert_called_once()

    def test_switch_and_back_run_in_place(self):
        win = self.window([page.item('Trailers', enabled=True), page.item('Back')], lambda i: page.DONE if i == 1 else None)
        for self.position in (0, 1):
            win._busy = False
            win.onClick(500)
            win.drain_events()
        win.child.assert_not_called()
        win.close.assert_called_once()

    def test_error_dialog_is_shown_while_the_page_is_hidden(self):
        self.position = 0
        shown = []
        win = self.window([page.item('Add-ons')], lambda i: (_ for _ in ()).throw(ValueError('broken')))
        win.child = mock.Mock(side_effect=lambda fn: (shown.append('hidden'), fn())[1])
        with mock.patch.object(page.xbmcgui, 'Dialog') as dialog:
            dialog.return_value.ok.side_effect = lambda *a: shown.append('dialog')
            win.onClick(500)
            win.drain_events()
        self.assertEqual(shown, ['hidden', 'dialog'])

    def test_nested_page_does_not_hide_an_already_hidden_parent(self):
        parent = SimpleNamespace(_child_active=True, child=mock.Mock())
        opened = []

        class Window:
            def __init__(self, *a, **k):
                self.result = None

            def doModal(self):
                opened.append('modal')

            def close(self):
                pass
        with mock.patch.object(page, 'SettingsPage', Window), mock.patch.object(page, '_STACK', [parent]):
            page.show('x', lambda: [], lambda i: None)
        parent.child.assert_not_called()
        self.assertEqual(opened, ['modal'])


class PosterPreload(unittest.TestCase):
    def setUp(self):
        self.startup = importlib.import_module('nuvio_ui.startup')

    def test_cold_proxy_detection(self):
        props = {'nuvio.art_cache.base': 'http://127.0.0.1:9', 'nuvio.art_cache.usage': '1.0 MB · 3 images'}
        window = SimpleNamespace(getProperty=lambda k: props.get(k, ''))
        with mock.patch.object(self.startup.xbmcgui, 'Window', return_value=window):
            self.assertEqual(self.startup.art_cold(), 'http://127.0.0.1:9')
            props['nuvio.art_cache.usage'] = '150 MB · 900 images'
            self.assertEqual(self.startup.art_cold(), '')
            props['nuvio.art_cache.base'] = ''
            self.assertEqual(self.startup.art_cold(), '')

    def test_after_reboot_loading_screen_fills_posters(self):
        provider = {'id': 'p', 'manifest': {'id': 'm'}}
        catalog = {'id': 'top', 'type': 'movie'}
        job = ('k', provider, catalog, {})
        data = {'metas': [{'id': 'tt%d' % i, 'name': 'T', 'poster': 'https://img.invalid/%d.jpg' % i} for i in range(15)]}
        heads, props = [], {}
        created = []

        class Loading:
            def __init__(self, *a, **k):
                self.cancelled = False
                created.append(self)

            def show(self):
                pass

            def close(self):
                pass

            def setProperty(self, k, v):
                props[k] = v
        home = SimpleNamespace(getProperty=lambda k: '', setProperty=lambda k, v: props.__setitem__('home:' + k, v))
        cache = mock.Mock(lookup_many=lambda keys: {'k': True})
        home_data = importlib.import_module('resources.lib.home_data')

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                return b''
        with mock.patch.object(self.startup, 'jobs', return_value=[job]), \
                mock.patch.object(self.startup.browse_cache, 'instance', return_value=cache), \
                mock.patch.object(self.startup.browse_cache, 'peek', return_value=data), \
                mock.patch.object(self.startup, 'art_cold', return_value='http://127.0.0.1:9'), \
                mock.patch.object(self.startup, 'Loading', Loading), \
                mock.patch.object(self.startup.xbmcgui, 'Window', return_value=home), \
                mock.patch.object(home_data, '_api', return_value=SimpleNamespace(
                    extract_ids=lambda m: {}, _normalize_meta_art_urls=lambda p, m: m)), \
                mock.patch('urllib.request.urlopen', side_effect=lambda req, timeout: (heads.append(req.full_url), Response())[1]):
            report = self.startup.prepare()
        self.assertEqual(len(created), 1)
        self.assertEqual(report['posters'], self.startup.POSTERS_PER_CATALOG)
        self.assertEqual(len(heads), self.startup.POSTERS_PER_CATALOG)
        self.assertTrue(all(h.startswith('http://127.0.0.1:9/image?url=') for h in heads))
        self.assertIn('Loading posters into memory', props['nuvio.loading'])
        self.assertEqual(props.get('home:nuvio.art_warm.session'), 'http://127.0.0.1:9')

    def test_warm_proxy_and_cached_catalogs_skip_the_loading_screen(self):
        with mock.patch.object(self.startup, 'jobs', return_value=[('k', {}, {}, {})]), \
                mock.patch.object(self.startup.browse_cache, 'instance', return_value=mock.Mock(lookup_many=lambda keys: {'k': True})), \
                mock.patch.object(self.startup, 'art_cold', return_value=''), \
                mock.patch.object(self.startup, 'Loading', side_effect=AssertionError('loading screen')):
            self.assertEqual(self.startup.prepare()['posters'], 0)


class ConfigurePage(unittest.TestCase):
    def setUp(self):
        self.root = ET.parse(ROOT / 'plugin.video.nuviohub/resources/settings.xml').getroot()

    def test_every_setting_is_inside_a_category(self):
        self.assertEqual(self.root.findall('setting'), [])
        ids = [s.get('id') for c in self.root.findall('category') for s in c.findall('setting')]
        self.assertIn('nuvio_subtitle_language', ids)
        self.assertIn('nuvio_subtitles_on_start', ids)

    def test_sections_open_update_and_remove(self):
        categories = {c.get('label'): c for c in self.root.findall('category')}
        self.assertEqual(list(categories), ['Nuvio Hub', 'Remove'])
        actions = [s.get('action') for s in categories['Nuvio Hub'].findall('setting') if s.get('type') == 'action']
        self.assertEqual(actions[:3], ['RunScript(script.nuvio,settings)',
                                       'RunPlugin(plugin://plugin.video.nuviohub/?action=nuvio_install)',
                                       'RunPlugin(plugin://plugin.video.nuviohub/?action=nuvio_update_check)'])
        remove = [s.get('action') for s in categories['Remove'].findall('setting') if s.get('type') == 'action']
        self.assertEqual(remove, ['RunPlugin(plugin://plugin.video.nuviohub/?action=nuvio_uninstall)'])

    def test_update_check_route_exists(self):
        source = (ROOT / 'plugin.video.nuviohub/resources/lib/plugin.py').read_text(encoding='utf-8')
        self.assertIn("if action == 'nuvio_update_check':", source)
        updater = importlib.import_module('resources.lib.updater')
        self.assertTrue(callable(updater.interactive_check))


class Sleep(unittest.TestCase):
    def test_service_stops_its_own_preview_before_sleep(self):
        source = (ROOT / 'plugin.video.nuviohub/service.py').read_text(encoding='utf-8')
        self.assertIn("elif method=='System.OnSleep':_stop_owned_preview()", source)
        self.assertIn("getPlayingItem().getProperty('nuvio.preview')==token", source)


if __name__ == '__main__':
    unittest.main()
