# Nuvio Hub 6.0.35 — GitHub issues #3–#9, Library, Sports, Title options

Prepared 2 October 2026 from 6.0.34 (test build, not released).

## GitHub issues

* **#3 Stream add-ons chosen on the phone went back to one.** A one-time
  6.0.12 repair ("keep one stream add-on when all are ON") ran at the first
  MegaNexus start of a fresh install, right after the phone setup. It is
  removed. Add-ons imported from the Nuvio account are now switched ON in
  both lists (playback no longer waits for the slowest stream add-on).
* **#4 Trailer: black picture, sound only, box stuck.** With Kodi's "Adjust
  display refresh rate" on, a trailer or preview in a small window switched
  the TV mode; on some CoreELEC builds the video then stays black.
  `resources/lib/refresh_guard.py` turns the setting off while a trailer,
  Home preview or Sports preview plays and puts it back afterwards (also
  after a crash, at the next start). When the setting is already off nothing
  is touched, so devices that work today behave exactly as before.
* **#5 Continue Watching: Remove and Play from the beginning** in Title
  options. Remove only hides the title (progress and watched state stay as
  they are); it returns by itself once the title is played again.
* **#6 Finished titles stayed in Continue Watching.** Watched now at 90 %
  (Simkl 80 %), like the Nuvio apps, instead of 95 % — titles stopped in the
  end credits leave the row and their next episode appears.
* **#7 Old shows in Next episode.** Continue Watching shows titles watched in
  the last 60 days (30 / 60 / 90 / no limit) and "airs tomorrow" cards can be
  switched off: HUB Settings > Continue Watching. Like in the Nuvio apps these
  are settings of this device.
* **#8 Sports add-ons.** Recognised automatically (sports types such as
  `sport`/`events`, or a clearly sports name) and kept out of the movie and
  series Home, Search, Continue Watching and the tracking services — like IPTV
  channels. They have their own **Sport** screen (HUB button between IPTV
  Channels and HUB Settings): logo and Home / Settings / HUB at the top,
  "Sports", a glass box with the streams of the selected event, the small
  video (plays the first stream automatically, OK = full screen) and one row
  per catalog (Live and Today first). Its posters are loaded into the same
  image RAM behind its own loading screen. Playback is a preview to the
  playback service, so nothing is tracked. Setting: HUB Settings > Playback >
  "Sport · play the selected event in the small video".
* **#9 Catalog rows on Home.** HUB Settings > Home & appearance > Home layout
  (and the phone's Display tab): *MegaNexus collections* (default, as before)
  or *Catalog rows* — every catalog is a poster row right on Home, like the
  Nuvio apps.

## Also

* **Title options** float over the screen (no dimming, translucent glass
  panel) and list only what fits the card: Play from the beginning, Choose
  stream manually, Remove from Continue Watching, Add to / Remove from
  Library, More like this, Info. Home stays visible; only choices that open a
  screen hide it. **More like this** opens straight as a grid.
* **Library** (Home header, between Home and Search; the header buttons were
  re-spaced evenly): title, two pills **Local** and **Tracking Services**, rows
  Movies and Series. It opens on Tracking Services (Trakt watchlist + Simkl
  Plan to Watch) when one is connected, else on Local. "Add to Library" saves
  locally (synced with the Nuvio account library) and also to Trakt / Simkl
  when connected; it no longer requires a Simkl sign-in.
* **Trakt** in HUB Settings > Accounts & tracking services (connect with code,
  scrobble, Continue Watching import, watchlist in Library).
* **Phone setup: Tracking services** right after the Nuvio account. Connect
  opens the Trakt / Simkl activation page in a new tab and shows the code; the
  TV waits for the approval and saves the connection.
* **Skip on the poster loading screen works again.** The loading loops waited
  with `concurrent.futures`; Kodi delivers a window's onAction (Back) only
  while the script waits in Kodi (`Monitor.waitForAbort`). They now do.
* HUB buttons are a little narrower to fit six (Sport added).

## After the first test build

* Sport: only **LIVE** events look for streams, and only after the cursor
  rests **5 seconds**; upcoming events never do (OK says "Not live yet").
  OK / Enter on the playing stream (or event) goes full screen: the player is
  now recognised by its item token - live HLS streams report another file
  path, so the old path check restarted the stream instead.
* Every sports add-on gets its metadata and stream switches ON (each serves
  its own metadata).
* Catalog rows: Movies and Series are two rows, one under the other.
* Library: row titles bold like everywhere else; the second tab is named after
  the connected services ("Trakt · Simkl"; `library.TRACKERS` is the one list
  to extend); new **Calendar** tab - everything in the Library by the month
  it was added (month and year only); a small badge on each card shows where
  it comes from (Local / Trakt / Simkl / MDBList). Watchlist titles keep the
  date they were first seen when the service sends none (Simkl's
  `added_to_watchlist_at` is used).
* Phone setup: "Copy code" works - `navigator.clipboard` exists only on https
  pages and this page is plain http on the home network; it falls back to a
  selected text area, and the code can be selected with one tap.
* Nuvio collections named **World** are imported again (only Sports stays out
  of the MegaNexus Home).

Checks: `test_nuvio_635.py` (37 tests) plus updated 601, 602, 605, 612, 615,
618, 628, 631, home_iptv and reliability expectations. `python
review/check_635.py`, release guard, builder, packaged smoke test. The Sports
backend was also run against https://sports.highfly.dev/manifest.json
(detection, 17 catalogs, a page of 32 events, streams).
