# Nuvio Hub 6.0.17 — "Remove Nuvio build" fixed

Prepared 30 September 2026 from the local 6.0.16 candidate (whose changes are all
included). Status: **local test candidate**; nothing pushed or published.

## Why removal did not work

Kodi's own *Uninstall* refuses an add-on that another installed add-on needs, or
that is the active skin or screensaver: `skin.nuvio` and `screensaver.nuvio` need
`script.nuvio`, which needs `plugin.video.nuviohub`. Kodi does not allow that to be
bypassed, so the whole build is removed with Nuvio's own **Remove Nuvio build**.

That tool switches Kodi to Estuary and the default screensaver, disables the four
components leaves-first (screensaver and skin, then the interface, then the
backend) and removes them, keeping accounts and history unless you choose
otherwise. It runs as a standalone copy in `special://temp` so disabling the
backend cannot stop it halfway — but that copy still contained a package-relative
import (`from .seek_profile import restore`). It failed right after the components
were disabled, the error handler re-enabled everything, and nothing was removed.

## Fix

* The seek-settings restore function is loaded from the installed backend by path
  before any file moves; if it cannot be loaded, removal continues without it.
* **Kodi > Add-ons > Nuvio Hub > Configure** now also has *Remove the Nuvio build
  (all four components, in the right order)*, besides Nuvio Settings >
  Maintenance & updates > Remove Nuvio build.
* The add-on settings text about updates now describes the automatic GitHub
  updates.

## Checks

New `test_nuvio_617.py` runs the helper exactly as Kodi does (a copy outside any
package) against a fake Kodi that enforces its rules (no disabling an add-on
that an enabled add-on needs, nor the active skin or screensaver). It removes all
four components in dependency order, switches skin and screensaver, and keeps
Estuary; the same test fails on 6.0.16 with the original ImportError.
`python review/check_617.py`, release guard, builder and packaged smoke test.

## Please check

Nuvio Settings > Maintenance & updates > Remove Nuvio build (answer *Yes* when
Kodi asks to keep Estuary), then restart Kodi; also the new Configure button.
