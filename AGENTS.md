# Nuvio Hub — engineering and review contract

This is a four-component Kodi build: `plugin.video.nuviohub` (backend/service),
`script.nuvio` (Python/XML frontend), `skin.nuvio` (Kodi shell), and
`screensaver.nuvio` (screensaver entrypoint). The 6.0.27 release is the
baseline for this 6.0.39 candidate. Do not publish, push, or change live user
profiles as a side effect of reviewing code.

## Required repository skills

Read `.agents/skills/kodi-quality/SKILL.md` for every code change. Also read
`.agents/skills/kodi-performance/SKILL.md` for UI, metadata, artwork, service,
cache, network, or playback changes. These are repository instructions, not
claims that a runtime plugin or global agent skill has been installed.

## Before modifying code

Read the relevant call sites, tests, and `docs/RELEASE-6.0.39.md` (and 6.0.36 back to 6.0.10). Identify which
Kodi process/interpreter owns the work. Keep existing public add-on IDs,
profile paths, encrypted credentials and migration aliases. Never mass-rename
legacy state keys or remove upstream license notices. Since 6.0.24 the
project's own code is under the MegaNexus License (LICENSE.md, all rights
reserved); the Estuary-based skin stays GPL-2.0 and bundled third-party code
keeps its license (python-qrcode BSD, flags MIT, CC0 images). Never replace an
existing collection file until validation and cancellation checks succeed.

Check primary sources for changed external API contracts. Nuvio wire progress
uses milliseconds and episode keys `<content_id>_s<season>e<episode>`; local
playback uses seconds. Preserve the remote title ID when a verified alias
connects it to local state. SIMKL stop/completion thresholds differ from the
local policy. Do not make up runtime, IDs, air dates, translations, or credits.

## Invariants

* Accounts are optional and nothing blocks entry into Nuvio (6.0.15): with no
  configuration Cinemeta supplies metadata and default collections. Cinemeta
  is always installed (6.0.23), OFF once the user has own metadata add-ons, and
  a hand-made Cinemeta switch is never changed automatically; collection
  checks are reports only. The numb3rs presets are an explicit choice. Match manifest/catalog/type identities and
  filters (catalog ID also before a comma, tv = series, like Nuvio). Since
  6.0.36 a collection naming another instance of an add-on (another ID) uses
  the installed add-on that publishes the same catalog (most similar name
  first); general IDs (top, popular...) never move to an unrelated add-on and
  a name alone never matches. Manifests are re-read by the service
  (`manifest_refresh.py`); a Nuvio import always reads the current manifest.
* OFF providers stay OFF. Respect per-resource `types` and `idPrefixes`,
  configuration/profile cache boundaries and a bounded request budget.
* Never change a Kodi window class after creation (no class-level setattr,
  no __init_subclass__ wrapping): Kodi 22 RC1's SWIG 4.5 bindings make those
  attributes read-only. Wrap callbacks per instance (`nuvio_ui/dialog.py`).
  Touch gestures (IDs 501-599) are handled in Dialog; remote/mouse/keyboard
  paths stay untouched.
* Settings pages run any row that can open a Kodi dialog with the page hidden
  (Dialog.child); a dialog left behind a page looks like a frozen screen.
* Kodi GUI callbacks do not perform HTTP, long SQLite scans, sleeps or joins.
  Use the dialog job queue, cooperative cancellation and stale-generation
  guards. Only the owning UI context publishes results or changes focus.
* Home Back does not reveal HUB. HUB is explicit. Last-row Down stays put.
  Preserve focus by stable content identity across refreshes, not by a changed
  resume URL or unconditional `selectItem(0)`.
* Video inside a Nuvio dialog needs a `videowindow` in the ACTIVE window too
  (hidden ones exist in `nuvio_session.xml` and the skin Home/SkinSettings):
  Kodi presents hardware video layers only via the active window's RenderEx.
* IPTV: first click previews, second active-channel click enters native
  fullscreen, Esc returns to the same guide without EPG over fullscreen video.
  Do not change the user's global screen resolution or unrelated PVR settings.
* Cache budgets count serialized metadata/image payload bytes, not Kodi GPU
  textures or process RSS. No unlimited warm-up, unbounded thread-per-item,
  repeated full catalog scan, or unconditional cache clearing on Settings.
* Playback progress uses a durable account/profile-scoped outbox. Pull before
  push, compare real timestamps, acknowledge only the exact queued version,
  keep failures for retry, avoid overlapping sync cycles and honor backoff.
  Do not infer a deletion from a failed, empty, partial or paginated snapshot.
* Preserve original Unicode names, combining marks and emoji sequences. Use
  Kodi's installed Unicode font; do not bundle system font binaries. Missing
  glyphs and provider localization are distinct from encoding corruption.
* Releases are published on GitHub as tag `v<version>` with asset
  `Nuvio-Hub-Complete-<version>.zip` (+ `.sha256`); `resources/lib/updater.py`
  reads exactly that naming for automatic updates.
* The service installs the bundled interface/skin/screensaver by itself after
  any backend update (`bundle_installer.auto_install`), never while video
  plays or the interface is open (waits up to 24 h, retries failures). The
  update check covers all components (`component_report`), not only the
  backend (6.0.36).
* Keep all four manifests and internal dependencies at one release version.
  Retain Kodi Python 3 / GUI 5.17 compatibility gates; no removed-stdlib APIs.
  `repository.meganexus` (Kodi repository for GitHub Pages, built by
  `review/build_repo_site.py`) has its own version and is never in the bundle.
