# Nuvio Hub 6.0.14 — video on CoreELEC, trailer shade, screensaver loop

Prepared 30 September 2026 from the local 6.0.13 candidate. Status: **local test
candidate**; nothing pushed or published. Home/menu speed code is unchanged.

## 1. Black video with sound on CoreELEC — root cause and fix

Home trailer previews, the IPTV guide preview, the trailer window and the video
screensaver all play inside Nuvio *dialogs*. Kodi presents hardware video layers
(Amlogic/CoreELEC, Android, and similar) only from `CGUIWindowManager::RenderEx`,
and that function deliberately skips dialogs:

> "We don't call RenderEx for now on dialogs since it is used to trigger non gui
> video rendering." — xbmc `GUIWindowManager.cpp` (Omega)

The dialog's own `videowindow` still clears its rectangle, so the picture area
was black while the audio played. On Windows/PC the video is drawn into the GUI
(`CRenderManager::Render` returns early for GUI-layer renderers in that pass),
which is why it always worked there, and why skin-based trailers (e.g. Bingie /
Arctic skins, whose video window lives in a skin *window*) work on CoreELEC.

Fix: a never-shown `videowindow` in the windows that sit under Nuvio dialogs —
the frontend session window (`nuvio_session.xml`, active during every Nuvio
session) and the skin's Home and SkinSettings windows (HUB and screensaver
outside a session). `RenderEx` visits every child control, visible or not, so
Kodi now presents each video frame; the frame goes to the rectangle last set by
the dialog's visible `videowindow`, i.e. exactly where the preview is. No Python
playback code changed, and nothing changes on PCs.

The 6.0.13 workaround (Dolby Vision helper, one-time CoreELEC notice, "Windowed
video" switch and fullscreen fallback) was removed instead of kept alongside the
real fix; the trailer, Home preview and settings code is back to the 6.0.12
version. The 6.0.13 IPTV HUB button and the single loading screen remain.

## 2. Trailer shade restored

The 6.0.13 change that lightened the Home hero shade/fade to 55% during a preview
was reverted; the hero XML is identical to 6.0.12 again.

## 3. Video screensaver stopped after one pass

When a short clip ended, Kodi still reported "playing" for a moment while no
video was left to own; the loop took that as another program taking the player
and closed the screensaver. It now waits up to 3 s for Kodi's end-of-file
teardown and starts the next loop. The artwork shown until the first frame is
unchanged (it avoids a black flash).

## 4. Checks

`python review/check_614.py`, `python review/check_608_rebrand_kodi22.py 6.0.14`,
builder and packaged smoke test. New `test_nuvio_614.py`; the 6.0.13 tests for
the removed workaround were removed with it.

## 5. Please check on CoreELEC

Home auto-trailer, IPTV guide preview (first click), Details trailer button, the
MP4 screensaver (normal activation and Kodi's preview button, including a clip
shorter than a minute), and that fullscreen playback is unchanged.
