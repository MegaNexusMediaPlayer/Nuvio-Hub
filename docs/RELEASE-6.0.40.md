# Nuvio Hub 6.0.40 — 6.0.37/6.0.39 features, touch left to Kodi

Released 3 October 2026. Everything in [6.0.39](RELEASE-6.0.39.md) (and the
6.0.37 features: Kodi 22 RC1, Trakt / TMDB collection sources, Local storage,
security notice, phone setup port 8765), with one change after testing:

* **Touch is Kodi's own again.** The 6.0.37/6.0.39 code turned vertical drags
  into Up/Down row steps. It fought Kodi's own panning: a small finger move
  scrolled too far and each step moved the focus, so Home kept repainting.
  It was removed; touch screens behave as in 6.0.36. Better touch scrolling
  needs Kodi's native panning in the skin and is planned separately.
* The Android "Could not open the interface" fix stays (a failing click or
  key is logged and shown as a notification; MegaNexus stays open).

Also in this release (from 6.0.39): Simkl syncs only changes and nothing
during playback; Trakt watched marks, Mark watched to Trakt, offline watch
queue, 401/429 retry; RAM budgets by device memory; Plex (v2 resources) and
Jellyfin 12 / Emby (beta, off by default) as first sources and Home rows,
Quick Connect, phone setup; Jellyfin copies matched by an ID index.

Checks: `python review/check_640.py`, release guard 6.0.40, builder, packaged
smoke test. Jellyfin was checked live on demo.jellyfin.org 12.1 / 13.0; Plex,
Emby and devices were not.
