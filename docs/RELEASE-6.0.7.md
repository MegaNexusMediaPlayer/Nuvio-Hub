# Nuvio Hub for Kodi 6.0.7 — first public baseline

This release opens the project to community testing and contributions. It packages Nuvio Hub, the Nuvio interface, skin and screensaver together, all at version 6.0.7.

## Included experience

- A remote-friendly home screen with collections and Continue Watching.
- Season tabs with Specials last, poster/landscape episode artwork and individual descriptions.
- Cast and crew portraits, Info, More like this and manual stream selection through the context menu.
- Watched indicators, local resume records and account/tracking integration.

## Changes in 6.0.7

The newest locally watched title appears first on the left in Continue Watching, followed by older local titles and remote-only records. Saved progress, completion and metadata merge rules are unchanged. The separate Resume video button and its unused launcher handler were removed; selecting a Continue Watching card still resumes the video.

## Required setup

Kodi 21, a Nuvio account, AIOStreams or another compatible stream-providing add-on, AIOMetadata for the intended full metadata experience, and Simkl for the complete Continue Watching/tracking setup. Some local fallback functionality exists without account connections.

## Installation

Download **Nuvio-Hub-Complete-6.0.7.zip**, install through Kodi's **Install from zip file**, launch **Nuvio Hub** once, then restart Kodi. Existing users should stop playback and close the interface first, while preserving userdata. The automatic GitHub source archive is not the installer.

## Validation

The baseline records seven targeted Continue Watching tests and four Kodi 21.3 ordering scenarios. Packaged module and asset checks are included in the development tools. CoreELEC hardware and live account behavior need broader community testing.

This is an unofficial project. We welcome testers, Python/Kodi developers, skin contributors and documentation help. Open an issue or pull request; ongoing collaborators can be invited to the repository.
