"""Cancellable first-page warm-up; bounded workers, no invisible infinite crawl."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import time
import xbmc
import xbmcgui
from resources.lib import browse_cache, collection_profile, collection_validation
from resources.lib.collections_home import matching_catalog
from resources.lib.nuviohub import store
from .playback import Loading, ROOT
from resources.lib.theme import folder as theme_folder

MAX_WORKERS = 4
MAX_STARTUP_SECONDS = 40


def shown_groups():
    """Only what Home shows: hidden rows and hidden cards are not prepared."""
    return [dict(g, folders=[f for f in g.get('folders') or [] if not f.get('hidden')])
            for g in collection_profile.load() if not g.get('hidden')]


def jobs(groups=None):
    providers = store.list_providers()
    result, seen = [], set()
    shown = shown_groups() if groups is None else groups
    for _, source in collection_validation.sources(shown):
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


POSTER_WORKERS = 6           # matches the image proxy's download workers
FRONT_ROWS = 3               # posters loaded before Home: the first rows on screen
POSTERS_PER_CATALOG = 10     # a screen of cards per collection catalog
MAX_POSTER_SECONDS = 60      # the rest continues in the background on Home
COLD_IMAGES = 600            # proxy RAM holding fewer images = filled after reboot/suspend


def art_cold():
    """Image proxy is on (RAM mode) and nearly empty, e.g. right after a reboot."""
    home = xbmcgui.Window(10000)
    base = home.getProperty('nuvio.art_cache.base')
    if not base.startswith('http://127.0.0.1:'):
        return ''
    try:
        images = int((home.getProperty('nuvio.art_cache.usage') or '0 · 0').split('·')[-1].split()[0])
    except (ValueError, IndexError):
        images = 0
    return base if images < COLD_IMAGES else ''


def poster_urls(all_jobs, per_catalog=POSTERS_PER_CATALOG):
    """Exactly the artwork URLs Home will request for each collection catalog.

    Pages are read from the disk cache too: the 40 MiB in-memory page cache
    holds only ~75 rich catalog pages, so a RAM-only read silently skipped the
    rest (both test boxes showed the same 738 posters for different layouts)."""
    import xbmcaddon
    from resources.lib import home_data
    landscape = xbmcaddon.Addon('plugin.video.nuviohub').getSetting('nuvio_card_shape') == 'landscape'
    urls, seen = [], set()
    for _, provider, catalog, extra in all_jobs:
        data = browse_cache.peek(provider, catalog, extra, memory_only=False, revalidate=False)
        if not data:
            continue
        try:
            rows = home_data._job_rows(provider, catalog, extra, data)[:per_catalog]
        except Exception:
            continue
        for row in rows:
            url = str((row.get('landscape') or row.get('fanart') or row.get('poster')) if landscape else row.get('poster') or '')
            if url.startswith(('https://', 'http://')) and '|' not in url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def _warm_catalogs(window, monitor, all_jobs, missing, report):
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='NuvioWarm')
    pending, remaining = set(), iter(missing)
    deadline = time.monotonic() + MAX_STARTUP_SECONDS
    def submit():
        try:
            _, provider, catalog, extra = next(remaining)
        except StopIteration:
            return False
        pending.add(pool.submit(browse_cache.catalog, provider, catalog, extra, 5))
        return True
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
    finally:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=False)


def _warm_posters(window, monitor, base, urls, report):
    """Fill the image proxy's RAM with the posters Home shows, in parallel."""
    from urllib.parse import quote
    from urllib.request import Request, urlopen
    def head(url):
        with urlopen(Request(base + '/image?url=' + quote(url, safe=''), method='HEAD'), timeout=4) as response:
            response.read(0)
    pool = ThreadPoolExecutor(max_workers=POSTER_WORKERS, thread_name_prefix='NuvioPosters')
    pending, remaining = set(), iter(urls)
    deadline = time.monotonic() + MAX_POSTER_SECONDS
    def submit():
        try:
            pending.add(pool.submit(head, next(remaining)))
            return True
        except StopIteration:
            return False
    try:
        for _ in range(min(POSTER_WORKERS, len(urls))):
            submit()
        while pending and not window.cancelled and not monitor.abortRequested() and time.monotonic() < deadline:
            done, _ = wait(pending, timeout=.05, return_when=FIRST_COMPLETED)
            for future in done:
                pending.remove(future)
                report['posters'] += 1
                submit()
            window.setProperty('nuvio.loading', 'Loading posters into memory · %d / %d · Back to skip'
                               % (report['posters'], len(urls)))
        if not pending and report['posters'] >= len(urls):
            # Only the first rows are done: Home's background warm-up loads the
            # rest (it pauses while the user navigates) and marks the session.
            xbmcgui.Window(10000).setProperty('nuvio.art_warm.front', base)
    finally:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=False)


def prepare():
    """Before Home: make sure every collection's first page is cached and - after
    a reboot, when the image RAM is empty - load the posters of the first rows
    on screen. Back skips. The other rows' posters are loaded by Home in the
    background, paused while the user navigates."""
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
    report = {'cached': len(all_jobs) - len(missing), 'loaded': 0, 'failed': 0, 'deferred': len(missing), 'posters': 0}
    base = art_cold()
    if not missing and not base:
        return report
    window = Loading('nuvio_loading.xml', ROOT, theme_folder(),'1080i',
                     label='Preparing your collections', full=True)
    monitor = xbmc.Monitor()
    window.show()
    try:
        if missing:
            _warm_catalogs(window, monitor, all_jobs, missing, report)
        if base and not window.cancelled and not monitor.abortRequested():
            urls = poster_urls(jobs(shown_groups()[:FRONT_ROWS]))
            if urls:
                _warm_posters(window, monitor, base, urls, report)
        return report
    finally:
        window.close()
