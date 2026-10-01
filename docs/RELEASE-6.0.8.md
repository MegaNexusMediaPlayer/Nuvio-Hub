# Nuvio Hub for Kodi 6.0.8 — rebrand and Kodi 22 compatibility maintenance

6.0.8 is a compatibility and cleanup release built on the 6.0.7 public baseline. It does not intentionally change the add-on's media-provider model or remove support for Arabic media titles/subtitles. It removes the Arabic **interface** layer and completes the visible/runtime Nuvio Hub rebrand.

## Changes in 6.0.8

- Removed the `resource.language.ar_sa` UI locale and the old runtime Arabic-to-English translation table. English is now the single bundled UI language.
- Converted remaining Arabic UI labels/messages in the Python source to English.
- Renamed the active internal Python namespace to `resources.lib.nuviohub`.
- Renamed the active TMDb Helper player, keymap, preset and branding asset to Nuvio Hub names.
- Migrated active Kodi window-property/cache identifiers to `nuviohub.*`.
- Kept explicit legacy aliases for the pre-rename install, old setting keys, old TMDb player prefixes and old keymap filename so upgrades can cleanly migrate existing profiles.
- Kept the MIT copyright notice required by the license; it is not runtime branding.
- Raised all four bundled Nuvio components to 6.0.8.
- Kept `xbmc.gui` at 5.17.0 and `xbmc.python` at 3.0.0 so the bundle remains installable on Kodi 21 while satisfying Kodi 22/Piers add-on API compatibility floors.
- Added a Python 3.14 removed-standard-library scan and release guard for Kodi 22/Piers compatibility hardening.
- Changed the automatic subtitle-language fallback from `ar,en` to `en`; users can still explicitly configure Arabic or other subtitle languages.

## Validation

The release is validated by `review/check_608_rebrand_kodi22.py`, targeted current regression tests, Python compilation, XML/JSON parsing and `review/check_packaged_build.py` against the final installer ZIP. The historical full test directory contains older 4.x/5.x expectations that were already failing on the 6.0.7 baseline and is not used as a release-green signal.

Kodi 22/Piers is on the Python 3.14 line. This review statically checks the source and packaged imports for compatibility, but it does not replace a final run on an actual Kodi 22 RC1/CoreELEC target.

## Install / update

Install **`Nuvio-Hub-Complete-6.0.8.zip`** through Kodi's **Install from zip file**. Existing users should stop playback and close the interface first, install the ZIP, open Nuvio Hub once so bundled components and legacy aliases can migrate, and then restart Kodi. Userdata is preserved.
