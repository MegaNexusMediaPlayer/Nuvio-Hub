# Nuvio Hub 6.0.23 — MegaNexus release

Published 1 October 2026. Includes the 6.0.20 – 6.0.22 work: MegaNexus logo
and blue theme, skin-drawn animated screensaver, phone setup by QR code,
"Support MegaNexus · Ko-fi", and the `repository.meganexus` Kodi repository.

## New in 6.0.23

* **Phone page:** Ko-fi button with the Ko-fi cup icon next to the MegaNexus
  logo (opens ko-fi.com/master100janovic in a new tab).
* **Cinemeta is always installed.** With nothing configured it is switched ON
  and supplies metadata and the Cinemeta collections (as before). When your own
  metadata add-ons exist, Cinemeta is added OFF (or switched OFF if it was on
  automatically); switch it ON any time under Metadata add-ons or on the phone.
  A hand-made switch (TV or phone) is never changed automatically.
* **No more "Install or repair" after updates.** After the backend is
  installed or updated (Kodi repository, ZIP or GitHub updater) the service
  installs the bundled interface, skin and screensaver by itself, waiting while
  a video plays or MegaNexus is open, and shows a short notification.
* **Repository site** on GitHub Pages:
  `https://meganexusmediaplayer.github.io/Nuvio-Hub/` (File manager source →
  `repository.meganexus-1.0.0.zip` → Install from repository).

## Checks

New `test_nuvio_623.py` (Ko-fi link, Cinemeta added OFF / existing switch kept,
phone Cinemeta switch is manual, outdated-component detection, automatic
install after an update, waiting for video / open interface, abort). Updated
expectations: 6.0.15/6.0.16 Cinemeta tests (Cinemeta is now added OFF when
own add-ons exist). `python review/check_623.py`, release guard, builder,
packaged smoke test, repository site build.

Not device-tested: real phones with the setup page, Windows firewall prompt,
Android TV / CoreELEC.
