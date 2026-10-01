# Nuvio Hub 6.0.31 — crisp corners, proper pill shape, sharp logo, seamless saver loop

Prepared 1 October 2026 from the 6.0.30 test build (not released).

* **Pixelated corners (since the beginning)** had two causes:
  * card masks and the focus frames were drawn at 3x; Kodi shrinks GUI
    textures without mipmaps, so their curves came out jagged. They are now
    redrawn at 2x with supersampled edges (cards radius 19, focus frame
    radius 25);
  * pills/buttons used one 64 px 9-slice texture; Kodi draws 9-slice borders
    1:1 (GUITexture.cpp), so corners turn soft/blocky when the GUI is scaled
    up (4K) and the glass version lost its shape. Every pill and button of a
    fixed size now has its own crisp 2x texture (26 sizes), tinted by its
    colour; glass pills are 20 % white at rest and white when focused.
  Large panels keep their 9-slice texture (a 2x full-size texture would cost
  a lot of GPU memory).
* The capsule behind clock and weather is removed.
* The focus frame used when moving through menus and rows is the redrawn
  2x ring, so its edge is smooth.
* **Sharp MegaNexus logo everywhere.** The 1600x507 logo was shrunk 5-10x
  by Kodi (no mipmaps), so its edges were jagged. Every logo now uses its
  own 2x texture rendered with Lanczos from that master: Home and compact
  header and phone setup 568x180 (shown 284x90), IPTV 454x144, details
  303x96. The master stays for the phone setup page in the browser.
* **External MP4 screensaver loops without a black break.** The clip is
  rewound to 0 a full second before its end (was 0.35 s, often missed on
  slow boxes, so Kodi closed and reopened the file) and the end is checked
  every 20 ms during the last 2.5 s. A 15 s clip plays 0-14 s in an endless
  loop; the file is never reopened.

Implementation: `review/make_crisp_shapes.py` (assets, logos + idempotent XML
patch), `script.nuvio/nuvio_ui/saver.py` (loop);
Dark/Dim regenerated.

Checks: `test_nuvio_631.py` (2x masks/rings, every referenced pill texture
exists at 2x, nothing left to convert, HUB glass tints, capsule gone, every
logo uses a 2x texture of its drawn size, the saver rewinds a second early
with fast polling and never reopens the file);
`test_nuvio_628/629` updated. `python review/check_631.py`, release guard,
builder, packaged smoke test.
