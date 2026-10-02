# Nuvio Hub 6.0.37 — Kodi 22 RC1, touch screens, Trakt/TMDB collections, security notice, Local storage

Prepared 2 October 2026 (test build, not released).

* **Kodi 22 RC1: MegaNexus did not open** ("Could not open the interface").
  Kodi 22 RC1 builds its Python bindings with SWIG 4.5 and locks the window
  classes after creation (`cannot modify read-only attribute
  'SettingsPage.onInit'`). `nuvio_ui/dialog.py` wrapped onInit / onClick /
  onAction by changing each window class after creation. The wrappers are now
  set on each window object when it is created, with the same behaviour.
  Kodi 21.3 and 22 beta 2 call these methods through the window object
  (`PyObject_CallMethod(self, ...)` in their generated bindings), so they
  work as before. Tested on Kodi 22 RC1 (Flatpak) on Linux.
* When the interface fails, kodi.log now has the full traceback instead of
  only "Interface failed".
* **Touch screens:** dragging up or down with the finger starting on a poster
  did not move Home, because Kodi gives a horizontal row the whole drag. On
  Home, Sport and Library a vertical drag now steps between rows - the same
  Up / Down a remote sends - and while a finger is on the screen Home does
  not repaint rows or start previews (a row reset mid-drag felt like the
  posters got stuck). Only Kodi's touch gesture actions are used: remote,
  mouse and keyboard behave exactly as before, and nothing changes in size.

* **Trakt lists in collections**, like the Nuvio apps. A collection source
  `{"provider": "trakt", "traktListId": ..., "mediaType": "MOVIE"|"TV",
  "sortBy", "sortHow"}` from a Nuvio export becomes a row loaded like an
  add-on catalog (same cache, paged by 50). Public lists need no sign-in;
  with Trakt connected the request is signed, so private lists work too.
* **TMDB sources in collections** with the user's own TMDb API key (v3 key
  or v4 token): LIST, COLLECTION, COMPANY, NETWORK, PERSON, DIRECTOR and
  DISCOVER with Nuvio's filters and sort. Without a key the row says
  "Add your TMDb API key". The key is set in HUB Settings > Add-ons >
  TMDb API key or on the phone setup page (Add-ons tab); the phone never
  gets the key back, only whether one is set.
* **Security notice:** all-in-one add-ons with background services
  (Umbrella, Fen, Fen Light, POV, Seren, The Crew, Shadow, Otaku, Scrubs v2,
  Asgard, Homelander, Coalition, Ezra, The Magic Dragon, Red Light, The
  Chains), Open Wizard and - when MegaNexus' own Trakt is connected - the
  Trakt add-on (every title logged twice) overload Kodi. When one of them is
  enabled, MegaNexus shows a notice with a shield, the add-ons it found and
  two choices: a clean Kodi install is recommended for best performance, or
  **Turn them off** (one click, nothing deleted, reversible in Add-ons).
  **Skip** is remembered until another such add-on appears. Maintenance >
  System check shows it again at any time.

* **Local storage:** movies and series on the device itself (USB disk, NAS,
  SMB/NFS share) in MegaNexus. HUB Settings > Local storage: show the rows on
  Home, how many titles Kodi found, add a folder (opens Kodi's video sources
  with short steps: Add videos, set Movies or TV shows), scan for new files,
  remove missing files. Home gets **Local Movies** and **Local Series** rows
  (newest first; only kinds that have titles), switched on there or in
  Collections > Home rows > Local. A movie plays at once (Resume / From the
  beginning when Kodi has a resume point); a series opens a season and episode
  list on the next episode to watch. Playback opens Kodi's own library item,
  so its resume points and watched marks keep working, and these files never
  go to stream add-ons. Read through Kodi JSON-RPC (VideoLibrary.*), no
  network.

* **Set up on phone behind a firewall:** the phone page used a random port,
  so a device firewall with default-deny (ufw on a Linux PC) dropped the phone
  every time. It now uses port **8765** (any free port only when 8765 is
  busy), which can be allowed once, e.g. `sudo ufw allow from 192.168.0.0/16
  to any port 8765 proto tcp`. After 30 s without the phone the TV says so.

Checks: `test_nuvio_637.py`; `python review/check_637.py`, release guard,
builder, packaged smoke test.
