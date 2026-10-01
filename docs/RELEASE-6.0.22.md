# Nuvio Hub 6.0.22 — set up on the phone

Prepared 1 October 2026 from the 6.0.21 review candidate (all of it included).
Status: **local review candidate**; nothing pushed or published.

## Phone setup

* **HUB Settings → Set up on phone · QR code** (first row), **Accounts → Nuvio
  account → Sign in with phone**, the first-start welcome
  (*Set up on your phone / with the remote / Skip*) and
  `RunScript(script.nuvio,phone)` open a QR screen on the TV.
* While that screen is open, MegaNexus serves a page from Kodi itself on the
  local network (`http://<tv-ip>:<random port>/?k=<one-time key>`). The phone
  must be on the same Wi-Fi; no external server is involved.
* The page (dark-blue MegaNexus look) has four tabs:
  * **Account** – Nuvio sign-in, profile choice, import add-ons (and
    optionally the collection layout) from Nuvio, sign out;
  * **Add-ons** – paste a configured manifest link, metadata and stream
    switches, remove an add-on;
  * **Collections** – order rows and cards, show/hide, rename cards, card
    titles on/off, catalog switches per card;
  * **Display** – portrait/landscape cards, ratings, automatic trailers,
    Continue Watching row, screensaver (MegaNexus image / animated).
* **Save & start MegaNexus** applies everything through the same backend
  functions the TV settings use, closes the QR screen, stops the service and
  opens MegaNexus. Back/Cancel on the TV or 15 idle minutes also stop it.
  Nothing listens afterwards.
* Security: every API call needs the key from the QR code (constant-time
  compare); without it the page shows only "scan the QR code". Manifest URLs
  and tokens are never sent to the phone; unexpected errors are not echoed;
  requests are not logged; the QR image is deleted when the screen closes.
  Traffic is plain HTTP inside the home network (as the 6.0.7 QR sign-in was).
  If the device has no network, the TV says so instead of showing a QR code.

## Old QR sign-in

`qr_pair.py` only had its page and window left (its server code was lost in
the 6.0.10 import), and was reachable only from the old backend menu. The
backend route `nuvio_qr_login` now opens phone setup.

## Checks

New `test_nuvio_622.py` runs the real HTTP service on 127.0.0.1: key required
for page and API, wrong key rejected, Save answers then finishes the session,
errors do not leak links, bad bodies rejected, port closed after stop, idle
timeout; collection order/visibility/titles/catalog switches; display value
validation; provider switches; state without URLs/tokens; entry points; TV
window stops the service and deletes the QR; no-network case. The settings
"Done" index test moved by one (new first row). Packaged smoke test imports
the phone modules from the ZIP. Pages were also rendered in headless
Chromium at phone width. Not tested: real phones, Windows firewall prompt,
Android TV / CoreELEC networking.
