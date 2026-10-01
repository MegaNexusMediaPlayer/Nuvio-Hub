# Nuvio Hub for Kodi — 6.0.13 test candidate

A community-built Nuvio-style experience inside Kodi: browse collections, explore films and series, and return to what you were watching from a remote-friendly home screen.

**6.0.13 is a local test candidate, not a verified Windows/CoreELEC runtime release.** It adds CoreELEC windowed-video fixes, IPTV buttons and a steadier loading screen (see [6.0.13 changes](docs/RELEASE-6.0.13.md)); 6.0.12 fixed playback start/exit speed, trailers and details (see [6.0.12 changes](docs/RELEASE-6.0.12.md)). 6.0.11 focused on Home responsiveness: collections open from cache immediately, stale pages refresh in the background, the collection under the cursor is prefetched and collection sources load in parallel. See [6.0.11 changes](docs/RELEASE-6.0.11.md), [6.0.10 candidate changes and limitations](docs/RELEASE-6.0.10.md), [setup](docs/INSTALL.md) and [the engineering contract](AGENTS.md).

This candidate adds validated collections, independently enabled metadata providers, a person page, corrected progress wire identities and timestamps, a frequent outbox-based sync cycle, persistent browse caching and bounded startup prewarming. Nuvio and Simkl accounts are optional. No internal collection set is silently installed as a substitute for your configuration.

**6.0.7 was the first public baseline for this project. 6.0.8 is the branding, language and Kodi 22 compatibility maintenance release.** It keeps the Nuvio Hub backend, Nuvio interface, skin and screensaver in one installation package, removes the old Arabic UI layer, and completes the runtime Nuvio Hub rebrand while retaining only upgrade-safe legacy aliases. This is an unofficial community project with a custom Kodi interface. It is not an official Nuvio or Team Kodi release.

![Nuvio home with demonstration content](docs/screenshots/home.png)

## What we have built

Included experience
Nuvio Hub brings a complete Nuvio-style experience to Kodi, combining browsing, streaming, metadata, subtitles, and watch tracking in one interface.
- Nuvio account and addon integration — connect your account and bring your configured Nuvio addons into Kodi.
- AIOStreams integration — connect your streaming setup and browse available sources, with manual stream selection when you want more control.
- AIOMetadata integration — rich movie and series information, artwork, cast, crew, and recommendations.
- Simkl integration — connect your watch tracking and watched history.
- Automatic subtitles — automatic subtitle loading during playback, with options to change subtitles when needed.
- Continue Watching — resume movies and episodes from your saved progress, with recently watched content shown first.
- Movie and series discovery — browse addon catalogs, open detailed information, and explore related titles.
- Full episode browsing — season tabs, episode descriptions, watched indicators, and portrait or landscape layouts.
- A unified Kodi interface — access your addons, sources, metadata, subtitles, and playback through the Nuvio Hub skin.
The experience depends on your connected accounts, configured addons, and available sources.

[Download latest](https://github.com/MegaNexusMediaPlayer/Nuvio-Hub/releases/latest) · [View screenshots](docs/SCREENSHOTS.md) · [Installation](docs/INSTALL.md) · [Contribute](CONTRIBUTING.md) · [6.0.13 candidate notes](docs/RELEASE-6.0.13.md)

## What you need

For Home browsing, configure the following:

| Requirement | Purpose |
| --- | --- |
| **Kodi 21 / Omega or Kodi 22 / Piers** | Python 3 and the retained GUI ABI; target-device verification is still required. |
| **At least one enabled metadata addon** | Compatible title metadata. AIOMetadata is supported but is not the only allowed provider. |
| **At least one enabled stream addon** | Playable sources from your authorized configuration. |
| **Imported or manually created, validated collections** | Source addon, catalog, filters and sample metadata identities must agree. |
| **Nuvio account — optional** | Account addon/collection import and cloud progress synchronization. JSON import and manual catalog setup work without login. |
| **Simkl account — optional** | Simkl progress/history synchronization; local resume works without it. |

Collection validation samples up to two items per catalog source. An empty, unreachable or incompatible source cannot pass initial verification. Internal presets are explicit candidates and must pass the same validation. A successful check is not a guarantee that every title or future provider response has full metadata.

The project does not host films, series or subscription services. Configure sources you are authorized to access. A collection name or service logo does not provide access to that service.

## Install the 6.0.13 test candidate

1. Back up your Kodi profile. Use **`Nuvio-Hub-Complete-6.0.13.zip`**, not GitHub's automatic source archive. This local candidate has not been published to GitHub Releases.
2. Stop playback, close Nuvio and select the bundle through **Add-ons → Install from zip file**.
3. Open the backend **Nuvio Hub** once to update the three bundled components, then restart Kodi. Keep existing userdata; do not uninstall to update.
4. Under **Nuvio Settings → Add-ons**, enable your metadata and stream providers separately.
5. Under **Collections**, import from Nuvio, import a JSON export without login, or create from installed catalogs. Existing collections are preserved and rechecked. Home opens only after validation succeeds.

The first Home load shows a cancellable collection preparation screen only when cache pages are missing entirely; pages kept from earlier sessions are shown at once and refreshed in the background. It warms initial catalog pages within bounded time and memory; it does not download all pages or full details of an unlimited catalog.

See [the complete installation guide](docs/INSTALL.md) for accounts, cache, trailers and troubleshooting.

## Help shape the next release

We are opening the project so other people can test it, improve it and help maintain it. Help is especially welcome with Python/Kodi development, skin XML and remote navigation, performance, metadata edge cases, documentation and testing on CoreELEC and other Kodi devices.

Start with an issue or a pull request. Everyone can contribute through a fork; trusted ongoing contributors can be invited as repository collaborators with write access. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Support development

Ko-fi support is optional. Contributions help cover development tools, AI token costs, testing and maintenance. Bug reports, code reviews and documentation are welcome contributions too.

**[Support development on Ko-fi](https://ko-fi.com/master100janovic).** There is no donation requirement to use the project or submit a contribution.

## Testing and current limits

Run `python review/check_613.py`, the release guard, builder and packaged smoke test documented in [AGENTS.md](AGENTS.md). Results are in `review/results-6.0.13.json` and the candidate report. These checks use Kodi/HTTP stubs and local SQLite, not a native Kodi process or live user accounts. Unicode glyph coverage, two-device sync and visual/navigation behavior require the manual checklist. No target-device speed benchmark has been performed.

The screenshots use fictional demonstration content. One separate development capture has identifying content and collection artwork blurred. They illustrate the interface, not bundled playable media.

## Credits and licenses

Thanks to NuvioTV, Kodi/Estuary and the upstream projects whose work made this possible. Original copyright notices and license files are retained. Components and assets carry different licenses; this repository does not apply a new blanket license over them. See [LICENSE.md](LICENSE.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
