# Nuvio Hub 6.0.16 — GitHub updates, Ko-fi, Cinemeta rules, seamless screensaver

Prepared 30 September 2026 from the local 6.0.15 candidate. Status: **local test
candidate**; nothing pushed or published.

## 1. Automatic updates from GitHub

`resources/lib/updater.py` reads the latest release of
`MegaNexusMediaPlayer/Nuvio-Hub` and its asset `Nuvio-Hub-Complete-<version>.zip`
(tag `v<version>`, e.g. the published
`releases/download/v6.0.7/Nuvio-Hub-Complete-6.0.7.zip`). Versions compare
numerically, so an older release is never installed over a newer one.

* The service checks 90 s after Kodi starts and then every 12 hours, never while
  a video plays or the Nuvio interface is open.
* **Settings > Maintenance & updates**: *Check for updates* (shows installed vs
  latest, installs on confirmation, offers a Kodi restart) and *Automatic updates
  from GitHub* (ON by default; OFF only notifies that a version is available).
* Install: download (200 MiB cap) → SHA-256 check against the `.sha256` asset
  when published → archive check (only the backend folder, no unsafe paths,
  exact version, bundled interface present) → backend folder swapped with the old
  one kept in `installation-backups` → interface, skin and screensaver installed
  by the existing hash-checked bundle installer → `UpdateLocalAddons`. Any failure
  restores the previous backend; the three newest backups of each kind are kept.
* Live check (30 Sep 2026): the real `v6.0.7` release is detected with its
  checksum; installing it into a scratch folder over a 6.0.6 test install
  replaced all four components and kept backups in about 6 s.

To ship an update: publish a GitHub release tagged `v6.0.17` with
`Nuvio-Hub-Complete-6.0.17.zip` and `Nuvio-Hub-Complete-6.0.17.zip.sha256`.

## 2. Support · Ko-fi

**Settings > Support Nuvio Hub · Ko-fi** (also under Maintenance) shows a QR code
for https://ko-fi.com/master100janovic to scan with a phone. The QR image is
generated offline by `review/make_kofi_qr.py` and ships in the bundle (verified to
decode to the link).

## 3. Home layout and Cinemeta rules

* Collections you import, choose or edit always win and are never replaced.
* Otherwise, when an add-on you added offers movie/series catalogs, Home is laid
  out from them automatically: one row per add-on, one card per catalog (movies and
  series of the same catalog share a card; search/required-filter catalogs are
  skipped). It is rebuilt when those add-ons or catalogs change. With no such
  add-on, Home uses the Cinemeta collections. The 6.0.15 automatic Cinemeta layout
  is recognised and upgraded.
* Cinemeta is switched ON for metadata only while you have no other metadata
  add-on. If it was switched on automatically, adding another metadata add-on
  switches it OFF. **Settings > Add-ons > Metadata add-ons** always lists Cinemeta
  ("Built-in · no setup"; "Add" if missing); switching it by hand is remembered and
  never undone automatically.
* A copy of the Cinemeta manifest ships in `resources/cinemeta_manifest.json`, so
  it can be added offline; the live manifest is used when reachable.

## 4. Video screensaver: smooth loop, no artwork flashes

Each loop used to end the file; Kodi closed and reopened it, the video area was
empty for a moment and the Nuvio artwork showed through, and a slow reopen could
end the screensaver. Now the clip is rewound 0.35 s before its end, so the file is
never reopened; in video mode the background is black (no artwork); a short video
gap of up to 2 s no longer ends the screensaver. Artwork is still used when a
video cannot play.

## 5. Small video on CoreELEC and in IPTV

A black frame (`nuvio_video_vignette.png`: fully opaque at the rim, clear in the
middle) now covers the edges of the IPTV guide preview on every device, and of the
Home trailer preview on devices with a hardware video layer (CoreELEC, LibreELEC,
OSMC, Android — detected at session start). On PCs the Home preview keeps its
6.0.12 look. The IPTV top HUB button was removed; the bottom one remains.

## 6. Speed and image cache

* Background catalog revalidation now waits while any page you opened is loading
  (and 1.5 s after); it shares each host's rate limit with your requests.
* Catalog pages stay fresh for 3 h (was 30 min) before a background refresh, which
  cuts refresh traffic; older pages still show instantly and refresh behind.
* Posters in RAM: once per Kodi session (and after a suspend that emptied it) a
  screen of posters (12) for every collection is loaded into the image proxy until
  it holds 600 images, one at a time, pausing whenever you navigate, open a
  collection or play video; an interrupted run resumes in the next Home window.
  Hovering a collection warms 10 posters (was 6).

## 7. Checks and limits

`python review/check_616.py` (incl. `test_nuvio_616.py`),
`python review/check_608_rebrand_kodi22.py 6.0.16`, builder, packaged smoke.
Four older expectations changed intentionally (IPTV HUB id, settings row index,
warm-up threshold and thread arguments). Not tested on a device: please check the
frame on CoreELEC, the screensaver loop with your clip, the Ko-fi page, and an
update once a newer release is published.
