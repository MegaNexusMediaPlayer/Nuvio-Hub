# Nuvio Hub 6.0.32 — seamless silent screensaver, more in RAM, plain header

Prepared 1 October 2026 from the 6.0.31 test build (not released).

* **Screensaver video without mute and without the stall at the loop point.**
  6.0.31 still muted Kodi and rewound the clip with a seek; a seek flushes the
  decoder, which froze the picture for about a second on Android boxes.
  MP4/M4V/MOV clips now play from a copy that already contains the clip back
  to back for one hour (`script.nuvio/nuvio_ui/mp4loop.py`): only the small
  index is rewritten to list the video samples again and again, the media
  bytes are copied once and unchanged, and the audio track is left out. The
  player sees one continuous video, so the last frame is followed directly by
  the first frame (no seek, no reopen), and with no audio track Kodi is never
  muted. The copy is written when the clip is chosen (progress dialog, can be
  cancelled) or, if missing, while the screensaver artwork shows; only the
  current clip's copy is kept in `addon_data/script.nuvio/saver_loop`.
  Fragmented MP4, MKV, WebM, AVI and TS keep the 6.0.31 behaviour (mute and
  seek loop); a notice says so when such a clip is chosen.
* **More in RAM, so catalogs and titles open faster.**
  * Catalog pages get 96 MiB of RAM with the default image preset (RAM
    256 MiB); 40 MiB held only ~75 of ~130 Home catalogs, the rest were read
    from disk and decoded on every open. Smaller presets keep 40 MiB. The disk
    cache grows from 128 to 192 MiB.
  * Full title details (cast, episodes, trailer) have their own 32 MiB RAM
    pool (12 MiB with smaller presets) and only share the disk; opening titles
    no longer pushes catalogs out of memory.
  * Resting on a title for 0.6 s (Home rows and catalog screens) loads its
    details quietly; Details then opens complete. One title at a time, the
    latest wins, it waits while a catalog you opened is loading or a video
    plays, and a failed title is not retried for 2 minutes.
  * When a catalog screen opens, the next page of every source is queued for
    the background refresher, so "Load more" opens from memory.
* **Header buttons** Home / Search / Settings / HUB are plain text at rest;
  the pill shows only on the focused button.

Not changed: Kodi keeps decoded textures on the GPU and re-reads window XML
on every open; Python cannot hold those.

Checks: `test_nuvio_632.py` (loop copy: every frame of every copy equals the
clip, one video track only, edit list, index-first input, one-hour default,
unsupported formats; saver plays the copy without muting and keeps the muted
seek loop otherwise; copy written once and old copies removed; page RAM by
preset; details stay out of page RAM; prefetch loads once, no duplicate jobs,
no retry storm, latest title wins, people skipped; next page queued only when
missing; header buttons). The loop copy was also decoded with FFmpeg 9:
H.264 with B-frames and HEVC/MOV, frame checksums equal the clip repeated,
presentation timestamps strictly continuous. `python review/check_632.py`,
release guard, builder, packaged smoke test.