* Themes (6.0.28): Light = `skins/Default` (MegaNexus blues, `review/make_blue_theme.py`);
  Dark and Dim are GENERATED from it by `review/make_theme_variants.py` (also
  skin.nuvio/colors dark.xml/dim.xml) - edit Default, then regenerate. Windows
  open with `resources.lib.theme.folder()`. Glass look (6.0.29/30): card boxes,
  focus rings (no shadows, no rim lines), pills and clock capsule come from `review/make_glass_ui.py`
  (assets + idempotent XML patch); posters fade by Window(Home) property
  nuvio.card_opacity (setting nuvio_card_opacity). Kodi cannot blur what is
  behind a control: glass = translucent layer. Crisp corners (6.0.31,
  `review/make_crisp_shapes.py`): card masks/focus rings at 2x; small pills
  and buttons use per-size 2x textures `nuvio_pill_<w>x<h>_r<r>.png` instead
  of 9-slice (Kodi draws 9-slice borders 1:1, GUITexture.cpp); large panels
  keep 9-slice. Never ship 3x GUI textures: Kodi shrinks without mipmaps.
  Logos likewise use per-size 2x `nuvio_wordmark_<w>x<h>.png` (same script);
  the 1600 px master is only for the phone page. Header buttons Home /
  Search / Settings / HUB have no rest pill (6.0.32).
* Screensaver video (6.0.32): MP4/MOV clips play from a silent loop copy
  (`nuvio_ui/mp4loop.py`, samples listed back to back for an hour, audio
  track dropped) - never seek-loop or mute when the copy exists; other formats
  fall back to the muted seek loop.
* Skin (6.0.33, `resources/lib/skin_activation.py`): check the skin and its
  required add-ons (version, enabled) before switching, write
  lookandfeel.skin to guisettings.xml at once (Android kills Kodi before it
  saves), re-check at every MegaNexus entry and at Kodi start, report the
  reason of a failed switch. The installer waits for Kodi to report the new
  component versions, else asks for a restart.
* Restart after updates (6.0.34, `resources/lib/kodi_restart.py`): Reboot on
  CoreELEC/LibreELEC (RestartApp froze Amlogic boxes), Quit on Android and
  Apple (RestartApp cannot reopen Kodi there), RestartApp elsewhere. Android
  reports System.Platform.Linux too: test it first.
* 6.0.35: sports add-ons (`resources/lib/sports.py`) never enter Home,
  Search, Continue Watching or tracking - only the Sport screen
  (`nuvio_ui/sports.py`, previews = untracked). Title options are a list built
  by `details.title_options`; show it over the caller, hide only for screen
  choices. Continue Watching rules (`continue_rules.py`): remove = hide until
  played again, 60-day period, unaired toggle; watched at 90 % (Simkl 80 %,
  `nuviohub.common`). Library = `library.py` (local + Trakt/Simkl mirror).
  Phone tracking links: `tracking_link.py`. `refresh_guard.py` pauses Kodi's
  refresh-rate switching only while small previews play. Loading loops must
  wait with `monitor.waitForAbort` or Back (skip) never arrives.
  Pipeline after XML edits: make_glass_ui.py --windows, make_crisp_shapes.py,
  make_theme_variants.py.
* RAM (6.0.32): catalog pages 96 MiB with ram256 (`browse_cache.page_ram`),
  details in their own pool (`browse_meta`, `remember=False` on the shared
  cache), cursor-rest details prefetch (latest wins, yields to foreground and
  playback, failures back off) and next-page prefetch via the refresher.
  logo/banner/screensaver layers come from `review/make_meganexus_brand.py`.
* Phone setup (`resources/lib/phone_setup.py`) listens only while its TV QR
  window is open; every API call needs the QR key; manifest URLs and tokens
  are never sent to the phone; it applies changes through the same backend
  functions as the TV settings.

## Required checks (Python 3.9+ review environment)

```sh
python review/check_637.py
python review/check_608_rebrand_kodi22.py 6.0.39
python review/build_bundle.py --output /tmp/Nuvio-Hub-Complete-6.0.39.zip
python review/check_packaged_build.py /tmp/Nuvio-Hub-Complete-6.0.39.zip
```

The first command runs the maintained unit suite, parses XML/JSON, and checks
runtime source against Python 3.8 grammar. The legacy-named 6.0.8 guard remains
a release-wide branding/ABI/stdlib gate; its version argument is authoritative.
The packaged smoke check must import modules from the expanded ZIP, not the
source checkout. Recursively inspect nested ZIPs for fonts, tokens, profiles,
bytecode, accidental repository ZIPs and version/hash mismatches.

Do not silently drop a test to get green. When a requirement intentionally
changes, update the old expectation and add behavioral coverage for the new
contract. Record commands, actual results, baseline, limitations and manual
acceptance work. Syntax, mock tests and packaged imports do NOT establish
Kodi 22 RC1, CoreELEC, Windows, native-player or live-account correctness.

## Manual acceptance before release

Use fresh and existing profiles on Kodi 21 and Kodi 22 RC1. Exercise offline
and malformed providers, incompatible/empty catalogs, CJK/emoji names, season
switching, long plots, portrait/landscape modes, native playback return, IPTV
preview/fullscreen, screensaver wake, multiple metadata/stream providers,
logout/profile switch during sync, two-device Nuvio/SIMKL progress, completion,
network interruption and retry. Measure cold/warm Home and collection latency
and resident memory on the target device. Publish only after actual results.

## Privacy and deployment

Never log or commit personalized manifest URLs, tokens, PINs, provider exports,
viewing history, keys, or databases. Sanitize exceptions. No access to a user's
LAN, cloud account, or machine is assumed merely because an address is known.
Keep rollout and rollback manual unless the user explicitly authorizes them.
