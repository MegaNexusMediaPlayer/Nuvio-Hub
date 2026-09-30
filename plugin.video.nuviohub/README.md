# Nuvio Hub 6.0.7

Complete first-install and update bundle for Kodi 21. The backend is **Nuvio Hub**; the program interface, skin and screensaver are **Nuvio**. All four installed components use version **6.0.7**. This release updates 6.0.4 and also supports older Nuvio bundles.

Stop playback and close the Nuvio interface, install `Nuvio-Hub-Complete-6.0.7.zip` through Kodi's Install from zip file, open Nuvio Hub once to update the bundled components, then restart Kodi. Keep the existing installation and userdata. Manual ZIP updates preserve accounts, providers, settings, collections, IPTV configuration and stored playback positions. The About screen reads the installed interface version.

Includes text season selection with Specials last, full poster/landscape episode images, individual episode descriptions, cast and crew portraits, More like this, a full Info view and a long-press context menu with manual stream selection. Includes the sharper watched badge and repaired early Continue Watching progress tracking. Series layout is unchanged from 1.1.6 pending user feedback.

For the documented full setup, a Nuvio account, AIOMetadata, a compatible stream provider and Simkl are required. AIOMetadata is mandatory for the intended metadata experience; Simkl is required for the complete Continue Watching/tracking setup. Some local functionality can operate without these connections. Metadata, streams and subtitles come from configured providers. Stream order is retained. Trailer previews do not write playback progress. Previously unrecorded playback positions cannot be reconstructed; start and stop those titles once after updating.

All Nuvio components are included locally. Optional IPTV Simple, Open-Meteo weather and YouTube components are installed separately from the official Kodi/CoreELEC repository and retain their own names and versions.

Validation for 6.0.7: targeted Continue Watching regression tests, Kodi layout checks and packaged module/asset checks. The full regression suite was not repeated for this layout update. Runtime branding is checked with Kodi 21.3 in an isolated Wine profile. CoreELEC hardware and personal watch-history synchronization still require target-device testing. The registered Nuvio Hub name was verified on the live Simkl PIN consent page.

All original copyright/license notices are preserved: MIT-licensed backend, Kodi 21.3 Estuary GPL/CC artwork foundation, official Nuvio logo attribution and supplied collection artwork. This is an unofficial build. Internal compatibility identifiers and third-party provider names are retained where required for existing profiles and integrations.

Earlier releases added portrait Genres/Themes, rounded title artwork, Settings > Subtitles (one Kodi language and Set subtitles on video start), first matching external subtitle in provider order, windowed trailer playback, a Resume video button, local watched status at 95%, live Continue Watching refresh, upcoming-episode banners based on provider release dates, and cached IPTV channel lists. Previews use a prepared local H.264 clip; the optional YouTube add-on remains configurable in Trailers settings. Airing banners require episode release dates from the selected metadata provider.

6.0.7 opens title and catalog pages using available shelf metadata, then updates them asynchronously. Recent metadata and shelf results are bounded in memory; optional recommendations no longer queue ahead of selected-title requests. Source labels normalize unsupported font glyphs while preserving readable quality/audio badges and provider ordering. Preview ownership accepts Kodi-translated local paths and ListItem identity. Optional add-on cancellation returns when Kodi closes its install dialog, without a second polling delay. Nuvio Settings starts with Accounts & tracking, Add-ons, Collections, IPTV and Playback. Native Kodi seeking remains unchanged.

Initial setup is offered once. Back/Cancel or a partially configured existing profile opens Home on subsequent launches. A connected Nuvio account is recognized without another login prompt. Setup remains available under Maintenance; optional steps are not required.

Continue Watching places the most recently stopped title first and resets the row to its first poster when progress changes. Upcoming-episode banners do not displace active resume entries. Back from fullscreen stops playback and returns to the same title; closing the OSD alone keeps playback running. The OSD Stop button is removed; native Stop actions remain supported.

The default Simkl PIN application is registered as Nuvio Hub. Existing legacy tokens continue using their original issuing application until Accounts & tracking → Simkl → Reconnect as Nuvio Hub succeeds; cancelling the new PIN preserves the current connection. No client secret is bundled.

6.0.7 resets Continue Watching to its leftmost card on every Home entry, independently of the progress revision. Other shelves retain their saved position.

The Home Resume video button is removed. Continue Watching cards still resume stored playback.

6.0.7 places the local playback journal first (newest watch first), followed by remote-only titles. Only display ordering changes; stored progress, completion and metadata merge rules stay unchanged. The launcher Resume video button, icons and handler are removed.
