# Install and configure Nuvio Hub 6.0.10 candidate

This is a supplied local test bundle, not an automatically published release.
The supported code/API target is Kodi 21 and Kodi 22; actual rendering, native
playback and live synchronization still need device acceptance.

## Safe upgrade

Back up your Kodi profile first. Stop playback and close the Nuvio frontend.
Install `Nuvio-Hub-Complete-6.0.10.zip` via Add-ons → Install from zip file. Open
backend **Nuvio Hub** once to update the interface, skin and screensaver, then
restart Kodi. All four Nuvio components must report 6.0.10. Keep userdata; do
not uninstall or delete credentials/settings to update. The source archive is
for development and is not installable through Kodi's ZIP installer.

## Accounts are optional; validated provider setup is required

In Nuvio Settings → Add-ons, add your own configured manifest URLs and enable
metadata providers under **Metadata add-ons**, then stream providers under
**Stream add-ons**. Multiple metadata providers can be ON independently. A
provider marked OFF must never be used as a silent metadata fallback.

Next open Collections. Choose one of: import from a connected Nuvio account;
import a collections JSON export without any account; or create a collection
from installed catalogs. Provide required catalog filter values. Home requires
nonempty validated collections and enabled metadata and stream providers.
An old saved collection set is revalidated without resetting its layout.

Internal presets are available only as an explicit validation candidate. They
are not automatically installed, and a provider name/domain alone is not a
match: manifest addon ID, catalog ID, type, filters and actual sample metadata
must agree. Each source validates up to two returned IDs; this is an import
sanity check, not exhaustive proof for every item. Empty/unreachable catalogs
cannot be verified during initial setup. A failed or canceled import does not
replace the previous collection file.

A metadata toggle or configuration change invalidates the validation proof.
Revalidate or update affected collections before returning to Home. A source
providing catalogs only may use a separately enabled compatible metadata addon.

## Continue Watching

Local progress works without Nuvio or Simkl. Optional account configuration is
under Accounts & tracking. Nuvio settings include upload/download/two-way
progress direction and a 30/60/120/300-second cadence (default 60). Local dirty
progress is debounced and sent sooner when connected; failed writes remain in
an account/profile-scoped queue. Do not disable the master cloud sync interval
and expect the faster progress worker to override that explicit OFF setting.

Simkl playback positions use the same configurable cadence; watched-history
refresh is no more often than 120 seconds. Requests may be delayed by active
sync cycles, network timeouts or retry backoff. Test with two devices before
relying on exact cross-device behavior. Outgoing Nuvio removals are queued;
remote delete-event/delta consumption is not implemented in this candidate.
A missing item in a remote snapshot is deliberately not treated as deletion.

## Performance, display and trailers

Performance & image cache offers **RAM 200 MiB**: 160 MiB compressed artwork
payload plus 40 MiB serialized browse payload, with a 128 MiB logical browse
cache on disk. The previous RAM 150 preset upgrades to RAM 200. Existing disk
or OFF choices are retained. This is not a global process-RAM limit: decoded
textures, Python objects, other caches and separate Kodi interpreters add use.

Initial Home loading promotes cached pages and warms missing initial pages
with four workers and a 40-second foreground ceiling. Back skips preparation;
remaining pages/details load on demand. Not every poster or full metadata body
is prefetched. Explicit Clear cache clears images and browse data. A normal
Settings visit does not clear persistent data.

Under Skin configuration → Automatic trailer settings, choose 90 seconds or
Full trailer (other durations remain available). New installations default to
90; an existing explicitly saved duration is kept until changed.

Names are preserved as Unicode, not machine-translated or transliterated. The
skin now uses Kodi's installed Unicode font. Exact CJK/emoji coverage and
colored emoji depend on that Kodi build; font binaries are not bundled.

## Regression checks on the device

Check Home final-row Down/focus after sync, actor round portrait and both
filmography rows, Season 2 labels and air dates, long plot scrolling, both card
layouts, cached/offline browsing, HUB access, film return without HUB flash,
IPTV preview/fullscreen/Esc, global clock/weather switch and screensaver wake.

For reports include device/OS/Kodi/component versions and reproduction steps.
Remove tokens, personalized URLs, PINs, profile exports and viewing history
from any shared log. A backup plus the previous bundle enables manual rollback.
