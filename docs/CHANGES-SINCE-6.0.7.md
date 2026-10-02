# Nuvio Hub — changes since 6.0.7

Summary of 6.0.8 – 6.0.37 (details in each `docs/RELEASE-6.0.x.md`).
6.0.19 and 6.0.23 are published GitHub releases.

| Area | What changed |
|---|---|
| Brand | Complete Nuvio Hub rename; the retired name appears nowhere (release guard enforces it); upgrade aliases are assembled at runtime in `legacy_names.py`. |
| Entry | Nothing blocks opening Nuvio. With no setup, Cinemeta supplies metadata and default collections; your own add-ons' catalogs or imported collections take over automatically. The MegaNexus skin is checked at every entry and Kodi start, saved at once and restored after an update or an Android restart, and a failed switch says why (6.0.33). |
| Collections | Default collections (Cinemeta or numb3rs with setup help), Home rows show/hide, per-catalog On/Off, changes save immediately, catalog check is a report only. |
| Speed | Stale-while-revalidate catalog cache (instant reopen), hover prefetch, parallel sources, memoized watched/provider data, keep-alive image proxy, posters preloaded into RAM after a reboot, all Home catalogs and title details kept in RAM with details of the title under the cursor and the next catalog page loaded ahead (6.0.32), background work yields to what you open and pauses during playback. |
| Playback | Video starts when the first stream add-on answers (slow ones are skipped), one stream add-on ON by default, one loading screen, faster return from the player. |
| Trailers | IMDb trailers (stream directly, quality setting) besides YouTube with automatic fallback; Kodi never asks to install YouTube for its own trailer button. |
| CoreELEC | Small video (Home preview, IPTV preview, trailer window, video screensaver) now shows its picture (hardware video layer driven through the active window); Nuvio's preview video stops before sleep. |
| Screensaver | Seamless MP4 loop (no artwork flash, no reopen); MegaNexus standard image (default) or built-in MegaNexus animation drawn by the skin (no player, no mute). |
| Cinemeta | Always installed; ON only while nothing else supplies metadata; Cinemeta collections when there is no other layout. |
| Themes | Light (MegaNexus blue), Dark (black, OLED) and Semi-dark (dark top, blue bottom) for the interface, HUB skin and screensaver; chosen in HUB Settings or on the phone (6.0.28). |
| Glass look | Translucent glass card boxes (no shadows), glass focus ring, glass HUB and header buttons; crisp (2x) corners on cards, focus frames and pills; posters 10 % transparent by default, adjustable Off to 50 % (6.0.29/6.0.30); sharp per-size logos (6.0.31); plain header buttons; screensaver clips loop seamlessly from a silent copy, Kodi is not muted (6.0.32). |
| Branding | MegaNexus logo, banner and icons; blue theme from the logo; HUB buttons "MegaNexus", "IPTV Channels", "HUB Settings"; "Support MegaNexus · Ko-fi". Nuvio accounts and settings unchanged. |
| Nuvio connect | Signing in imports add-ons, progress and collections and switches ON the metadata add-ons the collections use (6.0.25). |
| Phone setup | QR code → local page served by Kodi: Nuvio sign-in/import, add-ons, collections, display; Save starts MegaNexus and stops the service. |
| License | From 6.0.24 the MegaNexus License (all rights reserved; personal use free). Skin stays GPL-2.0 (Estuary). |
| Distribution | `repository.meganexus` Kodi repository on GitHub Pages (File manager source `https://meganexusmediaplayer.github.io/Nuvio-Hub/`); interface/skin/screensaver install themselves after every update. |
| IPTV | Refresh guide / IPTV setup / HUB at the bottom; one HUB button. |
| Details | No "Loading episodes" banner; ratings (IMDb/TMDb) under the Home title, switchable. |
| Maintenance | Automatic updates from GitHub releases (checksum, rollback, a restart question when no video plays and Nuvio is closed: Reboot on CoreELEC/LibreELEC, Close Kodi on Android and Apple, Restart elsewhere (6.0.34)), Ko-fi QR, organised Configure page, working "Remove Nuvio build". |
| Fixes | Several latent crashes (NameErrors), Continue Watching position after Details, settings dialogs no longer hidden behind pages, subtitle preferences saved. |
| 6.0.35 | GitHub issues #3–#9: phone add-on choices kept, no TV mode switch for previews, Continue Watching Remove / Play from start / 90 % / 60 days, Sport screen for sports add-ons, Catalog rows Home layout; Title options over the screen, Library (Local / Tracking Services), Trakt in settings and on the phone, Skip on the loading screen. |
| 6.0.36 | Collections connect to catalogs added later in an add-on's configuration (manifests re-read, Nuvio import reads the current one) and to other people's instances of an add-on (same catalog); Check for updates covers the interface, skin and screensaver, not only the backend, and offers the platform restart; the automatic component install waits up to 24 h and retries. |
| Latest (6.0.37) | Works on Kodi 22 RC1 (window callbacks wrapped per instance; SWIG 4.5 classes are read-only); full traceback in kodi.log on failures; touch: vertical drags over poster rows move between rows, no repaint mid-drag. |

Release naming for automatic updates: tag `v<version>`, assets
`Nuvio-Hub-Complete-<version>.zip` and `Nuvio-Hub-Complete-<version>.zip.sha256`.
