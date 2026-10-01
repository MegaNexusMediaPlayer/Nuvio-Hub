# Nuvio Hub 6.0.25 — MegaNexus wording and the last violet

Prepared 1 October 2026 from 6.0.24.

* "Welcome to Nuvio" is gone: the empty Home row says **Welcome to MegaNexus**
  and points to *HUB Settings › Set up on phone*; the backend menu says
  *Welcome to MegaNexus — start setup*; setup dialogs are titled
  *MegaNexus setup*. (Nuvio account names stay.)
* The remaining greyish-violet colours (HUB Settings focus bar, IPTV, person
  and source pills) are now logo blue: `make_blue_theme.py` also converts
  low-saturation violet (above 12 %), so neutral greys stay neutral.

Checks: `test_nuvio_625.py` (no "Welcome to Nuvio"/"Nuvio setup" in shipped
code, settings focus colour is blue), `test_nuvio_621` violet check now also
covers greyish violet; `python review/check_625.py`, release guard, builder,
packaged smoke test.
