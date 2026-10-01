# Nuvio Hub 6.0.18 — review candidate

Prepared 1 October 2026 from the local 6.0.17 candidate (all earlier changes
included). Status: **local review candidate**; nothing pushed or published. How
Kodi shows trailers and the small IPTV player is unchanged.

## 1. "Frozen" screen in some Nuvio settings until OK

Some settings rows (Collections, Add-ons, IPTV setup, Trailers options, …) open
Kodi's own dialogs (lists, keyboard, add-on install or settings) while the Nuvio
settings page stayed on screen. When such a dialog ended up behind the page, the
picture looked frozen, the remote still worked in the invisible dialog, and OK
closed it. Every row that is not a plain On/Off switch or Back/Done now runs with
the settings page hidden, the same mechanism the interface already uses for
child pages; error messages are shown while it is hidden as well.

## 2. All Home collections and their posters in RAM at entry

The entry check already loads every collection's first catalog page from the
disk cache into memory. After a reboot the image RAM is empty, so the loading
screen now also loads the posters Home will show — the first 10 cards of every
catalog of every visible collection, exactly the URLs Home requests — into the
image proxy: six in parallel, with progress ("Loading posters into memory ·
n / total · Back to skip") and a 60 s limit; anything left continues in the
background on Home. When the image RAM is already full (no reboot) there is no
loading screen. Hidden rows and cards are not prepared.

## 3. Nuvio Hub › Configure (Kodi add-on settings)

* **Nuvio Hub**: Nuvio interface (Open Nuvio settings, Install or repair the
  interface, skin and screensaver) and Updates (Check for updates now).
* **Remove**: a short explanation and *Remove the Nuvio build*.
* Two subtitle preferences (language, subtitles on start) were declared outside
  any settings category, where Kodi ignores them; they are inside it now, so the
  choices are saved.

## 4. Frozen picture after a long suspend (CoreELEC)

Kodi kept running (remote and sounds worked) but the picture stayed frozen until
a power cycle. This matches a known Amlogic/CoreELEC suspend/resume display
problem. Nuvio's part: the service now stops Nuvio's own windowed video (Home
trailer preview, video screensaver) when the box goes to sleep, so no hardware
video layer is active across suspend. User-started playback is never touched.
If it still happens, it is on the CoreELEC side (worth reporting there with the
build version).

## 5. Shade around the small trailer player on CoreELEC

Not changed (as requested, the display path stays as it is). Both the hero shade
and the 6.0.16 black frame are drawn by the interface over the video area;
CoreELEC's Amlogic renderer only positions the video plane and does not erase
them, so whether they are visible depends on how the box composes the interface
with video (output mode such as Dolby Vision/HDR can affect this). On PCs the
shade is shown as before.

## 6. Checks

`python review/check_618.py` (incl. `test_nuvio_618.py`), release guard, builder
and packaged smoke test; two settings-page tests now stub the hide step.

## 7. Please check on the device

Collections / Add-ons / IPTV setup rows in Nuvio Settings; first entry after a
reboot (poster loading screen, then instant collections); Configure page; a long
suspend with and without a trailer preview playing.
