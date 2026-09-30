import ast
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import types
import unittest
from unittest import mock
import urllib.parse
import importlib
import xml.etree.ElementTree as ET

import kodi_stub

p = kodi_stub.import_lib_module('plugin')
data = kodi_stub.import_lib_module('home_data')
import frontend_test_support
frontend_test_support.install()
window = importlib.import_module('nuvio_ui.home_window')
migration = kodi_stub.import_lib_module('fork_profile')
i18n = kodi_stub.import_lib_module('i18n')
ROOT = Path(kodi_stub.ADDON_ROOT)
UIROOT = ROOT.parent/'script.nuvio'


class MetadataTests(unittest.TestCase):
    def test_title_only_payload(self):
        self.assertEqual(p._meta_info({'title': 'Arrival'})['title'], 'Arrival')

    def test_bad_ratings_never_break_catalog(self):
        for raw in ('N/A', float('nan'), float('inf'), {}, [], -1, 12):
            self.assertEqual(p._meta_info({'name': 'Example', 'imdbRating': raw})['rating'], 0)
        self.assertEqual(p._meta_info({'imdbRating': '8,4'})['rating'], 8.4)

    def test_genre_normalization(self):
        self.assertEqual(p._meta_info({'genres': 'Drama'})['genre'], 'Drama')
        self.assertEqual(p._meta_info({'genres': [{'name': 'Drama'}, {'name': 'Mystery'}]})['genre'], 'Drama / Mystery')


class HomeSwitchTests(unittest.TestCase):
    def render(self, lightweight, off, old_nextup=True):
        emitted = []
        addon = types.SimpleNamespace(getSetting=lambda key: 'false' if key=='show_nextup_home' and not old_nextup else '')
        replacements = dict(
            ADDON=addon, _is_lightweight_mode=lambda: lightweight,
            _clear_tmdbh_transient=lambda: None, _clear_source_transient_props=lambda **kw: None,
            _import_pov_progress_if_available=lambda: None, _home_prefetch_kick=lambda pins: None,
            store=types.SimpleNamespace(list_providers=lambda: [{'id':'provider'}]),
            playback_store=types.SimpleNamespace(list_continue_items=lambda **kw: []),
            favorites_store=types.SimpleNamespace(list_favorites=lambda **kw: []),
            _load_catalog_pins=lambda: [], _home_bucket_defs=lambda **kw: [],
            _home_row_visible=lambda key: key not in off,
            _home_feature_art=lambda *a: {}, root_art=lambda *a: {},
            tmdbh_player=types.SimpleNamespace(has_tmdbhelper=lambda: False),
            add_item=lambda label,path,*a,**kw: emitted.append(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(path).query)).get('action')),
            end_dir=lambda **kw: None)
        with mock.patch.multiple(p, **replacements):
            p._home_impl()
        return emitted

    def test_continue_independent_of_legacy_nextup(self):
        for lite in (True, False):
            routes = self.render(lite, set(), old_nextup=False)
            self.assertIn('continue', routes)
            self.assertNotIn('nextup', routes)

    def test_every_utility_gate_in_both_modes(self):
        off = {'providers','plex','emby','tmdbh','search','collection','setup'}
        hidden = {'providers','plex_menu','emby_menu','integrations_menu','hub_search_menu','hub_collection','setup_center'}
        for lite in (True,False):
            routes = self.render(lite, off)
            self.assertFalse(hidden.intersection(routes), routes)
            self.assertIn('continue',routes)


