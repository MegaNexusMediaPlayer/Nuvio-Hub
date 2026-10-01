# Upstream acknowledgements

MegaNexus itself is under the [MegaNexus License](LICENSE.md). These parts keep their own licenses:

- [python-qrcode](https://github.com/lincolnloop/python-qrcode) in `plugin.video.nuviohub/resources/lib/qrcode`: BSD license, see its `LICENSE` file.
- Subtitle flag icons in `skin.nuvio/media/windows/subtitles/flags`: MIT (GoSquared). Home images in `skin.nuvio/extras/home-images`: CC0.
- [Kodi 21.3 Estuary](https://github.com/xbmc/xbmc/tree/21.3-Omega/addons/skin.estuary): the skin foundation, standard dialogs, fonts and OSD. Code and artwork have the licenses described in `skin.nuvio/LICENSE.txt`.
- [NuvioTV](https://github.com/NuvioMedia/NuvioTV): Nuvio mark/wordmark assets used up to 6.0.19 (commit `71632b9271e8bce6783e415d64f34cfa4e8b894c`); its GPL-3.0 text stays included. Since 6.0.20 the logos are the project's own MegaNexus artwork.
- [stremio-perfect-setup](https://github.com/luckynumb3rs/stremio-perfect-setup): the origin recorded for supplied collection artwork/configuration. Its inclusion is an attribution, not a claim that this project owns third-party media or service marks.

The four component directories contain the detailed notices. Third-party Python code and skin assets retain their individual headers and license files. Do not remove them when redistributing or contributing.

This community project is independent of Nuvio, Kodi/Team Kodi, Simkl and the metadata/stream providers it can connect to. Collection labels identify categories and do not grant subscriptions or playback rights.

## Font handling in 6.0.10

This candidate references the Unicode font installed with Kodi through `special://xbmc/media/Fonts/arial.ttf`; it does not redistribute font binaries. Historic upstream font credits remain as attribution. Actual glyph coverage depends on the installed Kodi build.
