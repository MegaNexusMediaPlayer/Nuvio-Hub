# Nuvio Hub 6.0.15 — no setup needed, Cinemeta defaults, Home rows on/off

Prepared 30 September 2026 from the local 6.0.14 candidate. Status: **local test
candidate**; nothing pushed or published. Home, menu and playback speed code is
unchanged; background catalog/poster loading works as before.

## 1. Nothing blocks entry into Nuvio

The setup gate no longer requires validated collections, enabled add-ons or a
passed catalog check. Opening Nuvio:

* no metadata add-on installed → **Cinemeta** is added and switched ON
  (`https://v3-cinemeta.strem.io/manifest.json`, id `com.linvo.cinemeta`:
  Popular / New / Featured catalogs for movies and series, genre filters, and
  metadata for IMDb `tt` IDs; no account or configuration);
* no collections → **Cinemeta default collections**: Discover (Popular, Top
  Rated, New in the current year) and 14 genres (Action … Western) for movies
  and series, using the collection artwork already in the bundle;
* offline on first start → the collections are saved anyway and fill when
  Cinemeta answers; entry is never refused;
* all metadata add-ons switched OFF → a one-step offer to switch them on
  (declining still enters).

Existing setups (Nuvio import, own collections, own add-ons) are left as they
are. Stream add-ons are still configured in Settings > Add-ons; without one,
Play explains what to enable.

## 2. Settings > Collections

* **Default collections · Cinemeta or numb3rs** — Cinemeta (default, no setup)
  or the numb3rs set. Choosing numb3rs shows what to do: set up AIOMetadata at
  https://numb3rs.stream, add its manifest URL under Settings > Add-ons and
  switch it ON under Metadata add-ons (Nuvio tells you when AIOMetadata is
  already installed). Until then those collections stay empty.
* **Home rows · show or hide** — Continue Watching and each collection group
  with an On/Off switch; hidden rows stay editable.
* **Edit each collection card** — "Show on Home" and each linked catalog's
  On/Off now save immediately. They used to be undone when the network check
  behind every save did not pass, which is why a switch appeared stuck on ON.
* **Check collection catalogs (report only)** — the former validation, now a
  report that never refuses or reverts anything.

## 3. Checks

`python review/check_615.py` (incl. new `test_nuvio_615.py`),
`python review/check_608_rebrand_kodi22.py 6.0.15`, builder, packaged smoke.
Two older expectations changed with the contract (saving collections no longer
depends on a check) and the setup-diagnosis test was removed with the gate.
Live check on 30 Sep 2026: all 34 default Cinemeta sources resolve against the
real manifest with valid filters; Crime series, 2026 movies, Featured and a
Shawshank meta request return data with Nuvio's User-Agent.

## 4. Please check

A fresh profile (Cinemeta appears, Home fills), Default collections → numb3rs
(help text, AIOMetadata detection), Home rows switches, Show on Home and catalog
switches in Edit, and that an existing Nuvio-imported setup is unchanged.
