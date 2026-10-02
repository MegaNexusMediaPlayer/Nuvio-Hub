# Nuvio Hub 6.0.36 — the update check looks at every component

Prepared 2 October 2026 after a report: a device showing 6.0.27 said "up to
date" on Check for updates.

* The check compared only the backend (Nuvio Hub). On that device the
  backend was already the newest version - Kodi had updated it from the
  MegaNexus repository - while the interface (the 6.0.27 shown next to
  "Check for updates") was still the old one, so "up to date" was true for the
  backend only. HUB Settings > Maintenance > Check for updates now also checks
  the interface, skin and screensaver (`bundle_installer.component_report`:
  version on disk and version Kodi has loaded):
  * not installed yet: says which ones, lets the service install them when
    MegaNexus is closed and offers to restart now (Reboot on CoreELEC /
    LibreELEC, Close Kodi on Android and Apple, Restart elsewhere);
  * installed but Kodi still runs the old version: offers the restart.
  The Maintenance row shows "6.0.36 · interface 6.0.27" when they differ.
* The service's automatic component install waited at most one hour while
  MegaNexus was open and gave up after a single failed attempt. It now waits
  up to 24 hours and retries a failed install (5 tries).

Checks: `test_nuvio_636.py`; `python review/check_636.py`, release guard,
builder, packaged smoke test.
