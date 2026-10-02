"""Keep Kodi callbacks short and remove parent modals while a child owns input."""
import queue
import threading
import time
import xbmc
import xbmcgui

BACK = (9, 10, 92, 216, 13, 247, 257, 275, 61448, 61467)
ACTIONS = (117, 101, 1009, 11)
# Touch screens (6.0.37). Kodi gives a horizontal row the whole drag when the
# finger starts on a poster, so dragging up/down over posters did not move
# Home. Windows with TOUCH_ROWS turn a vertical drag into row steps (the same
# Up/Down a remote sends). Remote, mouse and keyboard never send these IDs.
GESTURE_BEGIN, GESTURE_PAN, GESTURE_ABORT, GESTURE_END = 501, 504, 505, 599
GESTURES = (GESTURE_BEGIN, GESTURE_PAN, GESTURE_ABORT, GESTURE_END)
TOUCH_LOCK = 24          # px before the drag direction is decided
TOUCH_STEP = 0.16        # of the screen height per row step
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
        """A finger is on the screen (or just left it)."""
        state = self.__dict__
        return bool(state.get('_touch')) or time.monotonic() - float(state.get('_touch_ended') or 0.0) < TOUCH_SETTLE

    def _touch_gesture(self, aid, action):
        if aid == GESTURE_BEGIN:
            y = action.getAmount2()
            self._touch = {'x': action.getAmount1(), 'y': y, 'axis': None, 'last': y}
            return
        touch = self.__dict__.get('_touch')
        if aid in (GESTURE_ABORT, GESTURE_END) or touch is None:
            self._touch = None
            self._touch_ended = time.monotonic()
            return
        x, y = action.getAmount1(), action.getAmount2()
        if touch['axis'] is None:
            dx, dy = abs(x - touch['x']), abs(y - touch['y'])
            if max(dx, dy) < TOUCH_LOCK:
                return
            touch['axis'] = 'v' if dy > dx * 1.2 else 'h'
            touch['last'] = y
        if touch['axis'] != 'v' or not self.TOUCH_ROWS:
            return
        try:
            step = max(40.0, xbmcgui.getScreenHeight() * TOUCH_STEP)
        except Exception:
            step = 170.0
        moved = y - touch['last']
        while abs(moved) >= step:
            # Finger up = content up = the next row, like scrolling a page.
            xbmc.executebuiltin('Action(Down)' if moved < 0 else 'Action(Up)')
            touch['last'] += -step if moved < 0 else step
            moved = y - touch['last']

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
        try: fn = self._events.get_nowait()
        except queue.Empty: return
        self._dispatching = True
        try: fn()
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
