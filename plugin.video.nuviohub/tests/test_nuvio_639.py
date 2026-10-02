"""6.0.39: touch no longer breaks Home clicks, a failing action never closes
MegaNexus, speed-aware touch rows with a flick glide."""
import importlib
import unittest
from unittest import mock
from types import SimpleNamespace
import frontend_test_support
frontend_test_support.install()

dialog = importlib.import_module('nuvio_ui.dialog')
home = importlib.import_module('nuvio_ui.home_window')


def action(aid, x=0.0, y=0.0):
    return SimpleNamespace(getId=lambda: aid, getAmount1=lambda: x, getAmount2=lambda: y)


class Clock:
    def __init__(self, step):
        self.now, self.step = 100.0, step

    def __call__(self):
        self.now += self.step
        return self.now


class TouchThenClick(unittest.TestCase):
    def test_a_swipe_does_not_replace_the_home_window_methods(self):
        # 6.0.37: the touch state was stored as self._touch, which replaced
        # HomeWindow._touch(); the next click raised TypeError and Kodi showed
        # "Could not open the interface" (Android Kodi 22, opening a catalog).
        win = home.HomeWindow()
        win.onAction(action(dialog.GESTURE_BEGIN, 500, 500))
        win.onAction(action(dialog.GESTURE_END, 500, 300))
        self.assertTrue(callable(win._touch))
        self.assertNotIn('_touch', win.__dict__)
        win._touch()   # the method HomeWindow.onClick calls first

    def test_a_failing_action_keeps_the_window_open(self):
        win = dialog.Dialog()
        def broken():
            raise TypeError('boom')
        win.defer(broken)
        with mock.patch.object(dialog.xbmc, 'log') as log, mock.patch.object(dialog.xbmcgui, 'Dialog') as box:
            win.drain_events()   # must not raise
        self.assertIn('Traceback', log.call_args[0][0])
        box.return_value.notification.assert_called_once()
        self.assertFalse(win._dispatching)


class SpeedAwareTouch(unittest.TestCase):
    def window(self, can_step=True):
        class Rows(dialog.Dialog):
            TOUCH_ROWS = True
            def touch_can_step(self, down):
                return can_step or down
            def onAction(self, a):
                pass
        return Rows()

    def run_drag(self, win, points, step_seconds):
        sent = []
        clock = Clock(step_seconds)
        with mock.patch.object(dialog.xbmc, 'executebuiltin', side_effect=sent.append), \
                mock.patch.object(dialog.time, 'monotonic', side_effect=clock), \
                mock.patch.object(dialog.xbmcgui, 'getScreenHeight', return_value=1080, create=True):
            win.onAction(action(dialog.GESTURE_BEGIN, *points[0]))
            for point in points[1:]:
                win.onAction(action(dialog.GESTURE_PAN, *point))
            win.onAction(action(dialog.GESTURE_END, *points[-1]))
            for _ in range(200):   # the window loop
                win._touch_glide()
        return sent

    def test_slow_drag_moves_row_by_row_without_glide(self):
        sent = self.run_drag(self.window(), [(500, 900), (500, 870), (500, 600)], 0.4)
        self.assertEqual(sent, ['Action(Down)', 'Action(Down)'])
        self.assertFalse(self.window().touching())

    def test_fast_flick_glides_further(self):
        slow = self.run_drag(self.window(), [(500, 900), (500, 870), (500, 600)], 0.4)
        fast = self.run_drag(self.window(), [(500, 900), (500, 870), (500, 600)], 0.02)
        self.assertGreater(len(fast), len(slow))
        self.assertLessEqual(len(fast), 3 + dialog.TOUCH_FLING_MAX + 1)
        self.assertEqual(set(fast), {'Action(Down)'})

    def test_new_touch_stops_the_glide(self):
        win = self.window()
        self.run_drag(win, [(500, 900), (500, 870), (500, 600)], 0.02)
        win._touch_fling = {'down': True, 'left': 5, 'gap': 0.07, 'next': 0}
        win.onAction(action(dialog.GESTURE_BEGIN, 500, 500))
        self.assertIsNone(win._touch_fling)

    def test_touch_never_climbs_into_the_header(self):
        sent = self.run_drag(self.window(can_step=False), [(500, 200), (500, 230), (500, 900)], 0.02)
        self.assertEqual(sent, [])
        win = home.HomeWindow()
        win.getFocusId = lambda: home.ROW_BASE
        self.assertFalse(win.touch_can_step(False))   # first row: no Up into Home/Search
        self.assertTrue(win.touch_can_step(True))
        win.getFocusId = lambda: home.ROW_BASE + 2
        self.assertTrue(win.touch_can_step(False))


if __name__ == '__main__':
    unittest.main()
