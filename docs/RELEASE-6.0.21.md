# Nuvio Hub 6.0.21 — blue MegaNexus theme, sharp logo, Kodi repository

Prepared 1 October 2026 from the 6.0.20 review candidate (all of it included).
Status: **local review candidate**; nothing pushed or published.

## Logo (fixes 6.0.20)

* 6.0.20 recoloured the raster wordmark: white specks inside the blue "Nexus"
  and a blurry, upscaled mark. Now `review/make_meganexus_brand.py` draws the
  text from a vector font at its final size (white "Mega", clean blue gradient
  "Nexus") next to the original 770×539 mark, never upscaled.
* Home header logo is larger (284×90, was 240×76) with bigger letters; the
  "HUB" label moved right so nothing overlaps. Banner/fanart 1920×1080 and
  icons 1024×1024 regenerated.

## Blue theme

* `review/make_blue_theme.py` replaced the violet accents with the logo blue
  (same lightness; mid tones at least 70 % saturated) and the slate panel /
  background colours with the deep "space" navy around the M (650 values in the
  interface and skin XML, Kodi colour theme `defaults.xml`, 48 weather icons).
  Brand marks are unchanged.

## Screensaver

* The built-in **MegaNexus · animated** screensaver is now drawn by the skin
  (glow pulse, logo breathing, a light orbiting along the ring and dimming
  behind the M). The 6.0.20 MP4 went through Kodi's player: it muted Kodi
  (speaker icon on screen) and did not show reliably. No player, no mute now.
  A 6.0.20 setting pointing at the bundled MP4 is read as the animation.
* The MP4 is no longer in the bundle; a sharper 1080p loop is delivered
  separately (`MegaNexus-Screensaver-1080p.mp4`) for use as a custom video.

## Other

* Settings: **Support MegaNexus · Ko-fi** (main page and Maintenance); the QR
  page title says "Support MegaNexus".
* New `repository.meganexus` 1.0.0 and `review/build_repo_site.py`: a static
  Kodi repository for GitHub Pages
  (`https://meganexusmediaplayer.github.io/Nuvio-Hub/`). `index.html` lists the
  repository ZIP, so the URL works as a File manager source for "Install from
  zip file"; afterwards "Install from repository → MegaNexus Repository".
  Not in the bundle; nothing published.

## Checks

New `test_nuvio_621.py` (no violet left in shipped XML, colour mapping, logo
sizes, header layout, skin-drawn screensaver layers shipped and no MP4,
animated mode never starts a player or mutes, Ko-fi labels, repository addon
URLs and a full site build). `test_nuvio_620` screensaver expectations updated
to the new contract. `python review/check_621.py`, release guard, builder,
packaged smoke test.
