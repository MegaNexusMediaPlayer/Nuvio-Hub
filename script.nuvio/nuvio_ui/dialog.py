"""Keep Kodi callbacks short and remove parent modals while a child owns input."""
import queue
import threading
import time
import traceback
import xbmc
import xbmcgui

BACK = (9, 10, 92, 216, 13, 247, 257, 275, 61448, 61467)
ACTIONS = (117, 101, 1009, 11)
# Touch screens (6.0.37, 6.0.39). Kodi gives a horizontal row the whole drag
# when the finger starts on a poster, so dragging up/down over posters did not
# move Home. Windows with TOUCH_ROWS turn a vertical drag into row steps (the
# same Up/Down a remote sends). Remote, mouse and keyboard never send these IDs.
# 6.0.39: the step follows the finger's speed, a fast flick keeps gliding a few
# rows after the finger lifts (a new touch stops it), and touch never leaves
# the rows for the header (touch_can_step).
GESTURE_BEGIN, GESTURE_PAN, GESTURE_ABORT, GESTURE_END = 501, 504, 505, 599
GESTURES = (GESTURE_BEGIN, GESTURE_PAN, GESTURE_ABORT, GESTURE_END)
TOUCH_LOCK = 20          # px before the drag direction is decided
TOUCH_STEP = 0.11        # of the screen height per row step (slow drag)
TOUCH_STEP_FAST = 0.07   # ... while the finger moves fast
TOUCH_FAST = 1.2         # screen heights per second = a fast drag / flick
TOUCH_FLING_MAX = 8      # rows a flick may add after the finger lifts
TOUCH_FLING_GAP = 0.07   # s between glide steps, growing as it slows down
TOUCH_SAMPLE = 0.12      # s of finger movement used for the speed
TOUCH_SETTLE = 0.4       # s after the finger lifts that counts as touching

class Action:
    def __init__(self, aid): self.aid = aid
    def getId(self): return self.aid

