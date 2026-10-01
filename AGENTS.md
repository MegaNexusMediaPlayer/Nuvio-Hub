# Nuvio Hub — engineering and review contract

This is a four-component Kodi build: `plugin.video.nuviohub` (backend/service),
`script.nuvio` (Python/XML frontend), `skin.nuvio` (Kodi shell), and
`screensaver.nuvio` (screensaver entrypoint). The 6.0.25 release is the
baseline for this 6.0.26 release. Do not publish, push, or change live user
profiles as a side effect of reviewing code.

## Required repository skills

Read `.agents/skills/kodi-quality/SKILL.md` for every code change. Also read
`.agents/skills/kodi-performance/SKILL.md` for UI, metadata, artwork, service,
cache, network, or playback changes. These are repository instructions, not
claims that a runtime plugin or global agent skill has been installed.

## Before modifying code

Read the relevant call sites, tests, and `docs/RELEASE-6.0.26.md` (and 6.0.25 back to 6.0.10). Identify which
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
  checks are reports only. The numb3rs presets are an explicit choice. Match exact manifest/catalog/type identities and
  filters; never silently reinterpret a catalog as belonging to another addon.
* OFF providers stay OFF. Respect per-resource `types` and `idPrefixes`,
  configuration/profile cache boundaries and a bounded request budget.
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
  plays or the interface is open.
* Keep all four manifests and internal dependencies at one release version.
  Retain Kodi Python 3 / GUI 5.17 compatibility gates; no removed-stdlib APIs.
  `repository.meganexus` (Kodi repository for GitHub Pages, built by
  `review/build_repo_site.py`) has its own version and is never in the bundle.
* Theme colours are the MegaNexus logo blues (`review/make_blue_theme.py`);
  logo/banner/screensaver layers come from `review/make_meganexus_brand.py`.
* Phone setup (`resources/lib/phone_setup.py`) listens only while its TV QR
  window is open; every API call needs the QR key; manifest URLs and tokens
  are never sent to the phone; it applies changes through the same backend
  functions as the TV settings.

## Required checks (Python 3.9+ review environment)

```sh
python review/check_626.py
python review/check_608_rebrand_kodi22.py 6.0.26
python review/build_bundle.py --output /tmp/Nuvio-Hub-Complete-6.0.26.zip
python review/check_packaged_build.py /tmp/Nuvio-Hub-Complete-6.0.26.zip
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