class MigrationTests(unittest.TestCase):
    def test_copies_committed_wal_and_settings_without_modifying_source(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            source, dest = Path(tmp)/'old', Path(tmp)/'new'
            source.mkdir()
            settings = b'<settings><setting id="ui_language">Arabic</setting><setting id="home_style">0</setting><setting id="token">private-test-value</setting></settings>'
            (source/'settings.xml').write_bytes(settings)
            (source/'providers.json').write_text(json.dumps([{'url':'https://provider.invalid/token/manifest.json'}]))
            (source/'home_folders.json').write_text(json.dumps({'path':'plugin://plugin.video.dexhub/?action=continue'}))
            (source/'active_session.json').write_text('{}')
            db = sqlite3.connect(str(source/'playback.db'))
            try:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('CREATE TABLE progress (value INTEGER)')
                db.execute('INSERT INTO progress VALUES (42)')
                db.commit()
                migration.import_profile(source,dest)
                copied=sqlite3.connect(str(dest/'playback.db'))
                try:
                    self.assertEqual(copied.execute('SELECT value FROM progress').fetchone()[0],42)
                finally:
                    copied.close()
            finally:
                db.close()
            self.assertEqual((source/'settings.xml').read_bytes(), settings)
            vals={s.get('id'):s.text for s in ET.parse(dest/'settings.xml').getroot()}
            self.assertEqual(vals['ui_language'],'English')
            self.assertEqual(vals['home_style'],'1')
            self.assertEqual(vals['token'],'private-test-value')
            self.assertFalse((dest/'active_session.json').exists())
            self.assertEqual(json.loads((dest/'home_folders.json').read_text())['path'],'plugin://plugin.video.nuviohub/?action=continue')
            (dest/'providers.json').write_text('[]')
            migration.import_profile(source,dest)
            self.assertEqual((dest/'providers.json').read_text(),'[]')

    def test_existing_destination_settings_are_preserved(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            source,dest=Path(tmp)/'a',Path(tmp)/'b'
            source.mkdir(); dest.mkdir()
            (source/'settings.xml').write_text('<settings/>')
            (dest/'settings.xml').write_text('<settings version="2"/>')
            migration.import_profile(source,dest)
            self.assertEqual((dest/'settings.xml').read_text(),'<settings version="2"/>')


class WindowTests(unittest.TestCase):
    def make_window(self):
        win=window.HomeWindow()
        win.setProperty=mock.Mock()
        win.setFocusId=mock.Mock()
        win.close=mock.Mock()
        controls={}
        def control(cid):
            if cid not in controls:
                controls[cid]=types.SimpleNamespace(getSelectedPosition=lambda:0, reset=mock.Mock(), addItems=mock.Mock(),selectItem=mock.Mock())
            return controls[cid]
        win.getControl=control
        return win

    def test_closed_window_rejects_late_network_result(self):
        win=self.make_window()
        win._closed=True
        with mock.patch.object(data,'load_catalog',return_value=[{'title':'late'}]):
            win._load(0,{'path':'plugin://example'},0)
        win.setProperty.assert_not_called()

    def test_previous_tab_rejects_late_network_result(self):
        win=self.make_window()
        win._generation=3
        with mock.patch.object(data,'load_catalog',return_value=[{'title':'late'}]):
            win._load(0,{'path':'plugin://example'},2)
        self.assertEqual(win._shelves,[])

    def test_error_row_remains_actionable(self):
        win=self.make_window()
        win._shelves=[{}]
        win._set_rows=mock.Mock()
        with mock.patch.object(data,'load_catalog',side_effect=TimeoutError()):
            win._load(0,{'path':'plugin://plugin.video.nuviohub/?action=catalog'},0)
        win._set_rows.assert_not_called()
        win.drain_updates()
        self.assertEqual(win._shelves[0]['rows'][0]['title'],'Open catalog')
        self.assertTrue(win._shelves[0]['rows'][0]['path'])

    def test_unsafe_builtin_path_rejected(self):
        self.assertEqual(window.launch_command({'path':'http://example.invalid'}),'')
        self.assertEqual(window.launch_command({'path':'plugin://example/"),Quit()'}),'')
        self.assertEqual(window.launch_command({'path':'plugin://plugin.video.nuviohub/?action=continue','is_folder':True}),
                         'ActivateWindow(Videos,"plugin://plugin.video.nuviohub/?action=continue",return)')

    def test_progress_clamped(self):
        win=self.make_window()
        with mock.patch.object(window.xbmcgui.ListItem,'setArt',create=True):
            win._set_rows(0,[{'title':'Title','percent_value':150}])
        items=win.getControl(7000).addItems.call_args.args[0]
        self.assertEqual(items[0].getProperty('progress'),'100')


class SkinAndEnglishTests(unittest.TestCase):
    def test_all_xml_parses(self):
        for path in ROOT.rglob('*.xml'):
            ET.parse(path)

    def test_home_has_real_masks_and_unique_controls(self):
        root=ET.parse(UIROOT/'resources/skins/Default/1080i/nuvio_home.xml').getroot()
        ids=[c.get('id') for c in root.iter('control') if c.get('id')]
        self.assertEqual(len(ids),len(set(ids)))
        masks=[t.get('diffuse') for t in root.iter('texture') if (t.text or '')=='$INFO[ListItem.Art(poster)]']
        self.assertEqual(len(masks),96)
        self.assertEqual(sum(m.endswith('nuvio_poster_mask_v2.png') for m in masks),48)
        self.assertEqual(sum(m.endswith('nuvio_tile_mask_v2.png') for m in masks),48)
        for tag in ('texture','texturefocus','texturenofocus'):
            for t in root.iter(tag):
                if (t.text or '').startswith('special://home/addons/script.nuvio/'):
                    self.assertTrue((UIROOT / t.text.split('script.nuvio/',1)[1]).is_file())

    def test_english_settings_no_arabic_glyphs(self):
        text=(ROOT/'resources/language/resource.language.en_gb/strings.po').read_text(encoding='utf-8')
        self.assertNotRegex(text,r'[\u0600-\u06ff]')
        self.assertIn('msgid "Language"',text)

    def test_multiline_and_indirect_ui_strings_translate(self):
        ar=re.compile(r'[\u0600-\u06ff]')
        old=i18n._lang_cache
        i18n._lang_cache='en'
        try:
            for path in (ROOT/'resources/lib').rglob('*.py'):
                if path.name=='i18n.py': continue
                for n in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    args=[]
                    if isinstance(n,ast.Call):
                        name=n.func.id if isinstance(n.func,ast.Name) else getattr(n.func,'attr','')
                        if name in ('tr','trf','add_item','ok','yesno','notification','notify','error','setLabel','select'):
                            args.extend(n.args)
                    if isinstance(n,ast.Dict):
                        args.extend(v for k,v in zip(n.keys,n.values) if isinstance(k,ast.Constant) and k.value in ('title','plot','label','why'))
                    for a in args:
                        if isinstance(a,ast.Constant) and isinstance(a.value,str) and ar.search(a.value):
                            self.assertFalse(ar.search(i18n.tr(a.value)), '%s:%s' % (path.name,a.lineno))
        finally:
            i18n._lang_cache=old


if __name__=='__main__':
    unittest.main()
