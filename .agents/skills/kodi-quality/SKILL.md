---
name: kodi-quality
description: Review and verify Nuvio Hub Python, Kodi XML, metadata contracts, and release packaging.
---
# Kodi quality review

Read root AGENTS.md and the latest candidate notes before changing behavior.
Trace frontend → backend → provider / database → callback paths, not just the
function reporting an error. Explain invariants in tests rather than relying
only on text/AST assertions. Keep existing upgrade/profile compatibility.

## Review procedure

1. Reproduce with a focused failing fixture: malformed manifests, unsupported
   ID prefixes, repeated requests, Unicode text, cancellation, stale workers,
   runtime-less progress, seconds versus milliseconds and account changes.
2. Verify current primary API schemas. Metadata failures must fall through only
   to explicitly enabled compatible providers; an unrelated response ID must
   be rejected, not relabeled. Collection validation must preserve old data.
3. Inspect exception/finally paths, SQLite connection closure, thread ownership,
   secrets in logs, network timeout/retry bounds, and outbox acknowledgements.
4. Review matching XML control IDs, visibility, focus neighbors and skin assets.
   Validate both card orientations and empty/one-row/long-description states.
5. Run `python review/check_610.py`, the versioned ABI/rebrand guard, deterministic
   builder, and packaged smoke test from AGENTS.md. Inspect nested packages.
6. Record actual checks and unresolved device/API cases. Never treat mocked
   xbmc imports or XML parsing as rendered/native playback tests.

## Sync correctness checklist

Use real epoch timestamps. Older remote data must not undo newer local work;
newer remote data must not be overwritten by stale pending local rows. Queue
and acknowledgement must preserve changes written during HTTP requests. No
synthetic runtime from a percentage. Keep account/profile scope across retries.
Do not equate an absent item in a bounded response with a remote delete. Test
pause/stop/completion, offline retry, duplicate identities and direction flags.

## Release checklist

All component and dependency versions agree; zip root is a Kodi addon, not a
repository. Embedded component hashes match. Exclude tests/profile secrets,
font files, pycache and development artifacts. Retain licenses. Keep the
previous installer/profile backup for a manual rollback. No unrequested push.
