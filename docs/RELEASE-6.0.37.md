# Nuvio Hub 6.0.37 — Kodi 22 RC1, touch screens

Prepared 2 October 2026 (test build, not released).

* **Kodi 22 RC1: MegaNexus did not open** ("Could not open the interface").
  Kodi 22 RC1 builds its Python bindings with SWIG 4.5 and locks the window
  classes after creation (`cannot modify read-only attribute
  'SettingsPage.onInit'`). `nuvio_ui/dialog.py` wrapped onInit / onClick /
  onAction by changing each window class after creation. The wrappers are now
  set on each window object when it is created, with the same behaviour.
  Kodi 21.3 and 22 beta 2 call these methods through the window object
  (`PyObject_CallMethod(self, ...)` in their generated bindings), so they
  work as before. Tested on Kodi 22 RC1 (Flatpak) on Linux.
* When the interface fails, kodi.log now has the full traceback instead of
  only "Interface failed".
* **Touch screens:** dragging up or down with the finger starting on a poster
  did not move Home, because Kodi gives a horizontal row the whole drag. On
  Home, Sport and Library a vertical drag now steps between rows - the same
  Up / Down a remote sends - and while a finger is on the screen Home does
  not repaint rows or start previews (a row reset mid-drag felt like the
  posters got stuck). Only Kodi's touch gesture actions are used: remote,
  mouse and keyboard behave exactly as before, and nothing changes in size.

Checks: `test_nuvio_637.py`; `python review/check_637.py`, release guard,
builder, packaged smoke test.
