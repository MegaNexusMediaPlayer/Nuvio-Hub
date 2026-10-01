# Nuvio Hub 6.0.27 — posters for every row, 256 MiB image RAM, IMDb trailers

Prepared 1 October 2026 from 6.0.26.

## Posters

* The start screen counted posters only from catalog pages that were still
  in the 40 MiB in-memory page cache: about 75 rich catalogs fit, so the rest
  got no posters ahead of time and two different layouts both showed 738.
  Pages are now read from the disk cache too.
* The start screen loads the posters of the **first 3 rows** only (short).
  Home's existing background warm-up then loads the posters of **all other
  rows**, pausing while you navigate, open a collection or play video. Before,
  the start screen marked the session as done, so that warm-up never ran.

## Image RAM

* New default image cache **RAM · 256 MiB** (about 800 posters take ~90 MiB,
  so a full Home of ~130 catalogs fits). Earlier RAM 150/200 settings move to
  256 MiB; disk and off choices stay.

## Trailers

* Default trailer source is **IMDb, then add-on trailer / YouTube**: IMDb first
  (no add-on needed), then the metadata add-on's own trailer - a direct video
  file plays without any add-on, a YouTube link only when the YouTube add-on
  is installed, so YouTube is optional. (IMDb-only would drop the add-ons' own
  trailers; it stays selectable.) **Automatic trailers are ON** by default.
  Existing profiles that still had the old defaults (YouTube-then-IMDb,
  trailers off) switch once; any later choice in Settings > Trailers is kept.

## Restart after an automatic update

* When an update (Kodi repository or ZIP) replaced the interface, skin and
  screensaver while Kodi was running, parts of the old ones stayed loaded until
  a restart - e.g. the small trailer video on an Android tablet played sound
  without picture. The service now asks **"MegaNexus X is installed. Restart
  Kodi now?"** as soon as no video plays and MegaNexus is closed (the same
  question the GitHub updater already used; *Later* reminds at the next
  MegaNexus entry). A first install does not ask.

## numb3rs check (no change)

Nothing installs or loads the numb3rs collections unless *Collections >
Default collections > numb3rs* is chosen (or a Nuvio profile's own collections
are imported). The default Cinemeta layout reuses bundled cover images that
originate from the same artwork set; they are local pictures, not numb3rs
catalogs.

Checks: `test_nuvio_627.py` (restart question after an automatic update but
not after a first install, add-on trailers without YouTube, disk page read, first-rows preload and front
marker, background continuation, 256 MiB default and upgrades, IMDb default
and order, one-time trailer migration that keeps later choices, service
call). Updated expectations: 6.0.10 RAM preset upgrade, 6.0.11/6.0.12 trailer
source default, 6.0.18 poster preload marker. `python review/check_627.py`,
release guard, builder, packaged smoke test.
