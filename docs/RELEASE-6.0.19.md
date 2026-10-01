# Nuvio Hub 6.0.19 — restart question after automatic updates

Prepared 1 October 2026 from the 6.0.18 review candidate (all of it included).
Status: **local review candidate**; nothing pushed or published.

## Behaviour

* After an **automatic** update the service no longer shows a notification. It
  waits until no video plays and the Nuvio interface is closed, then asks:
  **"Nuvio Hub X is installed. Restart Kodi now?"** (Restart / Later).
* **Restart** runs Kodi's `RestartApp`.
* **Later** keeps the reminder: the same question appears at the next Nuvio
  entry, before the interface opens (never over a playing video). The service
  asks only once per Kodi session; every Nuvio entry asks again until restart.
* Restarting Kodi in any other way clears the reminder: the pending update is
  stored with a token of the Kodi session (a home-window property that does not
  survive a restart).
* **Check for updates now** (Configure) asks the same question after installing;
  an update installed from Nuvio Settings (the interface is open) asks when Nuvio
  is left / at the next entry.

## Checks

New `test_nuvio_619.py` (Restart, Later, no prompt over video, service waits for
"no video and Nuvio closed" and asks once, session token clears the reminder,
automatic install marks instead of notifying, entry asks before the interface).
`python review/check_619.py`, release guard, builder, packaged smoke test.
