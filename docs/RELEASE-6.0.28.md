# Nuvio Hub 6.0.28 — three themes

Prepared 1 October 2026 from 6.0.27.

* **HUB Settings → Home & appearance → Theme** (and *Display → Theme* on the
  phone setup page):
  * **Light** – the MegaNexus blue look (as before);
  * **Dark** – pure black background for OLED TVs, dark-grey panels and
    buttons, blue focus and text accents;
  * **Semi-dark** – black at the top around the small video, dark blue rising
    from the bottom behind the rows.
* The theme also changes the HUB (skin Home background and buttons through a
  Kodi colour theme of the MegaNexus skin) and the screensaver background /
  default image. Home redraws as soon as Settings closes.
* **Catalog card boxes keep their original colour** (grey-blue, as before
  6.0.21) in every theme.
* The two gradients around the small video are now tinted by the theme, so
  they match the background exactly (in Light too).

Implementation: Dark and Semi-dark are generated from the Light windows by
`review/make_theme_variants.py` (script.nuvio/resources/skins/Dark and Dim,
skin.nuvio/colors/dark.xml and dim.xml); `resources/lib/theme.py` chooses the
folder, banner and skin colours.

Checks: `test_nuvio_628.py` (default and folders, apply/sync incl. skin
colours only for the MegaNexus skin, variants up to date, no blue background
in Dark, blue bottom in Semi-dark, card boxes original in all themes,
gradients follow the theme, all variant XML parses, every window opens in the
theme folder, Settings and phone theme choice, HUB banners/colours,
screensaver banner). Packaged smoke test checks all three themes ship.
`python review/check_628.py`, release guard, builder.
