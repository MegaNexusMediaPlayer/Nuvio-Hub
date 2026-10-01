"""Lightweight Continue Watching cadence, independent of idle-only library sync."""
import time


def retry_delay(error, failures):
    try:
        delay = float((getattr(error, 'headers', None) or {}).get('Retry-After') or 0)
    except (TypeError, ValueError):
        delay = 0
    return min(3600, max(delay, min(900, 30 * (2 ** min(failures, 5)))))


class Scheduler:
    def __init__(self, window, clock=time.monotonic):
        self.window, self.clock = window, clock
        self.next_nuvio = self.next_simkl = self.next_flush = 0.0
        self.nuvio_failures = self.simkl_failures = 0
        self.dirty_since = None
        self.last_request = ''
        self.account = ''
        self.last_scope = None

    def step(self, sync, simkl, settings, cycle_lock):
        from . import nuvio_progress
        now = self.clock()
        try:
            interval = max(30, min(300, float(settings.getSetting('nuvio_progress_interval') or 60)))
        except (TypeError, ValueError):
            interval = 60
        account = nuvio_progress.scope()
        if account != self.account:
            self.account = account
            self.next_nuvio = 0
            self.nuvio_failures = 0
        request = self.window.getProperty('nuvio.progress.pull_requested')
        if request != self.last_request:
            self.last_request = request
            # Focus/return requests may advance the ordinary schedule, never backoff.
            if not self.nuvio_failures:
                self.next_nuvio = min(self.next_nuvio, now)
            if not self.simkl_failures:
                self.next_simkl = min(self.next_simkl, now)
        dirty = self.window.getProperty('nuviohub.sync_dirty')
        if dirty and self.dirty_since is None:
            self.dirty_since = now
        elif not dirty:
            self.dirty_since = None
        dirty_due = bool(dirty and self.dirty_since is not None and now-self.dirty_since >= 5)
        due_nuvio = now >= self.next_nuvio or (dirty_due and not self.nuvio_failures)
        if not cycle_lock.acquire(False):
            return
        try:
            if simkl.enabled() and simkl.authorized() and now >= self.next_flush:
                try:
                    simkl.flush_progress()
                except Exception:
                    pass  # Durable outbox is retained; its own backoff governs retries.
                self.next_flush = self.clock() + 10
            allowed = (account and 'nuvio' in sync.enabled_targets() and
                       sync._sections_for('nuvio').get('progress') and
                       settings.getSetting('cloud_sync_interval_min') != '0')
            if allowed and due_nuvio:
                try:
                    result = sync.run_sync(targets=['nuvio'], sections={
                        'progress': True, 'addons': False, 'collections': False, 'library': False})
                    if not result or not result.get('ok'):
                        raise RuntimeError('Progress sync not acknowledged')
                    self.nuvio_failures = 0
                    self.next_nuvio = self.clock() + interval
                    if self.window.getProperty('nuviohub.sync_dirty') == dirty:
                        self.window.clearProperty('nuviohub.sync_dirty')
                        self.dirty_since = None
                    # Bounded batches continue without discarding the rest of the queue.
                    if nuvio_progress.pending(limit=1):
                        self.next_nuvio = min(self.next_nuvio, self.clock()+10)
                except Exception as error:
                    self.nuvio_failures += 1
                    self.next_nuvio = self.clock() + retry_delay(error, self.nuvio_failures-1)
            if simkl.enabled() and simkl.authorized() and now >= self.next_simkl:
                try:
                    simkl.sync_playback_progress()
                    from . import simkl_watched
                    simkl_watched.refresh(max_age=max(120, interval))
                    self.simkl_failures = 0
                    self.next_simkl = self.clock() + interval
                except Exception as error:
                    self.simkl_failures += 1
                    self.next_simkl = self.clock() + retry_delay(error, self.simkl_failures-1)
        finally:
            cycle_lock.release()


def run(monitor, cycle_lock):
    import xbmcgui
    from .nuviohub import nuvio_stremio_sync as sync
    from . import simkl, settings_cache
    if monitor.waitForAbort(5):
        return
    scheduler = Scheduler(xbmcgui.Window(10000))
    while not monitor.abortRequested():
        try:
            scheduler.step(sync, simkl, settings_cache.cached_addon(), cycle_lock)
        except Exception:
            # Never emit tokenized endpoint URLs through an exception message.
            if monitor.waitForAbort(15):
                return
        if monitor.waitForAbort(2):
            return
