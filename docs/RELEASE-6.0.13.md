# Nuvio Hub 6.0.13 — CoreELEC windowed video, IPTV buttons, steadier loading

Prepared 30 September 2026 from the local 6.0.12 candidate. Status: **local test
candidate**; nothing pushed or published. The 6.0.12 speed changes are unchanged.

## 1. IPTV guide buttons

"Refresh guide" and "IPTV setup" are narrower and a **HUB** button sits next to
them at the bottom (same action as the HUB button at the top). Left/right
navigation runs Refresh guide → IPTV setup → HUB.

## 2. Small video black with sound on CoreELEC

On Windows the video is drawn into Kodi's interface, so the Home trailer preview,
the IPTV guide preview and the Details trailer window show it. Amlogic/CoreELEC
boxes draw hardware video on a separate plane under the interface; some CoreELEC
configurations — most often Dolby Vision processing of SDR video (VS10) — leave
that windowed video black while the sound plays, although fullscreen playback
(like IPTV fullscreen) is fine. CoreELEC builds have added a "Skip DV for
windowed playback" option for exactly this case (skin trailer previews).

6.0.13 offers three ways out, without changing speed-critical code:

* **Settings > Trailers > CoreELEC: windowed video is black?** reads the device's
  Dolby Vision settings through Kodi (no hard-coded, build-specific IDs). If the
  build has a windowed-playback exception, it offers to switch it on (only after
  confirmation). Otherwise it lists the Dolby Vision settings found and explains
  what to change in Settings > Player > Videos.
* **Settings > Trailers > Windowed video** (ON by default). OFF: Home trailer
  previews are not started, the Details trailer plays in Kodi's normal
  fullscreen player (Back returns to the title), and the first click on an IPTV
  channel opens fullscreen directly (Back returns to the guide).
* On CoreELEC, the first small video that starts shows a one-time notification
  pointing to the helper.

Independently of the device, the Home hero shade and fade drawn over the preview
become 55% opaque while a preview plays, so the video is brighter (the text
stays readable).

## 3. Image breaks during "Loading video"

With autoplay, source search and playback start used two separate loading
screens; closing one and opening the next briefly showed the page underneath.
One loading screen now stays up from the source search until the video starts
(it closes before any error dialog). Manual source selection is unchanged.

## 4. Checks

- `python review/check_613.py` (maintained suite incl. `test_nuvio_613.py`),
  `python review/check_608_rebrand_kodi22.py 6.0.13`, builder and packaged smoke.

## 5. Limits

Not tested on a device here. Check on CoreELEC: the helper (which Dolby Vision
settings it finds and whether the windowed exception exists), a Home preview and
an IPTV preview after the change, Windowed video OFF behaviour for trailer and
IPTV, and autoplay start without flashes.
