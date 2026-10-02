# Nuvio Hub 6.0.36 — collections connect to your add-ons, complete update check

Released 2 October 2026 after a report: a device showing 6.0.27 said "up to
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
* **Collections showed "Connect collection catalogs" / "not installed"**
  although the Nuvio app had them connected:
  * MegaNexus kept the add-on manifest from the day the add-on was added, and
    a Nuvio re-import even reused that copy. Catalogs added later in the
    add-on's configuration (e.g. streaming services in AIOMetadata /
    Xperience) never appeared. A Nuvio import now always reads the current
    manifest, the service re-reads all manifests at start and every 6 hours
    (never during video), and HUB Settings > Add-ons > "Refresh add-on
    catalogs now" does it at once (`resources/lib/manifest_refresh.py`).
  * Like the Nuvio apps, a catalog ID matches also before a comma and tv /
    show = series.
  * Collections shared by other people name *their* instance of an add-on
    (another host or configuration = another manifest ID). When no installed
    add-on has that ID, the installed add-on that publishes the same catalog
    is used (several: the most similar name, then an enabled metadata
    add-on). General IDs ("top", "popular"...) only move to an add-on with a
    similar name; a name alone never matches.
* The service's automatic component install waited at most one hour while
  MegaNexus was open and gave up after a single failed attempt. It now waits
  up to 24 hours and retries a failed install (5 tries).

Checks: `test_nuvio_636.py` (12 tests; 611 and extras updated for the new
matching rule); `python review/check_636.py`, release guard,
builder, packaged smoke test.
