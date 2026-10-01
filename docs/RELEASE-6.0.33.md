# Nuvio Hub 6.0.33 — the MegaNexus skin survives updates and restarts

Prepared 1 October 2026 from 6.0.32 after a report from an Android tablet
(Kodi 22 beta 2, 32-bit): after the update the skin was not offered, and after
restarting the app Kodi started with its default skin.

Causes and fixes (`plugin.video.nuviohub/resources/lib/skin_activation.py`):

* **The update was not fully loaded when the skin was used.** The skin needs
  the interface (`script.nuvio`) of the same version. The installer only
  waited until Kodi *knew* each component, not until it had loaded the new
  version, so Kodi could still report the old interface; at the next start it
  dropped the skin. The installer now waits for the new version (up to 10 s
  after discovery) and, if Kodi still reports the old one, asks for a Kodi
  restart. Before switching, the skin, the interface and the other add-ons it
  requires are checked (present, needed version, enabled; disabled ones are
  enabled, with a rescan and up to 20 s wait).
* **The skin choice was saved only on a clean exit.** Kodi writes
  `lookandfeel.skin` to guisettings.xml when it shuts down normally; Android
  often kills Kodi instead. The choice is now written to guisettings.xml as
  soon as Kodi keeps the skin.
* **The skin was checked only once.** `nuvio_skin_applied` was set at the
  first start and never re-checked, so a lost skin was never offered again.
  Now every MegaNexus entry and every Kodi start (after the component check)
  offers the skin again if it is not active, through Kodi's own "Keep this
  change?" question. "No" is respected until Kodi restarts; HUB Settings →
  Use MegaNexus skin always offers it.
* **A failed switch only returned to Home.** It now shows the reason (for
  example "Kodi still uses script.nuvio 6.0.32 … Restart Kodi").

Checks: `test_nuvio_633.py` (dependency/version/enable checks, rescan and
wait for the new version, guisettings.xml written at once and other formats
left alone, restore at Kodi start only when chosen/not declined/not active,
service order, failure reason, installer requests a restart while Kodi still
reports the old version); `test_nuvio_625_removal` and `test_nuvio_home_iptv`
updated for the new contract. `python review/check_633.py`, release guard,
builder, packaged smoke test.
