# Nuvio Hub 6.0.20 — MegaNexus branding

Prepared 1 October 2026 from the 6.0.19 review candidate (all of it included).
Status: **local review candidate**; nothing pushed or published.

First step of moving the interface's own branding to **MegaNexus**. Nuvio
accounts, sync, settings, add-on IDs, profile paths and the release/update
naming (`Nuvio-Hub-Complete-<version>.zip`) are unchanged.

## Branding

* MegaNexus logo (from the MegaNexus-App brand assets) replaces the previous
  logo in the Home header, Details, IPTV guide, HUB background, add-on icons and
  fanart. The header wordmark has a white "Mega" for dark backgrounds and no
  tagline; the banner keeps "Your media universe. connected.".
* HUB buttons: **MegaNexus** (was Open Nuvio), **IPTV Channels** (was Open IPTV),
  **HUB Settings** (was Nuvio Settings). The settings page title and every
  "… in Nuvio Settings" hint now say **HUB Settings**; the backend menu and the
  Kodi add-on settings button were renamed the same way.

## Screensaver

* Default (standard) screensaver: the MegaNexus banner image.
* New built-in **MegaNexus · animated video**: `script.nuvio/resources/media/meganexus_saver.mp4`
  (H.264 High, 1920×1080, 30 fps, 12 s seamless loop, no audio, 0.75 MB) —
  glow pulse and a light orbiting the logo. It uses the existing silent video
  saver path (paused media still falls back to the image).
* Screensaver media page: MegaNexus standard image · MegaNexus animated video ·
  Custom image / GIF · Custom video.

## Performance & image cache

* The RAM preset is labelled **RAM · 200 MiB**; the "(160 images + 40 metadata)"
  breakdown and the explanatory dialog on "Cache usage" were removed. Budgets
  are unchanged.

## Checks

New `test_nuvio_620.py` (HUB labels, settings title, RAM label, screensaver
media choices incl. the bundled MP4 passing the saver file check, identical
logo copies). `python review/check_620.py`, release guard, builder, packaged
smoke test.
