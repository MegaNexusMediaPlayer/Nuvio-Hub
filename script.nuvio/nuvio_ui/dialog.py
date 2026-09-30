"""Keep Kodi callbacks short and remove parent modals while a child owns input."""
import queue
import threading
import xbmc
import xbmcgui

BACK = (9, 10, 92, 216, 13, 247, 257, 275, 61448, 61467)
ACTIONS = (117, 101, 1009, 11)

class Action:
    def __init__(self, aid): self.aid = aid
    def getId(self): return self.aid

class Dialog(xbmcgui.WindowXMLDialog):
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        initialize=cls.__dict__.get('onInit')
        if initialize is not None:
            def ready(self,_fn=initialize):
                try:return _fn(self)
                finally:self._xml_ready.set()
            cls.onInit=ready
        for name in ('onClick', 'onAction'):
            original = cls.__dict__.get(name)
            if original is None: continue
            def callback(self, value, _fn=original, _name=name):
                if self._child_active or self._dialog_closed: return
                if _name == 'onAction':
                    aid = value.getId()
                    if aid not in BACK + ACTIONS: return  # Kodi owns navigation/seek.
                    value = Action(aid)
                    if aid in BACK: return _fn(self, value)
                # A busy operation already owns this click; do not replay held
                # Select after it returns. Irrelevant navigation never queues.
                if not self._dispatching:
                    self.defer(lambda: _fn(self, value))
            setattr(cls, name, callback)

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self._events = queue.Queue(maxsize=1)
        self._dispatching = False
        self._dialog_closed = False
        self._child_active = False
        self._restore_focus = None
        self._xml_ready=threading.Event()

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
