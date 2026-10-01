# Nuvio Hub — changes since the published 6.0.7

Summary for review of the local 6.0.8 – 6.0.19 candidates (details in each
`docs/RELEASE-6.0.x.md`). None of these is published on GitHub yet.

| Area | What changed |
|---|---|
| Brand | Complete Nuvio Hub rename; the retired name appears nowhere (release guard enforces it); upgrade aliases are assembled at runtime in `legacy_names.py`. |
| Entry | Nothing blocks opening Nuvio. With no setup, Cinemeta supplies metadata and default collections; your own add-ons' catalogs or imported collections take over automatically. |
| Collections | Default collections (Cinemeta or numb3rs with setup help), Home rows show/hide, per-catalog On/Off, changes save immediately, catalog check is a report only. |
| Speed | Stale-while-revalidate catalog cache (instant reopen), hover prefetch, parallel sources, memoized watched/provider data, keep-alive image proxy, posters preloaded into RAM after a reboot, background work yields to what you open and pauses during playback. |
| Playback | Video starts when the first stream add-on answers (slow ones are skipped), one stream add-on ON by default, one loading screen, faster return from the player. |
| Trailers | IMDb trailers (stream directly, quality setting) besides YouTube with automatic fallback; Kodi never asks to install YouTube for its own trailer button. |
| CoreELEC | Small video (Home preview, IPTV preview, trailer window, video screensaver) now shows its picture (hardware video layer driven through the active window); Nuvio's preview video stops before sleep. |
| Screensaver | Seamless MP4 loop (no artwork flash, no reopen). |
| IPTV | Refresh guide / IPTV setup / HUB at the bottom; one HUB button. |
| Details | No "Loading episodes" banner; ratings (IMDb/TMDb) under the Home title, switchable. |
| Maintenance | Automatic updates from GitHub releases (checksum, rollback, "Restart Kodi now?" when no video plays and Nuvio is closed), Ko-fi QR, organised Configure page, working "Remove Nuvio build". |
| Fixes | Several latent crashes (NameErrors), Continue Watching position after Details, settings dialogs no longer hidden behind pages, subtitle preferences saved. |

Release naming for automatic updates: tag `v<version>`, assets
`Nuvio-Hub-Complete-<version>.zip` and `Nuvio-Hub-Complete-<version>.zip.sha256`.
