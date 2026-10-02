"""Security notice: add-ons that overload Kodi (6.0.37).

All-in-one add-ons run background services at every Kodi start (Trakt sync,
library updates, cache cleaning, playback monitors); maintenance wizards wipe
caches and rewrite settings. With them MegaNexus cannot run as it should. The
notice recommends a clean Kodi install, offers to turn the add-ons off (one
click, nothing deleted, reversible in Add-ons) or Skip. Skip is remembered
until another such add-on appears. IDs checked against the add-ons' own
addon.xml in their public repositories.
"""
import json
import xbmc
import xbmcaddon
import xbmcgui
from resources.lib.theme import folder as theme_folder
from .dialog import Dialog, BACK

HEAVY = {   # all-in-one video add-ons with background services
    'plugin.video.umbrella': 'Umbrella', 'plugin.video.fen': 'Fen', 'plugin.video.fenlight': 'Fen Light',
    'plugin.video.pov': 'POV', 'plugin.video.seren': 'Seren', 'plugin.video.thecrew': 'The Crew',
    'plugin.video.shadow': 'Shadow', 'plugin.video.otaku': 'Otaku', 'plugin.video.scrubsv2': 'Scrubs v2',
    'plugin.video.asgard': 'Asgard', 'plugin.video.homelander': 'Homelander', 'plugin.video.coalition': 'Coalition',
    'plugin.video.ezra': 'Ezra', 'plugin.video.themagicdragon': 'The Magic Dragon',
    'plugin.video.magicdragon': 'Magic Dragon', 'plugin.video.redlight': 'Red Light', 'plugin.video.thechains': 'The Chains',
}
WIZARDS = {'plugin.program.openwizard': 'Open Wizard'}   # wipe caches / rewrite settings at start
TRAKT = {'script.trakt': 'Trakt'}                        # double scrobbling with MegaNexus' own Trakt
SKIPPED_SETTING = 'nuvio_conflicts_skipped'


def _enabled(addon_id):
    try:
        return bool(xbmc.getCondVisibility('System.AddonIsEnabled(%s)' % addon_id))
    except Exception:
        return False


def _name(addon_id, fallback):
    try:
        return xbmcaddon.Addon(addon_id).getAddonInfo('name') or fallback
    except Exception:
        return fallback


def found():
    """[(id, name)] of enabled add-ons that should be turned off."""
    result = [(aid, _name(aid, name)) for group in (HEAVY, WIZARDS) for aid, name in group.items() if _enabled(aid)]
    try:
        from resources.lib import trakt
        ours = trakt.authorized()
    except Exception:
        ours = False
    if ours:
        result += [(aid, _name(aid, name)) for aid, name in TRAKT.items() if _enabled(aid)]
    return result


def disable(ids):
    done = []
    for aid in ids:
        try:
            reply = json.loads(xbmc.executeJSONRPC(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.SetAddonEnabled',
                                                               'params': {'addonid': aid, 'enabled': False}})))
        except (TypeError, ValueError):
            continue
        if not reply.get('error'):
            done.append(aid)
    return done


def text(addons):
    lines = ['These add-ons run heavy background services at every Kodi start (sync, library updates, cache '
             'cleaning, playback monitors). They overload Kodi, so MegaNexus cannot run as it should.',
             '[B]Best performance:[/B] a clean Kodi install with MegaNexus only.',
             '[B]Or turn them off[/B] - MegaNexus then runs faster than on any Android box. Nothing is deleted; '
             'you can turn them back on in Add-ons.']
    if any(aid in TRAKT for aid, _ in addons):
        lines.append('The Trakt add-on also logs what you watch, so with MegaNexus connected to Trakt every title is logged twice.')
    return '[CR]'.join(lines)


class Notice(Dialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.addons = kwargs['addons']
        self.choice = ''

    def onInit(self):
        count = len(self.addons)
        self.setProperty('nuvio.notice.subtitle', '%d add-on%s slow%s down this Kodi' % (count, '' if count == 1 else 's', 's' if count == 1 else ''))
        self.setProperty('nuvio.notice.text', text(self.addons))
        self.setProperty('nuvio.notice.addons', 'Will be turned off: ' + ' · '.join(name for _, name in self.addons))
        self.setFocusId(300)

    def onClick(self, cid):
        if cid in (300, 301):
            self.choice = 'off' if cid == 300 else 'skip'
            self.close()

    def onAction(self, action):
        if action.getId() in BACK:
            self.choice = 'skip'
            self.close()


def run(force=False):
    """Show the notice when needed. ``force`` (Maintenance > System check) also
    shows it after Skip and says when nothing was found."""
    addon = xbmcaddon.Addon('plugin.video.nuviohub')
    addons = found()
    if not addons:
        if force:
            xbmcgui.Dialog().notification('System check', 'No add-ons that slow MegaNexus down.', time=3000)
        return ''
    key = ','.join(sorted(aid for aid, _ in addons))
    if not force and addon.getSetting(SKIPPED_SETTING) == key:
        return 'skip'
    win = Notice('nuvio_notice.xml', xbmcaddon.Addon('script.nuvio').getAddonInfo('path'), theme_folder(), '1080i', addons=addons)
    try:
        win.doModal()
        choice = win.choice or 'skip'
    finally:
        win.close()
    if choice == 'off':
        done = disable([aid for aid, _ in addons])
        addon.setSetting(SKIPPED_SETTING, '')
        xbmcgui.Dialog().notification('MegaNexus', 'Turned off %d add-on%s. Full speed.' % (len(done), '' if len(done) == 1 else 's'), time=4000)
    else:
        addon.setSetting(SKIPPED_SETTING, key)
    return choice
