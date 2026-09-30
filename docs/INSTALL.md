# Install and configure Nuvio Hub for Kodi 6.0.7

## Before installation

Use Kodi 21 / Omega. Prepare a Nuvio account, a configured AIOStreams or another compatible stream provider, AIOMetadata and a Simkl account. AIOMetadata is mandatory for the intended metadata experience, and Simkl is required for the full Continue Watching/tracking setup documented by this project. Local progress storage also exists without cloud tracking.

Your providers and accounts are configured separately. The bundle includes the four Nuvio components, not a ready-to-play personal provider profile.

## Install the bundle

1. Download `Nuvio-Hub-Complete-6.0.7.zip` from the repository's **Releases** page. Do not install GitHub's automatically generated source archive.
2. Enable **Kodi Settings → System → Add-ons → Unknown sources**, if Kodi requests it.
3. Open **Add-ons → Install from zip file** and select the bundle.
4. Launch **Nuvio Hub** from **Video add-ons** once. Allow it to install the included components.
5. Restart Kodi. Open **Nuvio** from **Program add-ons**. The Nuvio skin can also be selected under **Kodi Settings → Interface → Skin**.
6. In **Nuvio Settings → Accounts & tracking**, connect Nuvio and Simkl. Complete the displayed account/PIN flow.
7. In **Add-ons**, configure your AIOMetadata and stream provider setup, or synchronize the add-ons associated with your Nuvio account. Use the URLs supplied by your own provider configuration.
8. Open a title, confirm that metadata loads and that your provider returns playable sources. Play briefly and stop to create a fresh local resume record.
9. Use built in collections/you will need to setup aiometadata with https://numb3rs.stream or set up collections in nuvio web.

All four Nuvio components should report **6.0.7**: `plugin.video.nuviohub`, `script.nuvio`, `skin.nuvio` and `screensaver.nuvio`. External add-ons keep their own version numbers.

## Update an existing installation

Stop playback and close the Nuvio interface before installing the ZIP. Open Nuvio Hub once after installation, then restart Kodi. Keep the existing installation and userdata to retain accounts, settings, providers and playback positions. Manual ZIP updates are the current update mechanism.

## Optional integrations

IPTV requires the appropriate IPTV Simple component and your own authorized playlist/EPG configuration. YouTube and weather integrations are separate options. Skip/next-episode behavior depends on available episode metadata and timing data; missing data cannot be reconstructed by the interface.

## Common questions

**No playable sources:** check the stream provider configuration. AIOMetadata supplies metadata; it does not replace a provider that returns streams.

**Missing descriptions or cast pictures:** check AIOMetadata and the selected metadata provider. Some titles have incomplete upstream data.

**A title is missing from Continue Watching:** confirm Simkl is connected for the full tracking setup, then start and stop the title once. Positions never saved by an older version cannot be recovered retroactively.

**Continue Watching order:** 6.0.7 places recently watched local titles first, newest first, then remote-only records. The first card is selected when you return to Home. Continue Watching cards still resume playback; the separate Home/launcher Resume button was removed.

**Reporting a problem:** include device, OS, Kodi version, component versions and reproduction steps. Remove account tokens, personalized provider URLs and personal history from logs/screenshots before attaching them.
