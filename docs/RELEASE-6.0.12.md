# Nuvio Hub 6.0.12 — playback speed, trailers, details and ratings

Prepared 30 September 2026 from the local 6.0.11 candidate. Status: **local test
candidate**. Nothing has been pushed to GitHub `main` and no release has been
published. 6.0.11 changes are described in `RELEASE-6.0.11.md`.

## 1. "Loading video" was far too long (6.0.11 regression)

Cause: 6.0.11 switched every never-configured or Nuvio-imported stream add-on
ON, and source loading waited for **every** enabled add-on (up to 20 s each,
four at a time) before anything could play.

* Source loading now starts all enabled stream add-ons at once and, as soon as
  one returns streams, gives the others 2.5 s more. Slower add-ons are skipped
  for that play (reported separately from failed ones) instead of holding the
  screen. Results keep the configured add-on order. All failing still reports
  an error.
* Stream add-ons that were never configured: one is ON (the earlier choice, else
  an AIOStreams-style aggregator, else the first). A Nuvio import switches one
  on only when none is on. Metadata add-ons keep the 6.0.11 behaviour.
* One-time repair on the first Home entry: if three or more stream add-ons are
  all ON (the 6.0.11 state), only the preferred one stays ON and a notification
  says which. It never runs again, so later choices are kept.
* Background catalog refreshes, collection prefetch and poster warming wait
  while a video is starting or playing (Home trailer previews do not count).

## 2. Leaving a video

* The player-exit wait polls twice as often, and the wait for the service's
  "progress saved" flag is capped at 0.8 s (it is normally set in milliseconds).
* The details page that reappears after playback reuses its loaded
  recommendations instead of fetching them again.

## 3. Details

* Series no longer show a "Loading episodes…" banner. The banner was also never
  cleared once episodes had loaded; now the row simply fills when data arrives,
  and "No episodes supplied" appears only when the metadata really has none.

## 4. Trailers

* **IMDb trailers stream directly** from IMDb's video CDN instead of being
  downloaded first, so a preview or trailer starts in about a second.
* Settings > Trailers > **IMDb trailer quality · no add-on needed**: 480p
  (fastest start, default), 720p or 1080p. IMDb needs no Kodi add-on and no
  account; there is nothing else to configure.
* The default source is now **YouTube, then IMDb**: when a YouTube trailer cannot
  be resolved on the device (a common cause of "only the picture" previews on
  PCs, depending on the installed YouTube add-on version), IMDb is used. The next
  source is only asked when the previous candidate could not be used.
* Kodi's own trailer buttons no longer receive a YouTube link when the YouTube
  add-on is missing or the source is "IMDb" only — that link made Kodi offer to
  install the YouTube add-on.
* The YouTube row reads "Install (only for YouTube trailers)" when it is missing.

## 5. Ratings under the title

When the metadata add-on supplies a rating (`imdbRating`, `ratings.imdb`, or a
TMDb vote average), the Home hero shows it under the title in the top-left, e.g.
"2024 | Movie | IMDb 7.8". Nothing is shown when the add-on supplies none.
Settings > Appearance > **Ratings under the title** switches it on/off (on by
default).

## 6. Posters after restart or suspend

Once per Kodi session, when the image proxy's RAM holds fewer than 50 images (a
restart, or a suspend that dropped it), Home fills the first 6 posters of every
collection in the background from cached catalog pages — no catalog requests,
one image at a time, paused during playback. Collections opened later still fill
their images as before. Kodi's own texture cache keeps images it has already
shown regardless.

## 7. Automated checks

- `python review/check_612.py`: maintained suite including `test_nuvio_612.py`.
- `python review/check_608_rebrand_kodi22.py 6.0.12`, `review/build_bundle.py`,
  `review/check_packaged_build.py`: see the delivered report.
- Four older expectations were updated for intentional changes (extra
  `_nuvio_slow` key, YouTube-then-IMDb default, lazy trailer candidates, preview
  cache key) and each has new behavioural coverage.

## 8. Limits and manual checks

No device testing was possible here. Check on PC and CoreELEC: time from Play to
video with several stream add-ons ON; the one-time stream repair notice; leaving
a video back to Details; Home trailer previews with each source; the Details
trailer button; a series whose metadata loads slowly; ratings with and without
the setting; poster refill after a Kodi restart. The IMDb endpoint is unofficial
and may change; YouTube is then used when available.
