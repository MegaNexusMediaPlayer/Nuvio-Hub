# Nuvio Hub — engineering and review contract

This is a four-component Kodi build: `plugin.video.nuviohub` (backend/service),
`script.nuvio` (Python/XML frontend), `skin.nuvio` (Kodi shell), and
`screensaver.nuvio` (screensaver entrypoint). The supplied 6.0.9 source is the
baseline for this 6.0.10 candidate. Do not publish, push, or change live user
profiles as a side effect of reviewing code.

## Required repository skills

Read `.agents/skills/kodi-quality/SKILL.md` for every code change. Also read
`.agents/skills/kodi-performance/SKILL.md` for UI, metadata, artwork, service,
cache, network, or playback changes. These are repository instructions, not
claims that a runtime plugin or global Codex skill has been installed.

## Before modifying code

Read the relevant call sites, tests, and `docs/RELEASE-6.0.10.md`. Identify which
Kodi process/interpreter owns the work. Keep existing public add-on IDs,
profile paths, encrypted credentials and migration aliases. Never mass-rename
legacy state keys or remove upstream license notices. Never replace an
existing collection file until validation and cancellation checks succeed.

Check primary sources for changed external API contracts. Nuvio wire progress
uses milliseconds and episode keys `<content_id>_s<season>e<episode>`; local
playback uses seconds. Preserve the remote title ID when a verified alias
connects it to local state. SIMKL stop/completion thresholds differ from the
local policy. Do not make up runtime, IDs, air dates, translations, or credits.

## Invariants

* Accounts are optional; Home requires enabled metadata and stream providers
  plus a verified, nonempty collection configuration. Internal presets are
  explicit candidates only. Match exact manifest/catalog/type identities and
  filters; never silently reinterpret a catalog as belonging to another addon.
* OFF providers stay OFF. Respect per-resource `types` and `idPrefixes`,
  configuration/profile cache boundaries and a bounded request budget.
* Kodi GUI callbacks do not perform HTTP, long SQLite scans, sleeps or joins.
  Use the dialog job queue, cooperative cancellation and stale-generation
  guards. Only the owning UI context publishes results or changes focus.
* Home Back does not reveal HUB. HUB is explicit. Last-row Down stays put.
  Preserve focus by stable content identity across refreshes, not by a changed
  resume URL or unconditional `selectItem(0)`.
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
* Keep all four manifests and internal dependencies at one release version.
  Retain Kodi Python 3 / GUI 5.17 compatibility gates; no removed-stdlib APIs.

## Required checks (Python 3.9+ review environment)

```sh
python review/check_610.py
python review/check_608_rebrand_kodi22.py 6.0.10
python review/build_bundle.py --output /tmp/Nuvio-Hub-Complete-6.0.10.zip
python review/check_packaged_build.py /tmp/Nuvio-Hub-Complete-6.0.10.zip
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
