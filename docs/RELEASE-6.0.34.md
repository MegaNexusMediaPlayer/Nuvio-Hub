# Nuvio Hub 6.0.34 — the right restart after an update on every device

Prepared 1 October 2026 after a report from CoreELEC: answering "Restart" after
an update froze the box.

Kodi's `RestartApp` is implemented only for Windows and Linux
(ApplicationMessageHandling.cpp, Kodi 22): on Android it only closes Kodi, on
macOS / iOS / tvOS it does nothing, and on CoreELEC / LibreELEC Kodi exits and
the system starts it again, which can freeze Amlogic boxes while video and
HDMI are re-initialised. The question after an update
(`resources/lib/updater.py`) now uses `resources/lib/kodi_restart.py`:

| Device | Question | Action |
|---|---|---|
| CoreELEC / LibreELEC (`/etc/os-release` ID, or their settings add-on) | "Reboot the box now to finish the update?" — **Reboot** | `Reboot` |
| Android, macOS / iOS / tvOS | "Close Kodi now, then open Kodi again to finish the update?" — **Close Kodi** | `Quit` (settings are saved) |
| Windows, other Linux | "Restart Kodi now?" — **Restart** | `RestartApp` |

Android also reports `System.Platform.Linux`, so it is detected first.
**Later** keeps the reminder for the next MegaNexus entry, as before.

Checks: `test_nuvio_634.py` (platform detection incl. Android before Linux,
CoreELEC/LibreELEC by os-release or add-on, actions and texts, Later does
nothing); `test_nuvio_619` unchanged (Restart on other systems).
`python review/check_634.py`, release guard, builder, packaged smoke test.
