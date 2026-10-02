# Install and configure MegaNexus (Nuvio Hub) 6.0.38

The supported code/API target is Kodi 21 and Kodi 22.

## Install from the MegaNexus repository (recommended)

1. Kodi **Settings → File manager → Add source**: enter
   `https://meganexusmediaplayer.github.io/Nuvio-Hub/` and name it `MegaNexus`.
2. **Add-ons → Install from zip file → MegaNexus →
   repository.meganexus-1.0.0.zip**.
3. **Add-ons → Install from repository → MegaNexus Repository → Video add-ons →
   Nuvio Hub → Install.** Kodi then installs updates from the repository.

The interface, skin and screensaver install themselves a few seconds after the
backend is installed or updated (no "Install or repair" needed). Then open
MegaNexus and choose **Set up on your phone** to configure it with a QR code.

## Manual ZIP

Back up your Kodi profile first. Stop playback and close the Nuvio frontend.
Install `Nuvio-Hub-Complete-6.0.38.zip` via Add-ons → Install from zip file.
All four components must report 6.0.38. Keep userdata; do not uninstall or
delete credentials/settings to update. The source archive is for development
and is not installable through Kodi's ZIP installer.

## Accounts are optional; nothing has to be set up first

Nuvio opens straight away. When nothing is configured (no Nuvio import, no
metadata add-on, no collections), Cinemeta — Stremio's public metadata add-on —
is added automatically and supplies metadata plus default Home collections
(Popular, Top Rated, New this year and genres).

Settings > Collections:

* **Default collections** — Cinemeta (default, no setup) or the numb3rs
  collections. The numb3rs set needs AIOMetadata configured at
  https://numb3rs.stream; its manifest URL is added under Settings > Add-ons and
  switched ON under Metadata add-ons. Nuvio shows these steps when you pick it.
* **Home rows · show or hide** — switch each collection group and Continue
  Watching on or off.
* **Edit each collection card** — name, pictures, Show on Home, and each linked
  catalog with its own On/Off switch. Changes save at once.
* Import from a Nuvio account or a JSON export, or create collections from
  installed catalogs. **Check collection catalogs** gives a report only; an
  unavailable catalog simply stays empty on Home.

In Settings > Add-ons, add your own configured manifest URLs and switch metadata
and stream add-ons on or off. A metadata add-on that is OFF is never used as a
silent fallback.

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

Collections open from the local catalog cache. Pages stay fresh for 30 minutes
and remain usable for up to 7 days; an older page is shown immediately and
refreshed in the background, so the next visit shows the new titles. Keeping a
collection tile selected briefly prefetches it (and its neighbours) together
with its first posters.

Performance & image cache offers **RAM 256 MiB** (default since 6.0.27): 256 MiB compressed artwork
payload plus 40 MiB serialized browse payload, with a 128 MiB logical browse
cache on disk. Earlier RAM 150/200 presets upgrade to RAM 256. Existing disk
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
