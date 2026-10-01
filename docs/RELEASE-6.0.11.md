# Nuvio Hub 6.0.11 — Home responsiveness, fixes and checks

Prepared 30 September 2026 from the local 6.0.10 candidate source. Status:
**local test candidate**. Nothing has been pushed to GitHub `main` and no
release has been published.

## 0. Compared with the published 6.0.7 (GitHub main)

GitHub `main` (latest commit `6e585a2`) still contains 6.0.7. The 6.0.10 source
changes 208 files (156 Python files) relative to it; see `RELEASE-6.0.8.md`,
`RELEASE-6.0.9.md` and `RELEASE-6.0.10.md`: the complete Nuvio Hub rename of
internal packages and resources, removal of the Arabic UI layer, validated
collections and multiple metadata add-ons, an actor page, Unicode display,
corrected Nuvio progress wire format with an outbox sync, a persistent browse
cache and bounded startup warm-up. The only GitHub change made after the 6.0.7
code (an `docs/INSTALL.md` note about AIOMetadata/numb3rs.stream and Nuvio web
collections) is carried into this version.

## 1. Collections open immediately

* **Stale-while-revalidate catalog cache.** A page is fresh for 30 minutes and
  stays usable for up to 7 more days. An older page is shown at once and one
  background worker (bounded 64-entry queue, never blocking) refreshes it; the
  next visit shows the new titles. Previously every collection click after 30
  minutes waited for the network and Home showed "Preparing your collections"
  again for up to 40 seconds. Search results have no stale window (120 s).
  The cache now lives in `cache/browse611.db`; valid pages from `browse610.db`
  are imported once on first start and the old file is removed.
* **Synchronous paint from cache.** An opened collection draws its rows from
  memory (and SQLite point lookups for the first six rows) with no network work
  in the GUI callback. "Loading titles" remains only for a real cache miss.
* **Prefetch under the cursor.** When a collection tile stays selected for
  250 ms, one background worker loads it and its neighbours plus the first 6
  posters into the image proxy. Moving to another tile cancels prefetches that
  have not started. A Settings change discards late prefetch results.
* **Parallel sources.** A collection with films and series fetches its sources
  concurrently (at most 4); one failing source no longer blanks the row. The
  same applies to "Browse all" pages; a failed source is retried on "Load more".
* **No redundant redraws.** When a background load returns exactly the rows
  already shown, the list is not rebuilt (no flicker, focus kept). Home uses 4
  row workers (was 2) and applies results every 50 ms (was 100 ms).
* **Startup check** reads all cached pages with one SQLite query instead of one
  connection per catalog.

## 2. Less work on the GUI thread

* `simkl_watched.snapshot()` used to deep-copy the whole Simkl history for every
  painted row, card and return from Details. The merged view is now rebuilt only
  when the Simkl file or local playback database changes.
* `metadata_providers.signature()` (a hash of every manifest) is memoized until
  `providers.json` or the switches change; it runs when Details open.
* The collection profile is parsed once per file change; animation settings and
  `collection_animations.json` are read once per Home build, not per group.

## 3. Artwork

* The image proxy no longer **drops** the ninth concurrent request (that left
  blank cards while scrolling): up to 48 queued requests, 6 download workers.
* Downloads use the shared urllib3 keep-alive pool (no new TLS handshake per
  image); without urllib3 the previous urllib path is used.

## 4. Fixed defects

* **Continue Watching** no longer jumps back to the first title after returning
  from Details/Settings; the reset to the newest title happens only on a new Home
  entry. The row is no longer built twice on entry, and a progress write during
  that build is still detected.
* `plugin.py`: the cinematic source window is not in the Kodi bundle, so the
  fallback to the native dialog failed with `NameError: log` under the default
  setting. The same NameError hit a failed MDBList warm-up.
* `plugin.py`: Plex English titles (`tmdb_direct`) silently never worked because
  of an undefined name swallowed by `except`.
* `favorites_store.py`: any failing watchlist mirror (Trakt/Simkl/MDBList) aborted
  the whole sync with `NameError: xbmc`.
* "Browse all" now normalizes artwork URLs the same way as Home (relative
  Plex/Emby paths).

## 5. Setup, metadata and collection checks no longer lock Home

Reported: metadata blocked entering Home, collections imported from Nuvio
(which work in Nuvio) always ended with "Collection check failed", and the
collection editor showed only "2 catalogs" with no names or switches.

* **Add-on switches.** A metadata or stream add-on list that was never
  configured now has every installed add-on ON (a single earlier choice is
  kept). Add-ons imported from a Nuvio profile are switched ON; an explicit OFF
  is still respected. If all add-ons of a kind are OFF, entering Home offers to
  switch them on in one step, and the setup menu heading names what is missing
  (e.g. "all metadata add-ons are OFF; collections not checked yet"). Importing
  or editing collections that use an OFF metadata add-on asks to switch it on.
* **Catalog matching.** Nuvio exports carry no local provider ID, so an unknown
  `providerId` is a preference only. The same add-on installed twice resolves to
  the exported binding, then the enabled metadata add-on, then the first install
  (it used to fail as "ambiguous"). The same manifest ID written with different
  separators (`aio-metadata`/`aiometadata`) matches; a provider name still never
  proves identity.
