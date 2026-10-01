"""Cancellable first-page warm-up; bounded workers, no invisible infinite crawl."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import threading
import time
import xbmc
import xbmcgui
from resources.lib import browse_cache, collection_profile, collection_validation
from resources.lib.collections_home import matching_catalog
from resources.lib.nuviohub import store
from .playback import Loading, ROOT

MAX_WORKERS = 4
MAX_STARTUP_SECONDS = 40


def jobs():
    providers = store.list_providers()
    result, seen = [], set()
    for _, source in collection_validation.sources(collection_profile.load()):
        match = matching_catalog(source, providers)
        if not match:
            continue
        provider, catalog = match
        extra = collection_validation.extra_for(source)
        key = browse_cache.catalog_key(provider, catalog, extra)
        if key not in seen:
            result.append((key, provider, catalog, extra))
            seen.add(key)
    return result


def prepare():
    all_jobs = jobs()
    cache = browse_cache.instance()
    # One SQLite read promotes warmed disk pages to the bounded in-process LRU.
    # Stale pages count as present: Home shows them at once and they are
    # revalidated one by one in the background instead of behind a loading screen.
    state = cache.lookup_many([job[0] for job in all_jobs])
    missing = [job for job in all_jobs if job[0] not in state]
    for key, provider, catalog, extra in all_jobs:
        if state.get(key) is False:
            browse_cache.refresh(provider, catalog, extra)
    if not missing:
        return {'cached': len(all_jobs), 'loaded': 0, 'failed': 0, 'deferred': 0}
    window = Loading('nuvio_loading.xml', ROOT, 'Default', '1080i',
                     label='Preparing your collections', full=True)
    monitor = xbmc.Monitor()
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='NuvioWarm')
    pending, remaining = set(), iter(missing)
    report = {'cached': len(all_jobs) - len(missing), 'loaded': 0, 'failed': 0, 'deferred': len(missing)}
    deadline = time.monotonic() + MAX_STARTUP_SECONDS
    proxy = xbmcgui.Window(10000).getProperty('nuvio.art_cache.base')
    stopped = threading.Event()
    def warm(provider, catalog, extra):
        data = browse_cache.catalog(provider, catalog, extra, 5)
        if proxy.startswith('http://127.0.0.1:'):
            from urllib.request import Request, urlopen
            from urllib.parse import quote
            for meta in (data.get('metas') or [])[:2]:
                if stopped.is_set() or time.monotonic() >= deadline:break
                poster = str(meta.get('poster') or '')
                if not poster.startswith(('https://', 'http://')) or '|' in poster:continue
                try:
                    with urlopen(Request(proxy+'/image?url='+quote(poster,safe=''),method='HEAD'),timeout=1.5) as response:
                        response.read(0)
                except Exception:pass
        return data
    def submit():
        try:
            _, provider, catalog, extra = next(remaining)
        except StopIteration:
            return False
        pending.add(pool.submit(warm, provider, catalog, extra))
        return True
    window.show()
    try:
        for _ in range(min(MAX_WORKERS, len(missing))):
            submit()
        while pending and not window.cancelled and not monitor.abortRequested() and time.monotonic() < deadline:
            done, _ = wait(pending, timeout=.05, return_when=FIRST_COMPLETED)
            for future in done:
                pending.remove(future)
                try:
                    future.result()
                    report['loaded'] += 1
                except Exception:
                    report['failed'] += 1
                report['deferred'] -= 1
                submit()
            complete = report['cached'] + report['loaded'] + report['failed']
            window.setProperty('nuvio.loading', 'Preparing collections · %d / %d catalogs · Back to skip' % (complete, len(all_jobs)))
        return report
    finally:
        stopped.set()
        for future in pending:
            future.cancel()
        pool.shutdown(wait=False)
        window.close()
