"""Local storage (6.0.37): HUB Settings > Local storage and playback of the
"Local Movies" / "Local Series" Home rows (Kodi's own video library)."""
import xbmcgui
from resources.lib import local_media, settings_cache
from . import settings_page as page

ADDON = settings_cache.cached_addon()
HELP = ('Kodi opens Videos > Files.\n\n'
        '1. Choose [B]Add videos...[/B] and browse to the folder (USB disk, NAS, SMB/NFS share).\n'
        '2. Set [B]This directory contains[/B] to Movies or TV shows and confirm.\n'
        '3. Kodi scans the folder. Back in MegaNexus the titles are in the '
        '[B]Local Movies[/B] and [B]Local Series[/B] rows on Home.\n\n'
        'Movies work best as "Title (Year)" folders, series as "Show/Season 1/S01E01".')


def _clock(seconds):
    seconds = int(seconds or 0)
    hours, rest = divmod(seconds, 3600)
    return '%d:%02d:%02d' % (hours, rest // 60, rest % 60) if hours else '%d:%02d' % (rest // 60, rest % 60)


def _play(kind, item_id):
    """Ask Resume / From the beginning like Kodi does; '' when cancelled."""
    position = local_media.resume_seconds(kind, item_id)
    resume = False
    if position > 0:
        pick = xbmcgui.Dialog().contextmenu(['Resume from %s' % _clock(position), 'Play from the beginning'])
        if pick < 0:
            return ''
        resume = pick == 0
    if not local_media.play(kind, item_id, resume):
        xbmcgui.Dialog().notification('Local storage', 'This file could not be opened. Is the drive connected?', time=4000)
        return ''
    return 'playing'


def _episode_item(episode):
    label = '%dx%02d  %s' % (int(episode.get('season') or 0), int(episode.get('episode') or 0), episode.get('title') or episode.get('label') or '')
    resume = episode.get('resume') or {}
    position, total = float(resume.get('position') or 0), float(resume.get('total') or 0)
    if position > 0 and total > 0:
        state = '%d%% watched' % int(position * 100 / total)
    else:
        state = 'Watched' if episode.get('playcount') else ''
    li = xbmcgui.ListItem(label, '  ·  '.join(x for x in (state, str(episode.get('firstaired') or '')[:4]) if x))
    art = episode.get('art') or {}
    li.setArt({'thumb': art.get('thumb') or art.get('season.poster') or art.get('tvshow.poster') or ''})
    return li


def _series(show):
    seasons = local_media.seasons(show['id'])
    season = None
    if len(seasons) > 1:
        labels = []
        for row in seasons:
            left = int(row.get('episode') or 0) - int(row.get('watchedepisodes') or 0)
            labels.append(xbmcgui.ListItem(row.get('label') or 'Season %s' % row.get('season'),
                                           '%d episodes%s' % (row.get('episode') or 0, ' · %d new' % left if left and row.get('watchedepisodes') else '')))
        first = next((i for i, row in enumerate(seasons) if int(row.get('watchedepisodes') or 0) < int(row.get('episode') or 0)), 0)
        pick = xbmcgui.Dialog().select(show.get('title') or 'Seasons', labels, preselect=first, useDetails=True)
        if pick < 0:
            return ''
        season = seasons[pick].get('season')
    elif seasons:
        season = seasons[0].get('season')
    episodes = local_media.episodes(show['id'], season)
    if not episodes:
        xbmcgui.Dialog().notification('Local storage', 'No episodes found for this series.', time=3000)
        return ''
    pick = xbmcgui.Dialog().select(show.get('title') or 'Episodes', [_episode_item(e) for e in episodes],
                                   preselect=local_media.next_episode(episodes), useDetails=True)
    if pick < 0:
        return _series(show) if len(seasons) > 1 else ''
    return _play('episode', episodes[pick]['episodeid'])


def open_item(local):
    """A click on a Local row card: 'playing', a Kodi window command or ''."""
    kind = local.get('type')
    if kind == 'all':
        return local_media.library_window(local.get('kind'))
    if kind == 'movie':
        return _play('movie', local['id'])
    if kind == 'series':
        return _series(local)
    return ''


def _home_rows(value=None):
    on = local_media.enabled(ADDON) if value is None else value
    ADDON.setSetting(local_media.HOME_SETTING, 'true' if on else 'false')
    settings_cache.invalidate()


def run():
    def rows():
        have = local_media.counts()
        folders = len(local_media.sources())
        return [page.item('Show on Home · Local Movies and Local Series', enabled=local_media.enabled(ADDON)),
                page.item('On this device', '%d movies · %d series' % (have['movie'], have['series'])),
                page.item('Add a folder · Kodi video sources', '%d folder%s' % (folders, '' if folders == 1 else 's')),
                page.item('Scan folders for new files'),
                page.item('Remove missing files from the list'),
                page.item('Back')]

    def choose(pick):
        if pick == 0:
            _home_rows(not local_media.enabled(ADDON))
        elif pick == 1:
            local_media.forget_counts()
        elif pick == 2:
            if not xbmcgui.Dialog().yesno('Add a folder', HELP, nolabel='Cancel', yeslabel='Open Kodi'):
                return None
            _home_rows(True)   # whoever adds a folder wants to see it on Home
            local_media.forget_counts()
            return local_media.SOURCES_WINDOW
        elif pick == 3:
            local_media.scan()
            xbmcgui.Dialog().notification('Local storage', 'Scanning your folders. New titles appear on Home.', time=3000)
        elif pick == 4:
            local_media.clean()
            xbmcgui.Dialog().notification('Local storage', 'Removing files that are no longer there.', time=3000)
        elif pick == 5:
            return page.DONE
        return None
    return page.show('Local storage', rows, choose)
