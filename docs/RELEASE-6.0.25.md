# Nuvio Hub 6.0.25 — connect Nuvio and Home is ready; MegaNexus wording

Prepared 1 October 2026 from 6.0.24.

## Connecting a Nuvio account sets everything up

* Signing in (HUB Settings › Accounts, the first-start wizard, or the phone
  page) now imports in one go: the profile's add-ons and watch progress, its
  **Home collections**, and switches **ON the metadata add-ons those
  collections use**. An automatically enabled Cinemeta goes OFF. Home opens
  with the user's own rows on the first try.
* A Home layout the user made themselves is never replaced silently: the TV
  asks first, the phone keeps it (the explicit *Import* button with *Also
  import the collection layout* still replaces it on request).
* On the phone, one profile imports immediately after sign-in; with several,
  the profile buttons appear and choosing one imports it. The page shows what
  was imported and which metadata add-ons were switched on.

## Add-on icons

* Kodi kept showing the old Nuvio Hub logo for the add-ons: its thumbnail
  cache keys add-on art by path, and the paths had not changed. The icons and
  fanart of all four add-ons now use new files (`meganexus_icon.png`,
  `meganexus_fanart.png`), so Kodi loads the MegaNexus artwork at once.

## Add-on names

* The program add-on (`script.nuvio`), the skin and the screensaver are now
  named **MegaNexus** in Kodi (were "Nuvio"); provider is MegaNexus. Settings
  rows say *Use MegaNexus skin* and *MegaNexus screensaver*. Add-on IDs are
  unchanged, so updates and settings carry over.

## Wording and colours

* "Welcome to Nuvio" is gone: the empty Home row says **Welcome to MegaNexus**
  and points to *HUB Settings › Set up on phone*; the backend menu says
  *Welcome to MegaNexus — start setup*; setup dialogs are titled
  *MegaNexus setup*. (Nuvio account names stay.)
* The remaining greyish-violet colours (HUB Settings focus bar, IPTV, person
  and source pills) are now logo blue: `make_blue_theme.py` also converts
  low-saturation violet (above 12 %), so neutral greys stay neutral.

Checks: `test_nuvio_625.py` (no "Welcome to Nuvio"/"Nuvio setup" in shipped
code, settings focus colour is blue, collections pulled only when asked,
collection metadata switched ON, layout saved and reported, own vs automatic
layout, phone sign-in imports with/without collections, TV sign-in import), `test_nuvio_621` violet check now also
covers greyish violet; `python review/check_625.py`, release guard, builder,
packaged smoke test.
