# Nuvio Hub 6.0.9 — local test candidate

Based on the supplied 6.0.8 source. The backend is **Nuvio Hub**; the interface, skin and screensaver are **Nuvio**. All four components use **6.0.9**, with unchanged add-on IDs and profile locations. This is a test candidate, not a device-verified Kodi 22 RC1 release.

Changes: explicit HUB button after Settings; Back stays inside frontend Home; a retained native base window avoids exposing the launcher between video and the restored page; one weather/clock preference; image/GIF or looping silent video screensaver; actor/search routing and clear provider errors; multiple independently enabled stream add-ons with per-source names; IPTV preview on first click and native fullscreen on the second click, returning to the retained guide.

Actor filmographies require advertised People Search catalogs in the metadata provider, or the optional TMDb key. A video screensaver does not replace paused media: it falls back to artwork. Video playback depends on Kodi/device codec support. Additional stream add-ons are opt-in; the old single-provider selection remains the upgrade default.

Stop playback and close the Nuvio interface, install `Nuvio-Hub-Complete-6.0.9.zip` through Kodi's Install from zip file, open Nuvio Hub once to update the bundled components, then restart Kodi. Keep the existing installation and userdata. Manual ZIP updates preserve accounts, providers, settings, collections, IPTV configuration and stored playback positions. The About screen reads the installed interface version.

Includes text season selection with Specials last, full poster/landscape episode images, individual episode descriptions, cast and crew portraits, More like this, a full Info view and a long-press context menu with manual stream selection. Includes the sharper watched badge and repaired early Continue Watching progress tracking. Series layout is unchanged from 1.1.6 pending user feedback.

Nuvio and Simkl accounts are optional. Home requires enabled metadata and stream providers plus imported or manually created, validated collections. Multiple compatible metadata addons are supported; AIOMetadata is not the only permitted choice. Internal presets are explicit candidates and must pass the same validation. Local resume works without cloud accounts. Metadata, streams and subtitles come from configured providers. Stream order is retained. Trailer previews do not write playback progress. Previously unrecorded playback positions cannot be reconstructed; start and stop those titles once after updating.

All Nuvio components are included locally. Optional IPTV Simple, Open-Meteo weather and YouTube components are installed separately from the official Kodi/CoreELEC repository and retain their own names and versions.

Validation for 6.0.9: 243 targeted automated tests with Kodi API stubs, including 51 new issue-specific tests; 24 release guard checks; Python/XML/JSON parsing; actual packaged-module and asset-reference smoke tests. Tests run on CPython 3.13.5, not inside Kodi. The existing xbmc.python 3.0.0 and xbmc.gui 5.17.0 dependency floors are unchanged. Windows/CoreELEC rendering, actual playback and Kodi 22 RC1 installation remain device checks before publication.

All original copyright/license notices are preserved: MIT-licensed backend, Kodi 21.3 Estuary GPL/CC artwork foundation, official Nuvio logo attribution and supplied collection artwork. This is an unofficial build. Internal compatibility identifiers and third-party provider names are retained where required for existing profiles and integrations.

Earlier releases added portrait Genres/Themes, rounded title artwork, Settings > Subtitles (one Kodi language and Set subtitles on video start), first matching external subtitle in provider order, windowed trailer playback, a Resume video button, local watched status at 95%, live Continue Watching refresh, upcoming-episode banners based on provider release dates, and cached IPTV channel lists. Previews use a prepared local H.264 clip; the optional YouTube add-on remains configurable in Trailers settings. Airing banners require episode release dates from the selected metadata provider.

6.0.7 opens title and catalog pages using available shelf metadata, then updates them asynchronously. Recent metadata and shelf results are bounded in memory; optional recommendations no longer queue ahead of selected-title requests. Source labels normalize unsupported font glyphs while preserving readable quality/audio badges and provider ordering. Preview ownership accepts Kodi-translated local paths and ListItem identity. Optional add-on cancellation returns when Kodi closes its install dialog, without a second polling delay. Nuvio Settings starts with Accounts & tracking, Add-ons, Collections, IPTV and Playback. Native Kodi seeking remains unchanged.

Initial setup is offered once. Back/Cancel or a partially configured existing profile opens Home on subsequent launches. A connected Nuvio account is recognized without another login prompt. Setup remains available under Maintenance; optional steps are not required.

Continue Watching places the most recently stopped title first and resets the row to its first poster when progress changes. Upcoming-episode banners do not displace active resume entries. For movies/series, Back from fullscreen stops playback and returns to the same title; closing the OSD alone keeps playback running. The OSD Stop button is removed; native Stop actions remain supported.

The default Simkl PIN application is registered as Nuvio Hub. Existing legacy tokens continue using their original issuing application until Accounts & tracking → Simkl → Reconnect as Nuvio Hub succeeds; cancelling the new PIN preserves the current connection. No client secret is bundled.

6.0.7 resets Continue Watching to its leftmost card on every Home entry, independently of the progress revision. Other shelves retain their saved position.

The Home Resume video button is removed. Continue Watching cards still resume stored playback.

6.0.7 places the local playback journal first (newest watch first), followed by remote-only titles. Only display ordering changes; stored progress, completion and metadata merge rules stay unchanged. The launcher Resume video button, icons and handler are removed.


6.0.40 is a review candidate. See the repository release notes and AGENTS.md for automated checks, setup and device acceptance. Unicode fonts are provided by Kodi; this bundle does not include font binaries.
