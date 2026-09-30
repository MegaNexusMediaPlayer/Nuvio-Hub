# -*- coding: utf-8 -*-
"""Bounded runner for optional Nuvio Hub background work.

Kodi keeps the Python interpreter alive between plugin invocations.  Creating
one daemon thread for every cache warm, logo refresh, artwork refresh and
manual sync therefore accumulates native threads on long CoreELEC sessions.
This module gives those *optional* one-shot jobs one shared two-worker lane,
deduplicates equivalent jobs and bounds the waiting queue.

Playback, source-result polling and service loops deliberately do not use this
runner: those jobs own a lifecycle and must remain independently cancellable.
"""
from concurrent.futures import ThreadPoolExecutor
import threading


_MAX_QUEUED = 8
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='NuvioHub-bg')
_SLOTS = threading.BoundedSemaphore(_MAX_QUEUED)
_LOCK = threading.Lock()
_ACTIVE_KEYS = set()


def submit_optional(target, args=(), kwargs=None, key='', on_error=None):
    """Submit an optional one-shot job without ever blocking the caller.

    Returns ``True`` when accepted and ``False`` when an equivalent job is
    already active, the small queue is full, or Kodi cannot allocate a worker.
    Exceptions stay contained in the worker and may be reported through the
    optional ``on_error(exc)`` callback.
    """
    if not callable(target):
        return False
    task_key = str(key or '').strip()
    with _LOCK:
        if task_key and task_key in _ACTIVE_KEYS:
            return False
        if not _SLOTS.acquire(False):
            return False
        if task_key:
            _ACTIVE_KEYS.add(task_key)

    def _run():
        try:
            return target(*(tuple(args or ())), **dict(kwargs or {}))
        except Exception as exc:  # optional work must never crash Kodi UI
            if callable(on_error):
                try:
                    on_error(exc)
                except Exception:
                    pass
            return None
        finally:
            with _LOCK:
                if task_key:
                    _ACTIVE_KEYS.discard(task_key)
                try:
                    _SLOTS.release()
                except ValueError:
                    pass

    try:
        _POOL.submit(_run)
        return True
    except Exception as exc:
        with _LOCK:
            if task_key:
                _ACTIVE_KEYS.discard(task_key)
            try:
                _SLOTS.release()
            except ValueError:
                pass
        if callable(on_error):
            try:
                on_error(exc)
            except Exception:
                pass
        return False


def active_count():
    """Small diagnostic snapshot; contains no titles, URLs or user data."""
    with _LOCK:
        return len(_ACTIVE_KEYS)
