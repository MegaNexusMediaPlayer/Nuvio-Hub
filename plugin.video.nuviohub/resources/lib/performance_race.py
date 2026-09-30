# -*- coding: utf-8 -*-
"""Small, Kodi-free policies for fast-first parallel work."""
import time


def fair_job_order(jobs):
    """Round-robin jobs by provider (the first tuple element)."""
    groups = {}
    order = []
    for job in list(jobs or []):
        try:
            provider = job[0] or {}
            key = str(provider.get('id') or provider.get('name') or id(provider))
            if key in ('__plex__', '__emby__'):
                server = provider.get('_server') or {}
                key += ':' + str(server.get('id') or server.get('url') or
                                 server.get('name') or id(server))
        except Exception:
            key = str(id(job))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(job)
    out = []
    while any(groups.get(key) for key in order):
        for key in order:
            if groups.get(key):
                out.append(groups[key].pop(0))
    return out


def iter_search_results(race, result_count, has_real_source,
                        should_stop=None, on_ready=None, real_goal=12,
                        quiet_seconds=0.30, fallback_seconds=1.20,
                        poll_seconds=0.10, cancel_on_exit=True):
    """Yield completions until useful search results have settled."""
    first_useful = None
    last_progress = None
    last_count = 0
    try:
        while not race.done:
            if should_stop and should_stop():
                return
            for completed in race.poll(poll_seconds):
                yield completed
            now = time.monotonic()
            current = max(0, int(result_count() or 0))
            if current > 0 and first_useful is None:
                first_useful = last_progress = now
            if current != last_count:
                last_count = current
                last_progress = now
            if current <= 0 or first_useful is None:
                continue
            quiet_for = now - (last_progress or first_useful)
            useful_for = now - first_useful
            real_ready = bool(has_real_source()) and (
                current >= int(real_goal or 0) or quiet_for >= quiet_seconds)
            fallback_ready = useful_for >= fallback_seconds
            if real_ready or fallback_ready:
                if on_ready:
                    on_ready()
                return
    finally:
        if cancel_on_exit:
            race.cancel()


def iter_source_results(race, result_count, has_entries, started_at,
                        initial_timeout, stop_after_first, result_goal,
                        quick_grace, should_stop=None,
                        consume_continue=None, clear_sufficient=None,
                        mark_sufficient=None, full_timeout=25.0,
                        poll_seconds=0.10):
    """Yield initial source completions; leave the race alive for refresh."""
    first_result_at = None
    patient = False
    while not race.done:
        if should_stop and should_stop():
            return
        if consume_continue and consume_continue():
            patient = True
            if clear_sufficient:
                clear_sufficient()
        now = time.time()
        elapsed = now - started_at
        budget = full_timeout if patient else initial_timeout
        if elapsed >= budget:
            return
        for completed in race.poll(
                min(poll_seconds, max(0.01, budget - elapsed))):
            yield completed
        now = time.time()
        if has_entries() and first_result_at is None:
            first_result_at = now
        if (not stop_after_first or patient or int(result_goal or 0) == 0):
            continue
        enough = int(result_count() or 0) >= int(result_goal or 0)
        grace_done = bool(first_result_at is not None and
                          now - first_result_at >= quick_grace)
        if has_entries() and (enough or grace_done):
            if mark_sufficient:
                mark_sufficient()
            return
