# Nuvio Hub 6.0.39 — test build: Android fix, touch, sync, RAM, Plex and Jellyfin (beta)

Prepared 2 October 2026 (test build, not released; released as 6.0.40 without the touch changes). Built on 6.0.38 (the
6.0.36 code) with all 6.0.37 features restored (Kodi 22 RC1, Trakt / TMDB
collection sources, Local storage, security notice, phone setup port 8765;
see [RELEASE-6.0.37.md](RELEASE-6.0.37.md)).

## The 6.0.37 Android error

"Could not open the interface" when opening a catalog (e.g. Action) on
Android Kodi 22 beta. Cause: the 6.0.37 touch code kept the finger state in
`self._touch`, the name of a Home method that every click calls first. After
the first swipe the method was gone, the next click raised `TypeError` and
the whole interface closed. Only touch screens send swipes, so remote and PC
never showed it. Fixed: touch state has its own names, a regression test
swipes and then clicks, and a failing click or key is now logged with its
traceback and shown as a short notification - MegaNexus stays open.

## Touch

* A row step follows the finger: about 11 % of the screen height for a slow
  drag, 7 % for a fast one (was 16 % for every drag, so short swipes did
  nothing and several were needed).
* A fast flick keeps gliding a few rows after the finger lifts and slows down;
  a new touch stops it at once.
* Touch never leaves the rows for the header (it used to land on Home).
  Remote, mouse and keyboard are unchanged.

## Tracking services

* **Simkl:** watched lists are synced the way Simkl asks apps to sync:
  `/sync/activities` first (one small request), then only the lists that
  changed and only the titles changed since the last sync (`date_from`). Before,
  all three full lists were downloaded every two minutes, even during
  playback.
* **No watched downloads while a video plays** (Simkl and Trakt); they catch
  up right after. Sending progress continues.
* **Trakt watched marks:** Trakt-only users get watched badges and episode
  marks (`/sync/last_activities`, then `/sync/watched/*` only when changed).
* **Mark watched** on a title page saves to Simkl and/or Trakt, whichever is
  connected.
* **Trakt offline queue:** a finished watch that could not reach Trakt is kept
  and sent later as history with its real watch time.
* **Trakt 401 / 429:** an expired sign-in is refreshed once and the request
  retried; "too many requests" waits as long as Trakt asks (up to 10 s). Token
  refresh is serialized (Trakt revokes a used refresh token).

## Memory

HUB Settings > Performance > image cache has **Automatic** (new default): by
the device's total RAM, posters / catalog pages / details get 96 / 32 / 12 MiB
on 1-2.5 GB devices (Fire TV Stick, Mi Box), 160 / 64 / 24 MiB up to 4.5 GB
and the full 256 / 96 / 32 MiB above. Earlier RAM presets move to Automatic
once; disk and off choices are kept, and every preset can still be chosen.

## Plex and Jellyfin / Emby (beta)

Everything is off until you connect a server (HUB Settings > Accounts &
tracking services > Plex (beta) / Jellyfin / Emby (beta), or the phone setup
page). Nothing is requested or loaded before that.

* **Your server first:** when a title plays, your servers are searched by its
  IMDb / TMDb ID (episodes by season and number) at the same time as the
  stream add-ons, and their copies are listed first ("Plex · Home · 4K · HDR ·
  12 GB"), so autoplay prefers them. Progress and watched go back to the
  server.
* **Home rows:** "<Server> · Continue watching" and "· Recently added",
  switched on in Collections > Home rows. Posters come from the server,
  resized there (500 px); MegaNexus metadata only opens the title page of a
  title with an IMDb / TMDb ID - no second poster download. Episodes, resumes
  and home videos play straight from the server.
* **Jellyfin 12 (September 2026)** removed the old Emby-style sign-in headers,
  `api_key` and `/emby` paths, so the earlier client could not work with it.
  Jellyfin servers now use the standard `Authorization: MediaBrowser ...
  Token="..."` header, `ApiKey` and root paths (valid since Jellyfin 10.x);
  Emby servers keep their own scheme. The server type is read from
  `/System/Info/Public`. **Quick Connect:** a 6-digit code approved in another
  Jellyfin app.
* **Plex:** servers come from `clients.plex.tv/api/v2/resources` (the older
  XML list only as fallback). Plex needs Plex Pass or Remote Watch Pass to
  stream outside the home network; such a copy says so in the list.
* **Finding your copy on Jellyfin:** Jellyfin has no filter by IMDb / TMDb ID
  (it ignores Emby's `AnyProviderIdEquals` and returns the first library
  items - seen on Jellyfin 12.1 and 13.0), so the old client could offer an
  unrelated film as "your copy". The IDs of all movies and series are now
  read once (IDs only) and kept 15 minutes; a copy is offered only when its
  ID matches. Emby results are checked the same way.
* **Live check** on the public Jellyfin demo servers (12.1 stable, 13.0
  unstable): server type, sign-in, libraries, Continue watching / Next up /
  Recently added, a movie and an episode found by ID, the stream (HTTP 206)
  and poster (200) URLs, and playback reports all worked; the old Emby-style
  sign-in header was refused (400) and `/emby` paths returned 404 - the old
  client could not have worked with Jellyfin 12.
* Local storage is labelled beta too.

Checks: `test_nuvio_639.py`; `python review/check_639.py`, release guard
6.0.39, builder, packaged smoke test. Not verified on devices: Plex (no test
account), Jellyfin 10.10 / 11, Emby, Android touch feel, Trakt / Simkl live
accounts, memory on a 1-2 GB device.