class Dialog(xbmcgui.WindowXMLDialog):
    """Callbacks are wrapped per window instance (6.0.37). Kodi 22's SWIG 4.5
    bindings make the window classes' attributes read-only after creation
    ("cannot modify read-only attribute ...onInit"), so the earlier
    class-level wrapping in __init_subclass__ stopped every MegaNexus window."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self._events = queue.Queue(maxsize=1)
        self._dispatching = False
        self._dialog_closed = False
        self._child_active = False
        self._restore_focus = None
        self._xml_ready=threading.Event()
        self._install_callbacks()

    def _install_callbacks(self):
        cls = type(self)
        for name in ('onInit', 'onClick', 'onAction'):
            owner = next((k for k in cls.__mro__ if name in k.__dict__), None)
            if owner is None or owner is Dialog or not issubclass(owner, Dialog):
                continue
            original = owner.__dict__[name]
            if name == 'onInit':
                def ready(_fn=original):
                    try:return _fn(self)
                    finally:self._xml_ready.set()
                self.onInit = ready
                continue
            def callback(value, _fn=original, _name=name):
                if self._child_active or self._dialog_closed: return
                if _name == 'onAction':
                    aid = value.getId()
                    if aid in GESTURES:
                        self._touch_gesture(aid, value)
                        return
                    if aid not in BACK + ACTIONS: return  # Kodi owns navigation/seek.
                    value = Action(aid)
                    if aid in BACK: return _fn(self, value)
                # A busy operation already owns this click; do not replay held
                # Select after it returns. Irrelevant navigation never queues.
                if not self._dispatching:
                    self.defer(lambda: _fn(self, value))
            setattr(self, name, callback)

    TOUCH_ROWS = False

    def touching(self):
        """A finger is on the screen, just left it, or a flick still glides."""
        state = self.__dict__
        return (bool(state.get('_touch_state')) or bool(state.get('_touch_fling'))
                or time.monotonic() - float(state.get('_touch_ended_at') or 0.0) < TOUCH_SETTLE)

    def touch_can_step(self, down):
        """Windows refuse a step that would leave the rows (Home: the header)."""
        return True

    @staticmethod
    def _screen_height():
        try:
            return max(240.0, float(xbmcgui.getScreenHeight()))
        except Exception:
            return 1080.0

    def _touch_step(self, down):
        if not self.touch_can_step(down):
            return False
        # Finger up = content up = the next row, like scrolling a page.
        xbmc.executebuiltin('Action(Down)' if down else 'Action(Up)')
        return True

    def _touch_speed(self, touch):
        """Vertical finger speed in screen heights per second (signed)."""
        samples = touch['samples']
        if len(samples) < 2:
            return 0.0
        (t0, y0), (t1, y1) = samples[0], samples[-1]
        if t1 - t0 <= 0:
            return 0.0
        return (y1 - y0) / (t1 - t0) / self._screen_height()

    def _touch_gesture(self, aid, action):
        now = time.monotonic()
        if aid == GESTURE_BEGIN:
            y = action.getAmount2()
            self._touch_fling = None   # a new touch stops a glide
            self._touch_state = {'x': action.getAmount1(), 'y': y, 'axis': None, 'last': y, 'samples': [(now, y)]}
            return
        touch = self.__dict__.get('_touch_state')
        if aid in (GESTURE_ABORT, GESTURE_END) or touch is None:
            self._touch_state = None
            self._touch_ended_at = now
            if aid == GESTURE_END and touch and touch['axis'] == 'v' and self.TOUCH_ROWS:
                speed = self._touch_speed(touch)
                if abs(speed) >= TOUCH_FAST:
                    rows = min(TOUCH_FLING_MAX, int(abs(speed) * 1.5))
                    self._touch_fling = {'down': speed < 0, 'left': rows, 'gap': TOUCH_FLING_GAP, 'next': now}
            return
        x, y = action.getAmount1(), action.getAmount2()
        touch['samples'] = [s for s in touch['samples'] if now - s[0] <= TOUCH_SAMPLE] + [(now, y)]
        if touch['axis'] is None:
            dx, dy = abs(x - touch['x']), abs(y - touch['y'])
            if max(dx, dy) < TOUCH_LOCK:
                return
            touch['axis'] = 'v' if dy > dx * 1.2 else 'h'
            touch['last'] = y
        if touch['axis'] != 'v' or not self.TOUCH_ROWS:
            return
        fast = abs(self._touch_speed(touch)) >= TOUCH_FAST
        step = self._screen_height() * (TOUCH_STEP_FAST if fast else TOUCH_STEP)
        moved = y - touch['last']
        while abs(moved) >= step:
            touch['last'] += -step if moved < 0 else step
            if not self._touch_step(moved < 0):
                touch['last'] = y   # at the edge: no step stored up for later
            moved = y - touch['last']

    def _touch_glide(self):
        """One step of a flick's glide; called from the window loop."""
        fling = self.__dict__.get('_touch_fling')
        if not fling or time.monotonic() < fling['next']:
            return
        if fling['left'] <= 0 or not self._touch_step(fling['down']):
            self._touch_fling = None
            self._touch_ended_at = time.monotonic()
            return
        fling['left'] -= 1
        fling['gap'] *= 1.3
        fling['next'] = time.monotonic() + fling['gap']

    def show_ready(self):
        """Restored XML controls are valid only after Kodi delivers onInit."""
        self._xml_ready.clear()
        self.show()
        monitor=xbmc.Monitor()
        for _ in range(100):
            if self._xml_ready.is_set() or self._dialog_closed or monitor.waitForAbort(.01):break

    def defer(self, fn):
        try: self._events.put_nowait(fn)
        except queue.Full: pass

    def child(self, fn, *args, **kwargs):
        """Hide the parent natively; retain its Python state for Back/Stop."""
        try: focus = self.getFocusId()
        except Exception: focus = None
        self._child_active = True
        try:
            xbmcgui.WindowXMLDialog.close(self)
            return fn(*args, **kwargs)
        finally:
            self._restore_focus = focus
            if not self._dialog_closed and not xbmc.Monitor().abortRequested():
                self.show_ready()
            self._child_active = False

    def over(self, fn, *args, **kwargs):
        """Run a window on top of this one while it stays visible (translucent
        HUB Settings, 6.0.35). Its own input is paused meanwhile."""
        self._child_active = True
        try:
            return fn(*args, **kwargs)
        finally:
            self._child_active = False

    def restore_focus(self):
        focus, self._restore_focus = self._restore_focus, None
        if focus is not None:
            try: self.setFocusId(focus)
            except Exception: pass

    def drain_events(self):
        if self._dialog_closed or self._dispatching or self._child_active: return
        if self.TOUCH_ROWS: self._touch_glide()
        try: fn = self._events.get_nowait()
        except queue.Empty: return
        self._dispatching = True
        try: fn()
        except Exception:
            # 6.0.39: one failing click or key never closes MegaNexus ("Could
            # not open the interface"); the window stays and the log has why.
            xbmc.log('[Nuvio] Action failed: ' + traceback.format_exc(), xbmc.LOGERROR)
            try: xbmcgui.Dialog().notification('MegaNexus', 'That did not work. Please try again.', time=3000)
            except Exception: pass
        finally: self._dispatching = False

    def doModal(self):
        self._dialog_closed = False
        self.show_ready()
        monitor = xbmc.Monitor()
        while not self._dialog_closed and not monitor.abortRequested():
            self.drain_events()
            tick = getattr(self, 'tick', None)
            if tick and not self._dialog_closed: tick()
            monitor.waitForAbort(.05)

    def close(self):
        self._dialog_closed = True
        super().close()
