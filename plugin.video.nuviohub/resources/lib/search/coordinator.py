"""Fast-first provider search coordinator.

Providers are isolated, results are yielded as soon as they arrive, and a
slow task is never allowed to hold Kodi open after the deadline.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
import time


def iter_live(tasks, max_workers=6, timeout=None):
    """Yield ``(name, value)`` in completion order.

    ``tasks`` is a mapping of name -> zero-argument callable. Pending futures
    are cancelled at the deadline and executor shutdown never waits for them.
    """
    if not tasks:
        return
    pool = ThreadPoolExecutor(max_workers=max(1, min(int(max_workers or 1), len(tasks), 8)))
    futures = {}
    try:
        for name, fn in tasks.items():
            futures[pool.submit(fn)] = name
        iterator = as_completed(futures, timeout=timeout) if timeout else as_completed(futures)
        try:
            for future in iterator:
                name = futures[future]
                try:
                    yield name, future.result(timeout=0)
                except Exception:
                    yield name, []
        except TimeoutError:
            return
    finally:
        for future in futures:
            if not future.done():
                future.cancel()
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)


def run(tasks, max_workers=6, timeout=None):
    return {name: value for name, value in iter_live(tasks, max_workers=max_workers, timeout=timeout)}
