---
name: kodi-performance
description: Improve Nuvio Home and collection responsiveness without blocking Kodi UI or overloading devices/providers.
---
# Kodi performance work

Read AGENTS.md and kodi-quality. Optimize the measured slow path, not API call
counts in isolation. First define cold/warm Home and collection timing, focus
latency, request counts and resident memory measurements on the target device.
No benchmark claim without that measurement.

## Current architecture

The ram200 preset budgets 160 MiB downloaded artwork bytes in the backend art
service and 40 MiB serialized browse data per frontend cache instance. SQLite
has a 128 MiB logical browse-payload budget; pages, Python objects and decoded
Kodi/GPU textures add overhead. Separate Kodi interpreters can own separate
cache instances. Do not advertise this as a global 200 MiB process cap.

Home startup checks/promotes persisted first pages with one SQLite read, warms
misses with at most four workers and a 40-second total foreground budget, and
lets Back skip. Warm-up covers each configured catalog's initial page, not all
pagination or full details of every title. Poster priming is bounded and
cancellation-aware.

Catalog pages are stale-while-revalidate (6.0.11): fresh for 30 minutes, then
usable as stale for 7 days while one daemon worker with a 64-entry queue
revalidates them. Stale pages never trigger the loading screen. `peek` and
`load_catalog(cached_only=...)` are network-free; Home paints cached shelves
synchronously (disk point lookups only for the first six shelves). A collection
tile that stays selected for 250 ms is prefetched with its neighbours on one
worker; moving on cancels queued prefetches. Identical reloads do not rebuild a
list. `simkl_watched.snapshot()` and `metadata_providers.signature()` are
memoized and must be treated as read-only.

## Preferred optimizations

* Seed cards/details immediately, then fetch missing enrichment off the UI
  thread; coalesce concurrent identical requests and guard stale responses.
* Reuse validated disk entries across launches. Use cache keys that include
  provider configuration, resource, ID, type and filter. Do not serve one
  account/provider's stale result in another namespace.
* Keep an LRU with byte accounting; limit each entry and worker pool. Publish
  progress during cold loading, tolerate individual failures, and defer work
  when playback or cancellation requires priority.
* Do not clear cache on a normal Settings visit. Clear deliberately or change
  namespaces when relevant settings change. Test expiry, memory eviction,
  restart persistence, disk errors and duplicate-request coalescing.
* Update only changed rows and restore stable selected identity. Do not steal
  focus after Continue Watching sync or wrap the final Home row to the top.
* Retain native Kodi playback and texture caching. Avoid global advancedsettings,
  cache allocation, PVR fullscreen, resolution or decoder changes without need.

## Evidence to include

Run automated suite and packaged imports. For performance claims record device,
OS, Kodi version, catalog sizes, provider/network latency, cold/warm cache state,
median and worst observed times, peak RSS, and navigation during sync/prefetch.
Without a device, report architectural improvements, not guaranteed speedups.