* **Collection check.** One unavailable catalog no longer rejects the whole
  import. Each source is either ready, skipped (catalog not installed, add-on
  OFF, required filter missing, wrong item type, sampled title resolves to a
  different title) or ready with a warning (timeout, temporarily empty catalog,
  filter value not listed in the manifest). The import is saved when at least one
  catalog works and a summary lists what was skipped. Metadata identity is
  sampled for up to 16 catalogs; catalog pages come from and warm the Home cache,
  so a recheck after a small edit is fast. "Recheck current collections" is also
  in the setup menu.
* **Collection editor.** "Linked metadata catalogs" shows "1 of 2 ON · Popular
  (Movies) …" and opens a page listing every linked catalog by add-on, name, type
  and genre, each with its own On/Off switch, plus "Add or change catalogs…". A
  switched-off catalog is kept in the collection but not loaded or checked. The
  genre-filter picker uses the same names.

## 6. IMDb trailers

Settings > Trailers > **Trailer source**: YouTube (default, as before), IMDb,
IMDb then YouTube, or YouTube then IMDb. IMDb trailers come from IMDb's public
GraphQL endpoint as direct MP4 files (480p first, then SD/720p/1080p), so no
YouTube add-on is needed. They use the existing download/cache/playback path for
both Home previews and the Details trailer button; a too-large or failed file
falls back to the next candidate. A Home focus asks the second source only when
the preferred one has nothing. Lookups are cached for 30 minutes (misses for
2 minutes). Live check on 30 Sep 2026: lookup about 0.5 s, 480p trailer
(26.6 MB) downloaded and cached in about 4 s. IMDb may change or restrict this
endpoint; then the other source is used.

## 7. Retired name removed everywhere

The retired pre-rename name no longer appears in any source, setting, string,
test, document or review tool. Nothing was simply deleted; every feature was
renamed and stays connected:

* Upgrade identifiers (old add-on ID, hidden migration settings, old config
  backup key, old TMDb Helper player and keymap names) live in
  `resources/lib/legacy_names.py`, assembled at runtime. Profiles from 6.0.7
  and older are still migrated, old backups still import and the old player and
  keymap files are still cleaned up. If the old hidden settings cannot be read,
  an already configured profile (providers or collections present) is treated
  as migrated, so its settings are never reset to defaults.
* External AI-subtitles/IPTV service: `subtitle_service_info`,
  `subtitle_service_link` and `subtitle_service_unlink` routes (previously
  redirected to Settings and unreachable) now work. Linking asks for the API key
  when none is stored (`nuviohub_service_api_key`, optional
  `nuviohub_service_base_url`). Quality feedback moved to
  `subtitle_feedback.py`; the `subs_feedback_bad` route is unchanged.
* The hidden Pro IPTV folder-view flag is now `nuviohub_iptv_force_folders`
  (carried over from the old setting). AI-subtitle classification, bridge/Plexio
  provider detection and artwork host rules keep their behaviour.
* Internal helper names (`_library_to_local`, `_addons_to_local`,
  `_progress_to_local`, `_nuvio_player_url`) and the test package alias
  (`nuviolib`) were renamed with all call sites.
* `review/check_608_rebrand_kodi22.py` now fails the release if the retired name
  appears anywhere in repository text, including the licenses. The three
  `LICENSE.txt` files name "Nuvio Hub contributors" as copyright holder.
* The source acknowledgement sentence was removed from all `ATTRIBUTION.md` files.
* Two legacy tests that expected stale names now pass.

## 8. Automated checks (Python 3.14, Kodi/HTTP stubs, real SQLite)

- `python review/check_611.py`: maintained suite PASS (337 existing, 3 updated for the intentional
  collection-check change, + 64 new in `test_nuvio_611.py`), runtime Python 3.8 grammar parse, XML and JSON parse.
- `python review/check_608_rebrand_kodi22.py 6.0.11`: PASS.
- `review/build_bundle.py` + `review/check_packaged_build.py`: PASS (modules
  imported from the expanded ZIP, XML asset references, all components 6.0.11).
- The new NameError regression test fails on 6.0.10 code and passes on 6.0.11.
- Older tests outside the maintained set (`unittest discover`): no new failures
  compared with 6.0.10; two stale failures fixed (remaining ones encode obsolete
  4.x/5.x behaviour, as before).

## 9. Limits

These are architectural improvements verified by tests, **not a measured speedup
on a device**. No manual testing on Kodi 21/22, CoreELEC or Windows was done.
Check: cold and warm Home entry, opening a collection after more than 30 minutes
(stale display plus refresh), fast scrolling across collections (prefetch,
posters), returning from Details to Continue Watching, running without urllib3,
offline use with a stale cache, and memory use. A stale page can show older
titles for up to 7 days if refreshing keeps failing (e.g. provider offline).

## 10. Delivery and rollback

Install `Nuvio-Hub-Complete-6.0.11.zip` over 6.0.10 as before: back up the
profile, stop video, close the frontend, install the ZIP, open the backend Nuvio
Hub once, restart Kodi. The browse cache moves to `browse611.db` automatically.
Rolling back to 6.0.10 needs no deletion: 6.0.10 uses its own `browse610.db`,
which then starts empty (the collection preparation screen appears once), and
`browse611.db` may be deleted.
