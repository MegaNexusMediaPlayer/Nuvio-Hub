# Nuvio Hub 6.0.26 — first open does everything in order

Prepared 1 October 2026 from 6.0.25.

* Opening the video add-on (or *MegaNexus* / *HUB Settings* in its menu)
  before anything was installed now runs the whole first start in order:
  install the interface, skin and screensaver with a visible progress
  notice, switch to the **MegaNexus skin**, then open MegaNexus, whose first
  start offers **Set up on your phone**.
* The skin is remembered as set only when Kodi really kept it. Declined or
  timed out means it is offered again at the next open (before, it was
  never offered again).
* Slow devices: Kodi gets up to ~30 s (was 10 s) to discover the newly
  installed components instead of failing with "Restart Kodi".
* Removing MegaNexus while keeping settings resets the first-start flags, so
  a later reinstall switches the skin and screensaver again.

Checks: `test_nuvio_625_removal.py` now also covers the first open (install →
skin → MegaNexus, declined skin offered again, install error shown) and the
reset of first-start flags; `python review/check_626.py`, release guard,
builder, packaged smoke test.
