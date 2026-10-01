# Nuvio Hub 6.0.24 — MegaNexus License

Prepared 1 October 2026 from 6.0.23. No functional changes.

* The project's own code, design and artwork (`plugin.video.nuviohub`,
  `script.nuvio`, `screensaver.nuvio`, `repository.meganexus`) are now under
  the **MegaNexus License** (`LICENSE.md`): free personal, non-commercial use;
  redistribution, modified versions, forks published as separate projects,
  use of the name/logo and commercial use need the author's written
  permission. Versions up to 6.0.23 were released under MIT and keep it.
* `skin.nuvio` stays GPL-2.0 / CC BY-SA 4.0 (Estuary-based).
* The bundled python-qrcode library now ships its BSD license file, which was
  missing. Third-party notices updated.
* Add-on manifests show the new license; the repository ZIP includes it.

Checks: `test_nuvio_624.py` (license texts per component, skin keeps GPL,
qrcode license present and packaged), `python review/check_624.py`, release
guard, builder, packaged smoke test.
