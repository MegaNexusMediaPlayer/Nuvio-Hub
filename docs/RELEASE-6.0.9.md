# Nuvio Hub 6.0.9 — test candidate

Prepared 30 September 2026 from the supplied 6.0.8 source. This package has not been pushed to the GitHub main branch or published as a release. All four add-on IDs and profile paths remain unchanged. Installation should retain existing accounts, providers, collections, IPTV configuration and progress; back up your Kodi profile before testing.

## Navigation and native playback

Home now has **HUB** after **Settings**. Back at Home focuses Home rather than closing to the launcher. Back inside a collection/search returns to Home; the launcher is an explicit HUB action. Returning from internal Settings no longer requests Kodi Home.

A retained ordinary `WindowXML` stays beneath Nuvio's temporary modal pages while the native fullscreen player owns input. It shows a neutral/title-art background, not the HUB launcher, during page restoration. The parent Python page and selected item are retained. This is not a permanent EPG overlay on fullscreen video.

IPTV first click opens a native PVR preview; a second click on the same currently playing channel opens native fullscreen. The guide is hidden natively during fullscreen, then its existing groups, channel selection and EPG are restored. Stop/end does not automatically restart the last channel. Back/Stop in the IPTV page does not close it; the explicit HUB button leaves it. Fullscreen Back returns to preview/guide; another Back stops the preview and stays in the guide.

`Player.Open(channelid)` follows Kodi's PVR fullscreen preference, not an invented JSON-RPC `windowed` option. The code reads that preference, temporarily selects preview, issues the synchronous channel-open call and restores the previous value in `finally`. It never changes desktop fullscreen, resolution or zoom. Failure to establish preview is reported rather than intentionally starting fullscreen.

## Weather, clock and screensaver

**Settings → Skin configuration → Weather and clock · all Nuvio screens** is persistent and migrates the existing skin hide flag. Home, title/catalog pages, IPTV and the screensaver use the same gate. The supplied HUB launcher has no dynamic clock/weather widgets.

**Settings → Skin configuration → Screensaver media** selects an image/GIF or a video file. The chooser accepts MP4, M4V, MKV, WebM, MOV, AVI, TS and M2TS. Files may be local or accessible through Kodi's file browser, such as an SMB share. Videos loop silently in the screensaver's own video control. Missing/unplayable files fall back to artwork; existing paused/playing media is never replaced. The previous mute state is restored. The saved image remains the fallback when video mode is selected.

Because starting video deactivates Kodi's registered screensaver, video mode hands off to a separate ordinary script before playback. Startup is token-bound and time-limited. Stop cleanup checks item ownership, with a backend guard for a cancelled late AV start. It does not clear the user's video playlist or create a watched title for the screensaver. Input exits the video screensaver.

## Actors and search

Search is titled **Search movies, series, actors & more** and uses every compatible searchable catalog advertised by the selected metadata provider, including people/anime/custom types. Extra categories beyond the Home row limit remain accessible in a More search categories row. Browse all preserves the original query. Actor cards route to filmography, not a movie playback ID.

Actor filmography supports movie and series People Search catalogs, modern/legacy manifest extras, provider-relative artwork and optional authenticated TMDb combined cast/crew credits. A known TMDb person ID is preferred when a key is available; unrelated IMDb/TVDB IDs are not treated as TMDb numbers. Cancellation does not open a late empty page. Provider errors are shown rather than swallowed into an empty catalog.

**Configuration requirement:** enable movie and series People Search in your metadata provider and refresh/re-import that manifest. When the provider does not expose this capability, set an optional TMDb API key under **Settings → Add-ons → Actor search fallback**. A provider's unavailable API cannot be replaced by renaming the search heading. With a TMDb key, an Actors & crew result row is also available. Filmographies may be incomplete if the provider returns partial results.

## Multiple stream add-ons

Under **Settings → Add-ons**, **Stream add-ons** is immediately after metadata selection. Add manifest URLs and switch each stream-capable provider on/off independently. Changing these switches does not change metadata selection. New providers are opt-in; an unset configuration retains the 6.0.8 single-provider choice. An explicitly empty selection means all off.

Enabled compatible providers are queried with bounded concurrency. Responses retain provider order, source order, duplicates, labels, headers and subtitles. Each displayed source includes the configured add-on name. Its playback/subtitle context uses that actual source provider, not the first provider in the list. One failed provider does not erase successful sources from others; failure summaries exclude configured URLs/tokens.

## Validation status

See `review/QA-6.0.9.md` and `review/results-6.0.9.json` in the source archive for the recorded test scope and device checklist. The automated checks use explicit Kodi API boundary stubs. They do not prove Windows rendering, CoreELEC hardware video output, or installation/playback on Kodi 22 RC1. No Kodi/PVR server, user account, real metadata profile or device was connected for these runtime checks.

## Install or rebuild

Stop playback, close the Nuvio frontend, install `Nuvio-Hub-Complete-6.0.9.zip`, open the Nuvio Hub backend once to update the three bundled components, then restart Kodi. Do not uninstall the existing add-on or delete its data to update. A profile backup is recommended for rollback.

The source ZIP intentionally excludes generated installers, nested component ZIPs, test profiles and `.git`. Build the installer from the source root with:

```sh
python review/build_bundle.py --output Nuvio-Hub-Complete-6.0.9.zip
python review/check_packaged_build.py Nuvio-Hub-Complete-6.0.9.zip
```

The supplied patch is incremental **6.0.8 → 6.0.9**, not a patch directly against the still-6.0.7 GitHub main. Apply it to the matching 6.0.8 baseline, then rebuild. The complete source includes both the earlier 6.0.8 work and these new changes.
