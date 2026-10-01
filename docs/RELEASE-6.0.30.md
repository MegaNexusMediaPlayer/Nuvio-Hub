# Nuvio Hub 6.0.30 — clean glass, transparency up to 50 %

Prepared 1 October 2026 from the 6.0.29 test build (not released).

* **Shadows removed** completely: they showed an odd edge around pills and
  frames. Glass boxes and glass pills also lost their rim line - plain
  translucent glass only (cards ~10 % white at the top fading to 3 %).
* **Poster and catalog transparency** now goes up to **50 %**:
  Off / 10 % (default) / 20 % / 30 % / 40 % / 50 % in HUB Settings → Home &
  appearance.
* The glass focus ring with its glow is unchanged.

Checks: `test_nuvio_629.py` updated (no shadow files or controls, fade
animations for all five levels, choice up to 50 %). `python review/check_630.py`,
release guard, builder, packaged smoke test.
