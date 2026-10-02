"""6.0.37: Kodi 22 RC1 windows (read-only SWIG classes) and touch row dragging."""
import importlib
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()
import kodi_stub

dialog = importlib.import_module('nuvio_ui.dialog')
page = importlib.import_module('nuvio_ui.settings_page')
home = importlib.import_module('nuvio_ui.home_window')


class ReadOnlyClasses(unittest.TestCase):
    def test_window_classes_are_never_modified_after_creation(self):
        # Kodi 22 RC1: "cannot modify read-only attribute ...onInit".
        text = open(kodi_stub.ADDON_ROOT + '/../script.nuvio/nuvio_ui/dialog.py', encoding='utf-8').read()
        self.assertNotIn('def __init_subclass__', text)
        self.assertNotIn('setattr(cls', text)
        self.assertIs(page.SettingsPage.__dict__['onClick'].__name__, 'onClick')   # the class keeps its own method

    def test_callbacks_are_wrapped_per_window(self):
        class Probe(dialog.Dialog):
            def onInit(self):
                self.inited = True
            def onClick(self, cid):
                self.clicked = cid
        win = Probe()
        self.assertIn('onClick', win.__dict__)
        win.onInit()
        self.assertTrue(win.inited and win._xml_ready.is_set())
        win.onClick(7)
        self.assertFalse(hasattr(win, 'clicked'), 'deferred to the window loop, as before')
        win.drain_events()
        self.assertEqual(win.clicked, 7)


def action(aid, x=0.0, y=0.0):
    return SimpleNamespace(getId=lambda: aid, getAmount1=lambda: x, getAmount2=lambda: y)


class TouchRows(unittest.TestCase):
    def drag(self, rows, points, height=1080):
        class Rows(dialog.Dialog):
            TOUCH_ROWS = rows
            def onAction(self, a):
                self.handled = a.getId()
        win = Rows()
        sent = []
        with mock.patch.object(dialog.xbmc, 'executebuiltin', side_effect=sent.append), \
                mock.patch.object(dialog.xbmcgui, 'getScreenHeight', return_value=height, create=True):
            win.onAction(action(dialog.GESTURE_BEGIN, *points[0]))
            for point in points[1:]:
                win.onAction(action(dialog.GESTURE_PAN, *point))
                self.assertTrue(win.touching())
            win.onAction(action(dialog.GESTURE_END, *points[-1]))
        return win, sent

    def test_vertical_drag_over_posters_steps_rows(self):
        step = 1080 * dialog.TOUCH_STEP
        win, sent = self.drag(True, [(500, 900), (505, 870), (510, 900 - step * 2 - 40)])
        self.assertEqual(sent, ['Action(Down)', 'Action(Down)'])
        win, sent = self.drag(True, [(500, 200), (500, 240), (500, 200 + step + 50)])
        self.assertEqual(sent, ['Action(Up)'])

    def test_horizontal_drag_is_left_to_kodi(self):
        win, sent = self.drag(True, [(900, 500), (700, 510), (300, 520)])
        self.assertEqual(sent, [])

    def test_windows_without_rows_and_remote_keys_are_unchanged(self):
        win, sent = self.drag(False, [(500, 900), (500, 870), (500, 300)])
        self.assertEqual(sent, [])
        self.assertFalse(hasattr(win, 'handled'), 'gestures never reach the window handler')
        win.onAction(action(92))
        self.assertEqual(win.handled, 92)   # Back still at once

    def test_rows_screens_opt_in(self):
        sports = importlib.import_module('nuvio_ui.sports')
        library = importlib.import_module('nuvio_ui.library')
        self.assertTrue(home.HomeWindow.TOUCH_ROWS and sports.SportsWindow.TOUCH_ROWS and library.LibraryWindow.TOUCH_ROWS)
        self.assertFalse(dialog.Dialog.TOUCH_ROWS)


if __name__ == '__main__':
    unittest.main()
