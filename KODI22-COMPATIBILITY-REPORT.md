> Historical 6.0.8 report. For the current 6.0.9 local test candidate, see [QA-6.0.9](review/QA-6.0.9.md). No target-device Kodi 22 RC1 runtime was executed for 6.0.9.

# Nuvio Hub 6.0.8 — Kodi 22 RC1 compatibility review

## Result

**Static/package compatibility: PASS.** The 6.0.8 source and final package are structured for Kodi 21/Omega and Kodi 22/Piers. A real Kodi 22 RC1 target-device run is still the final runtime confirmation.

## Add-on API compatibility

- `plugin.video.nuviohub`: `xbmc.python` 3.0.0 and `xbmc.gui` 5.17.0.
- `script.nuvio`, `skin.nuvio`, and `screensaver.nuvio` remain on the compatible Nuvio 6.0.8 component set.
- `xbmc.gui` is intentionally not raised to a Kodi-22-only value; this keeps Kodi 21 compatibility.
- Python sources are scanned for standard-library modules removed by Python 3.14.

## Language cleanup

- Arabic UI locale removed.
- Runtime Arabic translation table removed.
- Remaining UI source text is English.
- English is the only bundled UI language.
- Arabic media title matching and explicitly selected Arabic subtitles are retained because they are content/provider capabilities, not UI localization.

## Branding cleanup

Active runtime branding now uses Nuvio Hub / `nuviohub` names. Retired pre-rename identifiers remain only as runtime-assembled values in `resources/lib/legacy_names.py`, for these compatibility cases:

- migration from profiles of the pre-rename add-on;
- cleanup of old TMDb Helper player/keymap names;
- import of old configuration keys;
- hidden legacy setting aliases used during upgrade;
- the MIT copyright line required by LICENSE.txt.

These exceptions must not be removed by a blind global search-and-replace.

## Release validation

- Dedicated 6.0.8 rebrand/Kodi-22 release guard: **24/24 checks PASS**.
- Current targeted regression suites for bundle install/update, backend, playback/progress, metadata, skin and branding: **127/127 tests PASS**.
- Static parse/compile guard: **247 Python files compiled, 144 XML files parsed, 4 JSON files parsed**.
- Final packaged smoke test: **PASS**, with **33 packaged modules imported** and **1,434 literal Kodi asset references validated**.
- Final installer contains no `resource.language.ar_*` path and no path using the retired name.
- Installer SHA-256: `47d937681d755b4ff096c5c0632e6902a1f568a279368aa90a336a528d35c503`.

The older full regression directory includes historical tests that encode obsolete 4.x/5.x behavior. It was already red on the untouched 6.0.7 baseline, so those failures are tracked separately rather than treated as new 6.0.8 regressions.
